# -*- coding: utf-8 -*-
"""
牛客网面经采集器 —— 纯 HTTP 接口逆向（无浏览器自动化）

逆向结论
--------
接口:   POST https://gw-c.nowcoder.com/api/sparta/pc/search
鉴权:   无需登录态（匿名可访问完整数据），Cookie 可选注入
Body:   {"query": str, "type": "post"|"all"|"subject", "page": int, "pageSize": int}
        注意 pageSize 服务端强制为 20，传入值被忽略
返回:   data.total / data.totalPage / data.records[]
        records[i].data.contentData -> {id,title,content,createTime,editTime,entityId,...}
        records[i].data.userBrief   -> {nickname,educationInfo,workTime,authDisplayInfo,...}
详情URL: https://www.nowcoder.com/discuss/{contentData.id}
        （/discuss/{entityId} 会 301 到 contentId 形式）

坑位
----
1. GET 请求返回 "Request method 'GET' not supported"，必须 POST
2. Body 必须 UTF-8 编码，Windows shell 下 curl 传中文会变 GBK 导致
   "Invalid UTF-8 middle byte"，所以用 Python 发包
3. 单关键词 total 上限约 400（20 页），需多关键词交叉扩大召回
"""
import json
import time
import random
import urllib.request
import urllib.error

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
API = "https://gw-c.nowcoder.com/api/sparta/pc/search"
POST_URL = "https://www.nowcoder.com/discuss/{}"


def search(query, page=1, type_="post", cookie=None, retry=3):
    """调用牛客搜索接口。返回 (total, totalPage, records)"""
    payload = {"query": query, "type": type_, "page": page, "pageSize": 20}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for attempt in range(retry):
        req = urllib.request.Request(API, data=data, method="POST")
        req.add_header("User-Agent", UA)
        req.add_header("Content-Type", "application/json;charset=UTF-8")
        req.add_header("Accept", "application/json, text/plain, */*")
        req.add_header("Referer", "https://www.nowcoder.com/")
        req.add_header("Origin", "https://www.nowcoder.com")
        if cookie:
            req.add_header("Cookie", cookie)
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                j = json.loads(r.read().decode("utf-8", "ignore"))
            if not j.get("success"):
                return 0, 0, []
            d = j.get("data") or {}
            return d.get("total") or 0, d.get("totalPage") or 0, d.get("records") or []
        except Exception as e:
            if attempt == retry - 1:
                print("    [warn] %s p%d failed: %s" % (query, page, e))
                return 0, 0, []
            time.sleep(1.5 * (attempt + 1))
    return 0, 0, []


def flatten(rec):
    """
    把一条 record 拍平成结构化字典。

    重要：牛客两种 type 返回结构不同，必须同时兼容
      type=all  -> rec["data"]["contentData"]  时间字段 createTime  URL /discuss/{id}
      type=post -> rec["momentData"]（顶层）    时间字段 createdAt   URL /feed/{id}
    早期版本只解析前者，导致 type=post 全部返回 None，池子为 0。
    """
    d = rec.get("data")
    # 某些聚合卡片(如课程/专题合集)的 data 是 list，必须防御，否则 .get 抛 AttributeError
    if not isinstance(d, dict):
        d = {}
    cd = d.get("contentData")
    if not isinstance(cd, dict):
        cd = {}
    ub = d.get("userBrief") or rec.get("userBrief")
    if not isinstance(ub, dict):
        ub = {}
    kind = "discuss"

    if not cd.get("id"):
        md = rec.get("momentData")
        cd = md if isinstance(md, dict) else {}
        kind = "feed"
    if not cd.get("id"):
        return None

    ct = cd.get("createTime") or cd.get("createdAt") or cd.get("showTime") or 0
    cid = str(cd.get("id"))
    if kind == "discuss":
        url = "https://www.nowcoder.com/discuss/%s" % cid
    else:
        # 2026-09-05 实测：feed 帖数字 id 路由已失效（对任何帖都显示"内容不存在"），
        # 正确 URL 必须用 momentData.uuid（32 位十六进制），游客可直接打开。
        fuuid = cd.get("uuid") or ""
        if fuuid:
            url = "https://www.nowcoder.com/feed/main/detail/%s" % fuuid
        else:
            url = "https://www.nowcoder.com/feed/main/detail/%s" % cid
    return {
        "content_id": cid,
        "entity_id": cd.get("entityId"),
        "kind": kind,
        "title": (cd.get("title") or cd.get("newTitle") or "").strip(),
        "content": (cd.get("content") or cd.get("newContent") or "").strip(),
        "create_ts": ct,
        "create_date": time.strftime("%Y-%m-%d", time.localtime(ct / 1000)) if ct else "",
        "year": int(time.strftime("%Y", time.localtime(ct / 1000))) if ct else 0,
        "author": ub.get("nickname") or "",
        "author_school": ub.get("educationInfo") or "",
        "author_grad_year": ub.get("workTime") or "",
        "author_tag": ub.get("authDisplayInfo") or "",
        "type_name": cd.get("typeName") or "",
        "ip_location": cd.get("ip4Location") or "",
        "has_interview_exp": bool(d.get("interviewExp")),
        "url": url,
    }


def safe_flatten(rec):
    """flatten 的容错包装：单条记录结构异常不应中断整轮采集"""
    try:
        return flatten(rec)
    except Exception:
        return None

def crawl(queries, max_page=20, cookie=None, sleep_range=(0.4, 0.9),
          types=("post", "all")):
    """多关键词 × 多 type 分页采集，按 content_id 去重"""
    pool = {}
    stats = []
    for qi, q in enumerate(queries, 1):
        got_before = len(pool)
        q_total = 0
        for t in types:
            total, total_page, recs = search(q, 1, type_=t, cookie=cookie)
            if total == 0:
                continue
            q_total = max(q_total, total)
            pages = min(total_page or 1, max_page)
            for r in recs:
                f = safe_flatten(r)
                if f:
                    pool.setdefault(f["content_id"], f)
            for p in range(2, pages + 1):
                _, _, rs = search(q, p, type_=t, cookie=cookie)
                if not rs:
                    break
                for r in rs:
                    f = safe_flatten(r)
                    if f:
                        pool.setdefault(f["content_id"], f)
                time.sleep(random.uniform(*sleep_range))
            time.sleep(random.uniform(*sleep_range))
        new = len(pool) - got_before
        print("[%2d/%d] %-28s total=%-5s new=%-4d pool=%d"
              % (qi, len(queries), q, q_total, new, len(pool)))
        stats.append((q, q_total, new))
    return pool, stats
