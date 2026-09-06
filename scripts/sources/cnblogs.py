# -*- coding: utf-8 -*-
"""博客园适配器 —— 浏览器路径（纯 HTTP 被人机验证拦截，已实测）。

实测（2026-09-03）
-----------------
GET https://zzk.cnblogs.com/s/blogpost?Keywords=安全+面经 纯 requests：
  HTTP 200，但页面只有 ~6.8KB，标题为「搜索结果提示」，
  正文含「找到相关内容 0 篇」+「请完成人机验证」。
结论：博客园搜索已加人机验证，纯 HTTP 拿不到结果，必须浏览器渲染。

定位：长尾补充源，量少。浏览器不可用时静默跳过，不影响主流程。
"""
import re
import time
import random
from urllib.parse import quote

from normalize import make_item
from sources import _browser

SOURCE = "cnblogs"
SEARCH_URL = "https://zzk.cnblogs.com/s/blogpost?Keywords=%s&pageindex=%d"

_ITEM_RE = re.compile(
    r'class="searchItemTitle">\s*<a[^>]*href="([^"]+)"[^>]*>([\s\S]*?)</a>')
_DESC_RE = re.compile(r'class="searchCon">([\s\S]*?)</span>')
_DATE_RE = re.compile(r'class="searchItemInfo-publishDate">([\d\-]+)')
_AUTHOR_RE = re.compile(r'class="searchItemInfo-userName"[^>]*>([^<]*)<')
_TAG_RE = re.compile(r"<[^>]+>")
# 博客园搜索结果标题锚文本里会带「 - 作者名」后缀，须剥掉，
# 否则标题变成「安全岗春招面经总结 - 春告鳥」，影响分级判断与去重。
_AUTHOR_SUFFIX_RE = re.compile(r"\s+[-–—]\s+[^-–—]{1,20}$")


def _clean(s):
    return _TAG_RE.sub("", s or "").replace("&nbsp;", " ").strip()


def _clean_title(s):
    t = _clean(s)
    t2 = _AUTHOR_SUFFIX_RE.sub("", t).strip()
    # 剥完不能太短，否则说明原标题本身就很短，保留原样
    return t2 if len(t2) >= 6 else t


def fetch(queries, max_kw=30, max_page=4, sleep_range=(2.0, 4.0), **kw):
    br = _browser.try_browser(headless=False)
    if br is None:
        print("  [skip] cnblogs: 浏览器基建不可用")
        return []

    pool = {}
    try:
        with br as b:
            for qi, q in enumerate(queries[:max_kw], 1):
                before = len(pool)
                for page in range(1, max_page + 1):
                    html = b.html(SEARCH_URL % (quote(q), page),
                                  wait=3.5, scroll=1)
                    if "请完成人机验证" in html and "searchItemTitle" not in html:
                        print("  [skip] cnblogs: 触发人机验证，"
                              "请在 Chrome 中手动通过一次后重试")
                        return list(pool.values())
                    titles = _ITEM_RE.findall(html)
                    if not titles:
                        break
                    descs = _DESC_RE.findall(html)
                    dates = _DATE_RE.findall(html)
                    authors = _AUTHOR_RE.findall(html)
                    for i, (u, t) in enumerate(titles):
                        key = u.split("?")[0]
                        if key in pool:
                            continue
                        ts = 0
                        if i < len(dates):
                            try:
                                ts = int(time.mktime(time.strptime(
                                    dates[i], "%Y-%m-%d")) * 1000)
                            except ValueError:
                                ts = 0
                        pool[key] = make_item(
                            SOURCE, key, title=_clean_title(t), url=u,
                            content=_clean(descs[i]) if i < len(descs) else "",
                            author=_clean(authors[i]) if i < len(authors) else "",
                            ts=ts,
                        )
                    time.sleep(random.uniform(*sleep_range))
                print("  [cnblogs %2d/%d] %-20s new=%-4d pool=%d"
                      % (qi, min(len(queries), max_kw), q[:20],
                         len(pool) - before, len(pool)))
    except Exception as e:
        print("  [warn] cnblogs 中断: %s（已采集 %d 条）" % (e, len(pool)))
    return list(pool.values())
