# -*- coding: utf-8 -*-
"""生成分域刷题计划 —— 把知识域分布转成可执行的复习排期。

与 cluster.py 的区别
------------------
cluster.py 回答「题库里有什么」，本脚本回答「我该按什么顺序、
花多少时间刷完」。输出一份可打勾的 checklist。

排期逻辑
--------
1. 按域题量降序 = 考频优先级（题量大说明面试官爱问）
2. 每域估时 = 题数 × 单题预估（默认 4 分钟：读题 + 回忆 + 查缺）
3. 按每日可投入时长切分成天，保证同一域尽量不跨天割裂
4. HR/软技能 类固定排最后（临面前突击即可，不占黄金时段）

用法
----
    python plan.py <题库json> --days 7 --hours 2
    python plan.py <题库json> --days 14 --hours 1.5 --out D:/out/计划.md
"""
import os
import sys
import json
import io
import math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cluster import classify, OTHER, DOMAINS     # noqa: E402

MIN_PER_Q = 4.0           # 单题预估分钟
DEFER_DOMAINS = ("HR 与软技能",)   # 排到最后的域


def collect(path):
    """按域归集题目。

    注意：一题可命中多域，若直接累加会导致总量虚高
    （实测 426 道题按域累加变成 624）。因此**每题只归入其首要域**
    （DOMAINS 中靠前者优先），保证 sum(各域题数) == 实际题数。
    """
    with io.open(path, encoding="utf-8") as f:
        d = json.load(f)
    priority = {name: i for i, (name, _) in enumerate(DOMAINS)}
    priority[OTHER] = len(DOMAINS) + 1

    buckets = {}
    for q in d.get("questions") or []:
        doms = classify(q.get("question") or "")
        primary = min(doms, key=lambda x: priority.get(x, 999))
        buckets.setdefault(primary, []).append(q)
    return buckets


def order_domains(buckets):
    """题量降序；DEFER_DOMAINS 与未归类挪到末尾。"""
    items = [(k, v) for k, v in buckets.items()]
    core = [x for x in items if x[0] not in DEFER_DOMAINS and x[0] != OTHER]
    tail = [x for x in items if x[0] in DEFER_DOMAINS]
    other = [x for x in items if x[0] == OTHER]
    core.sort(key=lambda x: -len(x[1]))
    tail.sort(key=lambda x: -len(x[1]))
    return core + tail + other


def spread_other(ordered, days):
    """把「未归类」打散穿插到各天，而不是独占末尾若干天。

    实测问题：未归类 118 道会独占 Day10~14 五天。这批题最杂、最难聚焦，
    连续刷五天效率低；而前面的高频域反而被压缩。
    解法：把未归类按天数均分成小块，插到每个核心域之后，
    让每天都是「主攻一个域 + 少量杂题」。
    """
    core = [x for x in ordered if x[0] != OTHER]
    other = [x for x in ordered if x[0] == OTHER]
    if not other or not core:
        return ordered
    qs = other[0][1]
    if len(qs) < days:
        return core + other

    chunk = int(math.ceil(len(qs) / float(days)))
    pieces = [qs[i:i + chunk] for i in range(0, len(qs), chunk)]
    out, pi = [], 0
    # 每放一个核心域，跟一小块杂题
    step = max(1, int(math.ceil(len(core) / float(len(pieces)))))
    for i, item in enumerate(core):
        out.append(item)
        if (i + 1) % step == 0 and pi < len(pieces):
            out.append((OTHER, pieces[pi]))
            pi += 1
    while pi < len(pieces):
        out.append((OTHER, pieces[pi]))
        pi += 1
    return out


def build_plan(ordered, days, hours):
    """把域切分到每一天。返回 ([(域, 题目切片)...] per day, 每日用时)

    设计要点
    -------
    1. 若总量超出 days×hours 预算，**按实际总量均摊**而非塞满前几天再把
       溢出全丢末日。早期版本会造成 Day14 堆 234 道（936 分钟）的畸形排期。
    2. 同一天内同一域只出现一个条目 —— 早期版本因先 append 再判断
       会让同域被拆成两条相邻记录（如「应急响应与溯源」重复两次）。
    """
    total_q = sum(len(v) for _, v in ordered)
    budget = hours * 60.0      # 每日时长由 render() 的 gap 提示使用

    plan = [[] for _ in range(days)]
    used = [0.0] * days
    # 每个域的待分配队列；bi 指向当前正在填的域
    queues = [list(qs) for _, qs in ordered]
    remain_total = total_q
    bi = 0

    for day in range(days):
        if bi >= len(queues):
            break
        # 配额按「剩余题数 / 剩余天数」动态计算，而不是固定 ceil(总量/天数)。
        # 固定配额会让 11 题排 7 天时只填满 6 天（ceil(11/7)=2 → 需 6 天），
        # 剩 1 天空着。动态配额下每天目标递减，天数刚好用满。
        left_days = days - day
        target = max(1, int(math.ceil(remain_total / float(left_days))))
        while used[day] < target * MIN_PER_Q and bi < len(queues):
            if not queues[bi]:
                bi += 1
                continue
            free = int(target - used[day] // MIN_PER_Q)
            slice_ = queues[bi][:free]
            queues[bi] = queues[bi][free:]
            dom = ordered[bi][0]
            # 同一天同一域合并，不产生重复条目
            if plan[day] and plan[day][-1][0] == dom:
                plan[day][-1][1].extend(slice_)
            else:
                plan[day].append((dom, list(slice_)))
            used[day] += len(slice_) * MIN_PER_Q
            remain_total -= len(slice_)
            if not queues[bi]:
                bi += 1
    return plan, used


def render(path_json, days, hours, out_md):
    buckets = collect(path_json)
    if not buckets:
        print("题库为空")
        return 1
    ordered = order_domains(buckets)
    total_q = sum(len(v) for _, v in ordered)
    total_min = total_q * MIN_PER_Q
    ordered = spread_other(ordered, days)
    plan, used = build_plan(ordered, days, hours)

    L = []
    L.append("# 分域刷题计划")
    L.append("")
    L.append("- 题目总量：**%d** 道" % total_q)
    L.append("- 预估总时长：**%.1f 小时**（单题 %.0f 分钟）"
             % (total_min / 60.0, MIN_PER_Q))
    L.append("- 排期：%d 天，实际每日约 %.0f 分钟"
             % (days, total_min / days))
    gap = total_min / 60.0 - days * hours
    if gap > 0.5:
        L.append("- 提示：按每日 %.1f 小时算需 %.1f 天。"
                 "当前已按 %d 天**均摊**（每天约 %.0f 分钟），"
                 "如需严格控制每日时长请增加 `--days`"
                 % (hours, total_min / 60.0 / hours, days, total_min / days))
    L.append("")
    L.append("> 排序依据：域内题量降序 = 考频优先级。"
             "HR/软技能 排在最后（临面突击即可）。"
             "未归类题目已**打散穿插**到各天，"
             "让每天都是「主攻一个域 + 少量杂题」，避免连续多天啃杂题。")
    L.append("")

    # ---- 优先级总览（用未打散的域视图）----
    overview = order_domains(buckets)
    L.append("## 优先级总览")
    L.append("")
    L.append("| # | 知识域 | 题数 | 预估 |")
    L.append("|---:|---|---:|---:|")
    for i, (dom, qs) in enumerate(overview, 1):
        L.append("| %d | %s | %d | %.0f 分钟 |"
                 % (i, dom, len(qs), len(qs) * MIN_PER_Q))
    L.append("")

    # ---- 每日安排 ----
    L.append("## 每日安排")
    L.append("")
    for i, blocks in enumerate(plan, 1):
        if not blocks:
            continue
        n = sum(len(s) for _, s in blocks)
        L.append("### Day %d　%d 道题　约 %.0f 分钟" % (i, n, used[i - 1]))
        L.append("")
        for dom, slice_ in blocks:
            L.append("**%s**（%d 道）" % (dom, len(slice_)))
            L.append("")
            for q in slice_:
                url = q.get("from_url", "")
                src = q.get("source", "")
                L.append("- [ ] %s　<sub>[%s](%s)</sub>"
                         % (q.get("question", ""), src, url))
            L.append("")

    with io.open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(L))

    print("题目 %d 道 | 预估 %.1f 小时 | 排 %d 天（每天约 %.0f 分钟）"
          % (total_q, total_min / 60.0, days, total_min / days))
    if gap > 0.5:
        print("[i] 按每日 %.1f 小时需 %.1f 天；已按 %d 天均摊"
              % (hours, total_min / 60.0 / hours, days))
    print("")
    peak = max(used) if used else 0
    for i, blocks in enumerate(plan, 1):
        if blocks:
            n = sum(len(s) for _, s in blocks)
            doms = "、".join(d for d, _ in blocks)
            print("  Day %-2d %3d 道  %3.0f 分钟  %s"
                  % (i, n, used[i - 1], doms[:44]))
    print("")
    empty = sum(1 for b in plan if not b)
    print("每日负载：最高 %.0f 分钟 / 最低 %.0f 分钟（越接近越均衡）"
          % (peak, min(u for u in used if u > 0) if any(used) else 0))
    # 空天是排期缺陷的信号，不能只统计 u>0 而把它掩盖掉。
    # 但题数 < 天数时（如 11 题排 14 天）空天是数学必然，属正常，不告警。
    if empty and total_q >= days:
        print("[!] 有 %d 天为空 —— 排期异常，检查 build_plan() 的每日配额"
              % empty)
    elif empty:
        print("[i] 题数 %d < 天数 %d，有 %d 天为空（正常）"
              % (total_q, days, empty))
    print("已输出: %s" % out_md)
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    src = sys.argv[1]
    days, hours, out = 7, 2.0, None
    if "--days" in sys.argv:
        i = sys.argv.index("--days")
        if i + 1 < len(sys.argv):
            days = max(1, int(sys.argv[i + 1]))
    if "--hours" in sys.argv:
        i = sys.argv.index("--hours")
        if i + 1 < len(sys.argv):
            hours = max(0.5, float(sys.argv[i + 1]))
    if "--out" in sys.argv:
        i = sys.argv.index("--out")
        if i + 1 < len(sys.argv):
            out = sys.argv[i + 1]
    if not out:
        base = os.path.basename(src).replace("题库_", "刷题计划_")
        out = os.path.join(os.path.dirname(src),
                           base.rsplit(".", 1)[0] + ".md")
    return render(src, days, hours, out)


if __name__ == "__main__":
    sys.exit(main())
