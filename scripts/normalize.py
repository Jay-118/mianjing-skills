# -*- coding: utf-8 -*-
"""归一层 —— 多源数据的统一 schema、去重、过滤、分级、题目抽取。

这是 interview-collector 的核心。各源适配器只负责把原始数据取回来并填成
统一 schema，所有清洗判断逻辑集中在这里，避免每个源各写一套。
"""
import re
import time
import hashlib

from keywords import (
    DIRECTION_KEYWORDS, ROLE_TITLE_WORDS, OTHER_ROLE_WORDS,
    NON_TECH_EXCLUDE, NOISE_WORDS, EXP_SIGNAL_WORDS, STRICT_EXP_SOURCES,
    CLICKBAIT_WORDS, CLICKBAIT_PUNCT, BOUNDARY_KEYWORDS,
)

# 短英文缩写预编译带边界的正则，避免 "RAII" 命中 "AI"、"MPC" 命中 "SMPCx" 等
_BOUNDARY_RE = {
    k: re.compile(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(k), re.I)
    for k in BOUNDARY_KEYWORDS
}
# 判断关键词是否含 ASCII 字母 —— 决定是否需要忽略大小写匹配
_HAS_ASCII_ALPHA_RE = re.compile(r"[A-Za-z]")


def hit(keyword, text):
    """判断关键词是否命中。

    三种匹配策略：
    1. 短英文缩写（BOUNDARY_KEYWORDS）→ 词边界正则，防 MCP 命中 SMPCx
    2. 含 ASCII 字母的关键词 → **忽略大小写**的子串匹配
       实测教训：词表写 `Skills`/`ReAct`，题目里是 `skills`/`react`，
       区分大小写会导致「skills是什么」命中 0 个方向词而被判为未归类
    3. 纯中文关键词 → 直接子串匹配（无大小写问题，最快）
    """
    if not text:
        return False
    rx = _BOUNDARY_RE.get(keyword)
    if rx is not None:
        return bool(rx.search(text))
    if _HAS_ASCII_ALPHA_RE.search(keyword):
        return keyword.lower() in text.lower()
    return keyword in text


def count_hits(keywords, text):
    return sum(1 for k in keywords if hit(k, text))

# ============ 1. 统一 schema ============

SCHEMA_FIELDS = (
    "uid",       # 全局唯一 id：{source}:{native_id}
    "source",    # nowcoder / xhs / zhihu / bilibili / cnblogs
    "title",
    "author",
    "date",      # YYYY-MM-DD，取不到留空字符串
    "ts",        # 毫秒时间戳，取不到为 0
    "url",
    "content",   # 摘要或正文
    "extra",     # dict，各源特有字段
)


def make_item(source, native_id, title, url, content="",
              author="", ts=0, extra=None):
    """构造标准 item。所有字段原样透传，不做任何编造。"""
    title = (title or "").strip()
    date = ""
    if ts:
        try:
            date = time.strftime("%Y-%m-%d", time.localtime(ts / 1000))
        except (ValueError, OSError):
            date = ""
    return {
        "uid": "%s:%s" % (source, native_id),
        "source": source,
        "title": title,
        "author": (author or "").strip(),
        "date": date,
        "ts": ts or 0,
        "url": url or "",
        "content": (content or "").strip(),
        "extra": extra or {},
    }


# ============ 2. 跨平台去重 ============

_PUNCT_RE = re.compile(r"[\s\W_]+", re.U)


def _norm_title(t):
    """标题归一化：去标点空白、转小写。"""
    return _PUNCT_RE.sub("", (t or "").lower())


def simhash(text, bits=64):
    """轻量 SimHash，用于近似标题去重（面经常被搬运到多个平台）。"""
    text = _norm_title(text)
    if not text:
        return 0
    # 中文按 2-gram 切
    grams = [text[i:i + 2] for i in range(max(1, len(text) - 1))] or [text]
    v = [0] * bits
    for g in grams:
        h = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16)
        for i in range(bits):
            v[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i in range(bits):
        if v[i] > 0:
            out |= 1 << i
    return out


def hamming(a, b):
    return bin(a ^ b).count("1")


def dedup(items, sim_threshold=3):
    """两级去重：
    1) URL 精确去重
    2) 标题 SimHash 近似去重（汉明距离 <= threshold 视为同一篇）

    保留策略：优先保留 content 更长的（信息量更大），其次保留有时间的。
    """
    # --- URL 精确 ---
    by_url = {}
    for it in items:
        u = it.get("url", "").split("?")[0].rstrip("/")
        key = u or it["uid"]
        old = by_url.get(key)
        if old is None or _richer(it, old):
            by_url[key] = it
    pool = list(by_url.values())

    # --- SimHash 近似 ---
    kept, sigs = [], []
    for it in sorted(pool, key=lambda x: -len(x.get("content", ""))):
        sig = simhash(it["title"])
        if sig and any(hamming(sig, s) <= sim_threshold for s in sigs):
            continue
        sigs.append(sig)
        kept.append(it)
    return kept


def _richer(a, b):
    """a 是否比 b 更值得保留。"""
    if len(a.get("content", "")) != len(b.get("content", "")):
        return len(a.get("content", "")) > len(b.get("content", ""))
    return bool(a.get("ts")) and not b.get("ts")


# ============ 3. 过滤 ============

def filter_noise(items):
    """丢掉软文推广与空标题。"""
    out = []
    for it in items:
        t = it.get("title", "")
        if not t:
            continue
        if any(w in t for w in NOISE_WORDS):
            continue
        out.append(it)
    return out


def filter_non_tech(items):
    """标题命中非技术岗词即剔除。"""
    return [it for it in items
            if not any(w in it.get("title", "") for w in NON_TECH_EXCLUDE)]


def filter_time_window(items, days=730):
    """时间窗过滤。ts=0（取不到时间）的默认保留，但会在报告里标注。"""
    cutoff = (time.time() - days * 86400) * 1000
    return [it for it in items if it.get("ts", 0) == 0 or it["ts"] >= cutoff]


def require_exp_signal(items):
    """对营销噪声重的源（B站/小红书/博客园）强制要求标题含面经信号。

    实测教训（2026-09-03）
    -------------------
    B站专栏营销软文远多于牛客。不加这条时，以下内容会被判为 A 档面经：
      「2026下半年软考中级-信息安全工程师学习计划及备考攻略」
      「做渗透测试工作，哪些证书比较有含金量？」
      「Strix：用AI做渗透测试，把安全漏洞扼杀在开发阶段」
    它们标题含「渗透测试/信息安全」+ 正文含方向词，但根本不是面经。
    牛客不启用此规则 —— 牛客站内 feed 类面经常常标题很短甚至无标题。
    """
    out = []
    for it in items:
        if it.get("source") in STRICT_EXP_SOURCES:
            lt = (it.get("title") or "").lower()
            if not any(w in lt for w in EXP_SIGNAL_WORDS):
                continue
        out.append(it)
    return out


def filter_clickbait(items):
    """拦标题党伪面经。

    实测教训（2026-09-03）
    -------------------
    营销号量产的内容标题里带「面试题」，能绕过 require_exp_signal，
    B站 A 档 13 条里有 8 条是这类：
      「速戳！网络安全与渗透测试工程师高频面试题一键解锁」
      「哇哦！网络安全与渗透测试工程师高频面试题，太实用」
      「网络安全工程师职场面试慌？15 个题库来救场！」
    特征是情绪化感叹词 + 连续感叹号，且同一批账号反复发。
    只对 STRICT_EXP_SOURCES 生效，牛客真实面经里也有人用感叹号。
    """
    out = []
    for it in items:
        if it.get("source") in STRICT_EXP_SOURCES:
            t = it.get("title") or ""
            lt = t.lower()
            if any(w in lt for w in CLICKBAIT_WORDS):
                continue
            if any(p in t for p in CLICKBAIT_PUNCT):
                continue
        out.append(it)
    return out


# ============ 4. 岗位方向三档分级 ============
# 铁律（来自牛客 skill 实测教训）：
# 标题无岗位方向词的一律不算该方向面经。
# 不加这条时，「前端面试之看看《埋点》」会因正文出现「加密」被误判为安全面经。

EXP_TITLE_WORDS = ("面经", "一面", "二面", "三面", "面试题", "offer", "凉经", "hr面")
INFO_TITLE_WORDS = ("趋势", "排名", "发布", "解析", "指南", "盘点", "综述")
# 强面经信号：出现这些词时，即便标题含资讯词也不降权
_STRONG_EXP_WORDS = ("面经", "真题", "一面", "二面", "三面", "凉经",
                     "已挂", "已过", "复盘", "面试题")
_NUM_Q_RE = re.compile(r"(?:^|[\n。；;])\s*(?:\d{1,2}\s*[、.．)）:：])")


def grade(items):
    """给每个 item 打上 grade(A/B/C) 与 score，并按综合分排序。"""
    for it in items:
        title = it.get("title", "")
        content = it.get("content", "")

        has_role = any(w in title for w in ROLE_TITLE_WORDS)
        has_other = any(w in title for w in OTHER_ROLE_WORDS)
        t_hits = count_hits(DIRECTION_KEYWORDS, title)
        c_hits = count_hits(DIRECTION_KEYWORDS, content)

        # --- 三档 ---
        if has_role and not has_other and t_hits >= 2:
            g = "A"
        elif has_role:
            g = "B"
        else:
            g = "C"

        # --- 面经属性分 ---
        exp = 0
        lt = title.lower()
        if any(w in lt for w in EXP_TITLE_WORDS):
            exp += 10
        exp += min(8, len(_NUM_Q_RE.findall(content)))
        # 资讯词降权。但若标题已含强面经信号（真题/面经/N面），
        # 说明是「面试真题拆解分析」这类内容，不应降权。
        # 实测误伤：「科大讯飞‖安全运营工程师面真题拆解分析」因"拆解分析"被降到排除。
        if any(w in title for w in INFO_TITLE_WORDS) and \
                not any(w in lt for w in _STRONG_EXP_WORDS):
            exp -= 9

        it["grade"] = g
        it["score"] = t_hits * 3 + c_hits
        it["exp_score"] = exp
        it["rank"] = exp * 3 + it["score"]

    items.sort(key=lambda x: -x["rank"])
    return items


def drop_c_grade(items):
    """铁律执行：标题无岗位方向词的 C 档直接排除。"""
    return [it for it in items if it.get("grade") in ("A", "B")]


# ============ 5. 题目抽取 ============
# 分两层：先切段（content 常是省略号拼接的摘要，不切会跨段粘连造出
# 不存在的题目），再按题号切。

_SEG_RE = re.compile(r"\.{3,}|。{2,}|…+|\n{2,}")
# 题号切分。注意前导边界必须包含**空格**：
# 摘要里题目常写成「1、xxx 2. yyy 3. zzz」，题号前只有空格没有换行/句号。
# 早期只允许 (^|[\n。；;]) 时，整段无法切开，会把 3 道题粘成 1 条。
#
# 另需支持小红书常见的 **Q1/Q2 式题号**（「Q2你的MCP实践…Q3你简历上…」）
# 与 **两位数点号**（「66.如何量化…」），否则整段粘成一条。
_Q_SPLIT_RE = re.compile(
    r"(?:^|[\n。；;，,]|\s)\s*"
    r"(?:\d{1,3}\s*[、.．)）:：]"
    r"|[（(]\d{1,3}[)）]"
    r"|[Qq]\s*\d{1,2}\s*[、.．)）:：]?"
    r"|[·•▪]\s*)"
)
# 星级/评分标记会污染题目边界（「…开发方向？ ★★★★☆（考察动机）」）
_RATING_RE = re.compile(r"[★☆✩✪⭐]+\s*(?:[（(][^）)]{0,20}[）)])?")
# 日期 / 面试轮次标记 —— 必须作为切分边界。
# 实测粘连案例：「…LLM的OWASP Top10 2025年4月18日 总裁面」
# 日期把上一道题和下一段元信息粘成了一条假题目。
_META_CUT_RE = re.compile(
    r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日"
    r"|\d{1,2}\s*月\s*\d{1,2}\s*日"
    r"|\d{4}[-/]\d{1,2}[-/]\d{1,2}"
    r"|(?:总裁面|交叉面|主管面|hr\s*面|HR\s*面|技术面|boss\s*面|一面|二面|三面|四面)"
)
_QUESTION_HINT = ("什么", "如何", "为什么", "怎么", "区别", "原理",
                  "讲讲", "说说", "介绍", "解释", "实现", "流程", "手写")
_CN_RE = re.compile(r"[\u4e00-\u9fff]")

# 题目级噪声：抽出来的"题"其实是叙述/评论/软文片段，须剔除。
# 实测案例（2026-09-03，520 题里的典型污染）：
#   「面试官不开摄像头。烦人。 自我介绍 拷打简历。问了20min。」→ 面试过程吐槽
#   「别再碰那些过时的东西了…工控安全工程师年薪45-80万，为什么」→ 培训软文
#   「一方面，360建立了一个"安全大脑"大模型…」→ 行业评论
#   「前言 今年下半年所有中高级AI安全岗…的面试逻辑已经彻底迭代」→ 文章开场
_Q_NOISE_WORDS = (
    "面试官不开", "烦人", "拷打简历", "年薪", "月薪", "薪资", "进坟墓",
    "别再碰", "前言", "综上", "总之", "本文", "文末", "点赞", "关注",
    "转载", "版权", "免责", "如下图", "见下文", "上文", "笔者",
    "一方面", "另一方面", "近期提出", "彻底迭代", "让它们",
    # --- 面试现场对话记录（不是题目本身）---
    "面试师傅", "面试官说", "我：", "面试官：", "答不出", "没答出来",
    "不会答", "答得不好", "凉了", "感觉良好", "等通知", "问了20min",
    "我一般见框", "喔喔", "嗯嗯", "忘记了", "记不清",
    # --- 推广话术 ---
    "帮助大家", "高薪就业", "分享三份", "少走一些弯路", "资料", "领取",
    "免费", "加群", "私信", "扫码", "公众号", "教程", "课程",
    # --- 资源清单物料（软文里罗列的赠品，不是题）---
    "电子书", "工具包", "学习路线", "面试题精选", "视频合集", "思维导图",
    "学习笔记", "实战靶场合集", "书籍推荐", "路线图",
    # --- 文章/软文结构性文字（实测未归类池里约 2/3 是这类）---
    "整理成pdf", "整理成 pdf", "持续更新中", "本套面试题", "本指南",
    "八股精", "希望由点达面", "帮助开发者", "分享一套", "学弟学妹",
    "求职者必须", "炙手可热", "越来越多的年轻人", "数以百计",
    "当头一棒", "进入甲方决策者", "第一批甲方",
    # --- 个人经历叙述 / 吐槽（不是考题）---
    "主包", "杰哥", "黑牛问号", "我扯了点", "双非一本", "陪跑",
    "听师傅们说", "有即将毕业的同学", "来问杰哥", "个人评价",
    "from 学弟", "某双非",
    # --- 岗位科普 / 职业规划议论文 ---
    "这个岗位的逻辑", "本质差别", "服务的是", "作为甲方安全管理人员",
    "领导授权", "转型线上开发", "我承认你可能", "可以考虑这个方向",
    # --- 求资料 / 引流话术 ---
    "需要电子版", "留言敲", "后台留言", "评论区", "点个关注",
    "针对性更新", "需要的朋友", "自取", "整理好了",
    # --- 求职经历叙述（不是考题）---
    "投的三个岗位", "被挂了", "牛泪", "捞了起来", "约下午的面试",
    "投递岗位", "投递时间", "投递简历", "校招大概", "boss上",
    "一眨眼", "回忆一下整个过程", "我们班大概", "剩下的没有做",
    "素质好点的", "毋庸置疑", "在某安全公司",
    # --- 行业感慨 / 长篇议论 ---
    "一线互联网大厂任职", "辛酸不易", "外人眼里", "我必须要讲清楚",
    "背锅的工作", "有一种火了的架势", "热议可能是怎么来的",
    "自信点", "不要一听", "感觉多高大上", "觉得还挺有发展",
    "护网面试步骤",
    # --- 流程/进度类闲聊（非考题）---
    "实习僧", "给好评", "面试流程很快", "周一就约", "没hc",
    "因为没hc", "没怎么问八股", "问的也不深", "围着简历",
    "求面经", "有没有面过的", "base长沙", "想跳槽看下机会",
    "有没有相关的面试题",
)
# 叙述性开头（题目不会这样起头）
_Q_NARRATIVE_PREFIX = ("我", "他", "她", "我们", "他们", "这其实", "这就是",
                       "所以", "因此", "但是", "然后", "接着", "最后",
                       "估计", "感觉", "可能", "据说", "确实", "为了")

# 媒体占位符：正文是图片时平台会输出 [图片] / [视频] / [表情] 等
_MEDIA_PLACEHOLDER_RE = re.compile(
    r"[\[【]\s*(?:图片|视频|表情|动图|音频|附件|链接|图)\s*[\]】]")
# 疑问/求解特征 —— 判断去掉占位符后是否还剩真题目
_QUESTION_LIKE_RE = re.compile(
    r"[?？]|什么|如何|为什么|怎么|区别|原理|讲讲|说说|介绍|解释|实现|流程|手写")


def _is_noise_question(c):
    """判断抽取出的候选是否其实不是题目。"""
    if any(w in c for w in _Q_NOISE_WORDS):
        return True
    if c.startswith(_Q_NARRATIVE_PREFIX):
        return True
    # 句号过多说明是段落而非单题
    if c.count("。") >= 2:
        return True
    # 以裸数字开头：日期/时间残留导致的叙述句，
    # 如「16 晚上19-20做了机考题，都是网络安全相关的客观题…」
    if re.match(r"^\d{1,2}\s+\S", c):
        return True
    # 叙述性连接词开头（题目不会这样起头）
    if re.match(r"^(?:有重复|还有|其余|其它|其他|另外|此外|以上|下面|"
                r"上面|同上|同前|略|无)", c):
        return True
    # 文章结构性开头：结尾/以下是/本文/随着/因此…（实测未归类池大量此类）
    if re.match(r"^(?:结尾|以下是|以上是|综合|随着|由于|鉴于|众所周知|"
                r"如今|近年来|目前来看|一般来说|总的来说|简单来说|"
                r"是不是|听说过|之后问|再往下|使用方式|从|在)", c):
        return True
    # 含 URL / 长哈希片段的抽取残渣
    if re.search(r"https?://|com/plugin/|[0-9a-f]{24,}", c):
        return True
    # 媒体占位符条目：B站/小红书正文全是图，文字只剩标题 + [图片] 占位符，
    # 没有任何实际题目内容。实测「71道网络安全面试题⑦ [图片] [图片] …」7 条。
    if _MEDIA_PLACEHOLDER_RE.search(c):
        stripped = _MEDIA_PLACEHOLDER_RE.sub("", c).strip()
        # 去掉占位符后没剩下实质内容（或只剩标题式短语）就判噪声
        if len(stripped) < 12 or not _QUESTION_LIKE_RE.search(stripped):
            return True
    return False

# 小红书正文短、口语化，套牛客的题号规则基本失效，需单独一套
_XHS_Q_RE = re.compile(r"[\n，,。；;]\s*([^，,。；;\n]{6,60}[?？])")


def extract_questions(item):
    """从单条 item 抽取候选题目，返回 list[str]。

    重要：抽取结果源自摘要，可能断句不全，必须在报告里声明并给出原帖链接。
    """
    content = item.get("content", "")
    if not content:
        return []

    # 先剥星级/评分标记，避免污染切分边界
    content = _RATING_RE.sub(" ", content)

    # 小红书：详情页正文常含编号题目（01./Q2/66.），此时走通用题号切分；
    # 只有无编号的口语化短文才退回问号抓取。
    has_numbered = bool(_Q_SPLIT_RE.search(content))
    if item.get("source") == "xhs" and not has_numbered:
        cands = _XHS_Q_RE.findall("\n" + content)
    else:
        cands = []
        for seg in _SEG_RE.split(content):
            seg = seg.strip()
            if not seg:
                continue
            # 先按日期/轮次标记二次切分，再按题号切，避免元信息粘进题目
            for sub in _META_CUT_RE.split(seg):
                sub = (sub or "").strip()
                if not sub:
                    continue
                parts = _Q_SPLIT_RE.split(sub)
                cands.extend(p.strip() for p in parts if p.strip())

    grade_ = item.get("grade", "C")
    out, seen = [], set()
    for c in cands:
        c = re.sub(r"\s+", " ", c).strip(" -—、.,;；")
        # 切分残留的前导标点（如「：自我介绍，做题…」）
        c = c.lstrip("：:，,。；;、）)】]》>|/ ")
        # 摘要里题目常以「下一题的题号」结尾（如「在绿盟做过什么项目 2」），
        # 尾部裸数字/裸序号属于切分残留，必须清掉
        c = re.sub(r"\s+\d{1,2}\s*[、.．)）:：]?$", "", c).strip(" -—、.,;；")
        if not (8 <= len(c) <= 130):
            continue
        if not _CN_RE.search(c):
            continue
        if _is_noise_question(c):
            continue
        is_q = ("?" in c or "？" in c
                or any(h in c for h in _QUESTION_HINT))
        hit_dir = any(hit(k, c) for k in DIRECTION_KEYWORDS)
        # A/B 档题目全收；C 档只收本身含方向关键词的
        if grade_ == "C" and not hit_dir:
            continue
        if not (is_q or hit_dir):
            continue
        if c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


def build_question_bank(items):
    """汇总题库，每题带来源帖标题与 URL，保证可回溯。"""
    bank, seen = [], set()
    for it in items:
        for q in extract_questions(it):
            for piece in _split_multi_question(q):
                key = _norm_title(piece)
                if key in seen:
                    continue
                seen.add(key)
                bank.append({
                    "question": piece,
                    "grade": it.get("grade", ""),
                    "source": it["source"],
                    "from_title": it["title"],
                    "from_url": it["url"],
                    "date": it.get("date", ""),
                })
    return bank


# 无题号的连排题目：「什么是SQL注入攻击 什么是XSS攻击 什么是CSRF攻击」
# 这类是题目清单被压成一条，有价值，应拆开而不是丢掉。
#
# ⚠️ 前导边界至关重要：必须要求标记词处于**句首或空格/标点之后**。
# 早期版本用裸 `(?=(?:什么是|如何|怎么|…))` 无边界约束，导致句中的
# 「该怎么做」也被当作题目起点，把
#   「杀软环境下需要权限维持该怎么做 常规问题不再记录，还问了渗透测试报告怎么写…」
# 切成「杀软环境下需要权限维持该」/「怎么做 常规问题…」/「怎么写，如果没有漏洞」
# 等 4 段碎片 —— 比不拆更糟。
_MULTI_Q_RE = re.compile(
    r"(?:(?<=^)|(?<=[\s，,。；;、]))"
    r"(?=(?:什么是|如何|为什么|简述|请简述|说明一下|解释一下|请问)\S)")


def _split_multi_question(c, min_parts=2, min_piece=8):
    """把连排的多道题拆开。单题或拆不出来时原样返回。

    判定依据是「能否切出 >=2 段各自成立的题目」，**不是长度**。
    早期版本用 `len(c) > 90` 做门槛，导致 66 字的
    「93道面试题 什么是SQL注入攻击 什么是XSS攻击 …」因为不够长而拆不开。

    安全阀：任一碎片短于 min_piece 就整体放弃拆分，避免切出残句。
    """
    parts = [p.strip(" -—、.,;；") for p in _MULTI_Q_RE.split(c)]
    parts = [p for p in parts if p]
    if len(parts) < min_parts:
        return [c]
    # 只要有一段过短或过长，就认为拆分不可靠，宁可保留原句
    if any(len(p) < min_piece or len(p) > 130 for p in parts):
        return [c]
    if not all(_CN_RE.search(p) for p in parts):
        return [c]
    return parts


# ============ 6. 完整流水线 ============

def pipeline(raw_items, days=730, keep_c=False):
    """raw -> 归一结果 + 漏斗统计。"""
    funnel = {"raw": len(raw_items)}

    items = dedup(raw_items)
    funnel["after_dedup"] = len(items)

    items = filter_noise(items)
    funnel["after_noise"] = len(items)

    items = require_exp_signal(items)
    funnel["after_exp_signal"] = len(items)

    items = filter_clickbait(items)
    funnel["after_clickbait"] = len(items)

    items = filter_non_tech(items)
    funnel["after_non_tech"] = len(items)

    items = filter_time_window(items, days=days)
    funnel["after_time"] = len(items)

    items = grade(items)
    if not keep_c:
        items = drop_c_grade(items)
    funnel["final"] = len(items)
    funnel["grade_A"] = sum(1 for i in items if i["grade"] == "A")
    funnel["grade_B"] = sum(1 for i in items if i["grade"] == "B")
    funnel["grade_C"] = sum(1 for i in items if i["grade"] == "C")

    bank = build_question_bank(items)
    funnel["questions"] = len(bank)

    by_source = {}
    for i in items:
        by_source[i["source"]] = by_source.get(i["source"], 0) + 1
    funnel["by_source"] = by_source

    return items, bank, funnel
