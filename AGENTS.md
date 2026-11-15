# 套件仓库工作约定

本仓库维护可公开发布的 `ai-paper-copilot` skill、中文文档、辅助脚本、隔离测试和初始 Vault 模板。维护工作从本文件、`README.md` 与本次相关的 skill 参考开始；无须为修改文档或代码先连接科研工具。

## 模板与真实使用环境

- `ResearchVault/` 是供用户复制的**初始模板**。保留全部初始目录、导航和模板文件；空目录用 Git 可追踪的占位文件保留。
- 保持模板未绑定状态：`research-profile.json` 中的 Zotero 数据目录留空，MinerU 后端未选择，自动解析关闭；通用本地 API 地址和 `users/0` 只是配置默认值。
- 不把本目录默认注册为 Obsidian 的实际库，不自动安装 skill 或插件，不绑定真实 Zotero 库、账号、API 凭据和模型后端。实际部署依照用户明确指定的目标路径进行。
- 演练说明与公开样例放在 `examples/`；测试和需要写入的演练使用隔离临时目录。真实阅读笔记、PDF、缓存、运行记录及个人设置不写回初始模板。
- 未获本次明确授权，不连接真实 Zotero、MCP 或云端解析服务，也不上传论文。仓库 CI 只运行隔离测试及本地结构检查。

## 修改与同步

- `skills/ai-paper-copilot/templates/` 保存套件模板源。模板改变后，同步 `ResearchVault/模板/` 的对应文件，保持文件集合与内容一致。
- 主 skill 保留任务入口和必要约束，细节放到按需参考；避免把完整手册复制进 `SKILL.md` 或根规则。
- 代码、模板、操作说明与实际命令接口同步更新。引用外部工具行为时使用官方或项目一手资料，注明核验版本或日期；不要把样例配置写成所有机器都成立的事实。
- 新增和修改代码使用详细、清楚的中文注释，尤其解释路径保护、身份匹配、人工内容保护、并发与失败恢复等重要约定。
- 使用 Git 管理，commit 提交信息使用中文。只提交与本次任务相关的文件，避免把虚拟环境、凭据、个人路径、真实库数据和转换缓存加入公开版本历史。

## 验证与交付

- 脚本依赖见 `skills/ai-paper-copilot/requirements.txt`；使用项目虚拟环境执行相关检查：

  ```bash
  .venv/bin/python -m unittest discover -s skills/ai-paper-copilot/tests -v
  .venv/bin/python skills/ai-paper-copilot/scripts/validate_vault.py --vault ResearchVault --json
  ```

- 涉及模板、目录或元信息的修改，还要检查模板 YAML 能由安全解析器读取，以及两套模板完全一致。CI 在 Python 3.9 和 3.12 上执行同样的隔离测试。
- 初始模板应返回 `empty_vault`、0 篇正式文献笔记及 0 个结构错误；该状态表示模板尚未积累真实资料，不能描述成科研全流程已经跑通。
- 交付时分别说明本地测试、模板检查、GitHub CI 和真实工具链的实际验证情况。没有运行的服务、解析、实验或投稿不得标为已经完成。
