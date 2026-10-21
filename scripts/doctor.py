# -*- coding: utf-8 -*-
"""环境自检 —— 换设备后第一件事就跑这个。

本 skill **自带全部依赖**（`scripts/vendor/`，约 145 KB），
不需要外部 skill 目录。只需要一个能跑 requests 的 Python。

用法
----
    python doctor.py              # 体检并打印修复指引
    python doctor.py --fix-venv   # 顺带尝试自动装缺失的包（需 uv 或 pip）
"""
import os
import sys
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(HERE, "vendor")
HOME = os.path.expanduser("~")

OK, WARN, FAIL = "OK  ", "WARN", "FAIL"
_results = []


def chk(name, status, detail="", fix=""):
    _results.append((name, status, detail, fix))
    print("  [%s] %-28s %s" % (status, name, detail))


def check_self():
    """本 skill 脚本完整性。"""
    need = ["collect.py", "normalize.py", "keywords.py", "output.py",
            "rebuild.py", "merge.py", "cluster.py", "plan.py", "deps.py",
            "login_all.py", "xhs_login_watch.py", "xhs_detail.py",
            "xhs_images.py", "xhs_note_images.py", "doctor.py"]
    miss = [f for f in need if not os.path.isfile(os.path.join(HERE, f))]
    srcs = ["nowcoder.py", "bilibili.py", "zhihu.py", "xhs.py",
            "cnblogs.py", "_browser.py", "__init__.py"]
    miss += ["sources/" + f for f in srcs
             if not os.path.isfile(os.path.join(HERE, "sources", f))]
    if miss:
        chk("本 skill 脚本", FAIL,
            "缺 %d 个: %s" % (len(miss), ", ".join(miss[:4])),
            "从旧设备重新复制整个 interview-collector 目录")
    else:
        chk("本 skill 脚本", OK, "%d 个脚本齐全" % (len(need) + len(srcs)))


def check_vendor():
    """内联依赖 —— 这是换设备可用性的核心。"""
    need = {
        "chrome_launcher.py": "Chrome 启动与探测",
        "nowcoder_api.py": "牛客接口（主力源）",
        "xhs/cdp.py": "CDP 浏览器控制",
        "xhs/login.py": "登录态管理",
        "xhs/search.py": "小红书搜索",
        "xhs/feed_detail.py": "小红书详情",
        "xhs/types.py": "数据类型",
        "xhs/cookies.py": "cookie 读写",
        "xhs/stealth.py": "反检测参数",
        "xhs/errors.py": "异常定义",
        "xhs/human.py": "拟人化延时",
        "xhs/selectors.py": "页面选择器",
        "xhs/urls.py": "URL 构造",
    }
    miss = [f for f in need if not os.path.isfile(os.path.join(VENDOR, f))]
    if miss:
        chk("内联依赖 vendor/", FAIL,
            "缺 %d 个: %s" % (len(miss), ", ".join(miss[:3])),
            "vendor/ 是随 skill 一起走的，缺失说明复制不完整。\n"
            "      从旧设备补齐，或从上游重新取：\n"
            "        git clone https://github.com/xpzouying/xiaohongshu-skills /tmp/xhs\n"
            "        cp /tmp/xhs/scripts/chrome_launcher.py vendor/\n"
            "        cp /tmp/xhs/scripts/xhs/*.py vendor/xhs/")
        return False
    size = sum(os.path.getsize(os.path.join(VENDOR, f)) for f in need)
    chk("内联依赖 vendor/", OK, "%d 个文件 / %d KB" % (len(need), size // 1024))
    return True


def check_import():
    """能否真正 import —— 比查文件存在更靠谱。"""
    sys.path.insert(0, HERE)
    try:
        import deps
        deps.setup()
    except Exception as e:
        chk("依赖加载", FAIL, "deps.py 异常: %s" % e)
        return False
    mods = [("chrome_launcher", "Chrome 探测"),
            ("nowcoder_api", "牛客源"),
            ("xhs.cdp", "CDP"),
            ("xhs.search", "小红书搜索")]
    allok = True
    for m, desc in mods:
        try:
            __import__(m)
            chk("  import %s" % m, OK, desc)
        except Exception as e:
            allok = False
            chk("  import %s" % m, FAIL, "%s（%s）" % (desc, type(e).__name__))
    src = getattr(sys.modules.get("deps"), "_source", None)
    if src:
        chk("依赖来源", OK, "vendor（内联）" if src == "vendor"
            else "外部 skill 目录（IC_PREFER_EXTERNAL）")
    return allok


def check_packages(fix=False):
    need = {"requests": ("必需", "所有源都要"),
            "websockets": ("必需", "CDP 连接"),
            "pillow": ("可选", "图片题目提取")}
    missing = []
    for p, (lvl, desc) in need.items():
        try:
            import importlib.metadata as md
            chk("  包 %s" % p, OK, md.version(p))
        except Exception:
            missing.append(p)
            chk("  包 %s" % p, FAIL if lvl == "必需" else WARN,
                "未安装 —— %s" % desc)
    if missing and fix:
        print("      → 尝试安装 %s ..." % " ".join(missing))
        for tool in (["uv", "pip", "install"], [sys.executable, "-m", "pip",
                                                "install"]):
            try:
                subprocess.run(tool + missing, check=True, capture_output=True)
                print("      → 安装成功，请重跑 doctor.py")
                return
            except Exception:
                continue
        print("      → 自动安装失败，请手动执行")
    elif missing:
        chk("包安装", WARN, "",
            "uv pip install %s\n      或 %s -m pip install %s"
            % (" ".join(missing), sys.executable, " ".join(missing)))


def check_chrome():
    """Chrome —— 仅浏览器源（知乎/小红书/博客园）需要。"""
    try:
        import chrome_launcher as cl
    except Exception:
        chk("Chrome 探测", WARN, "跳过（chrome_launcher 未加载）")
        return
    try:
        path = cl.find_chrome()
    except Exception:
        path = None
    if path:
        chk("Chrome", OK, path.replace(HOME, "~")[:46])
    else:
        chk("Chrome", WARN, "未找到 —— 仅影响浏览器源",
            "装 Chrome，或设环境变量 CHROME_BIN 指向可执行文件")
    running = False
    try:
        running = cl.is_chrome_running(int(os.environ.get("IC_CDP_PORT","9222")))
    except Exception:
        pass
    # 未启动是正常状态（按需启动），不算问题
    chk("Chrome 端口 " + os.environ.get("IC_CDP_PORT","9222"), OK,
        "在跑" if running else "未启动 —— 正常，用浏览器源前起一下即可",
        "" if running else
        "HOLD_MINUTES=90 python login_all.py --keepalive &")


def check_login_state():
    """登录态 —— 磁盘持久化，不随 Chrome 退出丢失，但换设备不跟过来。"""
    import time
    ck = os.path.join(HOME, ".xhs", "cookies.json")
    prof = os.path.join(HOME, ".xhs", "chrome-profile")
    if os.path.isfile(ck):
        try:
            import json
            d = json.load(open(ck, encoding="utf-8"))
            names = [c.get("name") for c in
                     (d if isinstance(d, list) else d.get("cookies", []))]
        except Exception:
            names = []
        mt = time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(ck)))
        if "web_session" in names:
            chk("小红书登录态", OK, "%d cookies，更新于 %s" % (len(names), mt))
        else:
            chk("小红书登录态", WARN, "缺 web_session，可能已失效",
                "python xhs_login_watch.py")
    else:
        chk("小红书登录态", WARN, "未登录 —— 仅影响小红书源",
            "python xhs_login_watch.py   # 扫码，二维码每 100 秒续期")
    chk("Chrome profile", OK if os.path.isdir(prof) else WARN,
        "存在（知乎/博客园登录态，不随 Chrome 退出丢失）"
        if os.path.isdir(prof) else "不存在 —— 浏览器源需重新登录")


def main():
    fix = "--fix-venv" in sys.argv or "--fix" in sys.argv
    print("=" * 60)
    print(" interview-collector 环境自检")
    print("=" * 60)
    print("")
    print("【1】本 skill 完整性")
    check_self()
    has_vendor = check_vendor()
    print("")
    print("【2】依赖可加载性")
    if has_vendor:
        check_import()
    else:
        chk("依赖加载", FAIL, "跳过（vendor 不完整）")
    print("")
    print("【3】Python 包")
    check_packages(fix=fix)
    print("")
    print("【4】浏览器与登录态（仅浏览器源需要）")
    check_chrome()
    check_login_state()

    fails = [r for r in _results if r[1] == FAIL]
    warns = [r for r in _results if r[1] == WARN]
    print("")
    print("=" * 60)
    if not fails:
        print(" 结论：可用。%s"
              % ("无警告" if not warns
                 else "%d 个警告（均为可选项，不影响免登录源）" % len(warns)))
    else:
        print(" 结论：有 %d 项必须修复" % len(fails))
    print("=" * 60)

    must = [r for r in _results if r[3] and r[1] in (FAIL, WARN)]
    opt = [r for r in _results if r[3] and r[1] == OK]
    if must:
        print("")
        print("需处理")
        print("-" * 60)
        for i, (name, st, _d, f) in enumerate(must, 1):
            print("")
            print(" %d) [%s] %s" % (i, st.strip(), name.strip()))
            for ln in f.split("\n"):
                print("      %s" % ln)
    if opt:
        print("")
        print("按需操作（当前不影响可用性）")
        print("-" * 60)
        for name, _st, _d, f in opt:
            print("")
            print(" · %s" % name.strip())
            for ln in f.split("\n"):
                print("      %s" % ln)
    print("")
    print("换设备只需两步：①复制整个 interview-collector 目录 "
          "②确保 python 有 requests")
    print("免登录源（牛客+B站）到这一步就能用；"
          "浏览器源再加 Chrome + 登录一次。")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
