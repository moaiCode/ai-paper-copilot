---
name: ai-paper-copilot
description: 以 Zotero、Obsidian 和 Codex 协作开展个人 AI/ML 科研：检索与入库、PDF 全文整理、论文精读与综合、研究问题、实验执行记录、LaTeX 写作和投稿准备。适用于维护科研 Vault、阅读论文或推进其中的研究项目；已有 PDF 或段落可直接处理，无须先入库。
metadata:
  version: "2.0.0"
  language: zh-CN
---

# AI Paper Copilot

让 Zotero 管理文献与批注，让 Obsidian 保存可复用的知识和项目状态，让 Codex 协调工具并完成有证据支撑的研究工作。AI 先形成完整笔记，用户复核后再沉淀个人判断；把理解、推断和实际实验结果清楚分开。

## 进入任务

- 先读当前工作区适用的 `AGENTS.md`。涉及 Vault 写回时，定位用户指定的 Vault，读取 `research-profile.json` 和相关项目的状态页。尚未配置时按 [工具接入与首次使用](references/integrations.md) 检测与引导。
- 用户直接给 PDF、摘要、代码或段落时，先完成材料支持的阅读、讨论或编辑；正式归档所缺的身份信息单独列出。不要把创建 Vault、接入 Zotero 或转换 Markdown 当成回答问题的前提。
- 用自然语言确定本轮成果：需要回答什么、写到哪里、何种证据或测试算完成。已有明确请求就继续，不要求用户填写 mode、证据等级或整套配置。
- 用户尚无细分研究方向时，围绕兴趣、背景与可用资源探索问题，不替用户锁定具体子领域。通用 AI/ML 透镜按论文类型取用。

## 按任务读取参考

只读本轮必要的参考，不默认加载整套文档。

| 当前任务 | 参考 |
|---|---|
| 安装提醒、首次配置、连接异常、跨 Agent 使用 | [integrations.md](references/integrations.md) |
| 搜论文、筛选、去重、导入 Zotero、追踪相关工作 | [literature-discovery.md](references/literature-discovery.md) |
| MinerU 转换、缓存导出、图像和页码核查 | [pdf-materials.md](references/pdf-materials.md) |
| 阅读单篇论文、解释方法、生成完整笔记 | [ai-reading-lens.md](references/ai-reading-lens.md) |
| 引用、数值、原文位置、区分事实与推断 | [evidence-contract.md](references/evidence-contract.md) |
| Vault 归档、更新笔记、人工区保护、跨论文综合 | [vault-and-index.md](references/vault-and-index.md) |
| 找研究问题、设计或执行实验、记录结果 | [idea-and-experiment.md](references/idea-and-experiment.md) |
| 英文 LaTeX 写作、`.bib` 接口、审稿与投稿 | [writing-and-review.md](references/writing-and-review.md) |

## 必须保持的工作约定

1. **材料强度决定结论强度。** 摘要支持速筛和有限总结；完整阅读优先使用全文并核查关键图表。缺材料可以交付明确受限的草稿，不编造原句、页码、数字、引用、实验或用户观点。
2. **身份与附件分开。** 正式文献身份为 `library_scope + zotero_key`；`pdf_key` 标识具体附件；`citekey` 服务写作。临时材料可暂缺 Zotero 身份，正式归档前再补齐，不猜 key。
3. **全文与理解分开。** `03fulltext/` 保存原文转换资料包；`02vault/` 保存理解；`01knowledge/` 保存综合判断。转换文本仍须检查错序、公式和表格，不能因存在 Markdown 就认为已核验。
4. **保护人工区。** 文献笔记用 `<!-- AI:START --> … <!-- AI:END -->` 与 `<!-- HUMAN:START --> … <!-- HUMAN:END -->` 分工。更新只替换 AI 区和必要元信息，保留人工区；没有有效标记或存在并发修改时先报告并处理冲突。详见更新参考。
5. **AI 核验不等于用户复核。** `agent_verified` 表示 Agent 对过原始材料；`human_verified` 必须有用户实际确认依据。AI 更新后复位 `review_status`，不代填“我的思考”，不把旧核查记录自动当成新版已复核。
6. **按已有授权持续推进。** 在明确目标、文件范围和预算内连续处理可逆操作；新增付费服务、上传未获授权的材料、扩大实验资源或执行删除/发布前，说明具体动作和影响再确认。不得直接修改 Zotero SQLite 数据库。

## 产出与执行

- 文献笔记优先使用 Vault 内当前模板；没有时使用 [精读笔记模板](templates/精读笔记模板.md)。保留最小元信息和核心 `claims`，正文按实际论文完整展开，不把每一句话都做成机器字段。
- 综合页面用 [主题综合模板](templates/主题综合模板.md)，研究问题用 [研究问题卡](templates/研究问题卡.md)，持续项目用 [项目状态模板](templates/项目状态模板.md)。重要判断链接到支持它的文献和具体证据。
- 实验设计和运行分别用 [实验设计单](templates/实验设计单.md) 与 [实验运行记录](templates/实验运行记录.md)；真实结果要能回到代码版本、配置、命令和原始日志。
- 写作使用目标 venue 的实际 LaTeX 模板和真实 `.bib`，投稿按 [投稿前检查表](templates/投稿前检查表.md) 结合当期要求核查。
- 工具检查执行 `python3 <skill-dir>/scripts/doctor.py --vault <vault> --json`；文件结构检查执行 `python3 <skill-dir>/scripts/validate_vault.py --vault <vault> --json`，必要时用 `--path` 限定本轮文档。校验通过只代表程序覆盖的结构检查通过，不代表科学结论或引用真实性已验证。
- 完成时交付成果路径、材料覆盖范围、已实际验证的事项、尚待用户核查或补齐的事项，并更新相关项目状态。只在本轮产生持久成果时向 `01knowledge/log.md` 追加简短记录，不把普通问答变成强制归档。
