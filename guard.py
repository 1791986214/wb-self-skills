#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小乐技能库 · 投毒防线（guard）
================================================================
自动同步是「盲提交」——它只看文件变没变，不看变的是什么。
这个模块就是那道闸门：在打包推送之前，逐技能做变更审计 + 威胁扫描，
命中就**拦住不推**，并出一份待审报告。

三层防线：
  ① 变更审计（对比上一次已提交状态 = git HEAD 里的 zip）
     · 新增技能        → 拦（没审过的东西不进门）
     · 新增文件        → 拦（新增文件是投毒最常见的载体）
     · 改动 vendor 目录 → 拦（node_modules 之类不该自己变）
     只有「已审过文件的正常内容修改」才走下一步
  ② 威胁扫描（正则规则，扫改动的文本文件）
     · 网络外传 / 管道执行 / 凭据读取 / 破坏性操作 / 持久化 / 远程装包
     · eval+exec / 提示词注入（SKILL.md 本质是给 AI 的指令）/ 超长 base64 混淆
     · 密钥样式（sk- / ghp_ / AKIA / 私钥头 …）—— 仓库是公开的，这条最要命
  ③ 留痕（不推也要留下证据）
     · 待审报告写进 ~/.workbuddy/logs/skills-review/
     · 通过的内容变更，diff 统计写进 commit message，历史可审计

用法（一般由 sync_skills.py 调用）：
    import guard
    res = guard.precheck(roster, repo_dir)   # {'blockers': [...], 'warnings': [...], 'report': path}
================================================================
"""

import hashlib
import os
import re
import subprocess
import zipfile
import io

# ---------- 扫描范围 ----------
TEXT_EXT = {
    ".md", ".markdown", ".txt", ".py", ".sh", ".bash", ".zsh", ".fish",
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".bat", ".cmd", ".ps1", ".html", ".htm",
    ".css", ".xml", ".rb", ".pl", ".php", ".go", ".rs", ".java", ".sql",
    ".env", ".example", ".gitignore", ".properties", ".gradle", ".make", ".mk",
}
VENDOR_MARKERS = ("node_modules/", "vendor/", "site-packages/", ".venv/", "dist-lib/")
DOC_EXT = {".md", ".markdown", ".txt"}          # 文档类
CODE_EXT = {".sh", ".bash", ".zsh", ".fish", ".py", ".js", ".mjs", ".cjs", ".ts",
            ".tsx", ".jsx", ".bat", ".cmd", ".ps1", ".rb", ".pl", ".php", ".go",
            ".rs", ".java", ".sql", ".yaml", ".yml", ".json"}   # 脚本/代码类
MAX_SCAN_BYTES = 2 * 1024 * 1024   # 单文件超过 2MB 不扫内容，只记警告

# ---------- 威胁规则 ----------
# (级别, 名称, 正则, 说明)
RULES = [
    # —— 高危：外传 / 执行 / 窃取 / 破坏 / 持久化 ——
    ("HIGH", "网络请求", r"(?i)\b(curl|wget|nc|ncat|telnet|scp|sftp|rsync|Invoke-WebRequest)\b[^\n]{0,120}https?://",
     "代码里出现联网取数/外传，技能几乎不需要这个"),
    ("HIGH", "管道执行远程脚本", r"(?i)(curl|wget)[^\n|]{0,160}\|\s*(ba|z|k)?sh\b|(curl|wget)[^\n|]{0,160}\|\s*(python|perl|ruby)\b",
     "curl | sh 是典型的远程代码执行后门"),
    ("HIGH", "解码后执行", r"(?i)base64\s+(-d|--decode)[^\n|]{0,80}\|\s*(ba|z)?sh\b|atob\([^)]*\)[^\n]{0,40}(eval|exec)|codecs\.decode[^\n]{0,40}exec\(",
     "把代码藏在 base64 里再执行 = 混淆"),
    ("HIGH", "读取凭据/密钥文件", r"(?i)(~/\.ssh/|/\.ssh/|id_rsa|id_ed25519|\.aws/credentials|\.netrc|\.git-credentials|credentials\.enc|encryption_key|keyblob|device-id|\.env\b|\.npmrc|\.pypirc|\.docker/config\.json|keychain)",
     "技能不需要碰这些个人凭据"),
    ("HIGH", "读钥匙串", r"security\s+(find|dump)-(generic|internet)-password|SecKeychainFindGenericPassword",
     "直接读 macOS 钥匙串"),
    ("HIGH", "破坏性删除", r"rm\s+(-[a-zA-Z]+\s+)*(/|~|\$HOME|\*)\s*$|shutil\.rmtree\s*\(\s*['\"]?(/|~)|\bdd\s+if=|mkfs|diskutil\s+(erase|reformat)|Remove-Item[^\n]*-Recurse[^\n]*(C:\\|\$env:USERPROFILE)",
     "可能清空家目录/整盘"),
    ("HIGH", "写入持久化项", r"(?i)(library/launchagents|crontab\s+-|login\s?items|/etc/(sudoers|passwd)|\.zshrc|\.bashrc|\.bash_profile|\.zprofile)",
     "持久化是后门常见手法（本技能的守护任务走审批，不准技能自己写）"),
    ("HIGH", "动态执行代码", r"(?i)\b(eval|exec)\s*\(|\bexec\s+[^\n]*\$|subprocess\.[A-Za-z_]+\([^)]*shell\s*=\s*True|os\.system\s*\(|child_process\.exec|new\s+Function\s*\(",
     "动态执行容易被注入"),
    ("HIGH", "远程装依赖", r"(?i)(pip|pip3|npm|yarn|pnpm|gem|cargo|brew)\s+(install|i|add)\s+[^\n]*(https?://|git\+|--index-url)",
     "从 URL 装包 = 引入不可控代码"),
    ("HIGH", "提示词注入", r"(忽略(之前|上面|上述|前面|所有)(的)?(全部)?(指令|规则|约束)|ignore\s+(all\s+)?(previous|above|prior)\s+instructions|不要(告诉|提示|提醒|通知)(用户|大哥)|别让(用户|大哥)知道|偷偷|静默地(上传|发送|删除)|silently\s+(upload|send|delete)|删除(日志|记录)|清除(日志|痕迹)|不要(记录|留)(日志|痕迹))",
     "SKILL.md 是给 AI 的指令，注入比脚本更隐蔽"),
    ("HIGH", "指示外传文件", r"(?i)(上传|发送|提交|post|upload|send)[^\n]{0,24}(所有|全部|整个|each)?[^\n]{0,12}(文件|目录|数据|内容|内容|凭据|钥匙|token|key)[^\n]{0,24}(到|至|往|to)\s*(https?://|ftp://)",
     "指示 AI 把本地东西传出去"),
    ("HIGH", "读取其它会话/隐私", r"(?i)(~/?\.workbuddy/sessions|~/\.codex/|Library/Messages|Library/Mail|\.wechat|WeChat Files|聊天数据库)",
     "碰私人通讯数据"),

    # —— 中危：可疑但不一定恶意 ——
    ("MED", "写文件到系统目录", r"(?i)(/usr/local/bin|/etc/|C:\\Windows|~/Library/LaunchAgents)", "往系统位置写东西"),
    ("MED", "权限放开", r"chmod\s+(-R\s+)?(777|a\+rwx)|icacls[^\n]*Everyone", "权限放开过大"),
    ("MED", "超长编码串（可能混淆）", r"[A-Za-z0-9+/]{600,}={0,2}", "长 base64/编码块，建议人工看一眼"),
    ("MED", "写环境变量文件", r"(?i)>>?\s*['\"]?~/?\.(zshrc|bashrc|profile|bash_profile)", "改 shell 启动配置"),
    ("MED", "大量反斜杠转义", r"(\\x[0-9a-fA-F]{2}){20,}", "十六进制转义堆叠，常用于藏字符串"),
    ("MED", "下载可执行文件", r"(?i)(curl|wget)[^\n]{0,160}-[oO]\s+\S+\.(app|dmg|exe|bin|so|dylib)",
     "下载二进制到本地"),
]

# 每条规则该在哪种文件里才作数（不写就是 all）
#   code = 只在脚本/代码里算真危险；出现在文档里降级成警告
#          （README 里说「守护任务装在 LaunchAgents」是正当说明，脚本里去写才是后门）
#   doc  = 只在文档里作数（提示词注入只对「给 AI 的指令」有意义）
RULE_SCOPE = {
    "写入持久化项": "code",
    "写文件到系统目录": "code",
    "写环境变量文件": "code",
    "提示词注入": "doc",
    "指示外传文件": "doc",
}

# 密钥样式：仓库是公开的，命中必须拦
SECRET_PATTERNS = [
    (r"sk-[A-Za-z0-9]{20,}", "OpenAI 风格密钥"),
    (r"ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}", "GitHub Token"),
    (r"gho_|ghu_|ghs_|ghr_[A-Za-z0-9]{30,}", "GitHub Token"),
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key"),
    (r"xox[baprs]-[A-Za-z0-9-]{10,}", "Slack Token"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "私钥"),
    (r"AIza[0-9A-Za-z_\-]{30,}", "Google API Key"),
    (r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.", "JWT"),
    (r"(?i)(secret|token|password|passwd|api[_-]?key)\s*[:=]\s*['\"][A-Za-z0-9_\-/+]{24,}['\"]", "硬编码口令/密钥"),
]

_COMPILED = [(lvl, name, re.compile(rx), why) for lvl, name, rx, why in RULES]
_COMPILED_SECRETS = [(re.compile(rx), name) for rx, name in SECRET_PATTERNS]


# ===================== 基础工具 =====================

def _is_vendor(rel):
    return any(m in rel for m in VENDOR_MARKERS)


def _looks_text(rel):
    ext = os.path.splitext(rel)[1].lower()
    return ext in TEXT_EXT or os.path.basename(rel).startswith(".")


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def _read(path):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except Exception:
        return b""


def source_files(skills_src, skill_dir, exclude_dirs, exclude_files):
    """技能源目录下的文件指纹表 {相对技能目录的路径: sha256}。"""
    root = os.path.join(skills_src, skill_dir)
    out = {}
    if not os.path.isdir(root):
        return out
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in exclude_dirs]
        for f in sorted(fns):
            if f in exclude_files:
                continue
            full = os.path.join(dp, f)
            rel = os.path.relpath(full, root)
            out[rel] = sha256_bytes(_read(full))
    return out


def head_zip_files(repo_dir, zip_name):
    """上一次已提交状态：从 git HEAD 里那个 zip 取指纹表。没有就返回 None。"""
    if not zip_name:
        return None
    blob = subprocess.run(["git", "show", "HEAD:skills/%s" % zip_name],
                          cwd=repo_dir, capture_output=True).stdout
    if not blob:
        return None
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except Exception:
        return None
    prefix = zip_name  # 占位
    out = {}
    for n in zf.namelist():
        if n.endswith("/"):
            continue
        # zip 内层级是 <技能目录>/<相对路径>
        parts = n.split("/", 1)
        if len(parts) == 2:
            out[parts[1]] = sha256_bytes(zf.read(n))
    return out


def diff_fingerprints(prev, cur):
    if prev is None:
        return {"new_skill": True, "added": sorted(cur), "removed": [], "changed": []}
    added = sorted(set(cur) - set(prev))
    removed = sorted(set(prev) - set(cur))
    changed = sorted(f for f in set(cur) & set(prev) if cur[f] != prev[f])
    return {"new_skill": False, "added": added, "removed": removed, "changed": changed}


def file_kind(rel):
    ext = os.path.splitext(rel)[1].lower()
    if ext in DOC_EXT:
        return "doc"
    if ext in CODE_EXT:
        return "code"
    return "other"


def scan_text(rel, text, kind=None):
    """对一段文本跑全部规则，返回 [(级别, 名称, 说明, 命中片段)]。

    kind: doc / code / other。规则按 RULE_SCOPE 决定是否作数、要不要降级。
    """
    if kind is None:
        kind = file_kind(rel)
    findings = []
    lines = text.splitlines()
    for lvl, name, rx, why in _COMPILED:
        scope = RULE_SCOPE.get(name, "all")
        if scope == "doc" and kind != "doc":
            continue                      # 只查文档的规则，代码文件不适用
        level = lvl
        if scope == "code" and kind == "doc":
            level = "MED"                 # 文档里提到 ≠ 真去干，降级成提醒
        for i, line in enumerate(lines, 1):
            if len(line) > 4000:
                line = line[:4000]
            m = rx.search(line)
            if m:
                snippet = line.strip()
                if len(snippet) > 160:
                    pos = max(0, m.start() - 40)
                    snippet = ("…" if pos else "") + snippet[pos:pos + 160] + "…"
                findings.append((level, name, why, "第 %d 行：%s" % (i, snippet)))
                break
    for rx, name in _COMPILED_SECRETS:
        m = rx.search(text)
        if m:
            hit = m.group(0)
            masked = hit[:6] + "…" + hit[-4:] if len(hit) > 12 else "…"
            findings.append(("HIGH", "疑似密钥泄漏（%s）" % name,
                             "本仓库是公开的，推上去等于公开泄露", masked))
    return findings


def scan_file(skills_src, skill_dir, rel):
    """扫单个文件；返回 findings。二进制/超大文件只给警告。"""
    full = os.path.join(skills_src, skill_dir, rel)
    if not os.path.exists(full):
        return []
    size = os.path.getsize(full)
    if size > MAX_SCAN_BYTES:
        return [("MED", "文件过大未扫内容", "超过 2MB，需要人工看", "%s（%.1f MB）" % (rel, size / 1024 / 1024))]
    if not _looks_text(rel):
        return [("MED", "二进制文件变动", "二进制无法静态扫描", rel)]
    raw = _read(full)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return [("MED", "非 UTF-8 文本", "可能是乱码或混淆编码", rel)]
    return scan_text(rel, text)


def line_delta(skills_src, skill_dir, rel, prev_bytes):
    """粗略的 +行/-行 统计，用于 commit message 留痕。"""
    full = os.path.join(skills_src, skill_dir, rel)
    cur = _read(full).decode("utf-8", "replace").splitlines()
    old = (prev_bytes or b"").decode("utf-8", "replace").splitlines()
    import difflib
    add = rm = 0
    for ln in difflib.unified_diff(old, cur, lineterm="", n=0):
        if ln.startswith("+") and not ln.startswith("+++"):
            add += 1
        elif ln.startswith("-") and not ln.startswith("---"):
            rm += 1
    return add, rm


def head_zip_contents(repo_dir, zip_name):
    blob = subprocess.run(["git", "show", "HEAD:skills/%s" % zip_name],
                          cwd=repo_dir, capture_output=True).stdout
    if not blob:
        return {}
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except Exception:
        return {}
    out = {}
    for n in zf.namelist():
        if n.endswith("/"):
            continue
        parts = n.split("/", 1)
        if len(parts) == 2:
            out[parts[1]] = zf.read(n)
    return out


# ===================== 主闸门 =====================

def evaluate_skill(repo_dir, skills_src, skill, zip_name, exclude_dirs, exclude_files, strict=False):
    """审计 + 扫描单个技能。返回 dict。"""
    d = skill["dir"]
    cur = source_files(skills_src, d, exclude_dirs, exclude_files)
    prev = head_zip_files(repo_dir, zip_name)
    diff = diff_fingerprints(prev, cur)

    blockers, warnings, notes = [], [], []

    if diff["new_skill"]:
        blockers.append(("HIGH", "本仓库里没有这个技能的已审版本",
                         "首次收录必须人工过一眼", "%s（%d 个文件）" % (d, len(cur))))
    else:
        if diff["added"]:
            show = "、".join(diff["added"][:6]) + ("…" if len(diff["added"]) > 6 else "")
            blockers.append(("HIGH", "新增了 %d 个文件" % len(diff["added"]),
                             "新增文件是投毒最常见的载体，需要人工确认", show))
        vendor_touched = [f for f in diff["changed"] + diff["added"] if _is_vendor(f)]
        if vendor_touched:
            blockers.append(("HIGH", "第三方依赖目录被改动（%d 个文件）" % len(vendor_touched),
                             "vendor/node_modules 不该自己变", "、".join(vendor_touched[:4]) + "…"))
        if diff["removed"]:
            notes.append("删除 %d 个文件：%s" % (len(diff["removed"]), "、".join(diff["removed"][:6])))
        if strict and diff["changed"]:
            blockers.append(("HIGH", "严格模式：源码内容被修改（%d 个文件）" % len(diff["changed"]),
                             "strict 模式下任何源码改动都要人工放行",
                             "、".join(diff["changed"][:6])))

    # 内容扫描：只扫「新增 + 改动」的文件（便宜的路径）
    to_scan = diff["added"] + [f for f in diff["changed"] if not _is_vendor(f)]
    if diff["new_skill"]:
        to_scan = sorted(cur)
    hits = []
    for rel in to_scan:
        for f in scan_file(skills_src, d, rel):
            hits.append((rel,) + f)

    # 新增文件/首次收录的命中直接拦；改动文件的命中按级别分
    for rel, lvl, name, why, ev in hits:
        item = (lvl, name, why, "%s → %s" % (rel, ev))
        if lvl == "HIGH":
            blockers.append(item)
        else:
            warnings.append(item)

    # 留痕：改动行数
    deltas = []
    if not diff["new_skill"]:
        prev_map = head_zip_contents(repo_dir, zip_name)
        for rel in diff["changed"]:
            if _is_vendor(rel):
                continue
            a, r = line_delta(skills_src, d, rel, prev_map.get(rel))
            deltas.append("%s +%d/-%d" % (rel, a, r))

    return {
        "dir": d, "cn": skill.get("cn") or d, "zip": zip_name,
        "diff": diff, "blockers": blockers, "warnings": warnings,
        "notes": notes, "deltas": deltas,
        "no_change": (not diff["new_skill"] and not diff["added"]
                      and not diff["removed"] and not diff["changed"]),
    }


def precheck(roster, repo_dir, skills_src, zip_names, exclude_dirs, exclude_files,
             report_dir=None, tag=None, strict=False, force_report=False):
    """对全部技能跑一遍闸门。返回 blockers / warnings / report 路径。"""
    results = []
    for skill in roster:
        results.append(evaluate_skill(repo_dir, skills_src, skill,
                                      zip_names.get(skill["dir"]),
                                      exclude_dirs, exclude_files, strict=strict))

    blockers = [(r["dir"],) + b for r in results for b in r["blockers"]]
    warnings = [(r["dir"],) + w for r in results for w in r["warnings"]]
    report = None
    if blockers or force_report:
        report = write_report(results, blockers, warnings, report_dir, tag)
    return {"results": results, "blockers": blockers, "warnings": warnings, "report": report}


def write_report(results, blockers, warnings, report_dir, tag=None):
    import datetime
    report_dir = report_dir or os.path.join(os.path.expanduser("~"), ".workbuddy", "logs", "skills-review")
    os.makedirs(report_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(report_dir, "%s%s.md" % (ts, ("-" + tag) if tag else ""))
    L = []
    L.append("# 技能库待审报告 %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    L.append("")
    L.append("自动同步被**拦住**了，没有推送到 GitHub。下面是原因，看完确认没问题再放行。")
    L.append("")
    L.append("## 拦截项（%d）" % len(blockers))
    L.append("")
    L.append("| 技能 | 级别 | 问题 | 为什么危险 | 证据 |")
    L.append("|---|---|---|---|---|")
    for skill_dir, lvl, name, why, ev in blockers:
        L.append("| `%s` | %s | %s | %s | %s |" % (
            skill_dir, lvl, name, why, str(ev).replace("|", "／")))
    if warnings:
        L.append("")
        L.append("## 警告项（%d，不拦，但建议看一眼）" % len(warnings))
        L.append("")
        L.append("| 技能 | 级别 | 问题 | 说明 | 证据 |")
        L.append("|---|---|---|---|---|")
        for skill_dir, lvl, name, why, ev in warnings:
            L.append("| `%s` | %s | %s | %s | %s |" % (
                skill_dir, lvl, name, why, str(ev).replace("|", "／")))
    L.append("")
    L.append("## 各技能变更明细")
    L.append("")
    for r in results:
        if r["no_change"]:
            continue
        d = r["diff"]
        L.append("### `%s`（%s）" % (r["dir"], r["cn"]))
        L.append("")
        if d["new_skill"]:
            L.append("- **本仓库里没有已审版本**，属首次收录")
        if d["added"]:
            L.append("- 新增 %d 个：%s" % (len(d["added"]), "、".join(d["added"][:20])))
        if d["changed"]:
            L.append("- 改动 %d 个：%s" % (len(d["changed"]), "、".join(d["changed"][:20])))
        if d["removed"]:
            L.append("- 删除 %d 个：%s" % (len(d["removed"]), "、".join(d["removed"][:20])))
        if r["deltas"]:
            L.append("- 行数变化：%s" % "；".join(r["deltas"]))
        L.append("")
    L.append("## 怎么放行")
    L.append("")
    L.append("1. 先人工看上面每个文件到底改了什么（`diff` 或直接打开技能目录）")
    L.append("2. 确认没问题后按技能逐个放行：`python3 sync_skills.py --approve <技能目录名>`")
    L.append("3. 放行后会重新打包并推送；嫌麻烦可加 `--push`")
    L.append("")
    L.append("> 放行 = 把这个技能的当前状态记成「已审」，以后再改仍会重新检查。")
    L.append("> 如果不想让自动同步接手任何内容改动，用 `--strict` 模式：一律只推「重打包」不推源码改动。")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    return path


def scan_repo(repo_dir, extra_files=("README.md", "manifest.json", "roster.json")):
    """扫仓库里非技能的文件（README / manifest 等），防手滑把密钥写进去。"""
    out = []
    for f in extra_files:
        p = os.path.join(repo_dir, f)
        if not os.path.exists(p):
            continue
        hits = scan_text(f, _read(p).decode("utf-8", "replace"))
        for lvl, name, why, ev in hits:
            if lvl == "HIGH":
                out.append((f, lvl, name, why, ev))
    return out
