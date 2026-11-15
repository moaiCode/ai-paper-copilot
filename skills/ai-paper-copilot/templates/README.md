# templates：模板与元数据说明

这里保存可复制到 Obsidian Vault 的页面模板。模板使用中文正文，保留英文术语、公式和原文；YAML frontmatter 是给 Obsidian、Dataview 和脚本读取的最小索引，不是论文内容的替代品。

## 使用约定

- `templates/` 是模板目录，文件名可以按个人习惯调整，但 `type`、身份字段、证据状态和 AI/HUMAN 分区要保留。`ResearchVault/templates/` 应与本目录同步。
- `{{...}}` 是创建页面时要替换的占位符；模板本身可以保留占位符，正式笔记不应保留。
- 页面级 `evidence_status` 只表示该页引用材料的覆盖范围；文献页 `claims[].verification` 才表示某一条主张是否核查。二者不能互相推断。
- `source_notes`、`related` 和 `aliases` 保存稳定链接或笔记名，不复制整篇原文。来源应回到 Zotero 条目、PDF/全文资料包或实验原始记录。
- AI 只能维护 `<!-- AI:START -->` 与 `<!-- AI:END -->` 之间的内容；人工核查、判断和修改保留在 HUMAN 区。AI 内容实质变化时，相关主张回到待核查状态。

## 通用元数据字段

| 字段 | 含义与填写规则 |
| --- | --- |
| `type` | 页面机器类型，例如 `literature-note`、`knowledge-page`、`experiment-plan`；供脚本路由，不表示质量。 |
| `knowledge_kind` | 知识页子类型：`theme`、`concept`、`method`、`relation`、`controversy` 或 `synthesis`。仅知识页使用。 |
| `title` | 页面显示标题；文献使用规范题名，知识页使用稳定概念名。 |
| `aliases` | Obsidian 检索或旧称列表；没有别名时保留空列表 `[]`。 |
| `tags` | 少量导航标签；标签不能代替来源或研究结论。 |
| `created` / `updated` | 页面创建日期 / 最近一次内容或元数据更新日期，使用 `YYYY-MM-DD`。 |
| `status` | 页面工作状态，例如 `exploring`、`active`、`draft`、`archived`；按模板约定使用，不代表证据质量。 |
| `project` | 所属课题笔记或项目标识；尚未归属时留空字符串。 |
| `evidence_count` | 页面实际引用的独立来源数量，是提醒用计数，不替代来源清单。 |
| `evidence_status` | 页面证据覆盖：`fulltext_verified`（关键来源回到全文核查）、`note_only`（只依据笔记/摘要）、`mixed`（两者混合）。 |
| `source_notes` | 支撑页面判断的笔记链接或 citekey 列表；每项应能追溯到具体材料。 |
| `related` | 相关主题、概念、方法或项目链接；关系应在正文说明，不凭链接本身推断关联。 |
| `relation_type` | 关系页的证据角色：`direct`、`mechanism`、`conditional`、`contextual` 或 `related`；没有证据时保持 `related`。 |
| `research_questions` | 项目状态页关联的研究问题卡列表；只列实际存在的页面。 |
| `stage` | 项目所处阶段，如 `exploration`、`validation`、`writing`；与实验结果状态分开。 |
| `venue` | 投稿检查对应的目标期刊、会议或其他 venue；空值表示尚未选择。 |
| `library_scope` | Zotero 库身份，如 `users/0` 或 `groups/<ID>`；与 `zotero_key` 共同确定条目。 |
| `zotero_key` | Zotero 条目 key，必须是 8 位大写字母/数字；未知时临时笔记可留空。 |
| `pdf_key` | 具体 PDF 附件 key；同一条目有多个附件时必须区分。 |
| `citekey` | Better BibTeX 生成的写作引用键；不能用题名代替。 |
| `fulltext_path` | Vault 内全文资料包的 `full.md` 相对路径；没有资料包时留空。 |
| `material_status` | 材料完整度：`abstract`、`pdf` 或 `parsed`。它不表示科学结论已经正确。 |
| `review_status` | 文献整体人工核查状态：`unreviewed`、`partial` 或 `reviewed`。脚本会依据 claims 检查一致性。 |
| `claims` | 文献的少量核心主张列表；每项至少含 `id`、`text`、`source`、`verification`，可选 `quote`。 |

## 文献页的摘要字段

`精读笔记模板.md` 额外保留一组便于检索和快速比较的短字段。它们不是新的证据层，也不要求把复杂论文压缩成一句话；无法从材料可靠得到时留空或写“未披露”。

| 字段 | 含义 |
| --- | --- |
| `authors` / `year` | 作者列表 / 发表或版本年份；按 Zotero 题录填写。 |
| `source` | 期刊、会议、预印本或官方来源名称。 |
| `publication_type` | `journal`、`conference`、`preprint` 等题录类型；版本差异在正文说明。 |
| `doi` / `url` | DOI 或可复核的公开来源链接。 |
| `keywords` | Zotero/AI 建议的关键词列表；用于检索和导航，不代替 `tags` 或知识页。 |
| `theme` | 一句话概括论文主题。 |
| `study_area` | 研究对象、任务、研究区或样本范围。 |
| `data_source` | 数据来源、样本和时间范围。 |
| `methodology` | 核心方法、模型或识别策略。 |
| `core_variable` | 核心变量、指标或概念。 |
| `key_finding` | 最关键的研究发现，避免超出证据强度。 |
| `relevance` | 对当前研究的启发或相关性；尚未形成判断时写候选用途。 |
| `related_notes` | 文献页的相关笔记链接；用于导航，不替代 claims 的原文定位。 |

## 知识页的六种类型

| `knowledge_kind` | 适合记录的内容 | 重点检查 |
| --- | --- | --- |
| `theme` | 一个方向或主题的边界与证据地图 | 范围、纳入标准、研究空白 |
| `concept` | 定义、边界、测量和易混淆概念 | 不把术语相似当作概念相同 |
| `method` | 方法机制、适用条件和诊断 | 假设、失败模式、常见误用 |
| `relation` | 两个概念/方法/结果之间的关系 | 区分直接、机制、条件、情境和相关关系 |
| `controversy` | 文献分歧、可能原因和可改变判断的证据 | 不把单篇论文结论写成共识 |
| `synthesis` | 围绕一个问题的跨文献综合 | 设定可比性、冲突、证据强弱和下一步 |

知识页模板共享 `title`、`aliases`、`tags`、`status`、`evidence_count`、`evidence_status`、`source_notes`、`related` 和 `updated`。正文应包含 30 秒摘要、边界、当前判断、证据矩阵、缺口和来源追踪；页面只在有明确判断和可追溯证据时创建。

模板结构参考了 [Zotero Analytical Workflow Skills](https://github.com/cheneternity/Zotero-Analytical-Workflow-Skills)（核对版本：2026-11-16），但本套件的 Zotero 身份、材料状态、claim 核验和人工内容保护规则优先。
