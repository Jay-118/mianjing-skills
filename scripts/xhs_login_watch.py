# -*- coding: utf-8 -*-
"""小红书长时扫码监听器。

为什么需要它
----------
`cli.py wait-login` 的等待窗口只有约 2 分钟，人工扫码常常来不及，
超时后二维码也失效，需要反复重来。

本脚本做三件事：
1. 复用常驻 Chrome（不自己启动，避免进程树绑定问题）
2. **二维码过期自动刷新**：每 `REFRESH_SEC` 秒重新生成一次并落盘
3. 持续检测登录态，成功后立刻保存 cookie 并退出

用法
----
    python xhs_login_watch.py                 # 默认监听 20 分钟
    WATCH_MINUTES=40 python xhs_login_watch.py

判断真登录的标准（不能只看 logged_in 字段）
-----------------------------------------
旧 cookie 残留会让 API 层判断失真，必须核对 ~/.xhs/cookies.json 的 **mtime**。
"""
import os
import sys
import time
import shutil

os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deps  # noqa: E402  依赖已内联到 vendor/，import 时自动 setup

import chrome_launcher as cl                     # noqa: E402
from xhs.cdp import Browser                      # noqa: E402
from xhs import login as xlogin                  # noqa: E402

PORT = 9222
WATCH_MINUTES = int(os.environ.get("WATCH_MINUTES", "20"))
REFRESH_SEC = int(os.environ.get("REFRESH_SEC", "100"))
POLL_SEC = 5
EXPORT_DIR = os.environ.get("QR_EXPORT_DIR", "")


def _cookie_path():
    return os.path.join(os.path.expanduser("~"), ".xhs", "cookies.json")


def _cookie_mtime():
    p = _cookie_path()
    return os.path.getmtime(p) if os.path.isfile(p) else 0


def _export(qr_path, tag):
    """把二维码复制到便于查看的目录。"""
    if not (EXPORT_DIR and qr_path and os.path.isfile(qr_path)):
        return None
    try:
        os.makedirs(EXPORT_DIR, exist_ok=True)
        dst = os.path.join(EXPORT_DIR, "小红书登录二维码.png")
        shutil.copyfile(qr_path, dst)
        return dst
    except OSError as e:
        print("  [warn] 导出二维码失败: %s" % e)
        return None


def _fresh_qr(page):
    """重新生成二维码。先清理旧文件，避免句柄锁导致 Errno 22。

    真实 API（已核实，勿凭直觉猜）：
      xhs.login.fetch_qrcode(page) -> (png_bytes, qr_url, logged_in)
      xhs.login.save_qrcode_to_file(png_bytes) -> path
    注意 fetch_qrcode 返回**三元组**，第三个值表示"是否已登录"。
    """
    import tempfile
    f = os.path.join(tempfile.gettempdir(), "xhs", "login_qrcode.png")
    if os.path.exists(f):
        try:
            os.remove(f)
        except OSError:
            pass
    try:
        page.navigate("https://www.xiaohongshu.com/explore")
        time.sleep(3)
        png, _url, already = xlogin.fetch_qrcode(page)
        if already:
            return "ALREADY_LOGGED_IN"
        return xlogin.save_qrcode_to_file(png) if png else None
    except Exception as e:
        print("  [warn] 生成二维码失败: %s" % e)
        return None


def main():
    if not cl.is_chrome_running(PORT):
        print("[!] Chrome 未运行。请先启动常驻会话：")
        print("    HOLD_MINUTES=60 python login_all.py")
        return 1

    br = Browser(port=PORT)
    br.connect()
    page = br.get_or_create_page()

    base_mtime = _cookie_mtime()
    print("=" * 58)
    print(" 小红书扫码监听中（最长 %d 分钟）" % WATCH_MINUTES)
    print(" cookie 基线时间: %s"
          % (time.strftime("%H:%M:%S", time.localtime(base_mtime))
             if base_mtime else "无"))
    print("=" * 58)

    deadline = time.time() + WATCH_MINUTES * 60
    last_refresh = 0.0
    rounds = 0

    while time.time() < deadline:
        # --- 二维码到期就刷新 ---
        if time.time() - last_refresh >= REFRESH_SEC:
            rounds += 1
            qr = _fresh_qr(page)
            last_refresh = time.time()
            if qr == "ALREADY_LOGGED_IN":
                print("\n[OK] 页面已是登录态，保存 cookie...")
                try:
                    xlogin.save_login_cookies(page)
                    print("  cookie 已保存")
                except Exception as e:
                    print("  [warn] 保存失败: %s" % e)
                break
            if qr:
                dst = _export(qr, rounds)
                print("[%s] 第 %d 版二维码已就绪 %s"
                      % (time.strftime("%H:%M:%S"), rounds,
                         "-> %s" % dst if dst else ""))

        # --- 检测登录态：cookie 文件被更新 = 真登录 ---
        if _cookie_mtime() > base_mtime:
            print("\n[OK] 检测到 cookie 更新，登录成功！")
            break

        try:
            if xlogin.check_login_status(page):
                print("\n[OK] 页面已登录，正在保存 cookie...")
                try:
                    xlogin.save_login_cookies(page)
                    print("  cookie 已保存")
                except Exception as e:
                    print("  [warn] 自动保存失败: %s" % e)
                    print("  请手动执行: python scripts/cli.py check-login")
                break
        except Exception:
            pass

        time.sleep(POLL_SEC)
    else:
        print("\n[!] 已到监听时限仍未登录。Chrome 仍在运行，可重跑本脚本。")
        return 1

    # --- 最终确认 ---
    m = _cookie_mtime()
    print("cookie 文件时间: %s"
          % time.strftime("%H:%M:%S", time.localtime(m)) if m else "无")
    return 0


if __name__ == "__main__":
    sys.exit(main())
