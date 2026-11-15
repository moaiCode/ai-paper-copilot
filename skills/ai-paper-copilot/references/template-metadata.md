# 模板元数据与填写契约

本说明解释 `templates/` 中模板的 YAML frontmatter。模板是起始骨架，不是已经完成的科研记录；空值表示尚未取得信息，不能被 Agent 当成允许猜测的提示。完整正文仍需按照页面中的证据、边界和人工核查区填写。

安装后的 Vault 可直接阅读 `templates/README.md` 获取不依赖 skill 的字段速查；本文是 Agent 执行任务时使用的详细契约，二者都以当前模板和根 `AGENTS.md` 为准。

## 读取和修改约束

- frontmatter 必须位于文件最顶部，使用一对 `---` 包围的 YAML 映射。
- 使用安全 YAML 解析；重复键、未闭合 YAML 或把列表写成字符串都应报告，不要静默修复。
- YAML 注释（以 `#` 开头）只解释字段，不属于字段值。字段含义的完整契约以本文为准。
- 模板占位符（如 `{{title}}`）只能留在模板目录或收件箱草稿；正式资料页必须替换为真实值，否则结构校验会报告占位符。
- `null` 表示“明确没有值或暂时未知”，空字符串表示“等待补齐的文本”，空列表表示“目前没有已记录条目”。三者不要为了让页面看起来完整而互换。
- Agent 可以补充 AI 区及允许更新的派生字段；不得填写用户的 `HUMAN` 区、伪造作者/年份/结论、把推断写成原文事实，或把 `human_verified` 当成默认值。

## 证据、身份和状态

文献页的四个身份字段承担不同职责：

```text
library_scope + zotero_key = Zotero 父条目身份
pdf_key                    = 具体 PDF 附件身份
citekey                    = Better BibTeX 写作引用键
fulltext_path              = Vault 内独立全文资料包中的 full.md 路径
```

| 字段 | 适用页面 | 谁提供/更新 | 含义与要求 |
|---|---|---|---|
| `type` | 所有结构化页面 | 模板；创建时确定 | 页面类型。校验器据此识别文献、知识、实验或投稿页，不应在补读时改变。 |
| `title` | 所有结构化页面 | Zotero 或用户；AI 可整理显示格式 | 页面标题。文献页使用规范论文标题，知识页使用稳定的研究单元名称，不把年份或作者强塞进知识页标题。 |
| `aliases` | 文献、知识页 | 用户/AI 建议，用户确认 | 可搜索的别名、缩写或旧称。不要把未经确认的同义词当作正式概念。 |
| `tags` | 文献、知识页 | 用户/AI 建议 | Obsidian 标签列表。用于导航，不替代证据和页面链接；保持少而稳定。 |
| `created` | 文献、问题、实验设计/运行 | 创建时记录 | 页面创建日期，不因补读或编辑反复改写。 |
| `updated` / `last_updated` | 知识、项目、投稿页 | 每次实际持久修改时更新 | 最近一次内容更新日期；必须是真实日期，不因校验命令运行而更新。 |
| `project` | 跨页面关联 | 用户选择 | 关联项目的稳定名称或 Vault 链接；没有项目时留空。 |
| `status` / `stage` | 知识、问题、项目、实验 | 用户决定；AI 只能建议 | 当前推进状态。状态值必须遵循对应模板，不用“完成”掩盖尚未运行或未核查的内容。 |
| `source_notes` | 知识页 | AI 汇总，用户核查 | 关联的正式文献笔记列表；应能回到 `zotero_key` 和原始证据。不要只填作者名或搜索结果 URL。 |
| `related` | 知识页 | AI 建议，用户确认 | 相关概念、方法、关系或争议页的链接列表。链接失效应修复或标记待处理。 |
| `related_notes` | 文献页 | AI 建议，用户确认 | 与当前论文直接相关的 Vault 笔记链接；只做导航，不替代 `claims` 的证据来源。 |
| `relation_type` | 关系页 | AI 建议，用户核查 | 关系证据角色，只用 `direct`、`mechanism`、`conditional`、`contextual`、`related`；没有足够证据时保持 `related`。 |
| `evidence_count` | 知识页 | AI 统计后，用户核对 | 页面实际使用的证据条目数，不是论文数量目标，也不代表质量或因果强度。 |
| `evidence_status` | 知识页 | Agent 根据来源，用户核查 | 页面级材料覆盖：`fulltext_verified`（关键结论已回全文）、`note_only`（目前只依据笔记）、`mixed`（两者混合）。不要填 claim 级的 `note_supported` 或 `interpretation`。 |

## 文献精读页字段

文献模板保留套件脚本依赖的身份和证据字段，同时吸收“主题、研究对象、数据、方法、核心变量、关键发现、相关性”等可扫描元数据。后者是摘要索引，不是对论文结论的免核查背书。

| 字段 | 来源与填写时机 | 规则 |
|---|---|---|
| `library_scope` | Zotero 条目/API | 个人库通常为 `users/0`，群组库为实际 `groups/<id>`；不得猜测。 |
| `zotero_key` | Zotero 父条目 | 8 位大写字母数字 key；题名相同不能代替 key。 |
| `pdf_key` | 选定的 Zotero 附件 | 8 位大写字母数字 key；同一论文的不同 PDF 作为不同附件记录。没有 PDF 时留空或使用 `abstract` 材料状态。 |
| `citekey` | Better BibTeX | 用于 LaTeX/BibTeX 的真实引用键；BBT 尚未导出时留空，不由标题猜测。 |
| `fulltext_path` | 全文导出脚本 | 指向 Vault 内资料包的 `full.md`；没有可核验资料包时留空。路径必须是 Vault 内相对路径。 |
| `material_status` | Agent 根据实际材料 | 只用 `abstract`、`pdf`、`parsed`。`parsed` 要同时有真实全文包和来源清单；Markdown 存在不等于内容已核验。 |
| `review_status` | 用户核查进度 | 只用 `unreviewed`、`partial`、`reviewed`。`reviewed` 要求每个核心 claim 均为 `human_verified` 且有来源。 |
| `claims` | Agent 建议，用户核验 | 结构化核心主张列表；每项至少有 `id`、`text`、`source`、`verification`，可选 `quote`。主张少而关键，不能把空列表当作内容正确。 |
| `authors` | Zotero/BBT 题录 | 作者列表；不确定时留空，不将贡献者或搜索摘要误填成作者。 |
| `year` | Zotero/出版物 | 出版年份；未知用 `null`，不把访问年份当出版年份。 |
| `doi` / `url` | Zotero/官方来源 | DOI 或稳定官方链接；优先记录出版商、会议、期刊或 arXiv 官方地址。 |
| `publication_type` | 题录与人工核对 | 如 journal、conference、preprint、technical-report；版本差异应在正文说明。 |
| `theme` | AI 速读后，用户核查 | 一句话说明论文主题；不得写成超出论文范围的领域结论。 |
| `study_area` | AI 从原文抽取，用户核查 | 研究对象、研究区域、任务或样本范围；没有区域研究时写任务/对象。 |
| `data_source` | AI 从方法/实验部分抽取 | 数据来源、样本和时间范围；缺失披露要写“未披露”，不能补猜。 |
| `methodology` | AI 从原文抽取，用户核查 | 核心方法、模型或识别策略；区分作者明确方法和 Agent 的解释。 |
| `core_variable` | AI/用户 | 核心变量、指标或概念；说明代理变量与真实概念的差别。 |
| `key_finding` | AI 草拟，必须回原文核查 | 最重要发现的一句话；不替代 `claims`、数字和页码证据。 |
| `relevance` | 用户判断优先 | 对当前研究的启发或相关性。AI 可以提出候选，不得写成用户已经接受的方向。 |
| `keywords` | Zotero/AI 建议 | 关键词列表，用于检索和导航；不要用它替代 `tags` 或知识页。 |

`claims.verification` 只使用：

- `unverified`：已有主张，但本轮尚未对原文定位核查；
- `agent_verified`：Agent 已查看原始 PDF/全文并记录页码、图表或公式位置；
- `human_verified`：用户实际核查并在人工区留下记录。

`source` 应写成可回溯位置，例如 `PDF p.5 / Table 2`、`full.md section 3.1` 或 `Figure 4`。无法定位时保持 `unverified`，不要用“看起来正确”替代来源。

## 知识页字段

知识页模板分为主题、概念、方法、关系、争议和综合六类。它们共享上述页面字段，但正文回答的问题不同：

- **主题**：研究对象与结果的综合判断、条件边界、证据缺口和候选问题。
- **概念**：定义、边界、测量、代理变量和相邻概念的区别。
- **方法**：方法适合回答什么、不适合回答什么、关键假设、诊断和误用。
- **关系**：`X → Y` 或 `X → M → Y` 的方向、机制、异质性和因果证据边界。
- **争议**：竞争性观点、分歧来源、不可直接比较的条件和能区分解释的新证据。
- **综合**：跨多个主题/关系/争议页的成熟判断，保留 claim 级来源链。

知识页的 `evidence_status` 是页面级状态；正文表格中的 `evidence_role` 建议只用 `direct`、`mechanism`、`conditional`、`contextual`、`related`。`interpretation` 表示 Agent 的解释，不得和已经由全文支持的事实混写。知识页先写当前判断和边界，再列文献，不以论文数量或标签数量作为完成标准。

## 项目、实验和写作字段

| 页面 | 关键字段 | 约束 |
|---|---|---|
| 研究问题 | `status`、`project`、`evidence_count`、`evidence_status`、`source_notes` | 保留候选问题、价值、证据、可证伪假设和最小验证；`exploring` 不代表已选择方向。 |
| 项目状态 | `stage`、`updated`、`research_questions`、`source_notes` | `stage` 记录探索/推进阶段；链接当前研究问题和来源，只记录实际存在的成果、阻碍、决定和下一步。 |
| 实验设计 | `status`、`created`、`project` | 记录假设、对照、数据协议、预算和停止条件；不能填尚未运行的数字。 |
| 实验运行 | `status`、`created`、`project` | 记录代码 commit、环境、数据版本、命令、日志、原始结果和失败；运行前用 `planned`，成功状态需有实际退出和产物证据。 |
| 投稿检查 | `venue`、`updated` | `venue` 是目标期刊/会议/投稿渠道；以其当期官方要求为准，空 `venue` 不代表适合所有 venue，勾选项要保留来源和检查日期。 |

实验记录中的状态与科学结论分开：代码跑通、指标得到、独立复现和假设成立是不同事实。写作页的 citekey 必须在项目级 `.bib` 中真实存在，不能从文献页标题自动推导。

## 添加字段和升级模板

可以为特定领域增加字段，但应满足：字段有明确用途、来源和核查责任；不重复已有身份字段；不会要求 Agent 猜测；正文仍能在空值时正常阅读。升级前比较 `skills/ai-paper-copilot/templates/` 与正式 Vault 的 `templates/`，只合并新增结构，不覆盖用户的 HUMAN 区、人工标签和已有链接。
