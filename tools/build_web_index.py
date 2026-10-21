#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「网页设计」技能索引页 + 同步预览图

数据来源（唯一事实）：
  roster.json                                    → 哪些技能属于「网页设计」分类
  ~/.workbuddy/skills/<dir>/manifest.json        → 名称、描述、源、提交、许可
  ~/.workbuddy/skills/<dir>/preview.gif          → 预览动图（必备）

产出两处（内容完全一致）：
  权威：<repo>/skills/网页设计/index.html + previews/
  副本：<work>/网页设计/index.html + previews/    （方便本地直接打开）

规则见同目录 README.md。改索引不要手改本文件产出的 html，重跑本脚本。
"""

import json
import os
import shutil
import sys
import html

HOME = os.path.expanduser("~")
REPO = os.path.join(HOME, "Documents", "wb-self-skills")
SKILLS_SRC = os.path.join(HOME, ".workbuddy", "skills")
ROSTER = os.path.join(REPO, "roster.json")

# 仓库内的权威目录
REPO_OUT = os.path.join(REPO, "skills", "网页设计")
# 本地副本目录（可用 --work 覆盖；默认跟着当前项目记忆线走）
WORK_OUT = os.environ.get("WEB_INDEX_WORK") or os.path.join(
    HOME, "WorkBuddy", "2026-10-13-17-22-57", "work", "网页设计")

CATEGORY = "网页设计"

# 每个技能一句「这张 GIF 演的是什么」，没有就退回 description
CAPTION = {
    "archify": "泳道流程图：节点入场 + 依赖曲线生长",
    "emil-skills": "三卡交错入场 · 开关弹性 · 按压回弹 · Toast",
    "design-systems": "Hold. Move. Release. — 拖动滑块、开关弹性、面板按压回弹",
    "onetake": "连锁反应：每一拍都是下一次碰撞的起点",
}

# 技能包内可能有子技能，索引里给个概览
SUBHINT = {
    "emil-skills": ("内含 15 个子技能", [
        "设计总纲", "动效构建", "动效评审", "动效改造", "动效机会",
        "动效性能", "动效词汇", "Apple 设计", "UI 库选型", "多版原型",
        "网页像原生", "UI 压测", "Sonner 通知", "Expo 动效", "Swift 写法"]),
    "design-systems": ("核心是 Lens 一套（液态玻璃）", [
        "18 类玻璃组件", "折射 .90", "雾化 .24", "色散 .65", "弹性 .70"]),
    "archify": ("支持 11 种图", [
        "workflow", "architecture", "sequence", "dataflow", "lifecycle",
        "erd", "class", "tree", "timeline", "waterfall", "explainer"]),
    "onetake": ("含 6 份动效设计手册", [
        "节奏与衔接", "构图", "动作库", "参考片拆解", "功能演示", "声音"]),
}


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d B" % n) if unit == "B" else ("%.0f %s" % (n, unit))
        n /= 1024.0


def dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def gif_info(path):
    """读 GIF 头里的宽高；顺带确认文件不是坏的。"""
    try:
        with open(path, "rb") as fh:
            head = fh.read(10)
        if head[:3] != b"GIF":
            return None
        w = head[6] | (head[7] << 8)
        h = head[8] | (head[9] << 8)
        return {"w": w, "h": h, "bytes": os.path.getsize(path)}
    except OSError:
        return None


def collect():
    """从 roster 里挑出网页设计分类，读齐每个技能需要的元信息。"""
    roster = json.load(open(ROSTER, encoding="utf-8"))["skills"]
    picked, problems = [], []
    for entry in roster:
        if (entry.get("category") or "").strip() != CATEGORY:
            continue
        d = entry["dir"]
        sdir = os.path.join(SKILLS_SRC, d)
        mpath = os.path.join(sdir, "manifest.json")
        if not os.path.isfile(mpath):
            problems.append("%s：缺 manifest.json" % d)
            continue
        m = json.load(open(mpath, encoding="utf-8"))
        gif = os.path.join(sdir, "preview.gif")
        info = gif_info(gif) if os.path.isfile(gif) else None
        if not info:
            problems.append("%s：缺 preview.gif（规则要求每个网页设计技能必备）" % d)
        picked.append({
            "dir": d,
            "cn": m.get("display_name") or entry.get("cn") or d,
            "desc": m.get("description", ""),
            "repo": m["source"]["repo"],
            "url": m["source"]["url"],
            "sha": (m["source"].get("sha") or "")[:7],
            "license": m["upstream"].get("license", "—"),
            "category": m.get("category", CATEGORY),
            "size": dir_size(sdir),
            "gif": os.path.join(sdir, "preview.gif") if info else None,
            "ginfo": info,
            "caption": CAPTION.get(d, ""),
            "sub": SUBHINT.get(d),
        })
    return picked, problems


def card_html(it, idx):
    if it["ginfo"]:
        gi = it["ginfo"]
        img = ('<img src="previews/%s.gif" alt="%s 预览" width="%d" height="%d">'
               % (it["dir"], html.escape(it["cn"]), gi["w"], gi["h"]))
        gif_note = "%d×%d · %s" % (gi["w"], gi["h"], human(gi["bytes"]))
    else:
        img = '<div class="noimg">缺<br>preview.gif</div>'
        gif_note = "待补"

    sub = ""
    if it["sub"]:
        title, items = it["sub"]
        chips = "".join('<span class="chip">%s</span>' % html.escape(x) for x in items)
        sub = ('<div class="subs"><div class="subs-h">%s</div><div class="chips">%s</div></div>'
               % (html.escape(title), chips))

    return """    <article class="card%s">
      <div class="head">
        <div class="headinfo">
          <span class="no">%02d</span>
          <h2>%s</h2>
          <code class="id">%s</code>
        </div>
        <figure class="prev">%s<figcaption>%s</figcaption></figure>
      </div>
      <p class="desc">%s</p>
      %s
      <dl>
        <dt>源</dt><dd><a href="%s" target="_blank">%s</a></dd>
        <dt>提交</dt><dd><code>%s</code></dd>
        <dt>许可</dt><dd>%s</dd>
        <dt>体积</dt><dd>%s</dd>
        <dt>预览</dt><dd>%s</dd>
      </dl>
    </article>""" % (
        "" if it["ginfo"] else " missing",
        idx, html.escape(it["cn"]), it["dir"], img, html.escape(it["caption"] or gif_note),
        html.escape(it["desc"]), sub,
        it["url"], html.escape(it["repo"]), it["sha"], html.escape(it["license"]),
        human(it["size"]), gif_note)


def build_html(items, problems, total_bytes):
    cards = "\n".join(card_html(it, i) for i, it in enumerate(items, 1))
    warn = ""
    if problems:
        warn = ('<div class="warn"><strong>有 %d 项不符合规则：</strong>%s</div>'
                % (len(problems), "；".join(html.escape(p) for p in problems)))

    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>网页设计技能索引</title>
<style>
  :root { --ink:#16161a; --mute:#6b6b76; --line:#e6e6ec; --bg:#fbfbfd; --accent:#2f6fed; --bad:#c2410c; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC","Helvetica Neue",sans-serif; }
  .wrap { max-width:1240px; margin:0 auto; padding:52px 32px 80px; }
  header h1 { font-size:29px; letter-spacing:-.02em; margin:0 0 8px; }
  header p { color:var(--mute); margin:0; }
  .bar { display:flex; gap:34px; flex-wrap:wrap; margin:24px 0 34px; padding:16px 20px;
    background:#fff; border:1px solid var(--line); border-radius:14px; }
  .bar b { display:block; font-size:21px; font-weight:600; }
  .bar span { color:var(--mute); font-size:12.5px; }
  .warn { background:#fdf2ec; border:1px solid #f3d3c2; color:var(--bad);
    border-radius:12px; padding:12px 16px; font-size:13px; margin-bottom:26px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(370px,1fr)); gap:20px; }
  .card { background:#fff; border:1px solid var(--line); border-radius:16px; padding:20px;
    display:flex; flex-direction:column; border-top:3px solid var(--accent); }
  .card.missing { border-top-color:var(--bad); }
  .head { display:flex; gap:14px; align-items:flex-start; margin-bottom:12px; }
  .headinfo { flex:1; min-width:0; }
  .no { font-size:11px; color:var(--mute); font-variant-numeric:tabular-nums; }
  .card h2 { font-size:17px; margin:4px 0 6px; font-weight:600; line-height:1.35; }
  .id { font-size:11px; color:var(--accent); background:#f4f6fd; border-radius:5px;
    padding:2px 7px; display:inline-block; font-family:ui-monospace,Menlo,monospace; }
  .prev { margin:0; width:144px; flex:none; }
  .prev img { width:144px; height:94px; object-fit:cover; border-radius:9px;
    border:1px solid var(--line); display:block; background:#f2f3f7; }
  .prev figcaption { font-size:10px; color:#9b9ba6; line-height:1.45; margin-top:6px; }
  .noimg { width:144px; height:94px; border-radius:9px; border:1px dashed #d9c3b8;
    background:#fdf6f2; color:var(--bad); font-size:11px; display:flex;
    align-items:center; justify-content:center; text-align:center; }
  .desc { font-size:13px; color:#3d3d47; margin:0 0 12px; }
  .subs { background:#fafafd; border:1px solid var(--line); border-radius:10px;
    padding:11px 12px; margin-bottom:12px; }
  .subs-h { font-size:11px; color:var(--mute); margin-bottom:7px; }
  .chips { display:flex; flex-wrap:wrap; gap:5px; }
  .chip { font-size:11px; color:#3d3d47; background:#fff; border:1px solid var(--line);
    border-radius:5px; padding:2px 6px; }
  dl { display:grid; grid-template-columns:40px 1fr; gap:4px 8px; margin:0;
    font-size:12px; border-top:1px solid var(--line); padding-top:11px; margin-top:auto; }
  dt { color:var(--mute); }
  dd { margin:0; overflow-wrap:anywhere; }
  a { color:var(--accent); text-decoration:none; }
  a:hover { text-decoration:underline; }
  code { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
  .rules { margin-top:42px; background:#fff; border:1px solid var(--line);
    border-radius:16px; padding:24px 26px; }
  .rules h2 { font-size:16px; margin:0 0 6px; font-weight:600; }
  .rules .lead { font-size:12.5px; color:var(--mute); margin:0 0 16px; }
  .rules ol { margin:0; padding-left:20px; font-size:13px; color:#3d3d47; }
  .rules li { margin-bottom:9px; }
  .rules li b { color:var(--ink); }
  .rules code { background:#f4f5f9; border-radius:4px; padding:1px 5px; font-size:12px; }
  .rules .gate { margin-top:14px; padding:11px 14px; background:#fdf2ec;
    border:1px solid #f3d3c2; border-radius:10px; color:var(--bad); font-size:12.5px; }
  footer { margin-top:34px; color:var(--mute); font-size:12.5px; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>网页设计技能索引</h1>
    <p>本目录同时存放 zip、索引页与预览图。索引由脚本生成，不要手改。</p>
  </header>

  <div class="bar">
    <div><b>%d</b><span>网页设计技能</span></div>
    <div><b>%s</b><span>合计体积</span></div>
    <div><b>%d</b><span>预览图</span></div>
  </div>

  %s

  <div class="grid">
%s
  </div>

  <div class="rules">
    <h2>维护规则（硬性，新增技能必须照做）</h2>
    <p class="lead">本目录的索引、预览图与技能包必须始终一致。任何一项缺失都算「没做完」。</p>
    <ol>
      <li><b>新增网页设计技能时，必须同时更新本索引。</b>只加技能不改索引 = 未完成，不得推送。</li>
      <li><b>每项技能必须有 <code>preview.gif</code></b>，放在技能包根目录。规格：宽 ≤ 320px、≤ 20fps、
          文件 ≤ 800KB、<b>首帧亮度 &gt; 200</b>（黑屏开场的图不能当缩略图）。</li>
      <li><b>预览图要展示该技能最综合的效果</b>，不是随便一帧截图。交互类技能要录到真实操作过程。</li>
      <li><b>索引不手改。</b>改完技能后执行
          <code>python3 tools/build_web_index.py</code> 重新生成，
          它会同步 <code>previews/&lt;技能目录名&gt;.gif</code>。</li>
      <li><b>提交前必须过一致性检查</b>：
          <code>python3 tools/check_web_index.py</code>。
          它比对「索引里列的技能」与「roster 里的分类」、逐张核对 GIF 的 md5 是否与包内一致、
          尺寸是否超限。不通过会以非 0 退出。</li>
      <li><b>技能改名或移除</b>时，索引与 <code>previews/</code> 里的旧图必须一起清掉，
          不允许留下孤儿文件。</li>
    </ol>
    <div class="gate">检查命令不通过时，不要推仓库：先修到通过为止。<br>
      <code>python3 tools/build_web_index.py &amp;&amp; python3 tools/check_web_index.py</code></div>
  </div>

  <footer>
    数据来自 <code>roster.json</code>（category=网页设计）与各技能 <code>manifest.json</code>；
    预览图取自各技能包 <code>preview.gif</code>。
  </footer>
</div>
</body>
</html>
""" % (len(items), human(total_bytes),
       sum(1 for it in items if it["ginfo"]), warn, cards)


def sync_previews(items, out_dir):
    """把每个技能的 preview.gif 复制成 previews/<dir>.gif，并清掉孤儿。"""
    pdir = os.path.join(out_dir, "previews")
    os.makedirs(pdir, exist_ok=True)
    want = set()
    for it in items:
        if not it["gif"]:
            continue
        name = it["dir"] + ".gif"
        want.add(name)
        shutil.copy2(it["gif"], os.path.join(pdir, name))
    removed = []
    for f in os.listdir(pdir):
        if f.endswith(".gif") and f not in want:
            os.remove(os.path.join(pdir, f))
            removed.append(f)
    return removed


def main():
    items, problems = collect()
    total = sum(it["size"] for it in items)
    doc = build_html(items, problems, total)

    for out in (REPO_OUT, WORK_OUT):
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(doc)
        removed = sync_previews(items, out)
        print("✓ %s（%d 个技能，清掉孤儿 %d 个）" % (out, len(items), len(removed)))

    if problems:
        print("\n✗ 规则未满足：")
        for p in problems:
            print("   ·", p)
        return 1
    print("\n✓ 索引与预览一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
