# -*- coding: utf-8 -*-
"""一次性打开所有需要登录的站点，并保持 Chrome 常驻等你登录。

用途：interview-collector 的三个浏览器源（知乎/小红书/博客园）都需要
人工登录一次，cookie 会持久化到 ~/.xhs/chrome-profile。
本脚本把三个站点在同一个 Chrome 里各开一个 tab，然后**阻塞常驻**。

⚠️ 重要设计说明（踩坑记录 2026-09-03）
--------------------------------------
`chrome_launcher.launch_chrome()` 用 `subprocess.Popen` 启动 Chrome，
Chrome 是本脚本的**子进程**。脚本一退出（含超时退出），Chrome 会被一起带走，
导致此后运行的采集任务突然失去浏览器（CDP 连接 ConnectionError）。

**实测结论：`--detach`（DETACHED_PROCESS）在 agent 的 Bash 工具下无效** ——
工具层会在命令结束时清理整个进程树，操作系统级的分离标志会被覆盖。

所以**唯一可靠的做法是：让本脚本作为后台常驻任务一直活着**，
即用 agent 的 `run_in_background` 启动，并把 `HOLD_MINUTES` 设足够大。
采集任务全部跑完之前，不要让这个后台任务结束。

`--detach` 保留给**用户在自己终端里手动执行**的场景，那时它是有效的。

用法
----
    # agent 场景（推荐）：作为后台任务常驻
    HOLD_MINUTES=180 python login_all.py

    # 长时间采集期间纯保活（不开 tab、掉线自动重启）
    HOLD_MINUTES=90 python login_all.py --keepalive

    # 用户在本机终端手动跑：开完即走，Chrome 留下
    python login_all.py --detach
"""
import os
import sys
import time
import subprocess

os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deps  # noqa: E402  依赖已内联到 vendor/，import 时自动 setup

import chrome_launcher as cl          # noqa: E402
from xhs.cdp import Browser           # noqa: E402

SITES = [
    ("小红书", "https://www.xiaohongshu.com/explore"),
    ("知乎", "https://www.zhihu.com/signin"),
    ("博客园",
     "https://zzk.cnblogs.com/s/blogpost?Keywords=%E5%AE%89%E5%85%A8%20%E9%9D%A2%E7%BB%8F"),
]

HOLD_MINUTES = int(os.environ.get("HOLD_MINUTES", "180"))
PORT = int(os.environ.get("IC_CDP_PORT", "9222"))


def launch_detached():
    """独立启动 Chrome，脱离本脚本的进程树，脚本退出后仍存活。"""
    chrome = cl.find_chrome()
    if not chrome:
        raise FileNotFoundError("未找到 Chrome，请设置 CHROME_BIN")
    profile = os.path.join(os.path.expanduser("~"), ".xhs", "chrome-profile")
    args = [chrome,
            "--remote-debugging-port=%d" % PORT,
            "--user-data-dir=%s" % profile]
    args.extend(getattr(cl, "STEALTH_ARGS", []))

    kw = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        # DETACHED_PROCESS(0x08) | CREATE_NEW_PROCESS_GROUP(0x200)
        kw["creationflags"] = 0x00000008 | 0x00000200
    else:
        kw["start_new_session"] = True
    subprocess.Popen(args, **kw)
    cl._wait_for_chrome(PORT, timeout=25.0)
    print("Chrome 已独立启动（脱离本脚本进程树，退出后仍存活）")


def main():
    detach = "--detach" in sys.argv
    keep_only = "--keepalive" in sys.argv

    if not cl.is_chrome_running(PORT):
        if detach:
            print("启动 Chrome（独立进程，非 headless）...")
            launch_detached()
        else:
            print("启动 Chrome（非 headless，profile 持久化）...")
            cl.launch_chrome(port=PORT, headless=False)
            cl._wait_for_chrome(PORT, timeout=25.0)
    else:
        print("复用已在运行的 Chrome (%d)" % PORT)

    # --keepalive：纯保活模式，不开新 tab、不打印登录指引。
    # 用于长时间采集期间顶住 Chrome，掉线自动重启。
    if keep_only:
        print("Chrome 保活守护启动（%d 分钟），掉线将自动重启" % HOLD_MINUTES)
        deadline = time.time() + HOLD_MINUTES * 60
        while time.time() < deadline:
            if not cl.is_chrome_running(PORT):
                print("[!] Chrome 掉线，重启中...")
                try:
                    cl.launch_chrome(port=PORT, headless=False)
                    cl._wait_for_chrome(PORT, timeout=25.0)
                    print("[OK] 已重启")
                except Exception as e:
                    print("[FAIL] 重启失败: %s" % e)
                    return 1
            time.sleep(10)
        print("保活时限到，守护退出")
        return 0

    br = Browser(port=PORT)
    br.connect()

    # 无需手动注入 cookie：Chrome 用的是持久化 profile
    # (~/.xhs/chrome-profile)，登录态自动保留在 profile 里。

    print("")
    for name, url in SITES:
        try:
            br.new_page(url)
            print("  [tab] %-6s -> %s" % (name, url[:56]))
        except Exception as e:
            print("  [warn] %s 打开失败: %s" % (name, e))

    print("")
    print("=" * 58)
    print(" Chrome 已就绪，请在窗口里依次完成：")
    print("   1. 小红书 —— 扫码登录")
    print("   2. 知乎   —— 账号登录（标题出现「N 封私信」即成功）")
    print("   3. 博客园 —— 点一下人机验证，无需账号")
    print("")
    print(" 验证是否真登录成功：")
    print("   小红书 -> 看 ~/.xhs/cookies.json 的修改时间是否为刚才")
    print("   知乎   -> 标签标题是否变成「(N 封私信) 首页 - 知乎」")

    if detach:
        print("")
        print(" [独立模式] Chrome 已脱离本脚本，现在退出不会影响它。")
        print("=" * 58)
        return 0

    print("")
    print(" [常驻模式] Chrome 是本脚本子进程，脚本退出会一并关闭。")
    print(" 将保持 %d 分钟；若要长期存活请改用 --detach。" % HOLD_MINUTES)
    print("=" * 58)

    deadline = time.time() + HOLD_MINUTES * 60
    try:
        while time.time() < deadline:
            if not cl.is_chrome_running(PORT):
                print("\n[!] Chrome 已被关闭，脚本退出")
                return 1
            time.sleep(5)
        print("\n[!] 已到保持时限，Chrome 即将随脚本退出")
    except KeyboardInterrupt:
        print("\n收到中断，脚本退出（Chrome 也会关闭）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
