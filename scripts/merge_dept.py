# -*- coding: utf-8 -*-
"""合并多批部门信息采集结果，并按「是否为本部门面经」做四档标注。

标注档位：
  【本部门面经】   标题/摘要明确命中「资源情报 / 归零实验室」且含面经信号
  【本部门信息】   明确命中「资源情报 / 归零实验室 / 阿里情报岗」，但是 JD/团队/技术文章，非面经
  【同类情报岗·通用】威胁情报/黑灰产/情报分析/溯源/风控方向的通用面经与信息（非阿里专属）
  【阿里安全·通用】  阿里安全岗通用面经（渗透/应急响应/逆向等，与情报岗无直接关系）

用法：
  python merge_dept.py <outdir> --topic 阿里安全资源情报
  自动读 outdir 下所有 `部门信息_*.json`，合并去重 + 标注 + 输出综合报告。
"""
import os
import sys
import glob
import json
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from normalize import dedup

SRC_LABEL = {
    "nowcoder": "牛客",
    "bilibili": "B站专栏",
    "zhihu": "知乎",
    "xhs": "小红书",
    "cnblogs": "博客园",
}

# 直接命中部门的词
DEPT_EXACT = ["资源情报", "归零实验室"]
# 阿里情报岗相关词
ALI_INTEL = ["阿里情报", "阿里安全情报", "阿里黑灰产", "阿里威胁情报", "阿里情报分析",
             "阿里情报溯源", "阿里反诈", "阿里反黑产", "阿里黑产", "阿里风控"]
# 情报岗通用词（非阿里专属）
INTEL_GENERIC = ["威胁情报", "情报分析", "情报溯源", "黑灰产", "黑产", "情报", "溯源",
                 "风控", "反诈", "薅羊毛", "黄牛", "刷量", "虚假注册", "恶意注册"]
# 面经信号
EXP_SIGNAL = ["面经", "一面", "二面", "三面", "面试", "面试题", "复盘", "凉经",
              "offer", "hr面", "真题", "已挂", "已过", "面评"]

RANK_LABEL = {
    "dept_exp": "【本部门面经】",
    "dept_info": "【本部门信息】",
    "intel_generic": "【同类情报岗·通用】",
    "ali_generic": "【阿里安全·通用】",
}
RANK_ORDER = ["dept_exp", "dept_info", "intel_generic", "ali_generic"]


def classify(it):
    title = it.get("title") or ""
    content = it.get("content") or ""
    text = "%s %s" % (title, content)
    is_exp = any(w in text for w in EXP_SIGNAL)

    if any(w in text for w in DEPT_EXACT):
        return "dept_exp" if is_exp else "dept_info"
    if any(w in text for w in ALI_INTEL):
        return "dept_exp" if is_exp else "dept_info"
    if any(w in text for w in INTEL_GENERIC):
        return "intel_generic"
    return "ali_generic"


def _label(s):
    return SRC_LABEL.get(s, s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir", help="采集输出目录")
    ap.add_argument("--topic", default="阿里安全资源情报")
    args = ap.parse_args()

    jsons = sorted(glob.glob(os.path.join(args.outdir, "部门信息_*.json")))
    if not jsons:
        print("[!] %s 下没有 部门信息_*.json" % args.outdir)
        return 1

    all_items, queries = [], []
    for jp in jsons:
        data = json.load(open(jp, encoding="utf-8"))
        all_items.extend(data.get("posts", []))
        queries.extend(data.get("queries", []))
        print("  读入 %s（%d 条）" % (os.path.basename(jp), len(data.get("posts", []))))

    items = dedup(all_items)
    print("  合并去重后 %d 条" % len(items))

    # 标注
    for it in items:
        it["rank"] = classify(it)

    # 按档位 + 来源统计
    from collections import Counter, defaultdict
    cnt = Counter(it["rank"] for it in items)
    by_src = defaultdict(int)
    for it in items:
        by_src[it["source"]] += 1

    # 输出综合报告
    L = []
    L.append("# %s · 部门信息全景报告（五源合并·已标注）" % args.topic)
    L.append("")
    L.append("- 合并时间：%s" % time.strftime("%Y-%m-%d %H:%M"))
    L.append("- 合并来源：%d 份采集，去重后 %d 条"
             % (len(jsons), len(items)))
    L.append("- 分源：%s"
             % "、".join("%s %d 条" % (_label(k), v)
                         for k, v in sorted(by_src.items(), key=lambda x: -x[1])))
    L.append("")
    L.append("## 标注总览")
    L.append("")
    L.append("| 档位 | 含义 | 数量 |")
    L.append("|---|---|---|")
    for r in RANK_ORDER:
        L.append("| %s | %s | %d |" % (RANK_LABEL[r], _RANK_MEANING[r], cnt.get(r, 0)))
    L.append("")
    L.append("> 说明：")
    L.append("> - **【本部门面经】** 是置信度最高的——标题/摘要里明确出现「资源情报 / 归零实验室」，且是面试经历。")
    L.append("> - **【本部门信息】** 是阿里该部门（资源情报/归零实验室/情报岗）的 JD、团队介绍、技术文章，不是面经但能帮你搞懂部门做什么。")
    L.append("> - 其余两档是「岗位相关通用信息」，非本部门专属，供横向参考。")
    L.append("")

    for r in RANK_ORDER:
        rows = [i for i in items if i.get("rank") == r]
        if not rows:
            continue
        # 按来源分组展示
        L.append("## %s（%d 条）" % (RANK_LABEL[r], len(rows)))
        L.append("")
        L.append("| # | 标题 | 来源 | 日期 | 作者 | 摘要 |")
        L.append("|---|---|---|---|---|---|")
        for n, it in enumerate(rows, 1):
            t = (it.get("title") or "(无标题)").replace("|", "\\|").strip()
            d = it.get("date") or "-"
            a = (it.get("author") or "-").replace("|", "\\|").strip()
            c = (it.get("content") or "").replace("|", "\\|").replace("\n", " ").strip()
            if len(c) > 60:
                c = c[:60] + "…"
            L.append("| %d | [%s](%s) | %s | %s | %s | %s |"
                     % (n, t, it.get("url") or "#", _label(it["source"]), d, a, c))
        L.append("")

    safe = args.topic.replace("/", "_").replace(" ", "")
    out_md = os.path.join(args.outdir, "部门信息全景_%s_%s.md"
                          % (safe, time.strftime("%Y%m%d")))
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(L))

    # JSON（带标注）
    out_json = os.path.join(args.outdir, "部门信息全景_%s_%s.json"
                            % (safe, time.strftime("%Y%m%d")))
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({"topic": args.topic, "items": items,
                   "rank_count": dict(cnt), "by_source": dict(by_src)},
                  f, ensure_ascii=False, indent=2)

    print("\n产出：")
    print("  md   %s" % out_md)
    print("  json %s" % out_json)
    print("  标注统计：%s" % dict(cnt))
    return 0


_RANK_MEANING = {
    "dept_exp": "明确资源情报/归零实验室 + 面经",
    "dept_info": "资源情报/归零实验室/阿里情报岗的 JD/团队/技术（非面经）",
    "intel_generic": "威胁情报/黑灰产/情报/溯源/风控通用",
    "ali_generic": "阿里安全岗通用（渗透/应急/逆向）",
}


if __name__ == "__main__":
    sys.exit(main())
