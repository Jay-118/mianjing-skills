# -*- coding: utf-8 -*-
"""牛客适配器 —— 直接复用 nowcoder-interview-crawler，不重写。

主力源，纯 HTTP 免登录，占总召回 70%+。
"""
import os
import sys

# 依赖已内联到 scripts/vendor/，deps 负责把它加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import deps  # noqa: E402  （import 时自动 setup）

from normalize import make_item

SOURCE = "nowcoder"


def available():
    try:
        import nowcoder_api  # noqa: F401
        return True
    except Exception:
        return False


def fetch(queries, max_page=12, cookie=None, **kw):
    """返回 list[标准 item]。依赖缺失时返回空列表并打印原因，不抛异常。"""
    try:
        from nowcoder_api import crawl
    except Exception as e:
        print("  [skip] nowcoder: 无法加载 nowcoder_api（%s）" % e)
        print("         预期位于 %s" % os.path.join(deps.VENDOR,
                                                 "nowcoder_api.py"))
        return []

    pool, _stats = crawl(queries, max_page=max_page, cookie=cookie)

    out = []
    for cid, f in pool.items():
        out.append(make_item(
            SOURCE, cid,
            title=f.get("title", ""),
            url=f.get("url", ""),
            content=f.get("content", ""),
            author=f.get("author", ""),
            ts=f.get("create_ts", 0),
            extra={
                "kind": f.get("kind", ""),
                "author_school": f.get("author_school", ""),
                "author_grad_year": f.get("author_grad_year", ""),
                "ip_location": f.get("ip_location", ""),
                "has_interview_exp": f.get("has_interview_exp", False),
            },
        ))
    return out
