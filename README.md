# AI 科研工作流：Zotero × Obsidian × Codex

源码与更新：[moaiCode/ai-paper-copilot](https://github.com/moaiCode/ai-paper-copilot)。

这是一套科研工作流技能与部署模板：Zotero保存题录/PDF/标注，Obsidian保存理解和项目，Codex协调阅读、代码、实验与LaTeX写作。AI先形成完整中文笔记，人核关键主张并保留自己的思考。

**本目录中的 `ResearchVault/`仅是模板和测试目录，不是正式科研库。**先在[安装与首次配置](00-安装与首次配置.md)中选择自己的正式 `VAULT_ROOT`，复制模板并配置各工具；不要把软件持续导出绑定到套件里的模板，也不依赖模板自带skill链接。

```mermaid
flowchart LR
    A[Zotero 收集与筛选] --> B[MinerU 按需解析]
    B --> C[正式库中的独立原文包与AI笔记]
    C --> D[人工核查与知识综合]
    D --> E[研究问题与最小实验]
    E --> F[代码与真实结果记录]
    F --> G[LaTeX 写作与修改]
    F --> D
```

| 入口 | 内容 |
|---|---|
| [00 · 安装与首次配置](00-安装与首次配置.md) | 选择正式库、安全复制、逐字段配置、插件/MCP/BBT/bridge、迁移与撤销 |
| [01 · 日常操作手册](01-科研AI工作流操作手册.md) | 部署后从探索、阅读、综合推进到实验、写作和修改 |
| [03 · Skill使用说明](03-ai-paper-copilot使用说明书.md) | 自然语言、脚本、笔记字段、补读更新和排错 |
| [02 · 设计说明](02-个人科研Skill设计方案.md) | 模板与部署分离、证据状态和人工内容保护 |
| [Skill入口](skills/ai-paper-copilot/SKILL.md) | 可复制安装的ai-paper-copilot v2 |
| [Vault模板说明](ResearchVault/说明.md) | 模板骨架及测试边界，不含正式部署承诺 |
| [公开论文演练](examples/公开论文演练.md) | 独立示例；不会自动成为你的正式笔记或研究方向 |
| [验收记录](验收记录.md) | 程序检查、历史能力验证和模板恢复的实际结果 |

## 开始使用

1. 阅读00，编辑正式库绝对路径；新目标必须不存在，已有库按增量接入，不覆盖合并整库。
2. 复制模板，安装项目级skill真实副本和独立Python依赖；修改正式库的根AGENTS及profile。
3. Obsidian与Codex主文件夹打开正式库；CLI以正式库为cwd。逐项绑定LLM笔记落点、BBT项目`.bib`和可选bridge。
4. 新会话先只读自检，再按已授权范围处理一篇公开论文。安装、连接、解析、原文质量与人工核验分别验收。

模板恢复不会卸载已经安装的BBT/LLM插件、清除MinerU Token、重置Codex登录或卸载本地MCP。它只撤销指向模板的持续输出绑定并恢复模板内容；正式部署需要新选定的位置。

## 仅验证发行包与模板

下面是开发/模板测试，不建立正式库，也不安装或绑定外部应用。首次需要时创建套件测试环境；已有`.venv`可复用。

```bash
# 当前目录是套件根；这里的ResearchVault仅作为检查输入。
python3 -m venv .venv
.venv/bin/python -m pip install -r skills/ai-paper-copilot/requirements.txt
.venv/bin/python skills/ai-paper-copilot/scripts/doctor.py --vault ResearchVault --json
.venv/bin/python skills/ai-paper-copilot/scripts/validate_vault.py --vault ResearchVault --json
.venv/bin/python -m unittest discover -s skills/ai-paper-copilot/tests -v
```

空模板的empty_vault与needs_setup是可解释结果，不能为了让报告全绿向模板填真实文献或绑定插件。科研结论、图表正确性和人工认可都需另行检查。

正式数据的Git记录与PDF/Zotero备份分别安排。Git commit信息用中文，新增代码写清晰中文注释；不把密钥、登录态或大体积环境加入版本库。

## 更新与版本管理

从公开仓库获取套件后，先检查`git status`和`git diff`再更新，保留自己对模板/skill的定制。正式库中的项目skill是独立副本，套件更新不会自动覆盖它；比较版本后按需合并，并重新运行检查。正式库路径变化时，按00的迁移清单重绑所有外部落点。

提交信息使用中文，例如`完善正式库安装配置说明`；新增代码写清晰中文注释。提交前检查暂存差异，不上传个人虚拟环境、API/MCP Token、登录配置、真实文献库、论文PDF或原文解析缓存。模板只保存可复用骨架，历史能力验证与正式科研成果分开。
