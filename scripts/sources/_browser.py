# -*- coding: utf-8 -*-
"""CDP 浏览器桥 —— 复用 xiaohongshu-skills 的 Chrome + CDP 基建。

为什么需要这个模块
----------------
知乎、博客园都做了反爬，纯 HTTP 拿不到数据（实测见下），必须用真实浏览器。
而 xiaohongshu-skills 已内置一套可用基建（依赖只有 requests + websockets，
CDP 直连，非 Playwright），直接复用比自己再写一套划算。

实测证据（2026-09-03）
--------------------
* 知乎 /api/v4/search_v3 纯 requests：HTTP 401
  {"error":{"code":101,"name":"AuthenticationError","message":"ZERR_NOT_LOGIN"}}
* 博客园 zzk.cnblogs.com 纯 requests：返回「搜索结果提示」页，
  正文含「请完成人机验证」，命中 0 篇

真实 API 签名（**必须照抄，别凭直觉猜**）
--------------------------------------
    from xhs.cdp import Browser
    browser = Browser(port=9222)      # 不是 CDPClient(port=...)
    browser.connect()                 # 从 /json/version 取 webSocketDebuggerUrl
    page = browser.new_page(url)      # new_page 挂在 Browser 上，不在 CDPClient 上

踩坑记录：初版误以为是 `CDPClient(port=...)` + `client.connect()` +
`client.new_page()`。实际 `CDPClient.__init__` 只收 `ws_url`，且它既没有
`connect()` 也没有 `new_page()` —— 那两个方法属于 `Browser`。
若不核实签名，三个浏览器源全是跑不起来的死代码。

额外收获：`Browser.new_page()` 内部已自动调 `_setup_page()`，
完成 inject_stealth + 真实 UA + 随机 viewport（1366~1920 × 768~1080）
+ 禁用 geolocation/notifications 等权限探测。
这正是知乎反爬所需，**不要再手动重复注入**。
"""
import os
import sys
import time

# 依赖已内联到 scripts/vendor/，deps 负责把它加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import deps  # noqa: E402


def _ensure_path():
    deps.setup()


def available():
    try:
        import chrome_launcher  # noqa: F401
        from xhs.cdp import Browser as _B  # noqa: F401
        return True
    except Exception:
        return False


class Browser(object):
    """极简封装：确保 Chrome 在跑、开页面、取渲染后 HTML。

    headless 必须为 False —— 知乎会检测 headless 特征。
    """

    def __init__(self, port=9222, headless=False, reuse_tab=True):
        self.port = port
        self.headless = headless
        self.reuse_tab = reuse_tab
        self._browser = None
        self._page = None

    def __enter__(self):
        _ensure_path()
        import chrome_launcher
        from xhs.cdp import Browser as XhsBrowser

        # ensure_chrome 会在端口未监听时启动，已在跑则复用
        if not chrome_launcher.is_chrome_running(self.port):
            chrome_launcher.launch_chrome(port=self.port,
                                          headless=self.headless)
            chrome_launcher._wait_for_chrome(self.port, timeout=20.0)

        self._browser = XhsBrowser(port=self.port)
        self._browser.connect()
        # 复用空白 tab，避免 tab 无限堆积
        if self.reuse_tab and hasattr(self._browser, "get_or_create_page"):
            self._page = self._browser.get_or_create_page()
        else:
            self._page = self._browser.new_page("about:blank")
        return self

    def __exit__(self, *a):
        # 不主动 close page：复用 tab 模式下关掉会影响后续调用；
        # Chrome 进程本身留给用户，便于手动登录后 cookie 持久化。
        return False

    def html(self, url, wait=3.0, scroll=0):
        """导航到 url，返回渲染后 HTML。scroll 为向下滚动次数（触发懒加载）。"""
        p = self._page
        p.navigate(url)
        try:
            p.wait_for_load(timeout=30.0)
        except Exception:
            pass
        time.sleep(wait)
        try:
            p.wait_dom_stable(timeout=8.0)
        except Exception:
            pass
        for _ in range(scroll):
            try:
                p.scroll_to_bottom()
            except Exception:
                break
            time.sleep(1.2)
        try:
            return p.evaluate("document.documentElement.outerHTML") or ""
        except Exception:
            return ""


def try_browser(port=9222, headless=False):
    """返回 Browser 或 None（基建不可用时）。调用方须处理 None。"""
    if not available():
        print("  [skip] CDP 基建不可用：未找到 xiaohongshu-skills/scripts/xhs/cdp.py")
        return None
    try:
        return Browser(port=port, headless=headless)
    except Exception as e:
        print("  [skip] CDP 初始化失败: %s" % e)
        return None
