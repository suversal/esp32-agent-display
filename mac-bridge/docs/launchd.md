# Mac 桥接自启与自动恢复

2026-10-15，当前 Mac 使用用户级 LaunchAgent com.suversal.agent-display。用户登录后启动；进程退出或崩溃后由 launchd 重新拉起，短时间连续退出时至少间隔 5 秒。它不依赖终端或当前聊天保持打开。Mac 关机、睡眠或网络不可用期间无法实时更新，恢复后设备按原有 WiFi/WebSocket 逻辑重连。

源配置：[com.suversal.agent-display.plist](../deploy/com.suversal.agent-display.plist)。已安装到 ~/Library/LaunchAgents/com.suversal.agent-display.plist。路径针对当前 Mac，迁移前需调整虚拟环境、配置、工作目录和日志路径。plist 不含 token。

桥接源码目录已从 `agent-display/` 改为 `mac-bridge/`。已有环境更新时，需要在新目录准备虚拟环境，并把 LaunchAgent 的 Python 路径改为 `mac-bridge/.venv/bin/python`；Python 可编辑安装和旧虚拟环境可能包含原绝对路径，不能只移动目录。服务标签、`~/.config/agent-display/`、状态与日志目录、已安装的 `agent-display-hook` 名称继续沿用，现有配置与 hooks 无需改名。

查看状态与主动重启：

~~~sh
launchctl print "gui/$(id -u)/com.suversal.agent-display"
launchctl kickstart -k "gui/$(id -u)/com.suversal.agent-display"
~~~

停止并禁止下次登录自启：

~~~sh
launchctl disable "gui/$(id -u)/com.suversal.agent-display"
launchctl bootout "gui/$(id -u)/com.suversal.agent-display"
~~~

重新启用：

~~~sh
launchctl enable "gui/$(id -u)/com.suversal.agent-display"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.suversal.agent-display.plist"
~~~

KeepAlive 生效时，单独 kill 进程会自动重启；需要停用时使用上面的 disable/bootout。不要同时运行手动 bridge 实例。现有配置和 hooks 保留，原来的非托管进程已正常退出。

应用日志：~/Library/Logs/agent-display/bridge.log，按 1 MiB 轮换，保留三个备份。launchd 标准输出/错误另记在同目录 launchd.log。配置为 ~/.config/agent-display/config.toml，状态为 ~/.local/state/agent-display/state.json。

已经验证 plist 语法、启用状态、RunAtLoad 和 KeepAlive、实际启动及端口唯一监听。正常终止后服务恢复并在 2.1 秒内收到 ESP32 0.3.0 的 hello；随后模拟 SIGKILL，launchd 再次拉起进程，设备重新连接。没有重启 Mac 或注销用户，因此登录流程本身尚未实际演练。证据见工作区 logs/agent-display-alert-fix-runtime.json 和 logs/agent-display-launchd-verification.json。
