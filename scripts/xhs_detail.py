# -*- coding: utf-8 -*-
"""小红书笔记详情批量抓取 —— 补齐搜索接口拿不到的正文。

为什么需要
--------
`search-feeds` 只返回标题 + 封面 + 互动数，**没有正文**，
导致小红书源虽有 100+ 帖但产出 0 道题。
本脚本对指定帖子逐条调 `get-feed-detail`，拿到 `desc` 正文后
走标准归一流水线抽题。

实测结论（2026-09-03）
--------------------
* 返回结构：`{"note": {...}, "comments": [...]}`
  note 字段：noteId / title / **desc**（正文）/ type / time /
            ipLocation / user / interactInfo / imageList
* **xsec_token 必须完整**：长度 46 字符。截断（如只存 28 位）会导致
  「笔记不可访问」，错误信息误报为「触发了小红书验证」，
  实际是 token 无效 —— 别被错误文案带偏去查风控。
* **正文常远少于标题承诺**：「60道高频面试题逐字稿」正文只有 5 道，
  其余 55 道在 5 张图片里。这类是引流帖（评论区自己发「完整版在这」）。
  纯文本方案拿不到图内题目，**要如实告知用户，不要按标题数字宣称收获**。
* 成本：每条约 20~40 秒（子进程 + CDP 重连），建议只抓高价值帖。

用法
----
    python xhs_detail.py <题库json> --filter AI安全 --limit 15
    python xhs_detail.py <题库json> --ids id1,id2 --out D:/out/详情.json
"""
import os
import re
import sys
import json
import io
import time
import random


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deps  # noqa: E402  依赖已内联到 vendor/，import 时自动 setup

from normalize import make_item, pipeline          # noqa: E402
from output import write_all                       # noqa: E402

TOKEN_LEN_EXPECT = 46
PORT = 9222
_page = None


def _get_page():
    """惰性开一个 CDP page 并全局复用（避免每条重连，早期 43 秒/条的主因）。"""
    global _page
    if _page is not None:
        return _page
    import chrome_launcher as cl
    from xhs.cdp import Browser
    if not cl.is_chrome_running(PORT):
        try:
            cl.launch_chrome(port=PORT, headless=False)
            cl._wait_for_chrome(PORT, timeout=25.0)
        except Exception as e:
            print("  [!] Chrome 启动失败: %s" % e)
            return None
    try:
        br = Browser(port=PORT)
        br.connect()
        _page = br.get_or_create_page()
        return _page
    except Exception as e:
        print("  [!] CDP 连接失败: %s" % e)
        return None


def fetch_detail(feed_id, token):
    """抓单条详情。token 必须完整（46 字符）。返回 (dict, err)。"""
    if len(token) < TOKEN_LEN_EXPECT - 6:
        return None, "token 过短(%d)，疑被截断" % len(token)
    page = _get_page()
    if page is None:
        return None, "无可用页面"
    try:
        from xhs.feed_detail import get_feed_detail
        resp = get_feed_detail(page, feed_id, token)
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, str(e)[:60])
    d = resp.to_dict() if hasattr(resp, "to_dict") else resp
    if not isinstance(d, dict) or not (d.get("note") or {}).get("noteId"):
        return None, "响应无 note 数据"
    return d, None


def to_item(j):
    """把详情响应转成标准 item。

    imageList 每项形如：
      {"width": 2480, "height": 3507, "urlDefault": "http://sns-webpic-qc.xhscdn.com/..."}
    **必须把 urlDefault 存下来** —— 小红书大量题目在图片里（实测 9 帖共 55 张），
    只存数量的话后续无法做图片解析。
    """
    n = (j or {}).get("note") or {}
    nid = n.get("noteId")
    if not nid:
        return None
    ii = n.get("interactInfo") or {}
    u = n.get("user") or {}
    ts = 0
    try:
        ts = int(n.get("time") or 0)
    except (TypeError, ValueError):
        ts = 0
    imgs = n.get("imageList") or []
    return make_item(
        "xhs", nid,
        title=n.get("title") or "",
        url="https://www.xiaohongshu.com/explore/%s" % nid,
        content=n.get("desc") or "",
        author=u.get("nickname", ""),
        ts=ts,
        extra={
            "liked": ii.get("likedCount", ""),
            "collected": ii.get("collectedCount", ""),
            "comment": ii.get("commentCount", ""),
            "image_count": len(imgs),
            "image_urls": [im.get("urlDefault", "") for im in imgs
                           if isinstance(im, dict) and im.get("urlDefault")],
            "ip": n.get("ipLocation", ""),
        },
    )


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    src = sys.argv[1]
    kw, limit, out = None, 15, None
    ids = None
    if "--filter" in sys.argv:
        i = sys.argv.index("--filter")
        if i + 1 < len(sys.argv):
            kw = sys.argv[i + 1]
    if "--limit" in sys.argv:
        i = sys.argv.index("--limit")
        if i + 1 < len(sys.argv):
            limit = int(sys.argv[i + 1])
    if "--ids" in sys.argv:
        i = sys.argv.index("--ids")
        if i + 1 < len(sys.argv):
            ids = sys.argv[i + 1].split(",")
    if "--out" in sys.argv:
        i = sys.argv.index("--out")
        if i + 1 < len(sys.argv):
            out = sys.argv[i + 1]

    with io.open(src, encoding="utf-8") as f:
        d = json.load(f)
    posts = [p for p in (d.get("posts") or []) if p.get("source") == "xhs"]
    if ids:
        posts = [p for p in posts if p["uid"].split(":", 1)[1] in ids]
    elif kw:
        posts = [p for p in posts if kw in (p.get("title") or "")]
    posts = posts[:limit]
    if not posts:
        print("没有匹配的小红书帖子")
        return 1

    print("准备抓取 %d 条详情（每条约 20~40 秒）" % len(posts))
    got, fails = [], []
    for i, p in enumerate(posts, 1):
        nid = p["uid"].split(":", 1)[1]
        token = (p.get("extra") or {}).get("xsec_token") or ""
        j, err = fetch_detail(nid, token)
        if err:
            fails.append((p.get("title", "")[:30], err))
            print("  [%2d/%d] FAIL %-28s %s"
                  % (i, len(posts), p.get("title", "")[:28], err[:38]))
        else:
            it = to_item(j)
            if it:
                got.append(it)
                n_img = it["extra"]["image_count"]
                print("  [%2d/%d] OK   %-28s 正文 %d 字 / %d 图"
                      % (i, len(posts), it["title"][:28],
                         len(it["content"]), n_img))
        time.sleep(random.uniform(3.0, 6.0))

    print("")
    print("成功 %d / 失败 %d" % (len(got), len(fails)))
    if not got:
        return 1

    with_text = [g for g in got if len(g["content"]) > 40]
    print("有实质正文（>40字）：%d 条" % len(with_text))
    items, bank, funnel = pipeline(got, days=1825, keep_c=True)
    print("抽取题目：%d 道" % len(bank))

    outdir = os.path.dirname(out) if out else os.path.dirname(src)
    paths = write_all(outdir, "小红书详情", items, bank, funnel, [])
    print("")
    for k, v in paths.items():
        print("  %-5s %s" % (k, os.path.basename(v)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
