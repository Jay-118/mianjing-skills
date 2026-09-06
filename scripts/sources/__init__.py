# -*- coding: utf-8 -*-
"""采集源注册表。

每个适配器统一暴露 fetch(queries, **kw) -> list[标准 item]，
内部自行处理失败并返回空列表，**绝不向上抛异常**，
保证单源故障不阻断整体采集。
"""
from sources import nowcoder, bilibili, xhs, zhihu, cnblogs

# 顺序即执行顺序：先跑免登录的纯 HTTP 源，浏览器源放后面
REGISTRY = {
    "nowcoder": nowcoder,   # 主力，纯 HTTP 免登录
    "bilibili": bilibili,   # 补充，纯 HTTP 免登录
    "zhihu": zhihu,         # 补充，需浏览器 + 登录
    "xhs": xhs,             # 补充，需浏览器 + 扫码登录
    "cnblogs": cnblogs,     # 长尾，需浏览器（有人机验证）
}

# 默认启用：五源全开，**牛客+小红书优先**（2026-09-05 用户指定：
# 牛客是笔试复盘主阵地、小红书独家公司最多），其余源随后补充。
# 浏览器源未登录/基建缺失时由各适配器优雅降级（打印 [skip] 返回空列表），
# 不影响免登录源；想省时间可显式 --sources nowcoder,xhs 只跑优先源。
DEFAULT_SOURCES = ("nowcoder", "xhs", "bilibili", "zhihu", "cnblogs")

NO_LOGIN_SOURCES = ("nowcoder", "bilibili")
BROWSER_SOURCES = ("zhihu", "xhs", "cnblogs")


def get(name):
    return REGISTRY.get(name)


def all_names():
    return list(REGISTRY.keys())
