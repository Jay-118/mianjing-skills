# -*- coding: utf-8 -*-
"""题库知识点聚类 —— 把扁平题目列表变成可用的复习地图。

为什么需要
--------
484 道题的扁平列表无法直接用于备考：不知道哪块考得多、哪块没覆盖、
按什么顺序复习。本脚本按安全领域知识体系做规则聚类，输出：
  1) 各知识域题目数与占比（识别高频考点）
  2) 每域题目清单（带来源链接）
  3) 覆盖缺口提示（哪些域题量偏少）

为什么用规则而不是 embedding
---------------------------
安全领域术语边界清晰（SQL注入/XSS/SSRF 各自明确），规则命中准确率高
且可解释、可审计；embedding 聚类结果不稳定且难解释来源。
题目短（中位 31 字）时规则更可靠。

用法
----
    python cluster.py <题库json路径> [--out <md路径>]
"""
import os
import re
import sys
import json
import io

# ---------- 知识域定义（有序，先匹配的优先）----------
# 每域: (域名, [关键词...])  关键词大小写不敏感
DOMAINS = [
    ("Web 漏洞 · 注入类", [
        "sql注入", "sqli", "注入", "sqlmap", "预编译", "宽字节",
        "报错注入", "盲注", "堆叠注入", "二次注入",
    ]),
    ("Web 漏洞 · XSS/CSRF", [
        "xss", "csrf", "跨站", "同源策略", "cors", "csp",
        "httponly", "samesite", "点击劫持", "clickjacking",
    ]),
    ("Web 漏洞 · SSRF/文件类", [
        "ssrf", "gopher", "dict协议", "文件上传", "文件包含",
        "任意文件读取", "路径穿越", "目录遍历", "解析漏洞",
    ]),
    ("Web 漏洞 · 反序列化/RCE", [
        "反序列化", "cc链", "cc1", "fastjson", "shiro", "log4j",
        "命令执行", "代码执行", "rce", "表达式注入", "ognl", "spel",
        "php爆", "绝对路径",
    ]),
    ("权限与认证", [
        "越权", "提权", "水平越权", "垂直越权", "未授权", "鉴权",
        "认证", "jwt", "oauth", "sso", "rbac", "session", "cookie",
        "token", "单点登录", "口令", "弱密码",
    ]),
    ("内网渗透 · 后渗透", [
        "内网", "横向", "域渗透", "域控", "kerberos", "黄金票据",
        "白银票据", "mimikatz", "隧道", "代理转发", "端口转发",
        "权限维持", "持久化", "痕迹清理", "shellcode", "免杀",
        "bypass edr", "edr", "杀软", "进程注入", "内存马",
    ]),
    ("密码学与加密", [
        "加密", "解密", "对称", "非对称", "aes", "des", "rsa",
        "哈希", "hash", "md5", "sha", "国密", "sm2", "sm4",
        "证书", "tls", "ssl", "https", "公钥", "私钥", "签名",
        "kms", "密钥", "salt", "加盐",
    ]),
    ("网络与协议", [
        "tcp", "udp", "http", "http2", "http3", "dns", "icmp",
        "arp", "三次握手", "四次挥手", "osi", "七层", "端口",
        "抓包", "wireshark", "cdn", "负载均衡", "socket",
    ]),
    ("系统与运维安全", [
        "linux", "windows", "进程", "文件权限", "suid", "计划任务",
        "systemd", "日志", "审计", "加固", "基线", "docker",
        "容器", "k8s", "云原生", "堡垒机",
    ]),
    ("安全防护与检测", [
        "waf", "ids", "ips", "防火墙", "蜜罐", "soc", "态势感知",
        "流量特征", "冰蝎", "哥斯拉", "webshell", "规则", "误报",
        "漏报", "sdl", "sast", "dast", "代码审计", "扫描器",
    ]),
    ("应急响应与溯源", [
        "应急响应", "溯源", "取证", "入侵检测", "排查", "被黑",
        "挖矿", "勒索", "后门", "webshell查杀", "日志分析",
    ]),
    ("AI 与大模型安全", [
        "大模型", "llm", "prompt", "提示注入", "越狱", "jailbreak",
        "ai安全", "agent", "rag", "对抗样本", "模型窃取", "数据投毒",
        "owasp top10", "mcp", "react",
    ]),
    ("数据安全与合规", [
        "数据安全", "数据分类", "分类分级", "脱敏", "dlp", "隐私",
        "个保法", "gdpr", "等保", "密评", "合规", "数据泄露",
        "隐私计算", "联邦学习", "差分隐私",
    ]),
    ("编程与开发基础", [
        "python", "java", "go语言", "golang", "php", "javascript",
        "hashmap", "多线程", "并发", "算法", "数据结构", "设计模式",
        "mysql", "redis", "数据库", "索引", "事务", "洋葱模型",
        "框架", "埋点",
    ]),
    ("HR 与软技能", [
        "自我介绍", "职业规划", "优缺点", "为什么选择", "反问",
        "薪资期望", "团队协作", "压力", "离职", "实习经历",
        "项目介绍", "hr面", "offer选择", "校园经历",
        "评估你所做", "解决问题的能力", "临场反应", "领导交代",
        "需要提升", "怎么看待", "为什么会想要转",
    ]),
    ("渗透测试方法论", [
        "渗透测试", "渗透思路", "渗透流程", "信息收集", "资产测绘",
        "漏洞挖掘", "靶场", "src", "众测", "红蓝对抗", "攻防演练",
        "metasploit", "burp", "nmap", "后台登陆", "本地渗透",
        "黑盒", "白盒", "灰盒", "授权", "报告",
        "扫目录", "目录扫描", "fuzz", "逻辑漏洞", "骚思路",
        "cms", "指纹识别", "子域名", "端口扫描", "漏洞复现",
    ]),
    ("安全管理与制度", [
        "等级保护", "等保", "安全管理", "安全体系", "安全运营工程师",
        "安全策略", "制度", "法律法规", "甲方", "乙方", "安全建设",
        "安全意识", "培训", "外挂", "账号被盗", "业务安全",
        "风控", "反欺诈", "广告安全",
        "battle", "推动修复", "研发觉得", "漏洞评级", "危害",
        "安全方案", "安全产品", "暗网", "威胁情报", "安全威胁",
        "3d打印", "iot", "车联网", "终端安全",
    ]),
    ("逆向与底层", [
        "systemcall", "system call", "lkm", "内核", "驱动", "hook",
        "逆向", "反调试", "脱壳", "汇编", "elf", "pe文件",
        "raii", "rtti", "内存管理", "指针", "栈溢出", "堆溢出",
        "rop", "gdb", "缩写",
    ]),
    ("绕过与对抗技巧", [
        "绕过", "bypass", "双写", "大小写绕过", "注释符", "编码绕过",
        "过滤", "黑名单", "白名单", "waf绕过", "免杀", "混淆",
        "拦截", "特征", "变形",
    ]),
    ("算法与手撕代码", [
        "手撕", "手写代码", "算法题", "力扣", "leetcode", "bitmap",
        "位图", "查找指定", "时间复杂度", "空间复杂度", "十六进制",
        "二进制表示", "字符串", "重复次数", "unsigned int",
    ]),
    ("游戏与业务安全", [
        "游戏安全", "外挂", "刷道具", "金币", "ddos攻击时", "封号",
        "作弊", "反外挂", "游戏运营", "玩家", "账号被盗",
    ]),
]

OTHER = "其他 · 未归类"


def classify(text):
    """返回命中的域列表（一题可属多域）。"""
    low = text.lower()
    hits = []
    for name, kws in DOMAINS:
        for kw in kws:
            if kw in low:
                hits.append(name)
                break
    return hits or [OTHER]


def build(questions):
    """返回 (域 -> 题目列表, 统计)。"""
    buckets = {}
    multi = 0
    for q in questions:
        text = q.get("question") or ""
        doms = classify(text)
        if len(doms) > 1:
            multi += 1
        for d in doms:
            buckets.setdefault(d, []).append(q)
    order = [n for n, _ in DOMAINS] + [OTHER]
    ordered = [(d, buckets[d]) for d in order if d in buckets]
    ordered.sort(key=lambda x: -len(x[1]))
    return ordered, {"multi_domain": multi}


def render(path_json, out_md):
    with io.open(path_json, encoding="utf-8") as f:
        d = json.load(f)
    qs = d.get("questions") or []
    if not qs:
        print("题库为空")
        return 1

    ordered, stat = build(qs)
    total = len(qs)

    L = []
    L.append("# 面经题库 · 知识点分布")
    L.append("")
    L.append("- 题目总数：**%d**" % total)
    L.append("- 知识域数：%d" % len(ordered))
    L.append("- 跨域题目：%d（一题命中多个知识域）" % stat["multi_domain"])
    L.append("")
    L.append("> 分类基于安全领域术语规则匹配，可解释、可追溯。"
             "一题可归属多个域，故各域题数之和大于题目总数。")
    L.append("")

    # ---- 分布总览 ----
    L.append("## 分布总览")
    L.append("")
    L.append("| 知识域 | 题数 | 占比 | 强度 |")
    L.append("|---|---:|---:|---|")
    for name, items in ordered:
        pct = 100.0 * len(items) / total
        bar = "█" * max(1, int(round(pct / 2)))
        L.append("| %s | %d | %.1f%% | %s |" % (name, len(items), pct, bar))
    L.append("")

    # ---- 复习优先级建议 ----
    top = [n for n, i in ordered if n != OTHER][:5]
    thin = [(n, len(i)) for n, i in ordered
            if n != OTHER and len(i) <= max(3, int(total * 0.015))]
    L.append("## 复习优先级")
    L.append("")
    L.append("**高频优先（题量最大的 5 个域）**")
    for i, n in enumerate(top, 1):
        L.append("%d. %s" % (i, n))
    L.append("")
    if thin:
        L.append("**题量偏少的域**（可能是采集覆盖不足，也可能确实少考）")
        for n, c in thin:
            L.append("- %s（%d 道）" % (n, c))
        L.append("")

    # ---- 各域题目 ----
    L.append("## 各域题目清单")
    L.append("")
    for name, items in ordered:
        L.append("### %s（%d 道）" % (name, len(items)))
        L.append("")
        for q in items:
            src = q.get("source", "")
            url = q.get("from_url", "")
            n = q.get("source_count", 1)
            mark = " `×%d源`" % n if n and n > 1 else ""
            L.append("- %s%s　<sub>[%s](%s)</sub>"
                     % (q.get("question", ""), mark, src, url))
        L.append("")

    with io.open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(L))

    print("题目 %d 道 -> %d 个知识域" % (total, len(ordered)))
    print("")
    for name, items in ordered:
        print("  %-24s %4d  %5.1f%%"
              % (name, len(items), 100.0 * len(items) / total))
    print("")
    print("已输出: %s" % out_md)
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    src = sys.argv[1]
    out = None
    if "--out" in sys.argv:
        i = sys.argv.index("--out")
        if i + 1 < len(sys.argv):
            out = sys.argv[i + 1]
    if not out:
        base = os.path.basename(src).replace("题库_", "知识点分布_")
        out = os.path.join(os.path.dirname(src),
                           base.rsplit(".", 1)[0] + ".md")
    return render(src, out)


if __name__ == "__main__":
    sys.exit(main())
