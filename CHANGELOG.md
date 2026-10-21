# 更新日志

## 1.2.0 · 2026-10-21

实战经验补充 + 一处配置项增强。

**新增章节**

- 「零·六、单公司 + 单岗位的定向全量采集（稀有岗位打法）」：
  三批编排（免登录源 → 浏览器源 → **变体词补充批**）、四个必做收尾动作、
  稀有岗位报告的四类材料切分范式。实测网易游戏·安全运营：五源 7398 原始 → 1390 入选 →
  真实面经仅 3 篇 42 题，**全部由变体词批捞到**

**坑表 +14 条（#69–#82）**

- #69 主词捞不到稀有岗位（须跑事业群/产品线/作弊生态变体词）
- #70 牛客列表接口只有摘要（须 WebFetch 原帖补全逐题原文）
- #71 售卖「面试真题库」不是面经（AI 生成模板题库的判别特征与附录处理）
- #72 小红书新登录撞「安全验证」墙：症状与「未登录/代码写错」完全相同，但重试无效，
  须把 tab 调前台让用户用 App 扫码验证
- #73 本机环境两个硬约束（Bash 缺 coreutils、托管 Python 3.13 无 requests）
- #74 后台任务在会话轮次结束时会被回收，长任务优先前台跑
- #75 开页面/调前台优先走 CDP HTTP 端点（`/json/new` `/json/list` `/json/activate`），比 websocket 稳
- #76 牛客 `create_ts` 可能是毫秒级，直接 `time.localtime` 抛 OSError 且崩点不指向时间戳
- #77 「安全」关键词在非安全公司的定向采集里被「安全工程」严重污染
- #78 定向单公司的第一步是查官方 JD（用户口语岗位名常与官方命名不一致）
- #79 `xhs_note_images.py` 首次抓取常失败、重试即成功
- #80 `collect.py` 子进程 stdout 是块缓冲，后台运行时全程看不到进度
- #81 「有几年没做校招」的公司公开面经本就极少，这不是采集失败
- #82 交付报告里的小红书链接必须带完整 `?xsec_token=`

**脚本改动（向后兼容）**

- 新增 `IC_CDP_PORT` 环境变量，Chrome 远程调试端口不再硬编码 `9222`。
  `collect.py` / `doctor.py` / `login_all.py` / `sources/_browser.py` / `sources/xhs.py` /
  `vendor/chrome_launcher.py` / `xhs_detail.py` / `xhs_login_watch.py` / `xhs_note_images.py`
  共 9 处统一读取该变量，未设置时仍为 `9222`，原有用法不受影响。
  多 Chrome 实例并行或端口被占用时：`IC_CDP_PORT=9333 python login_all.py --keepalive`

## 1.1.0 · 2026-09-07

- 开源到 GitHub：[Jay-118/mianjing-skills](https://github.com/Jay-118/mianjing-skills)，新增中文 README
- 采用 MIT 许可证（`license: MIT`，完整文本见仓库 `LICENSE`）
- 补全 SkillHub 发布元数据：`slug` / `displayName` / `summary` / `version` / `license`
- 发布包排除含个人绝对路径的一次性脚本与平台安装元数据（`.skillhubignore`）

采集、归一、聚类、排期主流程与 1.0.0 一致，行为无变更。

## 1.0.0

首个版本：

- 五源采集（牛客 / B站专栏 / 知乎 / 小红书 / 博客园）
- 归一层：统一 schema → 跨平台两级去重 → 固定顺序过滤链 → 岗位方向三档分级
- 题目抽取（每题带来源帖标题与 URL，可回溯）
- 质量体检（`rebuild.py --check` 五项缺陷指标）
- 多批次合并总库、22 域知识点聚类、分域刷题计划
- 部门信息定向采集三件套（collect_dept / merge_dept / finalize_dept）
