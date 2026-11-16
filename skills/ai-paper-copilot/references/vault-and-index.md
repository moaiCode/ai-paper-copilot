# Vault、身份、更新与综合

涉及归档、更新笔记、索引或知识页时读取。实际路径以 Vault 的 `research-profile.json` 为准，不把示例绝对路径当作用户路径。

## 六层职责

| 目录 | 职责 |
|---|---|
| `01knowledge/` | 跨论文主题、方法、研究问题与知识地图；`log.md` 追加持久成果摘要 |
| `02vault/` | 一篇文献一份主笔记，`_index/` 为导航页 |
| `03fulltext/` | 独立全文资料包，保留解析文本、图片和来源信息 |
| `04projects/<课题>/` | 研究问题、项目状态、实验设计与运行记录、代码/数据/结果链接 |
| `05writing/<论文>/` | LaTeX 稿件、`.bib`、图表源与审稿材料 |
| `06inbox/` | 未整理的候选与临时材料；定期整理，不自动清空或删除 |

`templates/` 存放 Vault 的实际模板；本技能同名 `templates/` 是默认来源。模板可以调整正文，但应保留脚本依赖的最小元信息和 AI/HUMAN 标记；升级先比较差异，不覆盖用户改动。字段含义与填写时机见 [`templates/README.md`](../templates/README.md)。

## 身份与最小元信息

正式文献身份是 `(library_scope, zotero_key)`。`library_scope` 默认本机个人库 `users/0`；其他个人库/群组使用实际 scope，不能用一个假 key 代替未知身份。`pdf_key` 标识具体 PDF 附件，`citekey` 为写作引用键；题名用于展示，不能据此确认同一条目。

```yaml
type: literature-note
title: "实际论文题名"
library_scope: users/0
zotero_key: ABCD1234
pdf_key: EFGH5678
citekey: author2026method
fulltext_path: ""
material_status: pdf
review_status: unreviewed
claims: []
```

临时阅读可缺 `zotero_key`、`pdf_key` 和 `citekey`，保留明确的来源说明；入库后补齐再移入正式笔记层。`fulltext_path` 指向资料包内 `full.md`，没有解析全文时留空。其他作者、年份、主题、DOI、arXiv 与标签可按需要增加，不强制所有论文填同一套 AI 实验字段。

建议文献笔记名为 `<citekey>-<短标题>.md`；citekey 未定时用可识别的临时名。现有笔记路径保持稳定，Agent 不能因改标题或 collection 自动搬家。一个条目可属于多个 collection：主题通过标签和链接表达，避免为每个 collection 复制同一篇笔记。

全文按库 scope 与附件 key 归档，详见 [全文资料包](pdf-materials.md)。`zotero://select/library/items/<key>` 仅用于对应个人库；群组链接需要正确的群组路径，不套用个人库模板。

## 同一文件的 AI 区与人工区

```markdown
<!-- AI:START -->
Agent 维护的论文理解、证据与待核项。
<!-- AI:END -->

<!-- HUMAN:START -->
用户维护的核查记录与我的思考。
<!-- HUMAN:END -->
```

- 首次创建可以写两个区；人工区使用清单与空白，不生成用户已核查、已认同或“我的判断”的叙述。
- 后续仅更新 AI 区及与本轮内容一致的 frontmatter。人工区及其历史核查记录原样保留。
- 文献页和综合知识页使用 `scripts/update_ai_note.py --note <现有笔记> --content <完整候选笔记文件> --dry-run` 检查，再去掉 `--dry-run` 执行。候选含合法 frontmatter 与 AI/HUMAN 标记；人工区可为空，脚本只提取候选 AI 区和该类型允许更新的机器元信息，保留原笔记人工区及其他正文。不要用整文件覆盖代替该工具；它不用于任意类型的项目或实验页。
- 已确定的 `library_scope`、`zotero_key`、`pdf_key`、`citekey` 不可随正文更新偷偷替换；身份补齐或修正是单独的明确归档操作。
- 更新前读取当前版本；出现缺失/重复/嵌套标记、人工区差异或并发编辑，停止该文件写回并给出冲突。无标记的旧笔记先展示迁移方案，不猜哪些段落属于用户。
- 文献页 AI 区或允许元信息实际改变后，`review_status` 复位 `unreviewed`；完全无变化返回 `unchanged`，避免无意义地取消复核。旧 claim 的 id/text/source/quote 以及来源指纹/全文路径未变时可保留既有 `human_verified`；新增或改变的 claim 不接受候选自报人工已核验，脚本会降为 `unverified` 并提示。提醒用户旧核查记录对应旧内容。
- 知识页保持 `type` 与已有的自定义分类，更新 AI 区、标题、别名、标签、来源/相关链接、证据覆盖和更新时间。创建日期、项目归属和用户状态不由该工具更改；这些人工决定如需变化，另按明确任务处理。知识页不注入论文专用 `material_status`、`claims` 或 `review_status`。实际更新时报告 `human_review_required: true`，交付中提醒用户：保留的人工记录不代表已经确认新版判断；不要替用户改写 HUMAN 区来“完成复核”。
- 知识页模板的标题与顶部摘要属于 AI 区，随正文一起更新；把结论、适用条件和下一步同步到新证据，不留下与正文冲突的旧摘要。已有页面升级只迁移经确认属于 AI 的标题/摘要；先比较并保护原有人工作品，不凭位置猜测作者。

## 从笔记到知识

先用索引、元数据和笔记缩小范围，必要时直接搜索全文；不把“先有笔记”作为发现材料的硬条件。引用数字与核心结论时回到原始证据。

主题、概念、方法讨论与跨论文综合先用同一份 `templates/主题综合模板.md`，按实际问题调整正文，无须先建立固定知识分类。先确定问题，再比较方法、设定、证据与冲突。表格按问题选择，不强制三张固定矩阵；每项重要判断链接支持它的笔记，并给足原文定位。可以结论为“现有材料不足”或“本轮未改变认知”，不为了更新而增加知识页。

`_index/` 与 `01knowledge/index.md` 是导航，可用简短手工入口加 Dataview/Bases 等可选视图；索引不是来源证据。新增笔记后更新相关导航，避免每次重建全部索引。

项目状态用 `templates/项目状态模板.md`，记录当前问题、已知证据、待办、产物与下一步，使新会话可恢复。日志只记录实际持久成果与关键决定；改错以追加纠正为主，不伪造历史完成状态。

新建文件的显示标题使用规范论文题名；文件名可附 citekey 便于引用，但须解释它是引用键。中文短题须准确反映论文，不以泛化主题替代规范题名。文件名、元数据标题和正文标题分别检查；旧笔记不为美化自动改名。
