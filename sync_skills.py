#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小乐技能库 · 一键同步脚本
================================================================
把本机 ~/.workbuddy/skills/ 下「名单里的技能」重新打包成中文名 zip，
刷新 manifest.json 与 README 清单，并可选推送到 GitHub。

名单在 roster.json —— 只放高频在用的技能，加一个减一个各一条。

常用命令：
    python3 sync_skills.py                     # 打包 + 刷新清单
    python3 sync_skills.py --usage             # 看技能使用频率排行（调 skill-meter）
    python3 sync_skills.py --list              # 看当前收录名单
    python3 sync_skills.py --add <目录名>       # 收一个技能进库
    python3 sync_skills.py --remove <目录名>    # 从库里剔除
    python3 sync_skills.py --push "说明"        # 打包后自动提交并推送

日常最省事：在 WorkBuddy 会话里跟小乐说「同步技能到 git」。
================================================================
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import zipfile

# ---------- 路径 ----------
HOME = os.path.expanduser("~")
SKILLS_SRC = os.path.join(HOME, ".workbuddy", "skills")   # 本机技能目录
REPO_DIR = os.path.dirname(os.path.abspath(__file__))     # 本仓库目录
ZIP_DIR = os.path.join(REPO_DIR, "skills")                # zip 落盘目录
MANIFEST = os.path.join(REPO_DIR, "manifest.json")
ROSTER = os.path.join(REPO_DIR, "roster.json")
README = os.path.join(REPO_DIR, "README.md")
TRACK_PY = os.path.join(SKILLS_SRC, "skill-meter", "scripts", "track.py")  # 使用频率统计

# ---------- 打包排除项 ----------
EXCLUDE_DIRS = {".state", "__pycache__", ".git", ".venv", "node_modules/.cache"}
EXCLUDE_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}

TABLE_BEGIN = "<!-- SKILLS-TABLE:BEGIN -->"
TABLE_END = "<!-- SKILLS-TABLE:END -->"


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
    """极简 YAML frontmatter 读取（只取单行 key: value）。"""
    path = os.path.join(SKILLS_SRC, skill_dir, "SKILL.md")
    if not os.path.exists(path):
        return {}
    fm = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read(8000)
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return fm
    for line in m.group(1).splitlines():
        kv = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.+?)\s*$", line)
        if kv:
            fm[kv.group(1)] = kv.group(2).strip().strip('"').strip("'")
    return fm


def auto_cn_name(skill_dir):
    """中文名缺省时：优先 display_name，其次 name，最后目录名。"""
    fm = read_frontmatter(skill_dir)
    for key in ("display_name", "display_name_zh", "name"):
        v = fm.get(key)
        if v and re.search(r"[\u4e00-\u9fff]", v):
            return v
    return skill_dir


def auto_summary(skill_dir, limit=160):
    """简介缺省时从 SKILL.md 的 description_zh / description 里摘。"""
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
    """打一个中文名 zip，返回结果字典。"""
    src_dir = entry["dir"]
    src = os.path.join(SKILLS_SRC, src_dir)
    cn = entry.get("cn") or auto_cn_name(src_dir)

    if not os.path.isdir(src):
        return {"ok": False, "dir": src_dir, "cn": cn, "error": "源目录不存在：%s" % src}

    no = "%02d" % index
    zip_name = "%s-%s(%s).zip" % (no, cn, src_dir)
    zip_path = os.path.join(ZIP_DIR, zip_name)
    os.makedirs(ZIP_DIR, exist_ok=True)
    if os.path.exists(zip_path):
        os.remove(zip_path)

    files = 0
    raw = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root, dirs, filenames in os.walk(src):
            dirs[:] = [d for d in dirs if not should_skip(d, True)]
            for f in sorted(filenames):
                if should_skip(f, False):
                    continue
                full = os.path.join(root, f)
                rel = os.path.relpath(full, SKILLS_SRC)   # 保留 <技能目录>/… 层级
                st = os.stat(full)
                info = zipfile.ZipInfo(rel, date_time=datetime.datetime.fromtimestamp(st.st_mtime).timetuple()[:6])
                info.external_attr = (stat.S_IFREG | (st.st_mode & 0o777)) << 16  # 保留可执行位
                info.compress_type = zipfile.ZIP_DEFLATED
                with open(full, "rb") as fh:
                    zf.writestr(info, fh.read())
                files += 1
                raw += st.st_size

    zip_bytes = os.path.getsize(zip_path)
    sha = hashlib.sha256(open(zip_path, "rb").read()).hexdigest()
    newest = max(
        (os.path.getmtime(os.path.join(r, f))
         for r, ds, fs in os.walk(src) for f in fs if not should_skip(f, False)),
        default=os.path.getmtime(src),
    )
    return {
        "ok": True,
        "no": no,
        "cn": cn,
        "dir": src_dir,
        "zip": zip_name,
        "kb": round(zip_bytes / 1024, 1),
        "zip_bytes": zip_bytes,
        "files": files,
        "sha256": sha,
        "src_updated": datetime.datetime.fromtimestamp(newest).strftime("%Y-%m-%d"),
    }


def human(kb):
    return "%.1f MB" % (kb / 1024) if kb >= 1024 else "%.0f KB" % kb


# ===================== 清单输出 =====================

def build_manifest(results, roster):
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
        "purpose": "自用 WorkBuddy 自制技能归档：中文名备注 + zip 打包，日常会话更新后一键同步",
        "source_dir": SKILLS_SRC,
        "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(items),
        "total_size_human": human(sum(r.get("kb", 0) for r in results if r["ok"])),
        "skills": items,
    }


def render_table(manifest):
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
    lines.append("> 共 **%d** 个技能，合计 **%s**；清单刷新时间 %s。" % (
        manifest["count"], manifest["total_size_human"], manifest["updated"]))
    return "\n".join(lines)


def sync_readme(manifest):
    """把清单表格写进 README 的标记区（不重写整份 README）。"""
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
    with open(README, "w", encoding="utf-8") as fh:
        fh.write(new)
    return True


# ===================== 使用频率排行 =====================

def usage_ranking():
    """调 skill-meter 的 track.py 看频率排行。"""
    if not os.path.exists(TRACK_PY):
        print("[!] 没找到 skill-meter（%s）" % TRACK_PY)
        print("    先在技能市场装「技能使用统计」(skill-meter)。")
        return 1
    for args in (["top", "20", "--since", "all"], ["unused"]):
        print("=" * 62)
        print(">>> track.py " + " ".join(args))
        subprocess.run([sys.executable or "python3", TRACK_PY] + args, cwd=os.path.dirname(TRACK_PY))
    return 0


# ===================== git =====================

def git(*args):
    return subprocess.run(["git"] + list(args), cwd=REPO_DIR, text=True, capture_output=True)


def ensure_git_ready():
    """确保 git 身份可用（本机全局身份未设，用仓库级兜底）。"""
    if not git("config", "user.email").stdout.strip():
        git("config", "user.email", "1791986214@users.noreply.github.com")
        print("[i] 已写入仓库级 user.email")
    if not git("config", "user.name").stdout.strip():
        git("config", "user.name", "1791986214")
        print("[i] 已写入仓库级 user.name")


# ===================== 主流程 =====================

def main():
    ap = argparse.ArgumentParser(description="小乐技能库：打包 + 刷新清单 + 推送")
    ap.add_argument("--push", nargs="?", const="", metavar="MSG", help="打包后自动提交并推送")
    ap.add_argument("--add", metavar="DIR", help="把某个技能收进库（自动取中文名）")
    ap.add_argument("--remove", metavar="DIR", help="把某个技能从库里剔除")
    ap.add_argument("--list", action="store_true", help="只看当前名单")
    ap.add_argument("--usage", action="store_true", help="看技能使用频率排行")
    args = ap.parse_args()

    roster = load_roster()

    # ---- 名单维护 ----
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
        if not args.push and not args.list:
            args.push = None

    if args.remove:
        d = args.remove.strip().rstrip("/")
        left = [s for s in roster if s["dir"] != d]
        if len(left) == len(roster):
            print("[i] 名单里没有 %s" % d)
        else:
            roster = left
            save_roster(roster)
            print("[OK] 已剔除：%s" % d)

    # ---- 只列名单 ----
    if args.list:
        print("== 小乐技能库 · 当前收录 %d 个 ==" % len(roster))
        for i, s in enumerate(roster, 1):
            src = os.path.join(SKILLS_SRC, s["dir"])
            flag = "" if os.path.isdir(src) else "   [本机缺失!]"
            print("%02d  %-24s %s%s" % (i, s.get("cn") or auto_cn_name(s["dir"]), s["dir"], flag))
        return 0

    # ---- 使用排行 ----
    if args.usage:
        return usage_ranking()

    if not roster:
        print("[!] roster.json 里没有技能，先 --add 收一个")
        return 1

    # ---- 打包 ----
    print("== 小乐技能库 · 同步 ==")
    print("源目录 : %s" % SKILLS_SRC)
    print("打包到 : %s" % ZIP_DIR)
    print("-" * 66)

    results = []
    fail = 0
    for i, entry in enumerate(roster, 1):
        res = pack_one(entry, i)
        results.append(res)
        if res["ok"]:
            print("{no} {cn:<22} {size:>8}  {files:>3} 文件  {sha}".format(
                no=res["no"], cn=res["cn"], size=human(res["kb"]),
                files=res["files"], sha=res["sha256"][:12]))
        else:
            fail += 1
            print("{no} {cn:<22} 失败：{err}".format(no="%02d" % i, cn=res["cn"], err=res["error"]))

    manifest = build_manifest(results, roster)
    with open(MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print("-" * 66)
    print("清单已刷新：manifest.json（%d 个技能，合计 %s）" % (manifest["count"], manifest["total_size_human"]))
    if sync_readme(manifest):
        print("README 清单表已同步")

    # 顺手清掉不在名单里的旧 zip（避免仓库留下已剔除的技能）
    keep = {r["zip"] for r in results if r["ok"]}
    for f in os.listdir(ZIP_DIR):
        if f.endswith(".zip") and f not in keep:
            os.remove(os.path.join(ZIP_DIR, f))
            print("已清理旧包：%s" % f)

    # ---- 推送 ----
    if args.push is not None:
        ensure_git_ready()
        msg = args.push.strip() or "同步技能 %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        print("-" * 66)
        git("add", "-A")
        c = git("commit", "-m", msg)
        out = (c.stdout + c.stderr).strip()
        if c.returncode != 0 and "nothing to commit" not in out:
            print("[!] commit 失败：\n" + out)
            return 1
        print(out.splitlines()[0] if out else "（无变更）")
        p = git("push", "origin", "HEAD")
        if p.returncode != 0:
            print("[!] push 失败：\n" + p.stdout + p.stderr)
            return 1
        print("[OK] 已推送到 %s" % manifest["repo"])

    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
