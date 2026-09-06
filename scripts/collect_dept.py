# -*- coding: utf-8 -*-
"""部门信息采集（collect_dept）—— 采集某公司/部门的所有相关信息，不限于面经。

与 collect.py（面经采集）的区别：
- 跳过 require_exp_signal / filter_clickbait / grade（这三道是面经专属过滤，
  会把岗位介绍、团队技术文章、招聘信息误砍掉）
- 增加「部门相关性过滤」：只保留与目标部门相关的岗位/团队/技术/招聘/面经等一切信息
- 输出：按来源分组的全量相关条目清单（含标题/作者/日期/摘要/链接）+ 原始 JSON

用法
----
python collect_dept.py --topic "阿里安全资源情报" --outdir D:/out \
    --extra "阿里安全资源情报,阿里归零实验室,阿里黑灰产,..." \
    --sources all --days 1095
"""
import os
import sys
import json
import time
import argparse
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sources
from normalize import dedup, filter_noise, filter_non_tech, filter_time_window
from collect import ensure_login

SRC_LABEL = {
    "nowcoder": "牛客",
    "bilibili": "B站专栏",
    "zhihu": "知乎",
    "xhs": "小红书",
    "cnblogs": "博客园",
}

# ---- 部门相关性词表（命中即视为「与该部门相关」，保留） ----
# HARD：强相关词，标题/摘要命中任一个即保留
HARD_WORDS = [
    "资源情报", "归零实验室", "黑灰产", "黑产", "威胁情报", "情报溯源",
    "风险溯源", "情报分析", "反黑产", "薅羊毛", "黄牛", "渠道拉活",
    "恶意注册", "虚假注册", "刷量", "情报体系", "情报数据", "反诈",
    "黑产情报", "情报对抗",
]
# SOFT：弱相关词，需同时命中 CTX 语境词才保留（避免「每日一家公司情报」这类噪声）
SOFT_WORDS = ["情报", "溯源", "风控", "黑产对抗", "情报挖掘"]
CTX_WORDS = ["阿里", "阿里巴巴", "安全", "攻防", "渗透", "逆向", "对抗"]


def relevant(it):
    """判断条目是否与目标部门相关。"""
    text = "%s %s" % (it.get("title") or "", it.get("content") or "")
    if any(w in text for w in HARD_WORDS):
        return True
    if any(w in text for w in SOFT_WORDS) and any(w in text for w in CTX_WORDS):
        return True
    return False


def _label(s):
    return SRC_LABEL.get(s, s)


def write_report(path, topic, items, funnel, queries):
    L = []
    L.append("# %s · 部门相关信息汇总" % topic)
    L.append("")
    L.append("- 采集时间：%s" % time.strftime("%Y-%m-%d %H:%M"))
    L.append("- 关键词数：%d" % len(queries))
    L.append("- 数据来源：%s"
             % "、".join("%s %d 条" % (_label(k), v)
                         for k, v in sorted(funnel.get("by_source", {}).items(),
                                            key=lambda x: -x[1])))
    L.append("")
    L.append("> 本清单不限于面经，含岗位介绍、团队、技术文章、招聘等一切相关条目。")
    L.append("> 标题/作者/时间/链接均为接口原样输出，未改写；摘要为搜索接口返回，可能不全，请点原帖核对。")
    L.append("")
    L.append("## 采集漏斗")
    L.append("")
    L.append("| 阶段 | 数量 |")
    L.append("|---|---|")
    for k in ("raw", "after_dedup", "after_noise", "after_non_tech",
              "after_relevant", "after_time"):
        L.append("| %s | %d |" % (k, funnel.get(k, 0)))
    L.append("| 最终入选 | %d |" % funnel.get("final", 0))
    L.append("")

    for src in sorted(funnel.get("by_source", {}).keys()):
        rows = [i for i in items if i.get("source") == src]
        if not rows:
            continue
        L.append("## %s（%d 条）" % (_label(src), len(rows)))
        L.append("")
        L.append("| # | 标题 | 作者 | 日期 | 摘要 |")
        L.append("|---|---|---|---|---|")
        for n, it in enumerate(rows, 1):
            t = (it.get("title") or "(无标题)").replace("|", "\\|").strip()
            a = (it.get("author") or "-").replace("|", "\\|").strip()
            d = it.get("date") or "-"
            c = (it.get("content") or "").replace("|", "\\|").strip()
            if len(c) > 80:
                c = c[:80] + "…"
            L.append("| %d | [%s](%s) | %s | %s | %s |"
                     % (n, t, it.get("url") or "#", a, d, c))
        L.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return path


def write_json(path, topic, items, funnel, queries):
    payload = {
        "topic": topic,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "dept_broad",
        "queries": queries,
        "funnel": funnel,
        "posts": items,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def main():
    ap = argparse.ArgumentParser(description="部门信息采集（不限于面经）")
    ap.add_argument("--topic", default="阿里安全资源情报", help="方向名")
    ap.add_argument("--outdir", default=".", help="输出目录")
    ap.add_argument("--sources", default="all", help="逗号分隔，all=全部")
    ap.add_argument("--extra", default="", help="关键词，逗号分隔（定向采集）")
    ap.add_argument("--max-page", type=int, default=8, help="每词翻页数")
    ap.add_argument("--days", type=int, default=1095, help="时间窗（天）")
    ap.add_argument("--wait-login", type=int, default=0,
                    help="浏览器源未登录时等待登录的分钟数，0=跳过未登录源")
    ap.add_argument("--xhs-scroll", type=int, default=4, help="小红书每词滚动屏数")
    args = ap.parse_args()

    queries = [x.strip() for x in args.extra.split(",") if x.strip()]
    if not queries:
        print("[!] 需要 --extra 提供关键词")
        return 1
    queries = list(dict.fromkeys(queries))

    names = (sources.all_names() if args.sources.strip() == "all"
             else [s.strip() for s in args.sources.split(",") if s.strip()])

    print("=" * 56)
    print(" 方向：%s（部门信息，不限于面经）" % args.topic)
    print(" 关键词：%d 个" % len(queries))
    print(" 启用源：%s" % ", ".join(names))
    print("=" * 56)

    if args.wait_login > 0:
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
            if name in sources.BROWSER_SOURCES and name != "cnblogs":
                kwargs["max_kw"] = max(len(queries), 20)
            if name == "xhs":
                kwargs["scroll"] = args.xhs_scroll
            got = mod.fetch(queries, **kwargs) or []
        except Exception as e:
            print("  [warn] %s 抛异常已隔离: %s" % (name, e))
            traceback.print_exc(limit=2)
            got = []
        per_source[name] = len(got)
        raw.extend(got)
        print("  => %s 采集 %d 条" % (name, len(got)))

    if not raw:
        print("\n[!] 所有源均无数据，未生成文件。")
        return 1

    funnel = {"raw": len(raw)}
    items = dedup(raw)
    funnel["after_dedup"] = len(items)
    items = filter_noise(items)
    funnel["after_noise"] = len(items)
    items = filter_non_tech(items)
    funnel["after_non_tech"] = len(items)
    items = [it for it in items if relevant(it)]
    funnel["after_relevant"] = len(items)
    items = filter_time_window(items, days=args.days)
    funnel["after_time"] = len(items)
    funnel["final"] = len(items)
    funnel["raw_by_source"] = per_source

    by_source = {}
    for it in items:
        by_source[it["source"]] = by_source.get(it["source"], 0) + 1
    funnel["by_source"] = by_source

    print("\n" + "=" * 56)
    print(" 过滤漏斗")
    print("=" * 56)
    for k in ("raw", "after_dedup", "after_noise", "after_non_tech",
              "after_relevant", "after_time", "final"):
        print("  %-16s %s" % (k, funnel[k]))
    print("  分源入选：%s" % by_source)

    os.makedirs(args.outdir, exist_ok=True)
    day = time.strftime("%Y%m%d")
    safe = args.topic.replace("/", "_").replace(" ", "")
    md_path = os.path.join(args.outdir, "部门信息_%s_%s.md" % (safe, day))
    json_path = os.path.join(args.outdir, "部门信息_%s_%s.json" % (safe, day))
    write_report(md_path, args.topic, items, funnel, queries)
    write_json(json_path, args.topic, items, funnel, queries)
    print("\n产出：")
    print("  md   %s" % md_path)
    print("  json %s" % json_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
