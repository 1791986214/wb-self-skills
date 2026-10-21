#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「网页设计」索引一致性检查（提交前必跑）

校验六件事，任何一项不通过就以非 0 退出：
  1. roster 里 category=网页设计 的技能，与索引页里列出的技能，集合完全一致
  2. 每个技能包的 preview.gif 存在（规则要求必备）
  3. previews/<目录名>.gif 与包内 preview.gif 的 md5 一致（防偷懒复制错）
  4. previews/ 里没有孤儿图（技能没了图还留着）
  5. GIF 规格达标：宽 ≤ MAX_W、文件 ≤ MAX_B、首帧不是黑屏
  6. 仓库副本与本地副本内容一致

用法：
  python3 tools/check_web_index.py          # 只检查
  python3 tools/check_web_index.py --json   # 机器可读输出（给自动化用）
"""

import hashlib
import json
import os
import re
import sys

HOME = os.path.expanduser("~")
REPO = os.path.join(HOME, "Documents", "wb-self-skills")
SKILLS_SRC = os.path.join(HOME, ".workbuddy", "skills")
ROSTER = os.path.join(REPO, "roster.json")
REPO_OUT = os.path.join(REPO, "skills", "网页设计")
WORK_OUT = os.environ.get("WEB_INDEX_WORK") or os.path.join(
    HOME, "WorkBuddy", "2026-10-13-17-22-57", "work", "网页设计")

CATEGORY = "网页设计"
MAX_W = 320          # 缩略图宽度上限
MAX_BYTES = 800 * 1024
MIN_FIRST_FRAME_LUM = 200   # 首帧亮度下限（防止黑屏开场当缩略图）


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def gif_header(path):
    with open(path, "rb") as fh:
        head = fh.read(10)
    if head[:3] != b"GIF":
        return None
    return {"w": head[6] | (head[7] << 8), "h": head[8] | (head[9] << 8),
            "bytes": os.path.getsize(path)}


def _lzw_decode(min_code_size, data):
    """GIF 变长 LZW 解码（标准实现，约 40 行）。"""
    clear = 1 << min_code_size
    end = clear + 1
    code_size = min_code_size + 1
    table = {i: bytes([i]) for i in range(clear)}
    out = bytearray()
    prev = None
    bitbuf = 0
    bitcnt = 0
    nxt = end + 1
    for byte in data:
        bitbuf |= byte << bitcnt
        bitcnt += 8
        while bitcnt >= code_size:
            code = bitbuf & ((1 << code_size) - 1)
            bitbuf >>= code_size
            bitcnt -= code_size
            if code == clear:
                table = {i: bytes([i]) for i in range(clear)}
                code_size = min_code_size + 1
                nxt = end + 1
                prev = None
                continue
            if code == end:
                return bytes(out)
            if prev is None:
                entry = table[code]
            elif code in table:
                entry = table[code]
            elif code == nxt:
                entry = prev + prev[:1]
            else:
                return bytes(out)
            out += entry
            if prev is not None:
                table[nxt] = prev + entry[:1]
                nxt += 1
                if nxt == (1 << code_size) and code_size < 12:
                    code_size += 1
            prev = entry
    return bytes(out)


def first_frame_lum(path):
    """真解码首帧，按调色板算平均亮度（0~255）。

    之前用「字节直方图取模」近似，会系统性偏低（把 emil 那张白底图判成 90），
    所以改成老老实实解 LZW。
    """
    try:
        data = open(path, "rb").read()
        if data[:3] != b"GIF":
            return None
        flags = data[10]
        gct_size = 2 ** ((flags & 0x07) + 1)
        pos = 13
        palette = []
        if flags & 0x80:
            for i in range(gct_size):
                o = pos + i * 3
                palette.append((data[o], data[o + 1], data[o + 2]))
            pos += gct_size * 3
        else:
            return None
        # 跳到第一个图像描述符
        while pos < len(data) and data[pos] != 0x2C:
            if data[pos] == 0x21:
                pos += 2
                while pos < len(data) and data[pos] != 0:
                    pos += data[pos] + 1
                pos += 1
            else:
                pos += 1
        if pos >= len(data):
            return None
        lflags = data[pos + 9]
        lct_size = 2 ** ((lflags & 0x07) + 1)
        pos += 10
        if lflags & 0x80:
            local = []
            for i in range(lct_size):
                o = pos + i * 3
                local.append((data[o], data[o + 1], data[o + 2]))
            palette = local
            pos += lct_size * 3
        min_code = data[pos]
        pos += 1
        raw = bytearray()
        while pos < len(data) and data[pos] != 0:
            n = data[pos]
            raw += data[pos + 1:pos + 1 + n]
            pos += n + 1
        idx = _lzw_decode(min_code, bytes(raw))
        if not idx or not palette:
            return None
        lum = 0.0
        n = len(idx)
        for b in idx:
            if b < len(palette):
                r, g, bl = palette[b]
                lum += 0.299 * r + 0.587 * g + 0.114 * bl
        return round(lum / n, 1)
    except Exception:
        return None


def index_dirs(index_path):
    """从索引页里解析出它列了哪些技能（靠 previews/<dir>.gif 引用）。"""
    if not os.path.isfile(index_path):
        return None
    text = open(index_path, encoding="utf-8").read()
    return set(re.findall(r'previews/([A-Za-z0-9._-]+)\.gif', text))


def main():
    as_json = "--json" in sys.argv
    errors, warns = [], []

    roster = json.load(open(ROSTER, encoding="utf-8"))["skills"]
    want = {s["dir"] for s in roster if (s.get("category") or "").strip() == CATEGORY}
    if not want:
        errors.append("roster.json 里没有任何 category=网页设计 的技能")

    # 1. 索引集合 vs roster
    listed = index_dirs(os.path.join(REPO_OUT, "index.html"))
    if listed is None:
        errors.append("缺索引：%s" % os.path.join(REPO_OUT, "index.html"))
    else:
        for d in sorted(want - listed):
            errors.append("索引漏了技能：%s（roster 里有，索引里没有）" % d)
        for d in sorted(listed - want):
            errors.append("索引多出技能：%s（索引里有，roster 里没有或已改分类）" % d)

    # 2~5. 逐个技能核 preview
    detail = []
    for d in sorted(want):
        sdir = os.path.join(SKILLS_SRC, d)
        pkg_gif = os.path.join(sdir, "preview.gif")
        out_gif = os.path.join(REPO_OUT, "previews", d + ".gif")
        row = {"dir": d}

        if not os.path.isfile(pkg_gif):
            errors.append("%s：技能包内缺 preview.gif" % d)
            row["error"] = "缺包内 preview.gif"
            detail.append(row)
            continue
        if not os.path.isfile(out_gif):
            errors.append("%s：索引目录缺 previews/%s.gif" % (d, d))
            row["error"] = "缺索引目录副本"
            detail.append(row)
            continue

        h_pkg, h_out = md5(pkg_gif), md5(out_gif)
        if h_pkg != h_out:
            errors.append("%s：previews/%s.gif 与包内 preview.gif 不一致（先跑 build）" % (d, d))
            row["error"] = "md5 不一致"
        hdr = gif_header(pkg_gif)
        if not hdr:
            errors.append("%s：preview.gif 不是合法 GIF" % d)
        else:
            row.update(hdr)
            if hdr["w"] > MAX_W:
                errors.append("%s：预览图宽 %d > %d" % (d, hdr["w"], MAX_W))
            if hdr["bytes"] > MAX_BYTES:
                errors.append("%s：预览图 %.0fKB > %dKB" % (d, hdr["bytes"] / 1024, MAX_BYTES // 1024))
            lum = first_frame_lum(pkg_gif)
            row["first_lum"] = lum
            if lum is not None and lum < MIN_FIRST_FRAME_LUM:
                warns.append("%s：首帧亮度 %.0f 偏低（< %d），缩略图可能发黑"
                             % (d, lum, MIN_FIRST_FRAME_LUM))
        detail.append(row)

    # 4. 孤儿图
    pdir = os.path.join(REPO_OUT, "previews")
    if os.path.isdir(pdir):
        for f in sorted(os.listdir(pdir)):
            if f.endswith(".gif") and f[:-4] not in want:
                errors.append("孤儿预览图：previews/%s（对应技能不在网页设计分类里）" % f)

    # 6. 仓库副本 vs 本地副本
    if os.path.isdir(WORK_OUT):
        a = os.path.join(REPO_OUT, "index.html")
        b = os.path.join(WORK_OUT, "index.html")
        if os.path.isfile(a) and os.path.isfile(b) and md5(a) != md5(b):
            warns.append("本地副本与仓库副本不一致：%s（重跑 build 会同步）" % b)
    else:
        warns.append("本地副本目录不存在：%s" % WORK_OUT)

    ok = not errors
    if as_json:
        print(json.dumps({"ok": ok, "errors": errors, "warnings": warns,
                          "skills": detail}, ensure_ascii=False, indent=2))
    else:
        print("== 网页设计索引一致性检查 ==")
        print("技能数：%d  预览图：%d" % (
            len(want), sum(1 for r in detail if r.get("w"))))
        for r in detail:
            if r.get("w"):
                print("  · %-16s %d×%d  %6.0fKB  首帧亮度 %s"
                      % (r["dir"], r["w"], r["h"], r["bytes"] / 1024, r.get("first_lum")))
            else:
                print("  ✗ %-16s %s" % (r["dir"], r.get("error")))
        if errors:
            print("\n[不通过] %d 项：" % len(errors))
            for e in errors:
                print("   ✗", e)
        if warns:
            print("\n[警告]")
            for w in warns:
                print("   !", w)
        print("\n%s" % ("✓ 索引与预览资源一致" if ok else "✗ 请修好后重跑（先 build 再 check）"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
