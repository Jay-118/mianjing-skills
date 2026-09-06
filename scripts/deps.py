# -*- coding: utf-8 -*-
"""依赖解析 —— 让本 skill 自带全部依赖，不再需要外部 skill 目录。

设计
----
所有需要 `chrome_launcher` / `xhs.*` / `nowcoder_api` 的模块，
统一 `import deps` 后调用 `deps.setup()`，之后就能正常 import。

查找顺序：
1. **内置 vendor/**（默认，随 skill 一起走，换设备零配置）
2. 外部 skill 目录（若存在且比 vendor 新，可用 IC_PREFER_EXTERNAL=1 优先）

为什么内联而不是依赖外部 skill
----------------------------
实测痛点：本 skill 原有 7 处硬编码 `~/.workbuddy/skills/{xiaohongshu-skills,
nowcoder-interview-crawler}/` 路径。换设备后这两个目录不会跟过来，
直接跑会全线报错，且用户得自己 clone + 建 venv。
内联后总共只多 105 KB，换来的是「复制一个目录即可用」。

vendor 内容来源（如需升级可重新复制）
-----------------------------------
* vendor/chrome_launcher.py  ← xiaohongshu-skills/scripts/chrome_launcher.py
* vendor/xhs/*.py            ← xiaohongshu-skills/scripts/xhs/
    实际用到 cdp(Browser/Page) + login + cookies，
    其余 stealth/errors/human/selectors/urls 是它们的内部依赖
* vendor/nowcoder_api.py     ← nowcoder-interview-crawler/scripts/nowcoder_api.py
上游项目：https://github.com/xpzouying/xiaohongshu-skills
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(_HERE, "vendor")

_EXT_XHS = os.path.join(os.path.expanduser("~"), ".workbuddy", "skills",
                        "xiaohongshu-skills", "scripts")
_EXT_NC = os.path.join(os.path.expanduser("~"), ".workbuddy", "skills",
                       "nowcoder-interview-crawler", "scripts")

_done = False
_source = None


def _has_vendor():
    return (os.path.isfile(os.path.join(VENDOR, "chrome_launcher.py"))
            and os.path.isfile(os.path.join(VENDOR, "xhs", "cdp.py")))


def setup():
    """把依赖目录加入 sys.path。返回 'vendor' / 'external' / None。"""
    global _done, _source
    if _done:
        return _source

    prefer_ext = os.environ.get("IC_PREFER_EXTERNAL") == "1"
    cands = []
    if prefer_ext:
        cands = [(_EXT_XHS, "external"), (VENDOR, "vendor")]
    else:
        cands = [(VENDOR, "vendor"), (_EXT_XHS, "external")]

    for path, tag in cands:
        if os.path.isfile(os.path.join(path, "chrome_launcher.py")):
            if path not in sys.path:
                sys.path.insert(0, path)
            _source = tag
            break

    # nowcoder_api 单独处理（vendor 里已有，外部作为补充）
    for path in (VENDOR, _EXT_NC):
        if os.path.isfile(os.path.join(path, "nowcoder_api.py")):
            if path not in sys.path:
                sys.path.insert(0, path)
            break

    _done = True
    return _source


def status():
    """返回各依赖的可用性，供 doctor.py 使用。"""
    setup()
    out = {"source": _source, "vendor_ok": _has_vendor()}
    for name, mod in (("chrome_launcher", "chrome_launcher"),
                      ("xhs.cdp", "xhs.cdp"),
                      ("xhs.login", "xhs.login"),
                      ("nowcoder_api", "nowcoder_api")):
        try:
            __import__(mod)
            out[name] = True
        except Exception as e:
            out[name] = "%s: %s" % (type(e).__name__, e)
    return out


# 便捷入口：import deps 时自动 setup，调用方无需显式调
setup()
