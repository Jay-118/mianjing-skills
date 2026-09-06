# -*- coding: utf-8 -*-
"""通过 CDP 读笔记页提取图片 URL —— 绕开被限流的 get-feed-detail。

为什么需要这条备用路径
--------------------
`cli.py get-feed-detail` 在短时间内重复调用会被风控
（报「没有捕获到 feed 详情数据」，实测 20 分钟内两轮即触发）。
本脚本改为直接用 CDP 打开笔记页，从 `window.__INITIAL_STATE__` 里取
`note.noteDetailMap[*].note.imageList`，拿到正文图 URL + desc 正文。

关键实测结论（2026-09-03）
------------------------
1. **必须在同一个 page 上先 navigate 再 evaluate**。
   `get_or_create_page()` 复用的是空白 tab，直接 evaluate 会得到 NO_STATE。
2. **不能扫全页 `<img src>`**：笔记页含大量推荐流缩略图（实测 30 个 URL
   里正文只有 3 张）。必须走 `__INITIAL_STATE__`，或退回
   `.note-slider-img` / `.swiper-slide` 容器内的图。
3. **`__INITIAL_STATE__` 不能用 Python json.loads 直接解析** ——
   里面含 `undefined` 等非标准值（实测在 char 19650 处报错）。
   正确做法是**在浏览器里用 JS 求值**后再 JSON.stringify 回传。
4. 页面需等 6~8 秒让前端渲染完，否则 state 里 imageList 可能为空。

用法
----
    python xhs_note_images.py <题库json> --filter AI安全 --outdir D:/out/笔记图片
"""
import os
import re
import sys
import json
import io
import time
import random

import requests

os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")

_XHS_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _XHS_SCRIPTS)
import deps  # noqa: E402  依赖已内联到 vendor/，import 时自动 setup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
MAX_WIDTH = 1600

# 在浏览器内求值：__INITIAL_STATE__ 含非标准 JS 值，必须由 JS 侧序列化
_JS_EXTRACT = """(function(){
  var s = window.__INITIAL_STATE__;
  if (!s) return 'NO_STATE';
  var m = (s.note && s.note.noteDetailMap) || {};
  var out = [];
  for (var k in m) {
    var n = m[k] && m[k].note;
    if (!n || !n.noteId) continue;
    var imgs = (n.imageList || []).map(function(x){
      return x.urlDefault || x.url || '';
    }).filter(Boolean);
    out.push({id: n.noteId, title: n.title || '',
              desc: n.desc || '', imgs: imgs});
  }
  return JSON.stringify(out);
})()"""


def _session():
    s = requests.Session()
    s.trust_env = False
    s.headers.update({"User-Agent": UA,
                      "Referer": "https://www.xiaohongshu.com/"})
    return s


def to_png(data, dst):
    try:
        from PIL import Image
    except ImportError:
        print("  [!] 需要 Pillow: uv pip install pillow")
        return None
    try:
        im = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return None
    if im.width > MAX_WIDTH:
        r = MAX_WIDTH / float(im.width)
        im = im.resize((MAX_WIDTH, int(im.height * r)), Image.LANCZOS)
    im.save(dst, "PNG")
    return im.width, im.height


def read_note(page, note_id, token, wait=7.0):
    """导航到笔记页并提取。返回 (dict, err)。"""
    url = "https://www.xiaohongshu.com/explore/%s?xsec_token=%s" % (
        note_id, token)
    page.navigate(url)
    try:
        page.wait_for_load(timeout=30.0)
    except Exception:
        pass
    time.sleep(wait)
    html = page.evaluate("document.documentElement.outerHTML") or ""
    title = re.search(r"<title>(.*?)</title>", html, re.S)
    title = title.group(1) if title else ""
    if "页面不见了" in title or "不存在" in title:
        return None, "页面不存在（token 可能失效）"
    try:
        raw = page.evaluate(_JS_EXTRACT)
    except Exception as e:
        return None, "evaluate 失败: %s" % type(e).__name__
    if not raw or raw == "NO_STATE":
        return None, "无 __INITIAL_STATE__（页面未渲染完或被拦）"
    try:
        arr = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None, "state 解析失败"
    for it in arr:
        if it.get("id") == note_id:
            return it, None
    return (arr[0], None) if arr else (None, "state 内无笔记数据")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    src = sys.argv[1]
    kw, ids, outdir, limit = None, None, None, 20
    for flag in ("--filter", "--ids", "--outdir", "--limit"):
        if flag in sys.argv:
            i = sys.argv.index(flag)
            if i + 1 < len(sys.argv):
                v = sys.argv[i + 1]
                if flag == "--filter":
                    kw = v
                elif flag == "--ids":
                    ids = v.split(",")
                elif flag == "--outdir":
                    outdir = v
                else:
                    limit = int(v)
    if not outdir:
        outdir = os.path.join(os.path.dirname(src), "笔记图片")

    with io.open(src, encoding="utf-8") as f:
        d = json.load(f)
    posts = [p for p in (d.get("posts") or []) if p.get("source") == "xhs"]
    if ids:
        posts = [p for p in posts if p["uid"].split(":", 1)[1] in ids]
    elif kw:
        posts = [p for p in posts if kw in (p.get("title") or "")]
    posts = posts[:limit]
    if not posts:
        print("没有匹配的帖子")
        return 1

    import chrome_launcher as cl
    from xhs.cdp import Browser
    if not cl.is_chrome_running(9222):
        print("[!] Chrome 未运行，请先: HOLD_MINUTES=50 python login_all.py --keepalive")
        return 1
    br = Browser(port=9222)
    br.connect()
    page = br.new_page("about:blank")   # 专用 tab，避免复用空白页导致 NO_STATE

    s = _session()
    os.makedirs(outdir, exist_ok=True)
    print("处理 %d 帖 -> %s" % (len(posts), outdir))
    index, total = [], 0

    for i, p in enumerate(posts, 1):
        nid = p["uid"].split(":", 1)[1]
        token = (p.get("extra") or {}).get("xsec_token") or ""
        title = (p.get("title") or "")[:28]
        info, err = read_note(page, nid, token)
        if err:
            print("  [%2d/%d] FAIL %-28s %s" % (i, len(posts), title, err))
            time.sleep(random.uniform(4.0, 8.0))
            continue

        imgs = info.get("imgs") or []
        desc = info.get("desc") or ""
        print("  [%2d/%d] OK   %-28s 正文 %d 字 / %d 图"
              % (i, len(posts), title, len(desc), len(imgs)))

        safe = "".join(c for c in title if c.isalnum() or c in "－—_ ").strip()
        sub = os.path.join(outdir, "%s_%s" % (safe or nid[:8], nid[:8]))
        os.makedirs(sub, exist_ok=True)
        paths = []
        for k, u in enumerate(imgs, 1):
            dst = os.path.join(sub, "p%02d.png" % k)
            if os.path.isfile(dst) and os.path.getsize(dst) > 10240:
                paths.append(dst)
                continue
            try:
                r = s.get(u, timeout=30)
                if r.status_code == 200 and len(r.content) > 2048:
                    if to_png(r.content, dst):
                        paths.append(dst)
            except requests.RequestException:
                pass
            time.sleep(random.uniform(0.5, 1.2))
        total += len(paths)
        if desc or paths:
            with io.open(os.path.join(sub, "正文.txt"), "w",
                         encoding="utf-8-sig", newline="") as f:
                f.write((desc or "(无正文)").replace("\n", "\r\n"))
            index.append({"note_id": nid, "title": info.get("title", ""),
                          "url": "https://www.xiaohongshu.com/explore/" + nid,
                          "desc_len": len(desc), "images": paths})
        print("        下载 %d 张" % len(paths))
        time.sleep(random.uniform(5.0, 9.0))

    with io.open(os.path.join(outdir, "index.json"), "w",
                 encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print("")
    print("成功 %d 帖，共 %d 张图" % (len(index), total))
    print("下一步：用 Read 工具直接读 PNG 提取题目")
    return 0


if __name__ == "__main__":
    sys.exit(main())
