# ai-paper-copilot 使用说明书

本技能接收自然语言任务，结合当前可用工具与本地资料，推进文献、知识、实验和写作。套件内 `ResearchVault/` 仅供模板/测试；正式任务先指定你已部署的独立 Vault，不从当前套件目录自动推断正式库。安装看 [00](00-安装与首次配置.md)，完整流程看 [01](01-科研AI工作流操作手册.md)。技能不会因为被加载就自动获得 Zotero/MCP 权限、MinerU 服务或外部算力。

## 1. 向 Agent 提出任务

首次会话先确认正式 Vault 绝对路径、根 `AGENTS.md`、`research-profile.json` 和工具状态。若当前打开的是套件或模板，只做只读检查；部署前不把论文、自动导出或项目进展写入模板。可以显式调用 `$ai-paper-copilot`，也可描述任务让客户端发现技能；如果列表里没有技能，先按安装说明核对项目级 `.agents/skills`，再新建会话。

| 你想完成什么 | 可直接使用的请求 | 应得到什么 |
|---|---|---|
| 探索研究方向 | “我还没有细分方向，结合兴趣和资源帮我建立候选问题地图，需要的信息集中问。” | 候选问题、代表文献、可验证性与未知项 |
| 检索和筛选 | “围绕这个问题检索，记录来源和筛选理由；把明确入选的可获取文献加到这个 collection。” | 检索记录、去重结果、入选/待获取清单 |
| 只读摘要 | “先做摘要速筛，判断与这个问题的关系，不展开完整精读。” | 筛选判断及证据边界，不冒充阅读全文 |
| 解析与归档 | “按已选后端处理这份 PDF，复用缓存，导出独立全文包。” | 真实解析结果或缺失说明，来源包与验证 |
| 完整精读 | “完整精读并归档中文笔记，列出要我核验的关键 claim。” | AI 区完整分析、claim 出处、人工区保留 |
| 更新已有笔记 | “补充新结果，只更新这篇笔记 AI 区，保留我的判断和已核验的未变 claim。” | 定向差异、保护检查、待审阅状态 |
| 多篇综合 | “比较这几篇的设定、方法、证据和冲突，更新主题页。” | 可比较项、不可比原因、回链与原文核验 |
| 选题和实验 | “把这个 gap 转成可证伪假设，设计最小验证；在指定仓库和预算内实现执行。” | 设计、代码、真实运行记录和下一决策；缺执行条件时明确缺口 |
| 写作与审稿 | “用已有原文和实验记录写 LaTeX 草稿，查引用并从审稿人角度挑证据缺口。” | 有来源的段落、真实 `.bib` 引用、编译/审阅记录 |
| 检查库 | “先只读检查这个库，给出错误、影响和最小修复。” | 实际检测报告，不把校验通过当科研结论通过 |

明确指出来源、目标目录/条目和执行范围后，Agent 可连续完成中间动作和检查。若信息缺口影响下一步，集中询问并先做独立部分；若要删除、迁移或向新服务发送资料，先明确具体目标。每个任务不要求机械走完整条流水线。

## 2. 三个常见场景

### 单篇首次归档

> 使用我已明确指定的正式 Vault。我选定这篇 Zotero 条目及其 PDF 附件，按已选 MinerU 后端解析。核对父 key、附件 key、citekey；先预览再导出独立全文包，生成完整中文笔记，至少核查核心结果与一个关键图表，列出仍需我核验的论断并完成校验。

如果只有用户上传 PDF，还未入 Zotero，可先临时阅读；正式归档前补充真实身份。没有后端时报告该缺口，不把模拟缓存当真实解析完成。

### 人工核验后继续更新

先在 HUMAN 区补充你自己的判断，并标记已经复核的 claim。之后：

> 我核验了 C1，其余仍待核。请根据补充材料更新 AI 分析，保持原笔记身份和人工区；未变化的 C1 保留人核记录，新 claim 不标成人核通过。检查更新前后的人工区字节相同。

脚本接收完整候选笔记，从中提取 AI 区和允许的机器元信息，忽略候选 HUMAN 区。更新 AI 分析后整篇 `review_status` 回到 `unreviewed`；旧 claim 的独立核验状态可以保留。不要手工整篇替换正式笔记。

### 从多篇阅读走到项目

> 以这些已归档论文为基础，回查关键原文，找出最值得验证的一个分歧。产出假设和最小实验设计；确认数据与算力约束后，在我指定的代码仓库实现并运行，记录版本、命令、日志和结果。再用真实结果写一个 LaTeX 小节。

“最值得验证”基于证据、成本和可失败性判断；“从未有人做过”不能从当前笔记库推出。实验是否执行、执行到哪里、结论支持到哪里分别报告。

## 3. 脚本接口

正式使用先按00完成部署。下面先填写并只读检查正式库变量；占位值、套件模板或尚未安装的路径会停止检查。只有检查成功，才运行后续脚本。`--help` 是脚本参数的最终依据。

```bash
# 当前目录是套件根；VAULT_ROOT必须编辑为已部署的正式库，不能填套件模板。
export RESEARCH_ROOT="$(pwd -P)"
export VAULT_ROOT="/请填写已部署正式库绝对路径"
export SKILL_ROOT="${VAULT_ROOT}/.agents/skills/ai-paper-copilot"
export PYTHON_BIN="${VAULT_ROOT}/.venv/bin/python"

python3 - <<'PY_CHECK'
import os
import subprocess
from pathlib import Path

# 这里只验证已部署环境，不创建目录、不安装或覆盖内容。
package = Path(os.environ['RESEARCH_ROOT']).expanduser().resolve()
raw = os.environ.get('VAULT_ROOT', '').strip()
if not raw or any(word in raw for word in ('请填写', '替换为', '<', '>')):
    raise SystemExit('请先填写正式VAULT_ROOT。')
vault_input = Path(raw).expanduser()
if not vault_input.is_absolute():
    raise SystemExit('正式库必须使用绝对路径。')
vault = vault_input.resolve()
if vault == package or package in vault.parents or vault in package.parents:
    raise SystemExit('这是套件、模板或其父目录，不作为正式库运行。')
for relative in ('AGENTS.md', 'research-profile.json', '.agents/skills/ai-paper-copilot/SKILL.md', '.venv/bin/python'):
    if not (vault / relative).is_file():
        raise SystemExit(f'正式部署缺少 {relative}；按00补齐，不能回退到模板。')
subprocess.run([str(vault / '.venv/bin/python'), '-c', 'import yaml'], check=True)
print(f'正式库和项目依赖已确认：{vault}')
PY_CHECK
```

后续命令使用正式库内的项目skill副本和解释器，套件移动不会改变脚本落点。仅做套件开发测试时，可以显式把模板作为只读检查输入；不要把这种测试当成正式部署或为全绿而绑定软件。

### 环境自检：doctor.py

```bash
# 只读报告库结构、配置、依赖和可探测的本地组件状态。
"${PYTHON_BIN}" \
  "${SKILL_ROOT}/scripts/doctor.py" \
  --vault "${VAULT_ROOT}" --json
```

它不安装插件、不开启自动解析、不替你选择后端。API 可访问不证明客户端有全部工具；配置齐全也不证明 PDF 已真实解析。缺依赖时按安装文档处理，不能用另一个 Python 的成功导入代替实际解释器检查。

### 原文导出：export_fulltext.py

下例的 `users/0` 仅演示本地个人库；实际 `--library-scope` 必须与正式profile及来源库一致，群组库不能沿用这个示例值。

```bash
# 这些变量必须来自实际发现的单篇缓存目录和对应 PDF，不按标题猜测。
export CACHE_DIR="/替换为实际绝对路径/单篇缓存目录"
export SOURCE_PDF="/替换为实际绝对路径/来源.pdf"

# 先预览：读取现有缓存和原 PDF、计算来源身份，报告拟生成的位置。
"${PYTHON_BIN}" \
  "${SKILL_ROOT}/scripts/export_fulltext.py" \
  --vault "${VAULT_ROOT}" --cache-dir "${CACHE_DIR}" \
  --source-pdf "${SOURCE_PDF}" --library-scope users/0 --dry-run --json

# 核对预览后执行；若缓存缺稳定 key，补 --parent-key 和 --attachment-key 的真实值。
"${PYTHON_BIN}" \
  "${SKILL_ROOT}/scripts/export_fulltext.py" \
  --vault "${VAULT_ROOT}" --cache-dir "${CACHE_DIR}" \
  --source-pdf "${SOURCE_PDF}" --library-scope users/0 --json
```

| 参数 | 含义 |
|---|---|
| `--vault` | 目标 Vault 的实际路径 |
| `--cache-dir` | 一个明确附件的缓存目录；不是整个缓存库 |
| `--source-pdf` | 必需的原 PDF，供指纹计算、独立归档和原文核验 |
| `--library-scope` | 实际库身份；本机个人库示例 `users/0` |
| `--parent-key` / `--attachment-key` | 缓存不能提供时显式补充；与已有来源冲突须先解决 |
| `--converter-version` | 已知的实际转换器/版本信息；未知时不伪造 |
| `--replace` | 仅在内容变化且已确认替换生成包时使用 |
| `--dry-run` / `--json` | 只预览 / 机器可读报告 |

输出包位于 `03fulltext/<library_scope 分段目录>/<attachmentKey>/`，包含 `full.md`、`provenance.json`、原 PDF、原缓存资料及 `assets.md`。个人库路径形如 `03fulltext/users/0/ABCD1234/`。原始图片位置不可恢复时只导航，不把图片插到猜测的正文段落。页索引到 PDF 物理页的映射与缺失情况单独记录。

脚本不调用解析服务、不上传、不改原 PDF 或插件缓存。相同包重复导出应保持不变；来源变化会要求处理冲突而非静默覆盖。`--replace` 不授权改人工笔记或其他包。

### 笔记更新：update_ai_note.py

```bash
# 候选文件是完整 Markdown 笔记，含正确标记；脚本只提取允许更新的部分。
export NOTE_PATH="${VAULT_ROOT}/02vault/实际笔记.md"
export CANDIDATE_PATH="${VAULT_ROOT}/06inbox/候选笔记.md"

# 先验证身份与区域，再查看拟更新的报告。
"${PYTHON_BIN}" \
  "${SKILL_ROOT}/scripts/update_ai_note.py" \
  --note "${NOTE_PATH}" --content "${CANDIDATE_PATH}" --dry-run --json

# 执行已明确范围内的 AI 区更新，保留正式笔记 HUMAN 区及其他受保护内容。
"${PYTHON_BIN}" \
  "${SKILL_ROOT}/scripts/update_ai_note.py" \
  --note "${NOTE_PATH}" --content "${CANDIDATE_PATH}" --json
```

标记缺失/重复/损坏、身份冲突和非法提升人核状态都应报告并拒绝不安全更新。候选不是只含 AI 正文的片段；不要把空白 HUMAN 区作为“清空人工内容”的指令。

### 结构与来源检查：validate_vault.py

```bash
# 全库检查，或将 --path 限定到本轮已有文件；--quiet 只减少常规输出。
"${PYTHON_BIN}" \
  "${SKILL_ROOT}/scripts/validate_vault.py" \
  --vault "${VAULT_ROOT}" --json
"${PYTHON_BIN}" \
  "${SKILL_ROOT}/scripts/validate_vault.py" \
  --vault "${VAULT_ROOT}" --path "${NOTE_PATH}" --json --quiet
```

先读错误对象、路径及原因，再修最小范围。没有论文的新库可以结构合格；`review_status: unreviewed` 也不等于文件非法。校验器不是论文质量评审或引用真实性的替代品。

## 4. 文献笔记字段与分区

使用 Vault 模板。以下示例只展示核心结构，不是一篇已经核验的论文：

```yaml
---
type: literature-note
title: "论文完整标题"
library_scope: "users/0"
zotero_key: "ABCD1234"
pdf_key: "EFGH5678"
citekey: "实际BetterBibTeX键"
fulltext_path: "03fulltext/users/0/EFGH5678/full.md"
material_status: parsed
review_status: unreviewed
claims:
  - id: C1
    text: "需要验证的具体论断"
    source: "PDF p.5 / Table 2"
    verification: unverified
---
```

| 字段 | 使用规则 |
|---|---|
| `type` / `title` | 文献类型与真实标题；标题不是唯一身份 |
| `library_scope` + `zotero_key` | 父条目的库内身份，正式归档必需；临时阅读允许未归档 |
| `pdf_key` | 实际使用的 PDF 附件 key；不能填父条目 key |
| `citekey` | 真实引用键；空缺不编造，正式写作前补齐 |
| `fulltext_path` | Vault 相对路径；没有导出包时可空，不假装存在 |
| `material_status` | `abstract` / `pdf` / `parsed`，只说明当前材料形式 |
| `review_status` | `unreviewed` / `partial` / `reviewed`，由人工实际审阅进度决定 |
| `claims` | 每项含稳定 `id`、具体 `text`、`source`、`verification`；`quote` 可选且仅用核对过的短原文 |
| `verification` | `unverified` / `agent_verified` / `human_verified`；Agent 不能替人授予新的人核状态 |

正文使用四个固定标记，每种只出现一次：

```markdown
<!-- AI:START -->
AI 的完整分析、关键论断、证据说明和待核验问题。
<!-- AI:END -->

<!-- HUMAN:START -->
你自己的理解、批注、判断与实际核验记录。
<!-- HUMAN:END -->
```

`agent_verified` 表示 Agent 对照当前可访问原文核验过，仍可能出错。`human_verified` 仅表示你确实做过对应核验，不保证论文结论普遍成立。多篇综合中的推断要标为分析，而非借一个引用变成原文事实。

## 5. 进度报告与故障处理

任务完成报告区分四件事：产物是否写入、结构是否通过、证据核验到哪里、是否真实解析/执行。不要把某一项通过合并成“科研流程已经全部验证”。

| 情况 | Agent 应如何继续 |
|---|---|
| 找不到唯一条目/PDF | 列出实际候选和区分字段，请用户选择，不靠相似标题猜 |
| 只有摘要/没有全文 | 完成速筛或临时笔记，保留材料状态；不写全文方法与结果细节 |
| 未选择解析后端 | 继续题录、检索、准备；在首次需要解析前请用户选择云或自托管 |
| 有 PDF 而 MD 解析失败 | 可直接核查 PDF，明确解析缺口；不强制整任务停住 |
| 缓存缺 key/原 PDF | 读取真实题录/附件元数据或索取缺项；不生成假的来源包 |
| 缺页码/图像定位 | 报定位缺失；可导航现有资产，不编造页码或图位置 |
| 同源结果已经存在 | 报告复用结果，不因为新会话重复写入/追加同一内容 |
| 内容不同而未指定替换 | 先比较来源差异，按具体授权处理生成包；不静默覆写 |
| HUMAN 区或身份发生冲突 | 停止该文件更新，保留原文件、候选和可读差异 |
| 检索/写库/运行工具缺失 | 报真实缺口，完成可独立部分，给明确的手工或连接步骤 |
| 实验未执行/失败 | 交付设计或失败记录，不写完成的数值与复现结论 |
| 无需新增知识页 | 记录“本篇未改变当前判断”及理由即可，不制造空主题页 |

外部插件、版本与连接问题集中看 [00 的正式部署自检](00-安装与首次配置.md#8-正式部署的自检与验收)及[迁移与撤销](00-安装与首次配置.md#9-迁移解绑和撤销)。本套接口报错时同时记录实际命令、所用 `.venv/bin/python`、文件路径和脱敏错误；不要打印含凭据的完整配置。


## 6. 独立示例与正式库入口

[公开论文演练](examples/公开论文演练.md)留在套件的examples目录，供阅读和核验流程参考，不自动进入正式库，也不证明你已选择该研究方向。此前放入模板的演练笔记/原文包/项目内容已纳入模板恢复范围，不能再用模板index当正式工作入口。

真实工作从你选择并部署的正式Vault开始。软件和凭据可以复用，但LLM笔记落点、BBT导出、research-vault桥接路径必须按[00配置清单](00-安装与首次配置.md)重绑并验证。2026-11-15的能力测试只作历史证据，当前恢复结果看验收记录。新开会话后分别核对主Codex和插件内Agent的工具发现。

`update_ai_note.py --dry-run --json` 现在返回只含变更行的 `diff`，便于检查 AI 正文和机器字段；不把未变化的人工内容重复打印出来。预览不会写文件。正式笔记未填 source key 时的身份绑定、合并文献等，需要作为明确归档动作单独核对，不借补读更新悄悄换身份。
