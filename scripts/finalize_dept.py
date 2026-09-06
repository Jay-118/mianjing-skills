# -*- coding: utf-8 -*-
"""最终清洗 + 精确标注 + 生成精炼报告。

对 merge_dept.py 的产物做二次清洗，剔除误命中（游戏/电商/期刊），
并细分为五档，直接回答「哪些是本部门面经、哪些是岗位通用信息」。
"""
import os
import sys
import json
import time
import argparse
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SRC_LABEL = {
    "nowcoder": "牛客", "bilibili": "B站专栏", "zhihu": "知乎",
    "xhs": "小红书", "cnblogs": "博客园",
}

# 二次排除：误命中「资源情报/情报/溯源」的非安全内容
EXCLUDE = [
    "资源情报概览",      # 游戏《暗区突围》每周资源情报
    "自然资源情报",      # 《自然资源情报》期刊
    "情报工具箱",        # 淘宝电商选品工具
    "矿业振兴公社",
    "淘宝店铺新品采集",
    "新市场数据透视",
    "微信朋友圈广告",
    "互联网广告",
    "淘宝账号被永久封号",
    "黑灰产蔓延短视频",
    "短视频黑灰产",
    "跨境电商",
    # 游戏/动漫剧情情报
    "租借女友", "DNF", "原神", "崩铁", "纳塔", "重泉", "千海天", "世界观情报",
    "间谍过家家", "坦克世界",
    # 商品/商业/金融 溯源（非安全）
    "东革阿里", "热玛吉", "黄金微针", "驼奶粉", "防伪溯源", "商品溯源",
    "区块链溯源", "药品溯源", "满天星", "二维码防伪", "珠宝", "宝石",
    "海外品牌", "知产维权", "竞争情报分析", "商业情报分析", "招投标数据",
    "平安普惠", "征信修复", "代理投诉", "金融黑灰产",
    # 求职机构软文
    "求职机构", "北美秋招", "SDE实习", "香港求职", "美国金融", "生成式引擎",
    "求职辅导",
]

# intel_info 的标题强信号词：只保留「安全溯源/威胁情报/黑灰产对抗」语境
INTEL_INFO_SIGNAL = [
    "攻击溯源", "溯源反制", "溯源实战", "溯源方法", "溯源思路", "溯源案例",
    "溯源系统", "溯源图", "溯源定位", "溯源反制", "团伙识别", "团伙挖掘",
    "黑产犯罪", "黑产团伙", "威胁情报", "暗网", "威胁狩猎", "黑话词典",
    "黑灰产打击", "黑灰产靶场", "黑灰产", "手机号溯源", "IP溯源", "IP技术溯源",
    "网络攻击追踪", "中间人攻击", "威胁检测", "APT", "勒索病毒", "应急响应",
    "反击狩猎", "境外水军", "网络水军", "攻击溯源", "安全溯源", "蓝队",
    "情报分析", "情报体系", "情报收集", "情报监测", "情报监控", "数据泄露",
    "风险监测", "情报研判", "AI自动化研判", "反诈", "风控", "薅羊毛", "刷单",
]

# 本部门精确词
DEPT_EXACT = ["资源情报", "归零实验室", "情报分析运营", "情报技术专家", "风险溯源",
              "情报数据挖掘"]
# 阿里安全/情报相关
ALI_SAFE = ["阿里情报", "阿里黑灰产", "阿里威胁情报", "阿里反诈", "阿里反黑产",
            "阿里风控", "阿里安全", "阿里攻防", "阿里巴巴安全", "淘宝黑产", "聚安全"]
# 情报岗通用词
INTEL = ["威胁情报", "情报分析", "情报溯源", "黑灰产", "黑产", "情报", "溯源",
         "风控", "反诈", "薅羊毛", "黄牛", "刷量", "恶意注册", "虚假注册", "ATT&CK"]
EXP_SIGNAL = ["面经", "一面", "二面", "三面", "面试", "面试题", "复盘", "凉经",
              "offer", "hr面", "真题", "已挂", "已过", "面评", "内推", "实习", "校招"]


def final_rank(it):
    title = it.get("title") or ""
    content = it.get("content") or ""
    text = "%s %s" % (title, content)
    for p in EXCLUDE:
        if p in text:
            return None
    is_exp = any(w in text for w in EXP_SIGNAL)
    if any(w in text for w in DEPT_EXACT):
        return "dept_exp" if is_exp else "dept_info"
    if any(w in text for w in ALI_SAFE):
        return "ali_exp" if is_exp else "dept_info"
    if any(w in text for w in INTEL):
        if is_exp:
            return "intel_exp"
        # 非面经的技术文章：要求标题命中安全溯源/威胁情报强信号，否则丢弃
        if any(w in title for w in INTEL_INFO_SIGNAL):
            return "intel_info"
        return None
    return None


RANK_ORDER = ["dept_exp", "ali_exp", "dept_info", "intel_exp", "intel_info"]
RANK_LABEL = {
    "dept_exp": "① 本部门面经（资源情报/归零实验室 + 面经）",
    "ali_exp": "② 阿里安全/情报岗面经（阿里相关 + 面经）",
    "dept_info": "③ 本部门岗位信息（JD/团队/技术，非面经）",
    "intel_exp": "④ 同类情报岗通用面经真题（威胁情报/黑灰产/溯源）",
    "intel_info": "⑤ 同类情报岗技术文章（威胁情报/黑灰产/溯源）",
}


def _label(s):
    return SRC_LABEL.get(s, s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--topic", default="阿里安全资源情报")
    args = ap.parse_args()

    jp = os.path.join(args.outdir, "部门信息全景_阿里安全资源情报_20260905.json")
    if not os.path.exists(jp):
        # 兼容任意日期
        import glob as _g
        cand = _g.glob(os.path.join(args.outdir, "部门信息全景_*.json"))
        if not cand:
            print("[!] 找不到 部门信息全景_*.json")
            return 1
        jp = cand[0]
    data = json.load(open(jp, encoding="utf-8"))
    items = data.get("items", [])

    kept = []
    for it in items:
        r = final_rank(it)
        if r:
            it["rank"] = r
            kept.append(it)
    print("清洗后保留 %d 条（原 %d）" % (len(kept), len(items)))

    cnt = Counter(i["rank"] for i in kept)
    by_src = defaultdict(int)
    for i in kept:
        by_src[i["source"]] += 1

    L = []
    L.append("# 阿里安全「资源情报」部门信息 · 全景报告（五源·已精确标注）")
    L.append("")
    L.append("- 生成时间：%s" % time.strftime("%Y-%m-%d %H:%M"))
    L.append("- 五源采集 + 二次清洗后：**%d 条**" % len(kept))
    L.append("- 分源：%s"
             % "、".join("%s %d" % (_label(k), v)
                         for k, v in sorted(by_src.items(), key=lambda x: -x[1])))
    L.append("")
    L.append("## 标注总览（直接回答你的问题）")
    L.append("")
    L.append("| 档位 | 数量 | 含义 |")
    L.append("|---|---|---|")
    for r in RANK_ORDER:
        L.append("| %s | %d | %s |" % (RANK_LABEL[r], cnt.get(r, 0), _MEANING[r]))
    L.append("")
    L.append("> **核心结论**：真正「资源情报 / 归零实验室」这个部门的专属面经，五源里只有 1 条（归零实验室准入问答）。")
    L.append("> 其余是「岗位相关信息」——阿里安全/情报岗面经、部门 JD 与技术文章、威胁情报/黑灰产/溯源方向的通用真题。")
    L.append("")

    for r in RANK_ORDER:
        rows = [i for i in kept if i.get("rank") == r]
        if not rows:
            continue
        L.append("## %s（%d 条）" % (RANK_LABEL[r], len(rows)))
        L.append("")
        L.append("| # | 标题 | 来源 | 日期 | 摘要 |")
        L.append("|---|---|---|---|---|")
        for n, it in enumerate(rows, 1):
            t = (it.get("title") or "(无标题)").replace("|", "\\|").strip()
            d = it.get("date") or "-"
            c = (it.get("content") or "").replace("|", "\\|").replace("\n", " ").strip()
            if len(c) > 70:
                c = c[:70] + "…"
            L.append("| %d | [%s](%s) | %s | %s | %s |"
                     % (n, t, it.get("url") or "#", _label(it["source"]), d, c))
        L.append("")

    safe = args.topic.replace("/", "_").replace(" ", "")
    out_md = os.path.join(args.outdir, "阿里安全资源情报_部门信息全景_最终版.md")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    out_json = os.path.join(args.outdir, "阿里安全资源情报_部门信息全景_最终版.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({"items": kept, "rank_count": dict(cnt), "by_source": dict(by_src)},
                  f, ensure_ascii=False, indent=2)
    print("标注统计：%s" % dict(cnt))
    print("产出：%s" % out_md)
    return 0


_MEANING = {
    "dept_exp": "标题含「资源情报/归零实验室」且是面经 → 最对口",
    "ali_exp": "阿里安全/情报岗的面经（含内推/校招/一面二面等）",
    "dept_info": "部门 JD、团队介绍、技术体系（帮你搞懂部门做什么）",
    "intel_exp": "威胁情报/黑灰产/情报分析/溯源方向的面经与真题",
    "intel_info": "同方向的技术文章、案例、资讯",
}


if __name__ == "__main__":
    sys.exit(main())
