# -*- coding: utf-8 -*-
"""B站专栏适配器 —— 纯 HTTP，无需登录。

实测要点（2026-09-03）
--------------------
1. 必须用 /x/web-interface/search/type，**不要**用 /wbi/search/type。
   带 wbi 的端点需要 w_rid 签名，不签名时返回 code=0 但 result 为空，
   属于「假成功」，最容易误判为「没数据」。
2. 必须先 GET https://www.bilibili.com/ 拿 buvid cookie，否则风控返回 -412。
3. search_type=article 检索专栏文章；实测「安全 面经」numResults=1000，
   20 条/页，标题质量高（长亭/华为/绿盟/4399 安全岗面经均精准命中）。
4. 返回字段 title/desc 内含 <em class="keyword"> 高亮标签，必须清洗。
5. pub_time 是**秒**级时间戳，注意 ×1000 转毫秒。
"""
import re
import time
import random

import requests

from normalize import make_item

SOURCE = "bilibili"
API = "https://api.bilibili.com/x/web-interface/search/type"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(s):
    return _TAG_RE.sub("", s or "").strip()


def _session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Referer": "https://search.bilibili.com/",
        "Accept": "application/json, text/plain, */*",
    })
    try:
        s.get("https://www.bilibili.com/", timeout=10)
    except requests.RequestException:
        pass
    return s


def fetch(queries, max_page=5, sleep_range=(0.5, 1.1), **kw):
    """检索 B站专栏。单源失败只打警告，不阻断整体流程。"""
    try:
        s = _session()
    except Exception as e:
        print("  [skip] bilibili: session 建立失败 %s" % e)
        return []

    pool = {}
    for qi, q in enumerate(queries, 1):
        before = len(pool)
        for page in range(1, max_page + 1):
            try:
                r = s.get(API, params={
                    "search_type": "article",
                    "keyword": q,
                    "page": page,
                }, timeout=20)
                j = r.json()
            except Exception as e:
                print("    [warn] bilibili %s p%d: %s" % (q, page, e))
                break

            if j.get("code") != 0:
                print("    [warn] bilibili %s code=%s %s"
                      % (q, j.get("code"), j.get("message")))
                break

            res = (j.get("data") or {}).get("result") or []
            if not res:
                break

            for it in res:
                aid = str(it.get("id") or "")
                if not aid or aid in pool:
                    continue
                ts = int(it.get("pub_time") or 0) * 1000
                pool[aid] = make_item(
                    SOURCE, aid,
                    title=_clean(it.get("title")),
                    url="https://www.bilibili.com/read/cv%s" % aid,
                    content=_clean(it.get("desc")),
                    author=it.get("mid") and str(it.get("mid")) or "",
                    ts=ts,
                    extra={
                        "view": it.get("view", 0),
                        "like": it.get("like", 0),
                        "category": it.get("category_name", ""),
                    },
                )
            time.sleep(random.uniform(*sleep_range))
        print("  [bilibili %2d/%d] %-24s new=%-4d pool=%d"
              % (qi, len(queries), q[:24], len(pool) - before, len(pool)))
    return list(pool.values())
