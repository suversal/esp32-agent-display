# Mac 桥接服务与助手 hooks

Mac 桥接服务代码位于现有 ESP32 工作区的 mac-bridge 目录，使用 Python 3.13 和 aiohttp。独立虚拟环境不修改系统 Python。2026-10-15 已接上真实 ESP32，横屏 400×300 固件见 [firmware-status-display/README.md](../firmware-status-display/README.md)。

已实现：观察型 hook 中继、标准事件适配、会话状态机、授权关联、乱序缓冲、重启持久化、局域网 WebSocket、提醒确认，以及可备份/合并/卸载的 hooks 安装器。

Claude Code 与 Codex 已安装观察 hooks；Codex 使用桌面版内核完成真实只读工具测试，状态和摘要已进入设备使用的 WebSocket 快照。Gemini 已安装 hooks，并通过标准事件样本的中继和状态测试，本机 PATH 中没有 Gemini CLI，尚未完成真实客户端验收；Grok 尚未接入。显示、WiFi/WebSocket、BOOT 确认、两种提示音与长按静音开关已实机验证。

已通过 96 项自动测试和实际 HTTP/WebSocket/ack 往返。此前设备收到 8.1 KB 的分段快照、9 会话总数及四张卡片；真实 BOOT 操作送达 ack，确认后 waiting 状态仍保留。0.5.0 新增分页，用户已确认自动轮播和短按翻页正常。两种提示音已实机听到，音量由用户确认合适。Claude 的会话开始/任务开始/会话结束 hooks 已送达；完整工具与授权链路仍待补验收，前期供应商 HTTP 429 记录见 docs/agents/claude-code.md。Codex 最新证据见 [接入记录](docs/agents/codex.md)。

已安装 Claude 11、Codex 8、Gemini 7 个观察 handler，原配置与其他 hooks 均保留并备份。Codex 8 个本项目 hook 定义已单独审核、启用并保存精确信任哈希。bridge 当前运行在 8787 端口，已由 macOS launchd 托管，登录后自启、退出后自动重启。配置与维护见 [launchd 说明](docs/launchd.md)。

## Vibe Island 会话内容

固件 0.5.0 使用白底黑字布局，直接显示本机 Vibe Island 缓存里的会话标题、最近提问、回复片段和工具名。仓库与标题合并，对话自动换行，三会话同屏或单、双会话展开；标题最长 100 字符，提问和回复各最长 240 字符。每秒检查 ~/Library/Application Support/vibe-island/session-terminals.json 的变化。用户已确认这些内容在真实屏幕正常显示。

同一 Agent 和会话 ID 与原生 hooks 合并，不重复创建卡片；原生 hooks 负责授权关联和声音提醒。原生运行事件超过 15 分钟未更新时，较新的缓存 processing / running_tool / waiting_for_input 可校正陈旧的显示状态，不能解除真实等待或生成提醒。没有足够新信息时显示“状态待更新”。缓存独有的会话不生成提醒，时间显示为“多久前”，不会冒充整轮耗时。缓存不可用时继续显示原生状态。

摘录遮盖常见凭据格式并限制长度，只放在 RAM 和设备快照中，不额外写入 bridge 状态文件或日志。不修改 Vibe Island 的文件，也不扫描完整历史。可在配置中设置 vibe_island_path = "" 禁用。详情见 [实现与验收](docs/vibe-island.md)。

## 多会话翻页

0.5.0 的 hello 显式协商 paging，每个设备连接独立维护页码与轮播状态。内容卡片每页 3 个，无内容字段时每页 4 个；桥接仅发送当前页，设备的卡片容量保持不变。未协商分页的旧客户端继续收到前四项。

默认每 20 秒翻页，手动翻页停留 60 秒，按住 BOOT 约 1 秒松开可暂停/恢复，长按约 2 秒仍切换静音；短按优先确认提醒。未确认的授权提醒自动定位到对应页并暂停翻页，确认只清除提醒。翻页不生成声音序号，不修改助手任务；只在 RAM 保存会话 key 与导航状态。/state 的 device_pages 提供页码、轮播与自动翻页计数，不包含额外对话文本。

各页按待处理等待、运行中、已完成、空闲排序；同一状态内稳定排序，状态变化和新增运行会话会及时前移。调整排序时保留当前页码，不跟着旧卡片跳到后面的页；暂停和手动停留继续生效，未确认的等待提醒始终保持在可见页。此规则只需更新桥接，固件保持 0.5.0。

## 启动桥接服务

当前 Mac 已由 launchd 启动，不要再手动启动第二个实例。查看和重启服务：

~~~sh
launchctl print "gui/$(id -u)/com.suversal.agent-display"
launchctl kickstart -k "gui/$(id -u)/com.suversal.agent-display"
~~~

未安装 launchd 的环境，在本目录手动执行：

~~~sh
.venv/bin/python -m bridge
~~~

首次运行会生成 ~/.config/agent-display/config.toml 和随机 token。默认端口 8787，HTTP/WS 共用一个进程；局域网设备只能使用带 token 的 /ws，hook、状态和模拟接口只接受本机连接。

状态写入 ~/.local/state/agent-display/state.json；摘要日志写入 ~/Library/Logs/agent-display/bridge.log。token 不写入访问日志，prompt、工具输入和工具返回值不落盘。

准备新环境时：

~~~sh
/opt/homebrew/bin/python3.13 -m venv .venv
.venv/bin/python -m pip install -e ./bridge
~~~

## 查看模拟状态

另开终端，在本目录执行：

~~~sh
.venv/bin/python bridge/simulate.py
curl --noproxy '*' http://127.0.0.1:8787/state
~~~

模拟器每次使用新的会话标识，创建 Claude 授权等待、Codex 运行中和 Gemini 已完成三个会话，避免已结束轮次的幂等保护吞掉重跑事件。模拟状态不会操作任何编程助手。`bridge/verify_device_payload.py` 会临时创建容量测试会话，验证超过 4KiB 的快照和溢出计数，并在结束后移除。

清理本模拟器留下的 demo 会话：

~~~sh
.venv/bin/python bridge/simulate.py --clear
~~~

## 安装和卸载 hooks

先检查拟修改的位置：

~~~sh
.venv/bin/python bridge/install_hooks.py install --agent claude-code --dry-run
~~~

安装仅追加本项目的 handler，修改前保留带时间戳的配置备份。中继脚本安装到 ~/.local/bin/agent-display-hook；端口单独保存在同目录的 agent-display.port，改变端口时不需要改变 hook 命令字符串。

~~~sh
.venv/bin/python bridge/install_hooks.py install --agent claude-code
.venv/bin/python bridge/install_hooks.py status
.venv/bin/python bridge/install_hooks.py uninstall --agent claude-code
~~~

端口改变时，在安装命令中传 --port。安装器不自动开启编程助手的权限，也不替用户信任 Codex hooks。Codex 用户可以在客户端 /hooks 中审核；本项目另提供 codex_hooks.py，通过实际内核检查定义和信任状态。

~~~sh
.venv/bin/python bridge/install_hooks.py install --agent codex
.venv/bin/python bridge/install_hooks.py install --agent gemini
.venv/bin/python bridge/codex_hooks.py
~~~

已审核工作区的中继代码后，可显式执行 codex_hooks.py --trust-reviewed-relay。它要求安装脚本逐字节等于工作区源文件，只写入本项目用户级 hooks 的当前哈希，修改前备份 config.toml。不会信任其他 hooks 或修改工具审批策略。安装前已启动的客户端会话可能需要重新打开，实际加载以 /hooks 或新会话事件为准。

安装器只移除自己生成的命令，保留其他设置和 hooks。安装后新增的用户设置也会保留；原来不存在的配置文件在卸载后恢复为不存在（文件没有用户新增内容时）。

## 本原型的提醒约定

- Codex 的 PermissionRequest 只说明正在检查权限。其他 hooks 或自动审核可能直接放行，既不证明电脑上存在人工弹窗，也不提供工具调用 ID。因此它按静默的 permission_check 处理，继续显示运行中，不创建“授权待确认”。当前 hooks 无法可靠确认 Codex 人工审批弹窗，暂不为它生成急促授权提醒；不会更改 Codex 的审批策略。旧版本遗留的这类等待及关联提醒在恢复时清除，其他 Agent 和回答等待保留。
- 新的授权或回答请求提醒一次。默认不重复，因为“曾经在等待”和“现在仍在等待”不同，批准后长命令执行期间不能据此重响。
- 10 秒内没有确定的解除信号，显示“授权待确认”或“回答待确认”。
- 其他并行工具的活动不代表这个授权已解决。
- 原始事件提供调用 ID 时，按同轮次、同子代理的精确 ID 关联。缺少 ID 时，仅在工具名和输入指纹一致且候选唯一时推断绑定；迟到的第二候选会撤销推断绑定，保留未确认状态。
- 每轮任务收到正常完成事件后产生一次柔和提醒，不再限制任务时长。done_alert_min_seconds 默认 0，取消门槛时即使整轮耗时未知也提醒；重复完成事件不重复提醒。中断和失败不发完成音。只有缓存显示等待输入而未收到完成事件时，不推断完成或生成声音。
- 当前固件 BOOT 的 ack 只确认提醒和高亮，不批准工具调用，也不把 waiting 改为 running。KEY 的 GPIO 尚待验证。
- 恢复出来的会话带 stale 标记；旧提醒保持静默。
- WebSocket 每个连接的首帧只同步，以顶层 current_sound_seq 建立声音基线。设备之后每收到快照都消费该全局序号，即使当前提醒被静音或被更高优先级提醒遮住，也不在稍后补响。
- 安静时段默认采用 Mac 本地时间 23:00–08:00。

这是一套尽力观察的状态显示。源工具不提供即时“已批准”事件、bridge 停机时丢失事件等限制，会直接呈现在未确认/stale 标记里。

## 验证

自动测试在 bridge 目录运行：

~~~sh
cd bridge
../.venv/bin/python -m unittest discover -s tests -v
~~~

测试覆盖状态转换、并行工具、迟到事件、授权关联、确认提醒、隐私摘要、配置往返、HTTP/WS、真实 curl 转发和持久化重启。网络测试需要本机允许绑定临时端口。

可用临时会话设置验证真实 Claude CLI：

~~~sh
.venv/bin/python bridge/verify_claude.py
.venv/bin/python bridge/verify_claude.py --offline
~~~

该脚本创建临时文件，只要求 Claude 使用 Read 读取它；不将 hooks 安装到 ~/.claude/settings.json，不烧录设备。它隔离用户已有 hooks，保留环境中的 Claude 认证/供应商配置，产生少量模型用量，单次 API 预算上限为 0.50 美元。只依靠用户 apiKeyHelper 的安装需要自行通过正常客户端进行验收。输出只包含验证摘要，不保存模型输出或原始 hook payload。

完整的人工授权、手动拒绝、子代理和桌面端验收，仍需按开发方案用真实任务完成。

Codex 的只读接入检查为 bridge/verify_codex.py，默认使用本机桌面版内核、已安装的观察 hooks 和实际 bridge。测试只读取临时文件，关闭该次调用的 MCP/插件，不保存会话历史，产生一次短任务的模型用量。结果只记录状态、摘要和成功标记，见 logs/agent-display-codex-live.json（工作区根目录）。
