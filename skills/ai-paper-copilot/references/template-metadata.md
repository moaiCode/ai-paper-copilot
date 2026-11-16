# 模板元数据与填写契约

元数据解决三件事：找到资料、回到来源、接续工作。默认保留 7 份核心模板；不把知识分类、证据计数或复杂看板作为科研前置条件。字段速查随 Vault 保存在 `templates/README.md`，正文依本轮问题展开。

## 填写原则

- frontmatter 位于文件最顶部，用一对 `---` 包围。安全解析 YAML，拒绝重复键；注释只说明含义，不属于值。
- `{{...}}` 仅用于模板或临时草稿；正式页面替换为真实值。未知值用空文本、`null` 或空列表，不为填满字段编造信息。
- `aliases`、`tags`、`source_notes`、`related`、`related_notes` 是列表；`title` 是非空文本。日期使用实际 `YYYY-MM-DD`；运行检查不更新日期。
- 模板中的检索扩展字段按需填。复杂方法、主要发现、相关性判断和局限写正文；核心主张只在 `claims` 维护一份结构化证据，不在多个元字段重复抄写。
- 新研究方向先在阅读、综合与讨论中形成，`project`、状态和人工决定以用户真实选择为准，不自动把建议写成已接受结论。

## 单篇文献：身份、材料、核查

| 字段 | 来源与要求 |
|---|---|
| `type`、`title` | `literature-note` 与规范论文题名；页面类型不随补读改变 |
| `library_scope` + `zotero_key` | Zotero 库与父条目身份；使用实际 scope 和 8 位大写字母数字 key，不按标题猜测 |
| `pdf_key` | 实际附件 key；不同附件独立关联。没有 PDF 的摘要阅读可空 |
| `citekey` | 真实 Better BibTeX 引用键；临时草稿可空，正式归档前补齐。条目已有引用键不要求先存在项目 `.bib` |
| `authors`、`year`、`venue`、`doi`、`url` | Zotero/出版来源题录；只用于快速浏览与定位，Zotero 继续作为题录管理入口 |
| `task`、`data_source`、`methodology` | 可选的任务、数据与方法索引，各用短语或一句话；可靠性、协议和细节写正文 |
| `project`、`related_notes` | 已选项目和相关页面；导航不替代原文证据 |
| `fulltext_path` | Vault 内独立资料包的 `full.md` 相对路径；没有转换包可空，直接可靠读取 PDF 也能核查 |
| `material_status` | `abstract`、`pdf`、`parsed`，只表示实际材料。`parsed` 需要真实全文包和来源清单 |
| `review_status` | `unreviewed`、`partial`、`reviewed`，是人工核查进度。`reviewed` 需要所有核心 claim 有实际人核记录 |
| `claims` | 少量核心主张；每项含 `id`、`text`、`source`、`verification`，可选 `quote`。省略 quote 可以，空引用不合格 |

`claims[].verification` 只用 `unverified`、`agent_verified`、`human_verified`。后两者必须有实际定位依据，例如 PDF 页码、图表、公式或全文章节；`human_verified` 还需用户实际确认，不能由 Agent 自授。材料齐全、Agent 对过原文、用户认可和实验已执行是不同事实。

正式归档保留上述身份/证据契约。其他检索字段不是校验门槛；缺身份的临时阅读可先放收件箱或直接回答，不为了进入正式层制造 key。

## 综合页：来源与判断

综合页使用 `type: knowledge-page`。主题、概念、方法讨论按问题调整同一份 `主题综合模板.md` 的正文，先形成可复用判断，需要时再扩展专门模板。

| 字段 | 用途 |
|---|---|
| `title`、`aliases`、`tags` | 稳定的问题名称、别名和少量检索标签 |
| `created`、`updated` | 创建与实际更新日期 |
| `project`、`status` | 所属项目和推进状态，按用户决定维护；与证据可靠性分开 |
| `source_notes` | 实际使用的文献笔记入口，应能回到 Zotero/PDF 证据；具体判断在正文保留原文位置 |
| `related` | 相关知识页或项目入口，只用于导航 |
| `evidence_status` | `note_only`：当前依据笔记/摘要；`mixed`：部分关键判断已回全文；`fulltext_verified`：本页关键判断已逐项回原始材料核查。都不表示用户已经认可 |

不靠来源数量判定质量，不要求一篇论文衍生多个知识页面。不同任务、数据与评测协议的指标不可直接排名；结论不足时可以只记录分歧与待查证据。

## 安全更新

`update_ai_note.py` 只支持已具 AI/HUMAN 分区的 `literature-note` 与 `knowledge-page`。预览差异后只更新 AI 区和该类型允许的派生字段，保留 HUMAN 与其他正文。新模板把 AI 标题与摘要也放入 AI 区，避免正文更新而摘要过时；旧页面迁移先识别作者和比较差异，不自动移动人工内容。

- 文献页：身份字段保持不变。实际变化后 `review_status` 复位；未变 claim 可保留旧人核状态，改变主张或来源的 claim 不能继承旧人核确认。
- 知识页：更新标题/别名/标签、来源/相关链接、证据覆盖和更新时间。保留创建日期、项目与用户状态；不强加文献的 `claims`、附件或 `review_status`。实际变化时报告 `human_review_required`，旧人工记录不代表新版认可。
- 已有自定义字段保持原样；未支持字段的变更会报告，不静默覆盖。可选 `knowledge_kind` 若已存在则保持不变，新页面不要求分类。
- 项目状态、研究问题、实验与投稿页按真实任务单独维护，不借该更新器重写用户决定或实验结果。详情分别见实验、写作参考。
