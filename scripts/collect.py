# -*- coding: utf-8 -*-
"""interview-collector 主入口。

用法
----
python collect.py --topic "安全" --outdir D:/out
python collect.py --topic "AI安全" --sources nowcoder,bilibili,zhihu
python collect.py --topic "安全" --extra "MCP安全,Agent越权" --days 365
python collect.py --check           # 只体检各源可用性，不采集
"""
import os
import sys
import json
import time
import argparse
import traceback
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sources
from keywords import build_matrix
from normalize import pipeline
from output import write_all


def _cdp_targets():
    """列出 Chrome 9222 的 targets（tab 标题/URL）。失败返回空表。"""
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["no_proxy"] = "127.0.0.1,localhost"
    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:9222/json")
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except Exception:
        return []


def _login_status():
    """探测浏览器源登录态。返回 {source: bool}；探测不了的源不出现。"""
    st = {}
    # xhs：cookie 文件含 web_session 即视为已登录（登录态持久化）
    ck = os.path.expanduser("~/.xhs/cookies.json")
    if os.path.exists(ck):
        try:
            data = json.load(open(ck, encoding="utf-8"))
            cookies = data if isinstance(data, list) else data.get("cookies", [])
            names = [c.get("name") for c in cookies if isinstance(c, dict)]
            st["xhs"] = "web_session" in names
        except Exception:
            st["xhs"] = False
    else:
        st["xhs"] = False
    # zhihu：CDP tab 停在 /signin 视为未登录，跳到其他页视为已登录
    zhihu_tabs = [t for t in _cdp_targets()
                  if isinstance(t, dict) and "zhihu.com" in (t.get("url") or "")]
    if zhihu_tabs:
        st["zhihu"] = any("signin" not in (t.get("url") or "") for t in zhihu_tabs)
    # cnblogs：只点人机验证、无账号，无法从外部可靠探测，交给适配器自行判断
    return st


def ensure_login(names, wait_minutes):
    """浏览器源未登录时，拉起 Chrome 登录页并等待用户完成登录。

    wait_minutes<=0 时直接返回（由各适配器自行 skip）。
    轮询可探测的源（xhs/zhihu）；cnblogs 无人机验证由用户手动点一次，
    采集时适配器会自行判断并通过/跳过。
    """
    browser_needed = [n for n in names if n in sources.BROWSER_SOURCES]
    if not browser_needed or wait_minutes <= 0:
        return
    st = _login_status()
    missing = [s for s in browser_needed if not st.get(s, False)]
    if not missing:
        ok = [s for s in browser_needed if st.get(s)]
        print("[login] 浏览器源登录态有效：%s（%s 无外部信号，采集时自行判断）"
              % (",".join(ok) or "无",
                 ",".join(s for s in browser_needed if s not in st) or "无"))
        return

    print("")
    print("=" * 56)
    print(" [login] 以下浏览器源需要登录：%s" % ", ".join(missing))
    print(" [login] 正在打开 Chrome 登录窗口，请在窗口里完成：")
    print("           小红书 —— 扫码登录")
    print("           知乎   —— 账号登录（登录后自动跳转）")
    print("           博客园 —— 点一下人机验证，无需账号")
    print(" [login] 脚本每 20 秒自动检测，最长等待 %d 分钟，" % wait_minutes)
    print("         到时后未登录的源将被跳过，不影响免登录源。")
    print("=" * 56)

    login_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "login_all.py")
    env = dict(os.environ, HOLD_MINUTES=str(max(wait_minutes + 15, 40)))
    subprocess.Popen([sys.executable, login_script], env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    deadline = time.time() + wait_minutes * 60
    need_probe = [s for s in browser_needed if s in ("xhs", "zhihu")]
    while time.time() < deadline:
        time.sleep(20)
        st = _login_status()
        done = [s for s in need_probe if st.get(s)]
        left = int(deadline - time.time())
        print("  [login] 已登录: %-12s 剩余 %d 秒" % (",".join(done) or "无", left))
        if need_probe and all(st.get(s, False) for s in need_probe):
            print("[login] 可探测的源全部登录完成，继续采集")
            break
    else:
        st = _login_status()
        print("")
        print("!" * 56)
        print(" [login][警告] 等待超时，以下源仍未登录：%s" %
              ", ".join(s for s in browser_needed if not st.get(s, False)) or "无")
        print(" [login][警告] 这些源的数据将缺失（实测占入选数据约 76%），")
        print(" [login][警告] 建议完成登录后重新运行采集；若用户明确同意降级，")
        print(" [login][警告] 才可继续本次免登录采集。")
        print("!" * 56)


def check_sources():
    """体检：逐个报告可用性，不做真实采集。"""
    print("=" * 56)
    print(" 采集源可用性体检")
    print("=" * 56)
    rows = []
    for name in sources.all_names():
        mod = sources.get(name)
        if hasattr(mod, "available"):
            ok = mod.available()
            note = "可用" if ok else "不可用（见上方提示）"
        else:
            need = "需浏览器+登录" if name in sources.BROWSER_SOURCES else "免登录"
            ok, note = None, "未提供自检，%s" % need
        rows.append((name, ok, note))
        flag = {True: "OK  ", False: "FAIL", None: "?   "}[ok]
        print("  [%s] %-10s %s" % (flag, name, note))
    print("")
    print("  默认启用（五源全开）：%s" % ", ".join(sources.DEFAULT_SOURCES))
    print("  浏览器源 %s 未登录/基建缺失时自动跳过（打印 [skip]），不影响免登录源"
          % ", ".join(sources.BROWSER_SOURCES))
    print("  只跑免登录源：--sources nowcoder,bilibili")
    return rows


def main():
    ap = argparse.ArgumentParser(description="多平台面经采集")
    ap.add_argument("--topic", default="安全", help="方向名，用于文件名与标题")
    ap.add_argument("--outdir", default=".", help="输出目录")
    ap.add_argument("--sources", default=",".join(sources.DEFAULT_SOURCES),
                    help="启用的源，逗号分隔；all 表示全部")
    ap.add_argument("--extra", default="", help="追加关键词，逗号分隔")
    ap.add_argument("--max-kw", type=int, default=80, help="关键词上限（默认 80，尽量覆盖全矩阵）")
    ap.add_argument("--max-page", type=int, default=12,
                    help="每词最大翻页数（默认 12；牛客每页 20 条，12 页≈240 条/词）")
    ap.add_argument("--days", type=int, default=730, help="时间窗（天）")
    ap.add_argument("--keep-c", action="store_true",
                    help="保留 C 档（默认按铁律排除标题无岗位词的条目）")
    ap.add_argument("--no-company", action="store_true", help="不铺公司线关键词")
    ap.add_argument("--only-extra", action="store_true",
                    help="只用 --extra 指定的关键词（定向采集，不铺岗位/公司/考点线）")
    ap.add_argument("--wait-login", type=int, default=10,
                    help="浏览器源未登录时拉起登录窗口并等待的分钟数（默认 10，0=不等待直接跳过）")
    ap.add_argument("--xhs-scroll", type=int, default=4,
                    help="小红书每词滚动翻屏次数（默认 4，即首屏+4 屏≈100+ 条/词；0=只取首屏）")
    ap.add_argument("--check", action="store_true", help="只体检，不采集")
    args = ap.parse_args()

    if args.check:
        check_sources()
        return 0

    extra = [x.strip() for x in args.extra.split(",") if x.strip()]
    if args.only_extra:
        if not extra:
            print("[!] --only-extra 需要配合 --extra 使用")
            return 1
        queries = list(dict.fromkeys(extra))
    else:
        queries = build_matrix(extra=extra,
                               with_company=not args.no_company,
                               max_kw=args.max_kw)
    names = (sources.all_names() if args.sources.strip() == "all"
             else [s.strip() for s in args.sources.split(",") if s.strip()])

    print("=" * 56)
    print(" 方向：%s" % args.topic)
    print(" 关键词：%d 个" % len(queries))
    print(" 启用源：%s" % ", ".join(names))
    print("=" * 56)

    ensure_login(names, args.wait_login)

    raw, per_source = [], {}
    for name in names:
        mod = sources.get(name)
        if mod is None:
            print("\n[?] 未知源 %s，跳过" % name)
            continue
        print("\n>>> %s" % name)
        try:
            kwargs = {"max_page": args.max_page}
            # 浏览器源：关键词数与查询数对齐（build_matrix 已按 --max-kw 截断），
            # 避免源内保守默认截断召回，也不放大到超出查询数
            if name in sources.BROWSER_SOURCES:
                kwargs["max_kw"] = max(len(queries), 1)
            if name == "xhs":
                kwargs["scroll"] = args.xhs_scroll
            got = mod.fetch(queries, **kwargs) or []
        except Exception as e:
            # 单源异常绝不阻断整体流程
            print("  [warn] %s 抛异常已隔离: %s" % (name, e))
            traceback.print_exc(limit=2)
            got = []
        per_source[name] = len(got)
        raw.extend(got)
        print("  => %s 采集 %d 条" % (name, len(got)))

    if not raw:
        print("\n[!] 所有源均无数据。请先运行 --check 体检，"
              "或检查网络与登录态。未生成任何文件。")
        return 1

    print("\n" + "=" * 56)
    print(" 归一处理")
    print("=" * 56)
    items, bank, funnel = pipeline(raw, days=args.days, keep_c=args.keep_c)
    funnel["raw_by_source"] = per_source
    for k, v in funnel.items():
        if k not in ("by_source", "raw_by_source"):
            print("  %-18s %s" % (k, v))
    print("  分源入选：%s" % funnel.get("by_source"))

    paths = write_all(args.outdir, args.topic, items, bank, funnel, queries)
    print("\n产出：")
    for k, p in paths.items():
        print("  %-5s %s" % (k, p))
    return 0


if __name__ == "__main__":
    sys.exit(main())
