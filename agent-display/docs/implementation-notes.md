# 原型实现决策

依据 ESP32状态屏-开发方案 第三版启动开发。2026-10-14。

当前源代码保存在 /Users/sue/Developer/ESP32/agent-display，便于在已授权的 ESP32 工作区内开发。暂未移动到方案中的另一个 Developer 目录。

为便于真实验证，直接把最后一轮评审结论落实为以下规则：

- 默认取消重复提醒；6 秒时的通知不能证明 120 秒时仍未批准。
- 不启用“其他工具开始即推断该授权已继续”，保留未确认文字。
- snapshot 顶层增加 current_sound_seq，完成卡片增加 turn_duration_seconds。
- 标准事件保留 source；PermissionDenied 映射为 wait_resolved；StopFailure 映射为 turn_failed。
- 相同调用出现第二个迟到候选时，撤销绑定。此关联始终属于观察推断，无法保证识别所有无限迟到的事件。
- debug 日志只记录安全标识和事件类别，不保存原始 payload。
- HTTP 请求体最多 1 MiB，排序队列最多 4096 个事件，会话最多 128 个，设备连接最多 8 个。超限只丢弃显示事件，不影响源工具。
- 2026-10-14 的桥接阶段未修改烧录入口或设备。2026-10-15 进入硬件阶段，新增独立 agent_display 固件和 IDF_PROJECT；默认仍为 hello_screen。硬件进度与验证边界见 ../../agent_display/README.md。

已具备 Claude、Codex 和 Gemini 标准事件映射；真实接入是否验收以 docs/agents 下的记录为准，不能从模拟事件或构建通过推定真实客户端行为。
