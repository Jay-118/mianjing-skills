# -*- coding: utf-8 -*-
"""下载小红书笔记图片并转成可读 PNG —— 补齐"题目在图里"的缺口。

背景
----
小红书大量面经把题目做成图片长文（实测 9 条 AI 安全帖共 55 张图），
`note.desc` 正文往往只有开头几道，其余全在图里。纯文本方案拿不到。

本脚本负责「取图」这一步：下载 + 转码 + 按需缩放，产出可直接阅读的 PNG。
**图片内容的识别由模型直接读图完成**（比传统 OCR 更能处理带样式的中文排版、
彩色星级标记、多级标题），因此这里不引入 OCR 依赖。

实测结论（2026-09-03）
--------------------
* `imageList[i].urlDefault` 可直接 GET，**无防盗链**，
  但建议带 `Referer: https://www.xiaohongshu.com/`（更稳）
* 返回 `image/webp`，需转 PNG 才便于阅读
* 声明尺寸 2480×3507，实际下载多为 1080×1527 —— 已足够读清正文
* 单图 80~150 KB，下载约 1~2 秒
* 图片内容质量很高：带目录结构、分类标题、★出题频率、（考察XX）标注，
  是正式排版的题库文档，远比正文摘要完整

用法
----
    python xhs_images.py <题库json> --filter AI安全 --outdir D:/out/imgs
    python xhs_images.py <题库json> --ids <noteId> --max-img 8
"""
import os
import sys
import json
import io
import time
import random

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Referer": "https://www.xiaohongshu.com/"}
MAX_WIDTH = 1600          # 超过则等比缩到此宽度，保证文字可读又不过大


def _session():
    s = requests.Session()
    s.trust_env = False   # 绕开沙箱代理，避免 502
    s.headers.update(HEADERS)
    return s


def to_png(webp_bytes, dst):
    """webp -> PNG，过宽则等比缩放。返回 (w, h) 或 None。"""
    try:
        from PIL import Image
    except ImportError:
        print("  [!] 需要 Pillow：uv pip install pillow")
        return None
    try:
        im = Image.open(io.BytesIO(webp_bytes)).convert("RGB")
    except Exception as e:
        print("  [!] 解码失败: %s" % e)
        return None
    if im.width > MAX_WIDTH:
        r = MAX_WIDTH / float(im.width)
        im = im.resize((MAX_WIDTH, int(im.height * r)), Image.LANCZOS)
    im.save(dst, "PNG")
    return im.width, im.height


def download_post(s, post, outdir, max_img=0):
    """下载单帖全部图片。返回本地 PNG 路径列表。"""
    urls = (post.get("extra") or {}).get("image_urls") or []
    if not urls:
        return []
    if max_img:
        urls = urls[:max_img]
    nid = post["uid"].split(":", 1)[1]
    safe = "".join(c for c in (post.get("title") or "")[:16]
                   if c.isalnum() or c in "－—_ ").strip() or nid[:8]
    sub = os.path.join(outdir, "%s_%s" % (safe, nid[:8]))
    os.makedirs(sub, exist_ok=True)

    out = []
    for i, u in enumerate(urls, 1):
        dst = os.path.join(sub, "p%02d.png" % i)
        if os.path.isfile(dst) and os.path.getsize(dst) > 10240:
            out.append(dst)
            continue
        try:
            r = s.get(u, timeout=30)
            if r.status_code != 200 or len(r.content) < 2048:
                print("    [warn] 图%d HTTP %s (%d B)"
                      % (i, r.status_code, len(r.content)))
                continue
            size = to_png(r.content, dst)
            if size:
                out.append(dst)
        except requests.RequestException as e:
            print("    [warn] 图%d 下载失败: %s" % (i, type(e).__name__))
        time.sleep(random.uniform(0.6, 1.4))
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    src = sys.argv[1]
    kw, ids, outdir, max_img = None, None, None, 0
    for flag, setter in (("--filter", "kw"), ("--ids", "ids"),
                         ("--outdir", "outdir"), ("--max-img", "max_img")):
        if flag in sys.argv:
            i = sys.argv.index(flag)
            if i + 1 < len(sys.argv):
                v = sys.argv[i + 1]
                if setter == "kw":
                    kw = v
                elif setter == "ids":
                    ids = v.split(",")
                elif setter == "outdir":
                    outdir = v
                else:
                    max_img = int(v)
    if not outdir:
        outdir = os.path.join(os.path.dirname(src), "笔记图片")

    with io.open(src, encoding="utf-8") as f:
        d = json.load(f)
    posts = [p for p in (d.get("posts") or []) if p.get("source") == "xhs"]
    if ids:
        posts = [p for p in posts if p["uid"].split(":", 1)[1] in ids]
    elif kw:
        posts = [p for p in posts if kw in (p.get("title") or "")]
    posts = [p for p in posts
             if (p.get("extra") or {}).get("image_urls")]
    if not posts:
        print("没有带 image_urls 的帖子。")
        print("提示：需先用 xhs_detail.py 抓详情（搜索结果不含图片 URL）。")
        return 1

    os.makedirs(outdir, exist_ok=True)
    s = _session()
    print("准备下载 %d 帖的图片 -> %s" % (len(posts), outdir))
    total, index = 0, []
    for i, p in enumerate(posts, 1):
        n = len((p.get("extra") or {}).get("image_urls") or [])
        print("  [%d/%d] %-30s %d 张" % (i, len(posts),
                                        (p.get("title") or "")[:28], n))
        paths = download_post(s, p, outdir, max_img)
        total += len(paths)
        if paths:
            index.append({
                "title": p.get("title", ""),
                "url": p.get("url", ""),
                "liked": (p.get("extra") or {}).get("liked", ""),
                "images": paths,
            })
        print("        -> 成功 %d 张" % len(paths))

    idx_path = os.path.join(outdir, "index.json")
    with io.open(idx_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print("")
    print("共下载 %d 张，索引: %s" % (total, idx_path))
    print("下一步：直接读这些 PNG 提取题目（模型读图优于传统 OCR）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
