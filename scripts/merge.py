# -*- coding: utf-8 -*-
"""合并多份题库为一个总库，跨批次去重。

为什么需要
--------
多次采集（不同方向、不同源组合、不同关键词量）会产出多份题库，
彼此有大量重叠。直接给用户 4 个 JSON 让他自己比对不合理。
本脚本把它们合成一份「总题库」，并保留每道题的全部来源。

去重策略
--------
* 帖子：按 uid（{source}:{id}）精确去重 + 标题 SimHash 近似去重
* 题目：按归一化文本去重；同一道题若来自多个帖子，**合并 sources 列表**
  而不是丢弃 —— 多源出现说明这题更高频，是有价值的信号

用法
----
    python merge.py <outdir> --topic 总库
    python merge.py <outdir> --topic 总库 --exclude 端到端验证
"""
import os
import re
import sys
import json
import glob
import io

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from normalize import dedup, grade, _norm_title      # noqa: E402
from output import write_all                          # noqa: E402


def load_all(outdir, exclude=None):
    """读取目录下全部题库 JSON，返回 (posts, questions, queries)。"""
    posts, questions, queries = [], [], []
    files = sorted(glob.glob(os.path.join(outdir, "题库_*.json")))
    used = []
    for p in files:
        base = os.path.basename(p)
        if exclude and any(e in base for e in exclude):
            print("  [skip] %s（被排除）" % base)
            continue
        try:
            with io.open(p, encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:
            print("  [warn] %s 读取失败: %s" % (base, e))
            continue
        n_p = len(d.get("posts") or [])
        n_q = len(d.get("questions") or [])
        print("  [load] %-34s 帖 %4d | 题 %4d" % (base, n_p, n_q))
        posts.extend(d.get("posts") or [])
        questions.extend(d.get("questions") or [])
        for q in (d.get("queries") or []):
            if q not in queries:
                queries.append(q)
        used.append(base)
    return posts, questions, queries, used


def merge_questions(questions, prefix_len=24):
    """按归一化文本合并题目，同题多源时合并 sources。

    两级去重：
      1) 全文归一化精确匹配
      2) 前 prefix_len 个归一化字符相同 → 视为同题（吸收表述末尾差异）

    实测（2026-09-03）：1300 题合并后 490 题，其中仅 1 道被多个帖子命中。
    **这是真实情况，不是 bug** —— 各平台面经的题目表述差异很大，
    真正字面重合的极少。二级前缀匹配又多收掉 6 条。
    """
    bag = {}
    prefix_map = {}

    def _src(q):
        return {
            "source": q.get("source", ""),
            "from_title": q.get("from_title", ""),
            "from_url": q.get("from_url", ""),
            "date": q.get("date", ""),
        }

    for q in questions:
        text = (q.get("question") or "").strip()
        if not text:
            continue
        key = _norm_title(text)
        if not key:
            continue
        # 二级：前缀命中已有题目则归并过去
        pk = key[:prefix_len]
        target = bag.get(key)
        if target is None and len(pk) >= prefix_len:
            hit = prefix_map.get(pk)
            if hit is not None:
                target = bag.get(hit)

        src = _src(q)
        if target is not None:
            urls = {s["from_url"] for s in target["sources"]}
            if src["from_url"] not in urls:
                target["sources"].append(src)
            if len(text) > len(target["question"]):
                target["question"] = text
        else:
            bag[key] = {
                "question": text,
                "grade": q.get("grade", ""),
                "sources": [src],
            }
            if len(pk) >= prefix_len:
                prefix_map.setdefault(pk, key)

    out = list(bag.values())
    # 多源命中的题排前面（高频题更值得先看）
    out.sort(key=lambda x: (-len(x["sources"]), -len(x["question"])))
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    outdir = sys.argv[1]
    topic = "总库"
    exclude = ["总库"]          # 避免把上次的总库再合进来
    if "--topic" in sys.argv:
        i = sys.argv.index("--topic")
        if i + 1 < len(sys.argv):
            topic = sys.argv[i + 1]
            exclude = [topic]
    if "--exclude" in sys.argv:
        i = sys.argv.index("--exclude")
        if i + 1 < len(sys.argv):
            exclude.extend(sys.argv[i + 1].split(","))

    print("读取题库（排除：%s）" % ", ".join(exclude))
    posts, questions, queries, used = load_all(outdir, exclude)
    if not posts:
        print("未读到任何数据")
        return 1

    print("")
    print("合并前：帖 %d | 题 %d | 关键词 %d" % (len(posts), len(questions), len(queries)))

    uniq_posts = dedup(posts)
    uniq_posts = grade(uniq_posts)
    uniq_q = merge_questions(questions)

    multi = sum(1 for q in uniq_q if len(q["sources"]) > 1)
    by_src = {}
    for p in uniq_posts:
        by_src[p["source"]] = by_src.get(p["source"], 0) + 1

    print("合并后：帖 %d | 题 %d（其中 %d 道被多个帖子命中）"
          % (len(uniq_posts), len(uniq_q), multi))
    print("分源：%s" % ", ".join("%s %d" % (k, v) for k, v in
                              sorted(by_src.items(), key=lambda x: -x[1])))

    # 输出层需要 questions 带 source/from_title/from_url，取首个来源铺平
    flat_q = []
    for q in uniq_q:
        s0 = q["sources"][0]
        flat_q.append({
            "question": q["question"],
            "grade": q["grade"],
            "source": s0["source"],
            "from_title": s0["from_title"],
            "from_url": s0["from_url"],
            "date": s0["date"],
            "source_count": len(q["sources"]),
            "all_sources": q["sources"],
        })

    funnel = {
        "raw": len(posts),
        "after_dedup": len(uniq_posts),
        "final": len(uniq_posts),
        "grade_A": sum(1 for i in uniq_posts if i.get("grade") == "A"),
        "grade_B": sum(1 for i in uniq_posts if i.get("grade") == "B"),
        "grade_C": sum(1 for i in uniq_posts if i.get("grade") == "C"),
        "questions": len(flat_q),
        "by_source": by_src,
        "merged_from": used,
    }
    paths = write_all(outdir, topic, uniq_posts, flat_q, funnel, queries)
    print("")
    for k, v in paths.items():
        print("  %-5s %s" % (k, os.path.basename(v)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
