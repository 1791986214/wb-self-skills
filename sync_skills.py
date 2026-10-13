#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小乐技能库 · 一键 / 自动同步脚本
================================================================
把本机 ~/.workbuddy/skills/ 下「名单里的技能」重新打包成中文名 zip，
刷新 manifest.json 与 README 清单，并在有真实变化时推送到 GitHub。

名单在 roster.json —— 只放高频在用的技能，加一个减一个各一条。

常用命令：
    python3 sync_skills.py                      # 手动跑一次：打包 + 刷新清单
    python3 sync_skills.py --push "说明"         # 打包后提交并推送
    python3 sync_skills.py --auto                # 自动模式：只在有真变化时才提交推送（守护任务用）
    python3 sync_skills.py --status              # 看守护任务 + 与远端的同步状态
    python3 sync_skills.py --install-agent       # 装 macOS 后台守护任务（改技能自动同步）
    python3 sync_skills.py --uninstall-agent     # 卸掉守护任务
    python3 sync_skills.py --usage               # 看技能使用频率排行（调 skill-meter）
    python3 sync_skills.py --list                # 看当前收录名单
    python3 sync_skills.py --add <目录名>         # 收一个技能进库
    python3 sync_skills.py --remove <目录名>      # 从库里剔除

自动同步机制（launchd，系统级，不依赖 WorkBuddy、不占会话性能）：
    装一次 --install-agent，之后只要 ~/.workbuddy/skills/ 有变动（AI 改、你手改、
    解压覆盖、市场装新技能…），最多 2 分钟内自动打包提交推送到 GitHub。
================================================================
"""

import argparse
import datetime
import hashlib
import io
import json
import os
import plistlib
import re
import stat
import subprocess
import sys
import zipfile

# ---------- 路径 ----------
HOME = os.path.expanduser("~")
SKILLS_SRC = os.path.join(HOME, ".workbuddy", "skills")      # 本机技能目录
REPO_DIR = os.path.dirname(os.path.realpath(__file__))       # 本仓库目录
ZIP_DIR = os.path.join(REPO_DIR, "skills")                   # zip 落盘目录
MANIFEST = os.path.join(REPO_DIR, "manifest.json")
ROSTER = os.path.join(REPO_DIR, "roster.json")
README = os.path.join(REPO_DIR, "README.md")

LOG_DIR = os.path.join(HOME, ".workbuddy", "logs")
LOG_FILE = os.path.join(LOG_DIR, "skills-sync.log")
STATE_FILE = os.path.join(LOG_DIR, "skills-sync-state.json")

AGENT_LABEL = "com.xiaole.skills-sync"
AGENT_PLIST = os.path.join(HOME, "Library", "LaunchAgents", AGENT_LABEL + ".plist")
AGENT_INTERVAL = 120              # 秒，兜底轮询周期
PROXY = "http://127.0.0.1:7897"   # 直连不通时用的本机代理

TRACK_PY = os.path.join(SKILLS_SRC, "skill-meter", "scripts", "track.py")

# ---------- 打包排除项 ----------
EXCLUDE_DIRS = {".state", "__pycache__", ".git", ".venv"}
EXCLUDE_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}

TABLE_BEGIN = "<!-- SKILLS-TABLE:BEGIN -->"
TABLE_END = "<!-- SKILLS-TABLE:END -->"


# ===================== 小工具 =====================

def log(msg, quiet=False):
    line = "[%s] %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass
    if not quiet:
        print(msg)


def git(*args):
    return subprocess.run(["git"] + list(args), cwd=REPO_DIR, text=True, capture_output=True)


def _json_norm(text):
    """去掉易变字段后归一化，用来判断「有没有真变化」。"""
    try:
        d = json.loads(text)
    except Exception:
        return text
    if isinstance(d, dict):
        d.pop("updated", None)
    return json.dumps(d, ensure_ascii=False, sort_keys=True)


def write_if_changed(path, content):
    """内容真变了才落盘，避免时间戳抖动产生空提交。"""
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                old = fh.read()
        except Exception:
            old = None
        if old is not None and _json_norm(old) == _json_norm(content):
            return False
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return True


# ===================== 名单读写 =====================

def load_roster():
    if not os.path.exists(ROSTER):
        return []
    with open(ROSTER, encoding="utf-8") as fh:
        return json.load(fh).get("skills", [])


def save_roster(skills):
    data = {
        "_说明": "小乐技能库收录名单。只放「高频在用」的技能；加一个减一个就增删一条。cn 留空会自动从技能自己 SKILL.md 里取名字。",
        "_指令": [
            "加技能：python3 sync_skills.py --add <技能目录名>",
            "减技能：python3 sync_skills.py --remove <技能目录名>",
            "看排行：python3 sync_skills.py --usage",
            "打包上传：python3 sync_skills.py --push \"说明\"",
            "会话里直接跟小乐说「同步技能到 git」也行",
        ],
        "skills": skills,
    }
    with open(ROSTER, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


# ===================== 读技能自身的元信息 =====================

def read_frontmatter(skill_dir):
    path = os.path.join(SKILLS_SRC, skill_dir, "SKILL.md")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read(8000)
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        kv = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.+?)\s*$", line)
        if kv:
            fm[kv.group(1)] = kv.group(2).strip().strip('"').strip("'")
    return fm


def auto_cn_name(skill_dir):
    fm = read_frontmatter(skill_dir)
    for key in ("display_name", "display_name_zh", "name"):
        v = fm.get(key)
        if v and re.search(r"[\u4e00-\u9fff]", v):
            return v
    return skill_dir


def auto_summary(skill_dir, limit=160):
    fm = read_frontmatter(skill_dir)
    for key in ("description_zh", "description"):
        v = fm.get(key)
        if v:
            return v[:limit] + ("…" if len(v) > limit else "")
    return ""


# ===================== 打包 =====================

def should_skip(name, is_dir):
    return name in (EXCLUDE_DIRS if is_dir else EXCLUDE_FILES)


def pack_one(entry, index):
    src_dir = entry["dir"]
    src = os.path.join(SKILLS_SRC, src_dir)
    cn = entry.get("cn") or auto_cn_name(src_dir)

    if not os.path.isdir(src):
        return {"ok": False, "dir": src_dir, "cn": cn, "error": "源目录不存在：%s" % src}

    no = "%02d" % index
    zip_name = "%s-%s(%s).zip" % (no, cn, src_dir)
    zip_path = os.path.join(ZIP_DIR, zip_name)
    os.makedirs(ZIP_DIR, exist_ok=True)

    buf = _build_zip_bytes(src)
    sha = hashlib.sha256(buf).hexdigest()
    old_sha = None
    if os.path.exists(zip_path):
        old_sha = hashlib.sha256(open(zip_path, "rb").read()).hexdigest()
    if old_sha != sha:
        with open(zip_path, "wb") as fh:
            fh.write(buf)

    files = 0
    newest = 0
    for root, dirs, filenames in os.walk(src):
        dirs[:] = [d for d in dirs if not should_skip(d, True)]
        for f in filenames:
            if should_skip(f, False):
                continue
            newest = max(newest, os.stat(os.path.join(root, f)).st_mtime)
            files += 1

    return {
        "ok": True,
        "no": no,
        "cn": cn,
        "dir": src_dir,
        "zip": zip_name,
        "kb": round(len(buf) / 1024, 1),
        "files": files,
        "sha256": sha,
        "src_updated": datetime.datetime.fromtimestamp(newest or os.path.getmtime(src)).strftime("%Y-%m-%d"),
    }


def _build_zip_bytes(src):
    """内存里打包，便于先算 sha 再决定要不要落盘。"""
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root, dirs, filenames in os.walk(src):
            dirs[:] = [d for d in dirs if not should_skip(d, True)]
            for f in sorted(filenames):
                if should_skip(f, False):
                    continue
                full = os.path.join(root, f)
                rel = os.path.relpath(full, SKILLS_SRC)
                st = os.stat(full)
                info = zipfile.ZipInfo(rel, date_time=datetime.datetime.fromtimestamp(st.st_mtime).timetuple()[:6])
                info.external_attr = (stat.S_IFREG | (st.st_mode & 0o777)) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                with open(full, "rb") as fh:
                    zf.writestr(info, fh.read())
    return bio.getvalue()


def human(kb):
    return "%.1f MB" % (kb / 1024) if kb >= 1024 else "%.0f KB" % kb


# ===================== 清单输出 =====================

def build_manifest(results, roster, updated=None):
    items = []
    for entry, res in zip(roster, results):
        item = {
            "no": res.get("no"),
            "cn_name": res.get("cn"),
            "dir_name": res["dir"],
            "summary": entry.get("summary") or auto_summary(res["dir"]),
            "triggers": entry.get("triggers", ""),
            "zip": res.get("zip"),
            "size_human": human(res["kb"]) if res["ok"] else None,
            "sha256": res.get("sha256"),
            "files": res.get("files"),
            "src_updated": res.get("src_updated"),
            "install": "解压后把 %s/ 整个放进 ~/.workbuddy/skills/" % res["dir"],
        }
        if not res["ok"]:
            item["error"] = res["error"]
        items.append(item)

    return {
        "name": "小乐技能库",
        "repo": "https://github.com/1791986214/wb-self-skills",
        "purpose": "自用 WorkBuddy 自制技能归档：中文名备注 + zip 打包，改动后自动同步",
        "source_dir": SKILLS_SRC,
        "updated": updated or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(items),
        "total_size_human": human(sum(r.get("kb", 0) for r in results if r["ok"])),
        "skills": items,
    }


def render_table(manifest):
    latest = max((it.get("src_updated") or "" for it in manifest["skills"]), default="")
    lines = [
        "| 编号 | 中文名 | 技能目录名 | 说明 | 体积 | 技能更新 |",
        "|:---:|---|---|---|:---:|:---:|",
    ]
    for it in manifest["skills"]:
        summary = (it.get("summary") or "").replace("|", "／")
        lines.append("| {no} | **{cn}** | `{dir}` | {s} | {size} | {upd} |".format(
            no=it["no"], cn=it["cn_name"], dir=it["dir_name"],
            s=summary, size=it.get("size_human") or "打包失败",
            upd=it.get("src_updated") or "-"))
    lines.append("")
    lines.append("> 共 **%d** 个技能，合计 **%s**；最近技能更新 %s。改动记录见本仓库 commit 历史。" % (
        manifest["count"], manifest["total_size_human"], latest or "-"))
    return "\n".join(lines)


def sync_readme(manifest):
    if not os.path.exists(README):
        return False
    with open(README, encoding="utf-8") as fh:
        text = fh.read()
    if TABLE_BEGIN not in text or TABLE_END not in text:
        return False
    new = re.sub(
        re.escape(TABLE_BEGIN) + r".*?" + re.escape(TABLE_END),
        TABLE_BEGIN + "\n" + render_table(manifest) + "\n" + TABLE_END,
        text, flags=re.S)
    if new == text:
        return False
    with open(README, "w", encoding="utf-8") as fh:
        fh.write(new)
    return True


# ===================== 打包主流程（不含 git） =====================

def do_pack(roster, quiet=False):
    results = []
    fail = 0
    for i, entry in enumerate(roster, 1):
        res = pack_one(entry, i)
        results.append(res)
        if not res["ok"]:
            fail += 1
        if not quiet:
            if res["ok"]:
                print("{no} {cn:<22} {size:>8}  {files:>3} 文件  {sha}".format(
                    no=res["no"], cn=res["cn"], size=human(res["kb"]),
                    files=res["files"], sha=res["sha256"][:12]))
            else:
                print("{no} {cn:<22} 失败：{err}".format(no="%02d" % i, cn=res["cn"], err=res["error"]))

    new_skills = scan_new_skills(roster)

    old_updated = None
    if os.path.exists(MANIFEST):
        try:
            old_updated = json.load(open(MANIFEST, encoding="utf-8")).get("updated")
        except Exception:
            pass
    manifest = build_manifest(results, roster, updated=old_updated)
    changed = write_if_changed(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    if changed:
        manifest = build_manifest(results, roster)   # 真变了才换新时间戳
        with open(MANIFEST, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    readme_changed = sync_readme(manifest)

    keep = {r["zip"] for r in results if r["ok"]}
    removed = []
    if os.path.isdir(ZIP_DIR):
        for f in os.listdir(ZIP_DIR):
            if f.endswith(".zip") and f not in keep:
                os.remove(os.path.join(ZIP_DIR, f))
                removed.append(f)

    return {"results": results, "fail": fail, "manifest": manifest,
            "changed": changed, "readme_changed": readme_changed,
            "removed": removed, "new_skills": new_skills}


def scan_new_skills(roster):
    """本机存在、但不在名单里的技能（提示用，不自动收录）。"""
    known = {s["dir"] for s in roster}
    if not os.path.isdir(SKILLS_SRC):
        return []
    local = [d for d in os.listdir(SKILLS_SRC)
             if os.path.isdir(os.path.join(SKILLS_SRC, d)) and not d.startswith(".")]
    return sorted(d for d in local if d not in known)


# ===================== git =====================

def ensure_git_ready():
    if not git("config", "user.email").stdout.strip():
        git("config", "user.email", "1791986214@users.noreply.github.com")
    if not git("config", "user.name").stdout.strip():
        git("config", "user.name", "1791986214")


def current_branch():
    return git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "main"


def unpushed_count():
    r = git("rev-list", "--count", "origin/%s..HEAD" % current_branch())
    try:
        return int(r.stdout.strip())
    except Exception:
        return 0


def has_pending_changes():
    return bool(git("status", "--porcelain").stdout.strip())


def push():
    """直连失败自动退到本机代理。返回 (成功, 说明)。"""
    p = git("push", "origin", "HEAD")
    if p.returncode == 0:
        return True, "直连"
    p2 = git("-c", "http.proxy=" + PROXY, "-c", "https.proxy=" + PROXY, "push", "origin", "HEAD")
    if p2.returncode == 0:
        return True, "走本机代理"
    blob = (p.stdout + p.stderr + p2.stdout + p2.stderr).strip()
    return False, ("推送失败：" + blob.splitlines()[-1]) if blob else "推送失败"


def commit_and_push(message):
    ensure_git_ready()
    if has_pending_changes():
        git("add", "-A")
        c = git("commit", "-m", message)
        out = (c.stdout + c.stderr).strip()
        if c.returncode != 0 and "nothing to commit" not in out:
            return False, "commit 失败：" + out
    if unpushed_count() == 0:
        return True, "无需推送"
    return push()


# ===================== launchd 守护任务 =====================

def agent_paths():
    """监听的路径：技能根目录 + 名单里每个技能目录。"""
    paths = [SKILLS_SRC]
    for s in load_roster():
        d = os.path.join(SKILLS_SRC, s["dir"])
        if os.path.isdir(d):
            paths.append(d)
    return paths


def build_plist():
    return {
        "Label": AGENT_LABEL,
        "ProgramArguments": [sys.executable or "python3",
                             os.path.join(REPO_DIR, "sync_skills.py"), "--auto"],
        "StartInterval": AGENT_INTERVAL,
        "WatchPaths": agent_paths(),
        "RunAtLoad": True,
        "StandardOutPath": os.path.join(LOG_DIR, "skills-sync.out.log"),
        "StandardErrorPath": os.path.join(LOG_DIR, "skills-sync.err.log"),
        "EnvironmentVariables": {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:" + os.path.join(HOME, ".local", "bin"),
            "HOME": HOME,
        },
    }


def install_agent():
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(AGENT_PLIST), exist_ok=True)
    with open(AGENT_PLIST, "wb") as fh:
        plistlib.dump(build_plist(), fh)
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", "gui/%d/%s" % (uid, AGENT_LABEL)], capture_output=True)
    r = subprocess.run(["launchctl", "bootstrap", "gui/%d" % uid, AGENT_PLIST],
                       text=True, capture_output=True)
    if r.returncode != 0:
        r2 = subprocess.run(["launchctl", "load", "-w", AGENT_PLIST], text=True, capture_output=True)
        if r2.returncode != 0:
            print("[!] 守护任务装载失败：\n" + (r.stderr or "") + (r2.stderr or ""))
            return 1
    subprocess.run(["launchctl", "enable", "gui/%d/%s" % (uid, AGENT_LABEL)], capture_output=True)
    print("[OK] 自动同步已开启")
    print("     任务名  ：%s" % AGENT_LABEL)
    print("     监听    ：%s（+ 名单里每个技能目录）" % SKILLS_SRC)
    print("     兜底轮询：每 %d 秒一次" % AGENT_INTERVAL)
    print("     日志    ：%s" % LOG_FILE)
    return 0


def uninstall_agent():
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", "gui/%d/%s" % (uid, AGENT_LABEL)], capture_output=True)
    subprocess.run(["launchctl", "unload", "-w", AGENT_PLIST], capture_output=True)
    if os.path.exists(AGENT_PLIST):
        os.remove(AGENT_PLIST)
    print("[OK] 自动同步已关闭")
    return 0


def agent_loaded():
    r = subprocess.run(["launchctl", "print", "gui/%d/%s" % (os.getuid(), AGENT_LABEL)],
                       text=True, capture_output=True)
    return r.returncode == 0


def show_status():
    print("== 小乐技能库 · 状态 ==")
    print("仓库目录 : %s" % REPO_DIR)
    print("本机技能 : %s" % SKILLS_SRC)
    print("名单数量 : %d" % len(load_roster()))
    loaded = agent_loaded()
    if loaded:
        print("自动同步 : 已开启（每 %d 秒轮询 + 技能目录变动即触发）" % AGENT_INTERVAL)
        r = subprocess.run(["launchctl", "print", "gui/%d/%s" % (os.getuid(), AGENT_LABEL)],
                           text=True, capture_output=True)
        m = re.search(r"^\s*last exit code = (\S+)", r.stdout, re.M)
        m2 = re.search(r"^\s*runs = (\d+)", r.stdout, re.M)
        if m2:
            print("累计触发 : %s 次" % m2.group(1))
        if m:
            print("上次退出 : %s" % m.group(1))
    else:
        print("自动同步 : 未开启（跑 --install-agent 开启）")
    print("待推送   : %d 个 commit" % unpushed_count())
    print("工作区   : %s" % ("有未提交改动" if has_pending_changes() else "干净"))
    new = scan_new_skills(load_roster())
    if new:
        print("未收录   : %d 个（%s）" % (len(new), "、".join(new)))
    if os.path.exists(LOG_FILE):
        print("---- 最近日志 ----")
        lines = open(LOG_FILE, encoding="utf-8", errors="replace").read().strip().splitlines()[-8:]
        for ln in lines:
            print("  " + ln)
    return 0


# ===================== 使用频率排行 =====================

def usage_ranking():
    if not os.path.exists(TRACK_PY):
        print("[!] 没找到 skill-meter（%s）" % TRACK_PY)
        print("    先在技能市场装「技能使用统计」(skill-meter)。")
        return 1
    py = sys.executable or "python3"
    for a in (["top", "20", "--since", "all"], ["unused"]):
        print("=" * 62)
        subprocess.run([py, TRACK_PY] + a, cwd=os.path.dirname(TRACK_PY))
    return 0


# ===================== 自动模式 =====================

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE, encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(d):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass


def auto_run():
    roster = load_roster()
    if not roster:
        log("名单为空，跳过")
        return 1

    res = do_pack(roster, quiet=True)
    if res["fail"]:
        log("有 %d 个技能打包失败，本次不推送" % res["fail"], quiet=True)
        return 1

    state = load_state()
    new = res["new_skills"]
    if new and new != state.get("new_skills"):
        log("本机有 %d 个技能还没进库：%s —— 要收录就跑 --add <目录名>" % (len(new), "、".join(new)), quiet=True)
        state["new_skills"] = new
        save_state(state)

    if not (has_pending_changes() or unpushed_count()):
        return 0   # 无变化，静默结束

    if has_pending_changes():
        names = [r["cn"] for r in res["results"] if r["ok"]]
        msg = "自动同步：%s（%s）" % (
            "、".join(names) if len(names) <= 3 else "%d 个技能" % len(names),
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    else:
        msg = "自动同步：补推本地未推送的 commit"

    ok, how = commit_and_push(msg)
    log(("成功 —— " if ok else "失败 —— ") + how, quiet=True)
    return 0 if ok else 1


# ===================== 主流程 =====================

def main():
    ap = argparse.ArgumentParser(description="小乐技能库：打包 + 刷新清单 + 同步到 GitHub")
    ap.add_argument("--push", nargs="?", const="", metavar="MSG", help="打包后提交并推送")
    ap.add_argument("--auto", action="store_true", help="自动模式（守护任务用）")
    ap.add_argument("--add", metavar="DIR", help="把某个技能收进库（自动取中文名）")
    ap.add_argument("--remove", metavar="DIR", help="把某个技能从库里剔除")
    ap.add_argument("--list", action="store_true", help="只看当前名单")
    ap.add_argument("--usage", action="store_true", help="看技能使用频率排行")
    ap.add_argument("--status", action="store_true", help="看自动同步状态")
    ap.add_argument("--install-agent", action="store_true", help="装 macOS 后台自动同步任务")
    ap.add_argument("--uninstall-agent", action="store_true", help="卸掉后台自动同步任务")
    args = ap.parse_args()

    if args.install_agent:
        return install_agent()
    if args.uninstall_agent:
        return uninstall_agent()
    if args.status:
        return show_status()
    if args.usage:
        return usage_ranking()
    if args.auto:
        return auto_run()

    roster = load_roster()

    if args.add:
        d = args.add.strip().rstrip("/")
        if not os.path.isdir(os.path.join(SKILLS_SRC, d)):
            print("[!] 本机没有这个技能目录：%s" % os.path.join(SKILLS_SRC, d))
            return 1
        if any(s["dir"] == d for s in roster):
            print("[i] %s 已在名单里，跳过" % d)
        else:
            roster.append({"cn": auto_cn_name(d), "dir": d})
            save_roster(roster)
            print("[OK] 已收录：%s（%s）" % (auto_cn_name(d), d))
            if agent_loaded():
                install_agent()

    if args.remove:
        d = args.remove.strip().rstrip("/")
        left = [s for s in roster if s["dir"] != d]
        if len(left) == len(roster):
            print("[i] 名单里没有 %s" % d)
        else:
            roster = left
            save_roster(roster)
            print("[OK] 已剔除：%s" % d)
            if agent_loaded():
                install_agent()

    if args.list:
        print("== 小乐技能库 · 当前收录 %d 个 ==" % len(roster))
        for i, s in enumerate(roster, 1):
            src = os.path.join(SKILLS_SRC, s["dir"])
            flag = "" if os.path.isdir(src) else "   [本机缺失!]"
            print("%02d  %-24s %s%s" % (i, s.get("cn") or auto_cn_name(s["dir"]), s["dir"], flag))
        new = scan_new_skills(roster)
        if new:
            print("\n未收录的本机技能（要收就跑 --add）：")
            for d in new:
                print("   %s" % d)
        return 0

    if not roster:
        print("[!] roster.json 里没有技能，先 --add 收一个")
        return 1

    print("== 小乐技能库 · 同步 ==")
    print("源目录 : %s" % SKILLS_SRC)
    print("打包到 : %s" % ZIP_DIR)
    print("-" * 66)
    res = do_pack(roster, quiet=False)
    print("-" * 66)
    for f in res["removed"]:
        print("已清理旧包：%s" % f)
    print("清单%s：manifest.json（%d 个技能，合计 %s）" % (
        "已刷新" if res["changed"] else "无变化",
        res["manifest"]["count"], res["manifest"]["total_size_human"]))
    if res["readme_changed"]:
        print("README 清单表已同步")
    if res["new_skills"]:
        print("提示：本机还有 %d 个技能没进库（%s），要收就跑 --add" % (
            len(res["new_skills"]), "、".join(res["new_skills"])))

    if args.push is not None:
        msg = args.push.strip() or "同步技能 %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        print("-" * 66)
        ok, how = commit_and_push(msg)
        print(("[OK] " if ok else "[!] ") + how)
        if ok and how == "直连" or (ok and how.startswith("走")):
            print("     仓库：%s" % res["manifest"]["repo"])
        return 0 if ok else 1

    return 0 if res["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
