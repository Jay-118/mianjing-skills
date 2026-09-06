# -*- coding: utf-8 -*-
"""用当前过滤器重算已有题库，不重跑网络采集。

用途
----
改动 normalize.py 的过滤/抽取/拆分逻辑后，历史交付物仍是旧代码产出的，
可能带着已修复的缺陷。本脚本读取已有 JSON 里的 `posts`（原始采集数据完好），
用最新逻辑重算题库并覆盖三件套。

**为什么需要它**（踩坑记录 2026-09-03）
交付给用户的旗舰产物「安全与AI安全」是 17:42 生成的，而拆分修复与
前导标点清理是之后才做的 —— 复核发现那份 JSON 里仍有 10 处缺陷
（前导标点 6 / 裸数字开头 2 / 关键词噪声 1 / 碎片 1）。
另一份「AI安全」有 16 处。**改完过滤器必须回头重算所有历史产物。**

用法
----
    python rebuild.py <outdir>                 # 重算该目录下全部题库
    python rebuild.py <outdir> --check         # 只体检，不改文件
    python rebuild.py <outdir> --topic 安全     # 只处理指定方向
"""
import os
import re
import sys
import json
import glob
import io

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from normalize import build_question_bank      # noqa: E402
from output import write_all                   # noqa: E402

_NOISE_PROBE = ("面试官不开", "年薪", "电子书", "工具包", "学习路线",
                "拷打简历", "面试师傅", "高薪就业", "前言", "有重复的问题")
_LEAD_PUNCT = "：:，,。；;、）)"


def audit(questions):
    """返回缺陷计数字典。用于重算前后对比。"""
    qs = [q["question"] for q in questions] if questions and \
        isinstance(questions[0], dict) else list(questions)
    return {
        "关键词噪声": len([q for q in qs if any(b in q for b in _NOISE_PROBE)]),
        "裸数字开头": len([q for q in qs if re.match(r"^\d{1,2}\s+\S", q)]),
        "多句段落": len([q for q in qs if q.count("。") >= 2]),
        "疑似碎片": len([q for q in qs
                     if re.match(r"^怎么(做|写|办|样)", q) or q.endswith("该")]),
        "前导标点": len([q for q in qs if q and q[0] in _LEAD_PUNCT]),
    }


def process(path, outdir, check_only=False):
    with io.open(path, encoding="utf-8") as f:
        d = json.load(f)
    topic = d.get("topic") or os.path.basename(path).split("_")[1]
    posts = d.get("posts") or []
    if not posts:
        print("  [skip] %s 无 posts 数据，无法重算" % os.path.basename(path))
        return None

    # 总库由 merge.py 维护（题目带 all_sources 多源信息），
    # 用单批逻辑重算会丢掉合并结果，故只体检不覆盖。
    is_merged = any(q.get("all_sources") for q in (d.get("questions") or [])[:20])
    if is_merged and not check_only:
        print("  [skip] %s 是合并总库，请用 merge.py 重建，不做覆盖"
              % os.path.basename(path))
        check_only = True

    old_q = d.get("questions") or []
    before = audit(old_q)
    bank = build_question_bank(posts)
    after = audit(bank)

    bad_before = sum(before.values())
    bad_after = sum(after.values())
    flag = "OK" if bad_after == 0 else "仍有缺陷"
    print("  [%s] 题库 %d -> %d | 缺陷 %d -> %d  %s"
          % (topic, len(old_q), len(bank), bad_before, bad_after, flag))
    if bad_before:
        detail = ", ".join("%s %d" % (k, v) for k, v in before.items() if v)
        print("        原缺陷明细: %s" % detail)

    if check_only:
        return topic

    f2 = dict(d.get("funnel") or {})
    f2["questions"] = len(bank)
    write_all(outdir, topic, posts, bank, f2, d.get("queries") or [])
    return topic


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    outdir = sys.argv[1]
    check_only = "--check" in sys.argv
    only = None
    if "--topic" in sys.argv:
        i = sys.argv.index("--topic")
        if i + 1 < len(sys.argv):
            only = sys.argv[i + 1]

    files = sorted(glob.glob(os.path.join(outdir, "题库_*.json")))
    if only:
        files = [p for p in files if only in os.path.basename(p)]
    if not files:
        print("未在 %s 找到题库 JSON" % outdir)
        return 1

    print("%s %d 份题库%s" % ("体检" if check_only else "重算",
                             len(files), "（只读）" if check_only else ""))
    done = 0
    for p in files:
        try:
            if process(p, outdir, check_only):
                done += 1
        except Exception as e:
            print("  [warn] %s 处理失败: %s" % (os.path.basename(p), e))
    print("完成 %d/%d" % (done, len(files)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
