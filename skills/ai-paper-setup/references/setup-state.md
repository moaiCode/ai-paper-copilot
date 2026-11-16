# 安装进度与接续

正式库根的 `setup-state.json` 是安装记录。它便于新会话接续，不能代替实际检查。只准备文件时也保留后续待办，不把未执行的环境配置写成完成。

## 读取与更新

1. 先读取根 `AGENTS.md`、`research-profile.json` 和状态文件，核对当前用户、正式库位置与本次安装范围。已有库没有状态文件时，依据实际检查创建记录，不推断历史已完成。
2. 保留脚本生成的 `schema_version: 1`、`source`、`paths`、`decisions` 和 `checks`。源码路径或 commit 是来源线索；`commit_matches_snapshot: not_checked` 不表示已确认工作区与该提交完全相同。
3. 只更新发生实际变化的项，保留未知字段与已有证据。若用户修改后端、目录或授权，先核对 profile 与实际工具配置，再同步对应决策；单改状态文件不会改变软件设置。
4. 写回前确认原文件未被他人修改，通过同目录临时文件替换完成写入。不要把全份日志、偏好文件、Token、登录响应或论文内容存入进度。

`checks` 的值保持字符串，使用以下状态；证据单独放在顶层 `evidence` 对象中，以检查项名称为键，记录简短说明、核验时间和必要的非敏感文件位置。

| 状态 | 含义 |
|---|---|
| `pending` | 尚未完成，或尚未实际检查 |
| `not_selected` | 尚未选择，例如 MinerU 暂不配置 |
| `configured` | 配置已写入并读回，功能尚未实测 |
| `verified` | 对该项确实执行了对应功能验证，附证据 |
| `needs_attention` | 原先完成的项失效或当前检查失败，记录具体原因 |
| `not_applicable` | 当前方案不需要，注明原因；不能用于掩盖必需项失败 |

新库脚本只会将 `local_files` 标成 `verified`，依赖、应用、插件、主 Agent 运行入口、连接和样本保持待办，未选 MinerU 为 `not_selected`。插件内 Codex 的选择记在 `decisions.zotero_codex_app_server`，不要从通用 `agent_runtime: pending` 推断插件内 Codex 是必装项。安装 Agent 可增加更细的检查项 `zotero_codex` 与 `plugin_bridge`：关闭为 `not_applicable`，稍后决定为 `not_selected`，启用但尚未配置为 `pending`。没有写作项目的 `bibliography` 可记 `not_applicable`。

## 分开记录完成程度

`stage` 初始为 `files_prepared`。配置期间可用 `configuring`；所选环境配置已读回后可用 `environment_configured`；具体论文样本实测通过后可用 `sample_verified`。阶段名称是摘要，交付仍列出各检查项。仅文件安装到 `files_prepared` 已完成用户当前请求，同时明确后续配置未执行。

- `local_files`：根规则、profile、目录、两份项目 skill 和模板已核对。空库结构通过不等于外部环境可用。
- `python_dependencies`：正式库所选解释器能导入依赖并运行脚本，不能用另一个环境代替。
- `obsidian`、`zotero_plugins`、`agent_runtime`：分别记录实际安装、配置与发现情况；仅“应用存在”不足以标为功能已验证。
- `mineru`、`connections`：明确验证的是连接还是解析；主 Codex、插件内 Codex、API 与 MCP 分别核对。Token 测试成功不能代替全文图文质量检查。
- `sample_validation`：仅在具体授权的论文确实处理并检查后更新，记录文献/附件身份与产物位置。人工核查状态继续保存在笔记中，不由安装进度代填。

续装先核对相关已完成项是否仍有效，再执行本次范围内的待办。用户暂不配置某项时，保留对应状态并推进独立步骤；不重复创建正式库、不重置已有凭据、不因安装待办自动上传样例。
