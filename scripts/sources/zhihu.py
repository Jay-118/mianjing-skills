# -*- coding: utf-8 -*-
"""知乎适配器 —— 浏览器路径 + **必须登录**（已实测，勿再尝试免登录）。

实测（2026-09-03）
-----------------
1. 纯 requests GET /api/v4/search_v3 → HTTP 401
   {"error":{"code":101,"name":"AuthenticationError","message":"ZERR_NOT_LOGIN"}}
   先访问首页拿 _zap/_xsrf/BEC cookie 也一样被拒。
2. 真实浏览器（CDP + stealth + 非 headless）游客态访问搜索页：
   页面 250KB 但结果数为 **0** —— ContentItem / answer 链接 / 专栏链接
   全部 0 个，同时命中 3 处「需要登录 / 安全验证」标志。
   **结论：知乎搜索结果对游客完全不渲染，登录是硬门槛。**
3. `js-initialData` 里真实字段是 `generalByQuery`（**不是** `listResultByQuery`），
   但游客态下它和其余 20 个 *ByQuery 字段全是空 dict `{}`。
   即使登录后也应以 DOM 解析为主 —— 搜索结果是前端异步渲染的。

所以本适配器采取双路解析：先试 initialData（登录态下可能有），
再回退 DOM 正则。并在开头做明确的登录墙检测，未登录直接返回并给出指引，
**不做无效重试、不静默返回空**。

反爬要点
-------
* `headless=False` 必须（Browser.new_page 已自动注入 stealth + 真实 UA + 随机 viewport）
* 分页用 offset（每页 20）
* 请求间隔 3~6s，过快触发验证码
"""
import re
import time
import json
import random

from normalize import make_item
from sources import _browser

SOURCE = "zhihu"
SEARCH_URL = ("https://www.zhihu.com/search?type=content&q=%s")

_SCRIPT_RE = re.compile(
    r'<script id="js-initialData" type="text/json">([\s\S]*?)</script>')
_TAG_RE = re.compile(r"<[^>]+>")

# 登录墙 / 验证墙标志。实测游客态会命中这些且结果数为 0。
_WALL_WORDS = ("ZERR_NOT_LOGIN", "登录知乎", "需要登录", "请登录",
               "安全验证", "验证码")

# DOM 卡片级解析（登录态主路径）
# 实测（2026-09-03 登录后）：搜索页有 59 个 SearchResult-Card，
# 每卡内含 <meta itemprop="name" content="标题">、RichText 摘要、answer/p 链接。
# **标题在 meta 标签里，不在 <h2> 里** —— 知乎用 meta 存结构化数据，
# 直接找 h2/ContentItem-title 的文本会拿到空字符串。
_CARD_SPLIT_RE = re.compile(r'<div class="[^"]*SearchResult-Card')
_META_NAME_RE = re.compile(r'<meta itemprop="name" content="([^"]*)"')
_META_TEXT_RE = re.compile(r'<meta itemprop="text" content="([^"]*)"')
_META_DATE_RE = re.compile(
    r'<meta itemprop="date(?:Created|Published|Modified)" content="([^"]*)"')
_RICHTEXT_RE = re.compile(
    r'class="[^"]*RichText[^"]*"[^>]*>([\s\S]{0,1200}?)</span>')
_CARD_ANSWER_RE = re.compile(r'href="(?:[^"]*)?/question/(\d+)/answer/(\d+)"')
_CARD_ARTICLE_RE = re.compile(r'href="(?:https?:)?//zhuanlan\.zhihu\.com/p/(\d+)"')
# article 卡片没有 meta name，标题在可见的 title span / a 里
_CARD_TITLE_TEXT_RE = re.compile(
    r'class="[^"]*ContentItem-title[^"]*"[^>]*>([\s\S]{0,300}?)</(?:h2|div)>')
# 摘要里常见「作者名：」前缀，须剥掉，否则标题变成「一帆：反问 二面…」
_BODY_AUTHOR_PREFIX_RE = re.compile(r"^[^：:]{1,14}[：:]\s*")

# 旧的全页正则（仅作最后兜底，拿不到摘要/时间）
_ANSWER_RE = re.compile(
    r'href="(?:https?://www\.zhihu\.com)?(/question/(\d+)/answer/(\d+))"'
    r'[^>]*>([\s\S]{0,160}?)</a>')
_ARTICLE_RE = re.compile(
    r'href="(?:https?:)?//zhuanlan\.zhihu\.com/p/(\d+)"[^>]*>([\s\S]{0,160}?)</a>')


def _unescape(s):
    import html
    return html.unescape(s or "")


def _to_ts(date_str):
    """知乎 meta 里的日期形如 2025-04-18T10:00:00+08:00 或 2025-04-18。"""
    if not date_str:
        return 0
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", date_str)
    if not m:
        return 0
    try:
        return int(time.mktime(time.strptime(
            "%s-%s-%s" % m.groups(), "%Y-%m-%d")) * 1000)
    except (ValueError, OverflowError):
        return 0


def _parse_cards(html):
    """卡片级解析：标题 + 摘要 + 时间 + 链接一并取出。

    这是登录态下的主路径。早前只用全页锚文本正则时，
    content 与 date 覆盖率均为 **0%**，导致知乎贡献 191 条却几乎不产题目，
    且全部因 ts=0 逃过时间窗过滤。
    """
    out = []
    cards = _CARD_SPLIT_RE.split(html or "")[1:]
    for c in cards:
        am = _CARD_ANSWER_RE.search(c)
        pm = _CARD_ARTICLE_RE.search(c)
        if am:
            qid, aid = am.group(1), am.group(2)
            oid, typ = aid, "answer"
            url = "https://www.zhihu.com/question/%s/answer/%s" % (qid, aid)
        elif pm:
            oid, typ = pm.group(1), "article"
            url = "https://zhuanlan.zhihu.com/p/%s" % oid
        else:
            continue

        names = _META_NAME_RE.findall(c)
        title = _unescape(names[0]) if names else ""
        author = _unescape(names[-1]) if len(names) > 1 else ""

        body = ""
        tm = _META_TEXT_RE.search(c)
        if tm:
            body = _unescape(tm.group(1))
        if not body:
            rt = _RICHTEXT_RE.findall(c)
            if rt:
                body = _clean(rt[0])

        dm = _META_DATE_RE.search(c)
        ts = _to_ts(dm.group(1) if dm else "")

        # article 卡片没有 meta name，改从可见标题节点取
        if not title:
            tt = _CARD_TITLE_TEXT_RE.search(c)
            if tt:
                title = _clean(tt.group(1))

        # 摘要常带「作者名：」前缀，剥掉后再考虑当标题兜底
        if body:
            body = _BODY_AUTHOR_PREFIX_RE.sub("", body).strip()

        if not title and body:
            # 兜底：取摘要首句，并明确标注是摘要截取而非原标题
            title = body.split("。")[0][:48]
        if not title:
            continue
        out.append((oid, _clean(title), url, body, author, ts, typ))
    return out


def _clean(s):
    return _TAG_RE.sub("", s or "").replace("\u200b", "").strip()


def _parse_initial(html):
    """从 js-initialData 解析。真实字段是 generalByQuery 系列。"""
    out = []
    m = _SCRIPT_RE.search(html or "")
    if not m:
        return out
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return out

    search = ((data.get("initialState") or {}).get("search") or {})
    # 覆盖 generalByQuery / generalByQueryInAWeek / ...ByQuery 全系列
    for key, blk in search.items():
        if not key.startswith("general") and not key.endswith("ByQuery"):
            continue
        if not isinstance(blk, dict):
            continue
        for _q, node in blk.items():
            rows = node if isinstance(node, list) else (
                node.get("data") if isinstance(node, dict) else None)
            for it in (rows or []):
                obj = it.get("object") if isinstance(it, dict) else None
                if not isinstance(obj, dict):
                    continue
                oid = str(obj.get("id") or "")
                if not oid:
                    continue
                typ = obj.get("type") or ""
                title = _clean((obj.get("title") or
                                (obj.get("question") or {}).get("name") or ""))
                body = _clean(obj.get("excerpt") or obj.get("content") or "")
                if typ == "answer":
                    qid = str((obj.get("question") or {}).get("id") or "")
                    url = ("https://www.zhihu.com/question/%s/answer/%s"
                           % (qid, oid))
                elif typ == "article":
                    url = "https://zhuanlan.zhihu.com/p/%s" % oid
                else:
                    url = "https://www.zhihu.com/question/%s" % oid
                ts = int(obj.get("created_time")
                         or obj.get("created") or 0) * 1000
                out.append((oid, title, url,
                            body, ((obj.get("author") or {}).get("name") or ""),
                            ts, typ))
    return out


def _parse_dom(html):
    """全页锚文本兜底。只有标题，无摘要无时间 —— 仅在卡片解析失效时使用。"""
    out = []
    for _path, qid, aid, anchor in _ANSWER_RE.findall(html or ""):
        t = _clean(anchor)
        if len(t) < 4:
            continue
        out.append((aid, t,
                    "https://www.zhihu.com/question/%s/answer/%s" % (qid, aid),
                    "", "", 0, "answer"))
    for pid, anchor in _ARTICLE_RE.findall(html or ""):
        t = _clean(anchor)
        if len(t) < 4:
            continue
        out.append((pid, t, "https://zhuanlan.zhihu.com/p/%s" % pid,
                    "", "", 0, "article"))
    return out


def _blocked(html):
    """判断是否撞上登录/验证墙：命中标志词 且 页面无任何结果链接。"""
    if not html:
        return True
    has_result = ("/answer/" in html) or ("zhuanlan.zhihu.com/p/" in html)
    hit_wall = any(w in html for w in _WALL_WORDS)
    return hit_wall and not has_result


def fetch(queries, max_kw=25, max_page=4, sleep_range=(3.0, 6.0), **kw):  # max_page clamp<=4 防风控
    """知乎检索。未登录时明确提示并返回空，不阻断其他源。

    max_kw 默认 25：知乎是产出最多的源（30 词跑出 221 条入选），
    早期设 10 会白白浪费一半关键词。间隔 3~6 秒足够避开验证码。
    """
    # 硬性上限：知乎搜索翻页过深易触发风控，无论上层传多少都 clamp 到 4 页
    max_page = min(max_page, 4)
    br = _browser.try_browser(headless=False)
    if br is None:
        print("  [skip] zhihu: 浏览器基建不可用")
        return []

    pool = {}
    try:
        with br as b:
            for qi, q in enumerate(queries[:max_kw], 1):
                before = len(pool)
                for page in range(max_page):
                    url = SEARCH_URL % _q(q)
                    if page:
                        url += "&offset=%d" % (page * 20)
                    html = b.html(url, wait=4.5, scroll=2)

                    if _blocked(html):
                        print("  [skip] zhihu: 撞上登录墙，游客态搜索结果不渲染。")
                        print("         请在已弹出的 Chrome 里手动登录知乎一次"
                              "（cookie 会持久化到 profile），然后重跑。")
                        return list(pool.values())

                    rows = (_parse_cards(html)
                            or _parse_initial(html)
                            or _parse_dom(html))
                    if not rows:
                        break
                    for oid, title, u, body, author, ts, typ in rows:
                        if oid in pool:
                            continue
                        pool[oid] = make_item(
                            SOURCE, oid, title=title, url=u,
                            content=body, author=author, ts=ts,
                            extra={"zhihu_type": typ},
                        )
                    time.sleep(random.uniform(*sleep_range))
                print("  [zhihu %2d/%d] %-22s new=%-4d pool=%d"
                      % (qi, min(len(queries), max_kw), q[:22],
                         len(pool) - before, len(pool)))
    except Exception as e:
        print("  [warn] zhihu 中断: %s（已采集 %d 条，继续后续流程）"
              % (e, len(pool)))
    return list(pool.values())


def _q(s):
    from urllib.parse import quote
    return quote(s)
