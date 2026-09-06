# 更新日志

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
