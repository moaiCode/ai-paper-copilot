# 工具接入与首次使用

用户希望安装、接入已有库或继续部署时，优先交给同项目的 `ai-paper-setup` 安装 skill；尚未取得它时读取[仓库安装入口](https://github.com/moaiCode/ai-paper-copilot/blob/main/INSTALL.md)。入口负责关键问答与安装进度，本页提供研究工作流的工具接入依据。讨论或维护套件时不因此连接真实资料库。

这套工作流以单台 Mac 上的个人 AI/ML 研究为默认场景。Zotero 保存题录、原 PDF 和阅读批注；Obsidian 保存 Markdown 知识与项目；主 Agent 会话以 Vault 为工作区，协调检索、整理、代码和写作。不要让多个工具同时覆盖同一份笔记。

安装时采用双通道：终端和文件工具处理模板、依赖、脚本与状态；如果当前 Agent 有 Computer Use，则用它打开应用、填写非敏感 GUI 设置、点击测试/重载并读回结果。Token、登录、系统权限、删除/覆盖和上传由用户接管，Computer Use 不会自动获得这些授权。

## 主路径与可选组件

| 组件 | 用途与首次检查 |
|---|---|
| Zotero 与浏览器 Zotero Connector | 收集题录与附件、阅读和批注；确认能保存一条真实文献并打开附件。[官方 Connector](https://www.zotero.org/download/connectors) |
| Better BibTeX for Zotero（BBT） | 稳定 citekey 与 `.bib` 导出；对已用于写作的键固定后再导出。[引用键](https://retorque.re/zotero-better-bibtex/citing/)、[自动导出](https://retorque.re/zotero-better-bibtex/exporting/auto/) |
| llm-for-zotero | Zotero 内辅助阅读与 MinerU 转换；插件自带的模型入口不是主流程依赖。主 Agent 仍在 Vault 中统筹，不要求每次从插件启动另一套 Agent。[项目与安装说明](https://github.com/yilewang/llm-for-zotero) |
| Obsidian | 打开 Vault，阅读、复核和编辑知识；本流程不依赖 Obsidian AI 插件。核心 Templates 可用于手工建页。 |
| 任意 AI Agent 客户端 | 读取 Vault 根规则、调用本地技能和脚本；把 Vault 设为主文件夹或工作目录后启动。不同客户端的规则与技能发现方式不同，按各自文档核对。 |

可选组件：

- **Zotero Integration（Obsidian）**：需要手工导入 Zotero 批注时再装。其模板采用 Nunjucks，与本套件的 Agent 填写模板不是同一格式；需要按插件文档设置持久化区，不能让插件重导覆盖本套件人工区。优先导入到独立批注页，再由 Agent 引用。[模板与 persist 文档](https://github.com/community-archive/obsidian-zotero-integration/blob/main/docs/Templating.md)
- **Obsidian CLI / MCP**：需要调用应用功能时启用；普通文件阅读、写回和全文检索可由 Agent 直接完成。CLI 需要按当前 Obsidian 官方说明启用，不把“安装 Obsidian”当作 CLI 已可用。[Obsidian CLI](https://obsidian.md/help/cli)
- **Zotero MCP**：已有兼容工具或希望更方便地查询时使用。不同实现支持的检索、全文、批注和写入能力不同，按实际工具检查；不要要求用户额外安装一个未选定的“通用 Zotero MCP”。
- **Dataview、Bases、Templater、Excalidraw**：仅在导航、模板或绘图确有需要时增加，不作为这套科研流程的必装门槛。
- **科研检索服务**：可用浏览器检索和出版方/预印本来源；已连接的文献检索工具可补充发现。说明实际覆盖来源，不把某个付费服务绑定为必需组件。

## 第一次配置顺序

LLM-for-Zotero 可以使用标准模型提供商、本地 OpenAI-compatible 模型、WebChat 或 Claude Code 等运行时。**插件不需要任何特定 Agent 才能安装、打开 PDF 或使用 MinerU。**本套件不配置插件内专属 Agent 运行时；主 Agent 会话以正式 Vault 为工作目录，插件负责阅读辅助、解析和临时笔记导出。

脚本命令中的 `python3` 指已安装本技能 `requirements.txt` 的解释器；优先使用套件准备的 `.venv/bin/python`，不要修改系统 Python。尚未准备依赖时先按安装手册建立虚拟环境，再运行检查。

1. 在实际 Vault 根打开主 Agent 会话，读取 `AGENTS.md` 和 `research-profile.json`；核实路径与当前研究项目。新 Vault 尚无细分方向时保留 `research.focus: []`。
2. 运行 `doctor.py --vault <vault> --json`。它是只读检查，不安装软件、不启用 API、不启动应用或转换、不发起上传。根据结果只处理相关缺项。
3. Zotero 启动后按官方说明开启本地 API，并检查 `http://127.0.0.1:23119/api`。本地个人库默认 `users/0`；`data_dir: null` 时检测实际位置，检测有歧义再让用户选择。[Zotero 本地 API](https://www.zotero.org/support/dev/web_api/v3/local_api)
4. 配置 BBT，选一条样本文献确认 citekey，并做一次可读的 BibTeX/BibLaTeX 导出。自动导出只针对实际写作项目需要的范围，不默认导出整个文献库。
5. **尚未选择 MinerU 后端时，让用户选云端或本地/自托管；已有明确授权与配置则复用，不重复询问。** `mineru.backend: null` 表示未选择，`automatic_parse: false` 保持转换按需。对需要全文转换的任务，已选后端是首选路径；无论云端还是本地，执行全文提取前都要先取得本篇论文的处理授权。云端涉及上传具体 PDF 与可能费用，`ask_before_upload` 还要求在上传前实际询问，不能先静默改走本地提取；用户选择本地时，该选择就是本次本地处理授权。自托管先确认已有可达服务，不默认在这台 Mac 上安装或承诺能运行 GPU 模型。[MinerU 项目](https://github.com/opendatalab/MinerU)
6. 依后端和当前插件版本完成配置，使用一篇获授权的真实 PDF 转换；缓存导出到独立资料包，核查文字、图表、公式和来源，再生成首篇笔记并验证跳转。已选方式暂停或失败时按[方式切换规则](pdf-materials.md#解析异常与方式切换)让用户决定下一步，不自动改本地、另一解析器或上传目标。
7. 如使用 llm-for-zotero 笔记导出，目标设为 profile 的 inbox 下 `Zotero导出/`，图片放其 `assets/` 子目录。先以中间材料导出，由主 Agent 核对来源并合并到正式笔记 AI 区；不要让插件直接重导覆盖 `02vault/` 的双区笔记。
8. 记录已配置/已连接/已实测的组件和遗留项。未装可选 MCP 不影响已有文件工作；所需组件不可用时说明可完成的替代步骤。

配置文件只存非秘密设置，密钥、token 和登录态不放入 Vault 或 Git。安装步骤、价格和兼容版本以当时一手文档为准；不能把一次环境检查结果当成永久可用保证。

## 技能、规则与跨 Agent

- 根 `AGENTS.md` 放在 Vault，不放进 `.obsidian/`。读取 `AGENTS.md` 的客户端通常从项目根到当前目录发现规则；使用其他规则机制的客户端要按自己的入口单独配置。仅从 Vault 的父目录启动不能保证发现子目录规则。
- 项目技能安装到 `<vault>/.agents/skills/ai-paper-copilot/`；是否支持用户级技能目录、目录名与加载方式按所用客户端的文档核对。只选择一个有效作用域，避免同名重复副本；符号链接是否适合备份与迁移要明确。
- 若在插件内使用 Agent，其运行目录由插件管理，不应假定它等于 Vault。主路径让独立主会话直接工作在 Vault；要从插件调用 Agent，先确认实际 cwd 和技能路径。
- 其他 Agent 使用同一份 Vault 规则正文，按各自支持的项目入口加载；不能声称所有 Agent 自动读取 `AGENTS.md`。需要 Claude Code 时使用简短 `CLAUDE.md` 入口指向 `AGENTS.md`，具体导入语法以其当前官方文档核实；不复制两份会漂移的科研规则。
- 技能说明流程，MCP/插件提供能力；安装 skill 不会自动安装外部程序或获得外部账号授权。
