# mianjing-skills（interview-collector）

> 多平台面经与面试题采集、清洗、聚类到备考的**完整流水线**。
> 一个 [WorkBuddy](https://www.workbuddy.cn) Agent Skill，也可脱离 Agent 直接当命令行工具用。

从**牛客、B站专栏、知乎、小红书、博客园**五个平台采集面经，统一归一去重 → 岗位方向三档
分级 → 题目抽取 → 质量体检 → 多批次合并总库 → 22 域知识点聚类 → 生成可打勾的分域刷题计划。

内置的关键词矩阵默认面向**安全 / AI 安全**方向，改 `keywords.py` 即可换方向。

---

## 它能做什么

| 环节 | 能力 |
|---|---|
| 采集 | 五源并发采集；免登录源（牛客/B站）开箱即用，浏览器源（知乎/小红书/博客园）登录一次长期有效 |
| 归一 | 统一 schema → 跨平台两级去重 → 固定顺序过滤链 → 岗位方向 A/B/C 三档分级 |
| 抽取 | 从正文/摘要自动抽题，**每题带来源帖标题与 URL**，可回溯 |
| 体检 | `rebuild.py --check` 五项缺陷指标，交付前必须全 0 |
| 合并 | 多批次结果合成总库，跨批去重 |
| 消费 | 22 域知识点分布（复习地图）+ 分域刷题计划（可打勾 checklist） |
| 深挖 | 补抓小红书正文；图片长文走 CDP 取图，由模型读图提题（优于传统 OCR） |
| 扩展 | `collect_dept.py` 三件套：采集某公司/部门的**全部**相关信息（JD、团队、技术文章、面经），跳面经过滤 |

## 安装

**方式 A：作为 WorkBuddy Skill（推荐）**

```bash
# 1) 复制整个目录到 skills 目录
cp -r mianjing-skills ~/.workbuddy/skills/interview-collector

# 2) 确保 python 能 import requests
pip install requests          # 浏览器源还需要 websockets；读图还需要 pillow

# 3) 体检
cd ~/.workbuddy/skills/interview-collector/scripts
python doctor.py              # 应显示「依赖来源: vendor（内联）」
```

**方式 B：独立使用**

直接 `git clone` 后按上面第 2、3 步操作即可，`scripts/` 下所有脚本都能单独跑。

> **自带依赖**：`scripts/vendor/` 已内联牛客接口逆向与 Chrome/CDP 基建（约 149 KB），
> **换设备只需复制目录**，不需要额外 skill、不需要 MCP、不需要单独建 venv。
> 想改用外部 skill 目录跟随上游更新时，设 `IC_PREFER_EXTERNAL=1`。

**外部要求只有两项**

| 要求 | 影响范围 | 缺了怎么办 |
|---|---|---|
| `requests` | 全部源 | `pip install requests`（`websockets` 用于 CDP，`pillow` 用于读图，按需） |
| Chrome | 仅浏览器源 | 装 Chrome 或设 `CHROME_BIN`；不装也能用牛客 + B站 |

## 快速开始

```bash
PY="$HOME/.workbuddy/skills/xiaohongshu-skills/.venv/Scripts/python.exe"   # Windows；Linux/macOS 用你的 python
cd scripts

$PY collect.py --check                        # 先体检各源可用性
$PY collect.py --topic "安全" --outdir D:/out # 默认五源全开；未登录的浏览器源自动跳过
$PY collect.py --topic "安全" --sources nowcoder,bilibili --outdir D:/out   # 只跑免登录源
$PY collect.py --topic "安全" --extra "MCP安全,Agent越权" --days 365 --outdir D:/out
```

常用参数：`--sources`（逗号分隔，`all` 为全部）、`--max-kw`（关键词上限，默认 80）、
`--max-page`（每词页数，默认 12）、`--days`（时间窗，默认 730）、`--keep-c`（保留 C 档）、
`--wait-login`（登录等待分钟数，默认 10，设 0 关闭）、`--only-extra`（只用 `--extra` 的关键词）。

**一次完整流程**

```bash
# 0) 换设备后先体检依赖
$PY doctor.py
# 1) 后台起 Chrome 保活（长任务必做）
HOLD_MINUTES=90 $PY login_all.py --keepalive &
# 2) 采集
$PY collect.py --topic "安全" --max-kw 30 --days 1095 --outdir D:/out
# 3) 体检 + 合并 + 消费
$PY rebuild.py D:/out --check
$PY merge.py   D:/out --topic 总库
$PY cluster.py D:/out/题库_总库_YYYYMMDD.json
$PY plan.py    D:/out/题库_总库_YYYYMMDD.json --days 14 --hours 2
```

## 五个源的实测账本

| 源 | 登录 | 路径 | 实测结论 |
|---|---|---|---|
| **牛客** | 免 | 纯 HTTP | 主力。单词 total 上限 400 |
| **B站专栏** | 免 | 纯 HTTP | 可用，但营销软文极多，需强制面经信号过滤 |
| **知乎** | 必须登录 | 浏览器 | 登录后产出最多，含华为/字节等牛客没有的真题汇总 |
| **小红书** | 需扫码 | 浏览器 | 独家公司最多（百度/OPPO/Shopee/快手/安克/科大讯飞） |
| **博客园** | 需过人机验证 | 浏览器 | 手动点一次验证后可用，内容偏旧（2020~2022） |

> ⚠️ **运行纪律**：登录源实测贡献了入选数据的约 **76%**。未登录时标准动作是走
> `--wait-login` 拉起 Chrome 让用户登录，**不要默默降级成免登录两源跑完**，
> 那等于丢掉大半数据。

默认源优先级：牛客 → 小红书 → B站 → 知乎 → 博客园。

## 目录结构

```
interview-collector/
├── SKILL.md                 # Skill 主文档（完整用法、踩坑清单、漏斗基线）
├── README.md
├── LICENSE                  # MIT
└── scripts/
    ├── doctor.py            # 环境依赖自检
    ├── deps.py              # 把 vendor/ 加入 sys.path（自动）
    ├── collect.py           # 五源采集主入口
    ├── normalize.py         # schema / 去重 / 过滤链 / 分级 / 题目抽取
    ├── keywords.py          # 关键词矩阵 + 各类词表（换方向改这里）
    ├── output.py            # md / json / txt 三件套
    ├── merge.py             # 多批次合成总库
    ├── cluster.py           # 22 域知识点分布
    ├── plan.py              # 分域刷题计划
    ├── rebuild.py           # 题库重算 + 五项缺陷体检
    ├── login_all.py         # 浏览器源登录 + Chrome 保活
    ├── xhs_login_watch.py   # 小红书扫码长时监听（二维码自动续期）
    ├── xhs_detail.py        # 补小红书正文
    ├── xhs_note_images.py   # CDP 取图（推荐，绕开风控）
    ├── xhs_images.py        # 走详情接口取图（备选）
    ├── collect_dept.py      # 部门信息定向采集
    ├── merge_dept.py        # 部门数据多批合并 + 四档标注
    ├── finalize_dept.py     # 二次清洗 + 五档精确标注
    ├── sources/             # 五个源的适配器
    │   ├── nowcoder.py  bilibili.py  zhihu.py  xhs.py  cnblogs.py
    └── vendor/              # 内联依赖（见下方致谢）
        ├── nowcoder_api.py  chrome_launcher.py
        └── xhs/             # CDP / 登录 / 搜索 / 详情 / 反检测
```

每个源适配器**内部消化异常并返回空列表**，任一源挂掉不影响其他源与后续流程；
全源无数据时提示跑 `--check`，且**不生成任何空文件**。

## 输出

每次采集产出 `md / json / txt` 三件套，题目按来源帖归档，均带原始标题、作者、时间、
链接和 URL，保证可回溯。合并后的总库可用 `cluster.py` 看知识点分布，用 `plan.py`
按可用天数/每天时长生成分域刷题计划。

## 诚信与合规（硬约束）

1. 标题、作者、时间、链接**一律接口原样输出**，不编造、不改写。
2. 题目由摘要自动抽取，每题必须带来源帖标题与 URL。
3. 报告里须声明：题目源自摘要，可能断句不全，需点原帖核对。
4. 采集**只读**，绝不点赞/评论/关注，避免账号风控。
5. 漏斗数据如实呈现；某方向面经稀少时直接说明，**不凑数、不混入其他方向或非技术岗**。

本项目仅用于个人学习与技术调研。请遵守各平台的服务条款与 `robots.txt`，
控制请求频率，勿将数据用于商业再分发。

## 许可证与致谢

本项目采用 [MIT](LICENSE) 许可证。

`scripts/vendor/` 下的代码来自以下上游项目，特此致谢：

| 文件 | 来源 | 用途 |
|---|---|---|
| `vendor/nowcoder_api.py` | nowcoder-interview-crawler | 牛客接口（主力源） |
| `vendor/chrome_launcher.py` | [xiaohongshu-skills](https://github.com/xpzouying/xiaohongshu-skills) | Chrome 启动与探测 |
| `vendor/xhs/*` | 同上 | CDP 控制、登录态、搜索与详情、反检测 |

## FAQ

**Q：为什么不用 MCP？**
有意选择。MCP 要配置 `mcp.json` 并手动点信任，换设备迁移成本更高；内联脚本复制即用。

**Q：Chrome 退出了，登录态会丢吗？**
不会。用的是持久化 profile，登录态长期有效。详见 `SKILL.md` 中「登录态的生命周期」。

**Q：换到别的岗位方向（后端/算法/前端）怎么用？**
改 `scripts/keywords.py` 的关键词矩阵即可，其余流程不变。归一层和过滤链与方向无关。

更多细节（必踩的坑、质量体检、漏斗基线、实战产出规模）见 [`SKILL.md`](SKILL.md)。
