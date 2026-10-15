# Codex 接入记录

2026-10-15。桌面版内核 codex-cli 0.162.0-alpha.17.2；PATH 中独立 CLI 为 0.158.0，验证选择桌面版实际使用的内核。

## 修复与配置

- 原先 ~/.codex/hooks.json 只有其他软件的 hooks，没有状态屏 handler。这是 Codex 不出现的直接原因之一。
- 保留原有配置和其他 hooks，追加 8 个观察 handler：SessionStart、UserPromptSubmit、PreToolUse、PostToolUse、PermissionRequest、Stop、Interrupt、SessionEnd。
- 使用本机内核 hooks/list 验证，无解析错误；审核本项目观察中继后，经 config/batchWrite 保存 8 个精确信任哈希。重新启动只读检查仍显示 enabled=true、trust=trusted。
- 对比修改前的 config.toml 备份，除了这 8 个信任项，其余 TOML 数据完全一致。没有修改工具授权模式，没有全局绕过 hook 信任。
- SessionEnd 按 Codex 接口要求同步运行；其他观察 handler 异步运行。中继不返回授权决定或模型上下文。
- 摘要新增命名空间工具名、apply_patch 文件名、计划更新与命令结果等待。默认不显示命令文本、补丁内容或完整路径。
- 授权事件提供 tool_use_id 时，优先按精确 ID 与轮次、子代理匹配，避免相同输入的并行调用互相清除等待。

## 真实测试

bridge/verify_codex.py 使用桌面版内核实际执行一次只读测试：读取临时 fixture.txt，工具成功退出，模型回复 BRIDGE_OK。原有 MCP/插件在该次调用中关闭，会话使用 ephemeral，不修改项目文件。

logs/agent-display-codex-live.json：CLI 退出码 0、未超时、耗时 31.72 秒、fixture_reply_confirmed=true、command_completed=true。设备使用的 /ws 快照先出现 codex/running，后出现 detail=执行命令。

测试完成后的实时 bridge 统计确认 session_start、turn_start、tool_start、tool_end、turn_end、session_end 各 1 次；临时 codex-check 会话已移除。

本次桥接重启后已收到 ESP32 的 hello。WebSocket 证据确认真实 Codex 事件进入设备快照，尚未由用户观察当前桌面会话的 [CX] 卡片；不能据此声称桌面旧会话已热加载新增 hooks。CLI 退出的 SessionEnd 会移除该临时卡片。

64 项桥接测试通过，包含 Gemini 原生结构样本经真实 zsh/curl 中继、HTTP、状态机到 WebSocket 的链路，以及精确调用 ID、无 ID 唯一/歧义关联和隐私摘要。

## 当前边界

用户已确认桌面 [CX] 卡片和摘要，以及后续 0.3.0 的标题、提问和工具/回复显示正常。安装前已启动的桌面会话可能缓存旧 hooks，需要重新打开后验证。工具 hooks 不覆盖所有托管工具，因此没有工具事件时，不会伪造摘要或百分比。

2026-10-15 修复授权误报：PermissionRequest 在最终审批决定前触发；其他 hooks 或 auto_review 可以直接放行，不一定向用户显示弹窗。它也不提供 tool_use_id，tool_input 可额外包含 description，与普通工具输入的整对象指纹不同。此前直接创建等待导致已执行命令留下未解除的授权记录，每次新的权限检查又产生急促音。

现将此事件标准化为静默的 permission_check，不推断“需要人工确认”；工具和任务状态仍由对应事件更新。恢复时只清除旧 Codex permission 等待及其关联提醒，保留回答请求和其他 Agent 的等待。当前 hook 接口无法可靠确认 Codex 人工审批弹窗，急促授权提示暂不适用于 Codex。没有返回审批决定，也没有改变权限、hook 中继或信任配置。

78 项测试通过，覆盖自动审核、多次检查、慢检查、完成后迟到检查、旧状态定向迁移及实际 HTTP/WebSocket 快照。运行中的 bridge 已清理 9 条残留误报；真实工具事件继续到达。审核结构样本经实际 zsh/curl 中继验证，声音序号保持 33，无等待和提醒；样本会话已移除。完整人工授权、拒绝与子代理 UI 仍待独立验收。

接口依据：[OpenAI 官方 Hooks 文档](https://learn.chatgpt.com/docs/hooks)，并以本机内核输出的实际 schema 和 hooks/list 结果核对。
