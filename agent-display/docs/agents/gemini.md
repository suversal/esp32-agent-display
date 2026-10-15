# Gemini CLI 接入记录

2026-10-15。

~/.gemini/settings.json 中原先只有其他软件的 hooks。现已追加状态屏 7 个 handler，并验证原有 settings 和其他 hooks 完全保留：SessionStart、BeforeAgent、BeforeTool、AfterTool、Notification、AfterAgent、SessionEnd。

摘要读取 Gemini 的 absolute_path 字段，仅显示文件名。Notification 的工具信息可从 details 中读取；没有调用 ID 的 AfterTool 仅在观察到唯一同轮次、同子代理、同工具与同输入指纹的未结束调用时关联；相同输入的并行调用保持待确认。元数据不足时继续保留未确认状态，直到收到确定的轮次结束事件。

已通过原生结构样本经真实 zsh/curl 中继、HTTP、状态机和 WebSocket 的链路验证：BeforeAgent → BeforeTool（读取 app.py）→ Notification/ToolPermission（waiting）→ AfterTool（running）→ AfterAgent（done）。prompt、文件内容和回答均未进入持久状态或设备快照。

本机当前 PATH 未找到 Gemini CLI，因此没有运行真实 Gemini 客户端。本记录的样本链路测试不能替代真实客户端和人工授权验收。

接口依据：[Gemini CLI 官方 Hooks reference](https://geminicli.com/docs/hooks/reference/)。
