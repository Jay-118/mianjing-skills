# -*- coding: utf-8 -*-
"""小红书适配器 —— 直接调用内联的 xhs 库（不再走子进程 CLI）。

实测结论（2026-09-03，Windows）
-----------------------------
1. 依赖已内联到 `scripts/vendor/`，**不再需要外部 xiaohongshu-skills 目录**。
   上游项目：https://github.com/xpzouying/xiaohongshu-skills
2. **从子进程改为直接调库**：早期每个关键词都 `subprocess.run` 起一次
   `cli.py`、各自重连 CDP，实测 30 词耗时 21.5 分钟（约 43 秒/词）。
   改为单进程内复用一个 Browser + Page 后，开销只剩真实网络往返。
3. 采集只读，绝不点赞/评论/关注，避免账号风控。

搜索返回结构（已实测核对，字段名是**驼峰**）
------------------------------------------
```json
{"feeds": [{
    "id": "69d642b9...", "xsecToken": "AB9uwav...",   // 不是 xsec_token
    "displayTitle": "京东安全工程师实习岗面经",          // 不是 title
    "user": {"userId": "...", "nickname": "网敌小A"},
    "interactInfo": {"likedCount": "108", "collectedCount": "125"},
    "cover": "http://sns-webpic-qc.xhscdn.com/..."
}], "count": 44}
```
**关键限制：搜索结果没有正文字段**，只有标题 + 封面 + 互动数。
想拿正文须对每条另调 `xhs_detail.py`（详情接口），成本高且易风控，
因此这里 `content` 留空。早期误用下划线命名导致 42 条标题摘要全空。

内容质量预期（务必如实告知用户）
------------------------------
小红书面经多为图片九宫格 + 短口语文案，文字里常常没有题目 ——
真正的题目在图片里，须用 `xhs_note_images.py` 取图后读图。
本源定位是**补充**（独家公司多），不是题目主力。
"""
import os
import sys
import json
import time
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import deps  # noqa: E402  依赖已内联到 vendor/，import 时自动 setup

from normalize import make_item  # noqa: E402

SOURCE = "xhs"
PORT = int(os.environ.get("IC_CDP_PORT", "9222"))


def available():
    """依赖是否就绪（vendor 内联后基本恒为 True）。"""
    try:
        import chrome_launcher  # noqa: F401
        from xhs.cdp import Browser  # noqa: F401
        from xhs.search import search_feeds  # noqa: F401
        return True
    except Exception as e:
        print("  [warn] xhs 依赖加载失败: %s" % e)
        return False


def _open_page():
    """确保 Chrome 在跑并返回 (browser, page)。失败返回 (None, None)。"""
    import chrome_launcher as cl
    from xhs.cdp import Browser
    if not cl.is_chrome_running(PORT):
        try:
            cl.launch_chrome(port=PORT, headless=False)
            cl._wait_for_chrome(PORT, timeout=25.0)
        except Exception as e:
            print("  [skip] xhs: Chrome 启动失败 %s" % e)
            return None, None
    try:
        br = Browser(port=PORT)
        br.connect()
        return br, br.get_or_create_page()
    except Exception as e:
        print("  [skip] xhs: CDP 连接失败 %s" % e)
        return None, None


def check_login(page=None):
    """返回 (logged_in, info)。page 为 None 时自行开一个。"""
    from xhs import login as xlogin
    own = page is None
    br = None
    if own:
        br, page = _open_page()
        if page is None:
            return False, {"error": "无法打开页面"}
    try:
        # 先尝试 cookie 恢复，再判断状态
        try:
            xlogin.try_cookie_login(page)
        except Exception:
            pass
        ok = xlogin.check_login_status(page)
        return bool(ok), {}
    except Exception as e:
        return False, {"error": "%s: %s" % (type(e).__name__, e)}


def _to_item(f):
    """把 Feed 对象/字典转成标准 item。"""
    d = f.to_dict() if hasattr(f, "to_dict") else f
    fid = str(d.get("id") or "")
    if not fid:
        return None, None
    token = d.get("xsecToken") or ""
    url = ("https://www.xiaohongshu.com/explore/%s%s"
           % (fid, "?xsec_token=%s" % token if token else ""))
    user = d.get("user") or {}
    inter = d.get("interactInfo") or {}
    return fid, make_item(
        SOURCE, fid,
        title=d.get("displayTitle") or "",
        url=url,
        content="",          # 搜索结果不含正文，见模块 docstring
        author=user.get("nickname", "") if isinstance(user, dict) else "",
        ts=0,
        extra={"xsec_token": token,
               "liked": inter.get("likedCount", ""),
               "collected": inter.get("collectedCount", ""),
               "comment": inter.get("commentCount", ""),
               "note_type": d.get("type", "")},
    )


def _search_feeds_scrolled(page, keyword, filt, scroll_rounds=2):
    """带滚动翻页的单词搜索：首屏 + 滚动触发懒加载，多屏合并。

    与 vendor 的 search_feeds 同思路（__INITIAL_STATE__.search.feeds），
    但在提取前滚动 scroll_rounds 次触发信息流懒加载，每词深度约
    (1+scroll_rounds) 屏 × 20 条。滚动在单次导航内完成，导航间状态不共享。
    """
    from xhs.search import _EXTRACT_SEARCH_JS, _apply_filters, _convert_filters
    from xhs.urls import make_search_url
    from xhs.human import sleep_random
    from xhs.errors import NoFeedsError
    from xhs.types import Feed

    page.navigate(make_search_url(keyword))
    page.wait_for_load()
    page.wait_dom_stable()
    sleep_random(1500, 3000)

    # 等 feeds 有数据（沿用 vendor 的就绪判断）
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            if page.evaluate("!!(window.__INITIAL_STATE__&&window.__INITIAL_STATE__.search&&window.__INITIAL_STATE__.search.feeds)"):
                break
        except Exception:
            pass
        time.sleep(0.5)

    if filt:
        try:
            _apply_filters(page, _convert_filters(filt))
        except Exception as e:
            print("    [warn] xhs 筛选应用失败: %s" % type(e).__name__)

    # 首屏提取 + 逐屏滚动合并（按笔记 id 去重）
    merged, order = {}, []
    def _extract():
        result = page.evaluate(_EXTRACT_SEARCH_JS)
        if not result:
            return 0
        new = 0
        for f in json.loads(result):
            fid = str(f.get("id") or "")
            if fid and fid not in merged:
                merged[fid] = f
                order.append(f)
                new += 1
        return new

    total_new = _extract()
    for r in range(max(0, scroll_rounds)):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        sleep_random(1200, 2200)  # 等懒加载注入
        total_new += _extract()

    if not order:
        raise NoFeedsError()
    return [Feed.from_dict(f) for f in order]


def fetch(queries, max_kw=30, scroll=4, sleep_range=(2.0, 4.0), **kw):
    """搜索笔记。未登录则跳过并给出明确指引，不做无效重试。

    max_kw=30：实测 30 词连续跑未被限流；早期设 8 过于保守。
    scroll=4：每词滚动 4 次触发懒加载（首屏+4 屏 ≈ 100+ 条/词）；
    发布时间筛选用"不限"——面板没有"一年内"选项，25/26 年内容
    的时裁交由 normalize 时间窗（--days）完成。
    """
    if not available():
        return []

    from xhs.types import FilterOption

    br, page = _open_page()
    if page is None:
        return []

    ok, info = check_login(page)
    if not ok:
        print("  [skip] xhs: 未登录，本次跳过小红书源")
        print("         登录: python xhs_login_watch.py"
              "（扫码，二维码每 100 秒自动续期）")
        if info.get("error"):
            print("         detail: %s" % info["error"])
        return []

    # 时间不限：面板无"一年内"选项；25/26 年内容由下游 --days 裁剪
    filt = FilterOption(sort_by="", note_type="",
                        publish_time="", search_scope="", location="")
    pool = {}
    total = min(len(queries), max_kw)
    for qi, q in enumerate(queries[:max_kw], 1):
        before = len(pool)
        try:
            feeds = _search_feeds_scrolled(page, q, filt, scroll_rounds=scroll) or []
        except Exception as e:
            print("    [warn] xhs 搜索失败 %s: %s" % (q[:16], type(e).__name__))
            feeds = []
        for f in feeds:
            try:
                fid, item = _to_item(f)
            except Exception:
                continue
            if fid and fid not in pool and item:
                pool[fid] = item
        print("  [xhs %2d/%d] %-24s new=%-4d pool=%d"
              % (qi, total, q[:24], len(pool) - before, len(pool)))
        time.sleep(random.uniform(*sleep_range))
    return list(pool.values())
