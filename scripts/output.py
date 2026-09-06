# -*- coding: utf-8 -*-
"""输出层 —— Markdown 汇总 / 题库 JSON / txt 报告 三件套。

txt 硬性要求：UTF-8 **带 BOM** + **CRLF** 行尾，
否则 Windows 记事本打开中文乱码。
"""
import io
import os
import json
import time

SRC_LABEL = {
    "nowcoder": "牛客",
    "bilibili": "B站专栏",
    "zhihu": "知乎",
    "xhs": "小红书",
    "cnblogs": "博客园",
}

DISCLAIMER = (
    "题目源自各平台搜索摘要，可能断句不全或缺失上下文，"
    "务必点开原帖链接核对，不要直接当成完整原题使用。"
)

NO_DATE_NOTE = (
    "知乎搜索卡片不提供发布日期，故知乎条目日期显示为「-」，"
    "且未参与时间窗过滤（可能包含较早内容），请自行留意时效。"
)


def _has_undated(items):
    return any(not it.get("date") for it in items)


def _label(s):
    return SRC_LABEL.get(s, s)


def _funnel_lines(f):
    return [
        "原始抓取           %d" % f.get("raw", 0),
        "跨平台去重后       %d" % f.get("after_dedup", 0),
        "去软文噪声后       %d" % f.get("after_noise", 0),
        "面经信号过滤后     %d" % f.get("after_exp_signal", 0),
        "去标题党后         %d" % f.get("after_clickbait", 0),
        "去非技术岗后       %d" % f.get("after_non_tech", 0),
        "时间窗过滤后       %d" % f.get("after_time", 0),
        "最终入选           %d  (A档 %d / B档 %d / C档 %d)"
        % (f.get("final", 0), f.get("grade_A", 0),
           f.get("grade_B", 0), f.get("grade_C", 0)),
        "抽取候选题目       %d" % f.get("questions", 0),
    ]


# ---------------- Markdown ----------------

def write_markdown(path, topic, items, bank, funnel, queries):
    L = []
    L.append("# %s 面经汇总" % topic)
    L.append("")
    L.append("- 采集时间：%s" % time.strftime("%Y-%m-%d %H:%M"))
    L.append("- 关键词数：%d" % len(queries))
    L.append("- 数据来源：%s"
             % "、".join("%s %d 条" % (_label(k), v)
                         for k, v in sorted(funnel.get("by_source", {}).items(),
                                            key=lambda x: -x[1])))
    L.append("")
    L.append("> %s" % DISCLAIMER)
    L.append("")
    if _has_undated(items):
        L.append("> %s" % NO_DATE_NOTE)
        L.append("")

    L.append("## 采集漏斗")
    L.append("")
    L.append("| 阶段 | 数量 |")
    L.append("|---|---|")
    for ln in _funnel_lines(funnel):
        name, num = ln.rsplit("  ", 1) if "  " in ln else (ln, "")
        L.append("| %s | %s |" % (name.strip(), num.strip()))
    L.append("")

    for g, gname in (("A", "A 档 · 直接对口"), ("B", "B 档 · 相关"),
                     ("C", "C 档 · 弱相关")):
        rows = [i for i in items if i.get("grade") == g]
        if not rows:
            continue
        L.append("## %s（%d 条）" % (gname, len(rows)))
        L.append("")
        L.append("| # | 标题 | 来源 | 日期 | 链接 |")
        L.append("|---|---|---|---|---|")
        for n, it in enumerate(rows, 1):
            t = (it["title"] or "(无标题)").replace("|", "\\|")
            L.append("| %d | %s | %s | %s | [原帖](%s) |"
                     % (n, t, _label(it["source"]),
                        it.get("date") or "-", it["url"]))
        L.append("")

    if bank:
        L.append("## 题库（%d 道）" % len(bank))
        L.append("")
        L.append("> 以下题目由摘要自动抽取，每题标注来源，请回原帖核对。")
        L.append("")
        for n, q in enumerate(bank, 1):
            L.append("%d. %s" % (n, q["question"]))
            L.append("   - 来源：%s · [%s](%s)"
                     % (_label(q["source"]),
                        (q["from_title"] or "原帖")[:40], q["from_url"]))
        L.append("")

    _dump(path, "\n".join(L), bom=False, crlf=False)
    return path


# ---------------- 题库 JSON ----------------

def write_json(path, topic, items, bank, funnel, queries):
    payload = {
        "topic": topic,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "disclaimer": DISCLAIMER,
        "queries": queries,
        "funnel": funnel,
        "posts": items,
        "questions": bank,
    }
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


# ---------------- txt 报告 ----------------

def write_txt(path, topic, items, bank, funnel, queries):
    W = []
    bar = "=" * 60
    W.append(bar)
    W.append("　　%s 面经采集报告" % topic)
    W.append(bar)
    W.append("")
    W.append("采集时间：%s" % time.strftime("%Y-%m-%d %H:%M"))
    W.append("关键词数：%d" % len(queries))
    W.append("")
    if _has_undated(items):
        W.append("　　注意：%s" % NO_DATE_NOTE)
        W.append("")
    W.append("-" * 60)
    W.append("【1】采集漏斗")
    W.append("-" * 60)
    for ln in _funnel_lines(funnel):
        W.append("　　%s" % ln)
    W.append("")
    W.append("　　分源统计：")
    for k, v in sorted(funnel.get("by_source", {}).items(),
                       key=lambda x: -x[1]):
        W.append("　　　　%-10s %d 条" % (_label(k), v))
    W.append("")

    W.append("-" * 60)
    W.append("【2】面经列表")
    W.append("-" * 60)
    for g, gname in (("A", "A 档 · 直接对口"), ("B", "B 档 · 相关"),
                     ("C", "C 档 · 弱相关")):
        rows = [i for i in items if i.get("grade") == g]
        if not rows:
            continue
        W.append("")
        W.append("　◆ %s（%d 条）" % (gname, len(rows)))
        W.append("")
        for n, it in enumerate(rows, 1):
            W.append("　　[%d] %s" % (n, it["title"] or "(无标题)"))
            W.append("　　　　来源：%s　日期：%s　作者：%s"
                     % (_label(it["source"]), it.get("date") or "-",
                        it.get("author") or "-"))
            W.append("　　　　链接：%s" % it["url"])
            W.append("")

    if bank:
        W.append("-" * 60)
        W.append("【3】题库（%d 道）" % len(bank))
        W.append("-" * 60)
        W.append("　　注意：%s" % DISCLAIMER)
        W.append("")
        for n, q in enumerate(bank, 1):
            W.append("　　%d. %s" % (n, q["question"]))
            W.append("　　　 ← %s《%s》"
                     % (_label(q["source"]), (q["from_title"] or "原帖")[:36]))
            W.append("　　　 %s" % q["from_url"])
            W.append("")

    W.append(bar)
    W.append("　　全部标题/作者/时间/链接均为接口原样输出，未做任何改写。")
    W.append(bar)

    _dump(path, "\n".join(W), bom=True, crlf=True)
    return path


def _dump(path, text, bom=False, crlf=False):
    if crlf:
        text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    enc = "utf-8-sig" if bom else "utf-8"
    with io.open(path, "w", encoding=enc, newline="") as f:
        f.write(text)


def write_all(outdir, topic, items, bank, funnel, queries):
    os.makedirs(outdir, exist_ok=True)
    day = time.strftime("%Y%m%d")
    safe = topic.replace("/", "_").replace(" ", "")
    paths = {
        "md": os.path.join(outdir, "面经汇总_%s_%s.md" % (safe, day)),
        "json": os.path.join(outdir, "题库_%s_%s.json" % (safe, day)),
        "txt": os.path.join(outdir, "报告_%s_%s.txt" % (safe, day)),
    }
    write_markdown(paths["md"], topic, items, bank, funnel, queries)
    write_json(paths["json"], topic, items, bank, funnel, queries)
    write_txt(paths["txt"], topic, items, bank, funnel, queries)
    return paths
