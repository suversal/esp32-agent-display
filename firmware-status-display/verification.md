# 设备端验证记录

2026-10-15，Waveshare ESP32-S3-RLCD-4.2，ESP-IDF 5.5.2，固件 0.1.0。

- 应用构建成功，1,306,896 字节，应用分区仍有 68% 空余。依赖版本已固定在 dependencies.lock。
- 烧录前备份 1,441,792 字节，每个读块已核对设备 MD5，另保存原 NVS；文件 SHA256 记在 backups/before-agent_display-20261015-002835.json。
- bootloader、分区表和应用写入后设备哈希校验通过；NVS 和 PHY 未列入写入范围。
- 从竖屏调整为用户实际使用的横屏。真实启动日志 DISPLAY_READY width=400 height=300；用户确认横屏方向和卡片排版正常。
- 设备复用已保存 WiFi，通过 mDNS 找到 Mac，WebSocket 握手成功，收到状态快照。
- simulate.py 的授权等待、运行中、完成状态均在真实固件接收日志中出现；不据此推定 Codex/Gemini 真实 hooks 已验收。
- 8,100 字节 JSON 快照超过组件 4,096 字节接收缓冲，设备成功重组并记录 9 个总会话。WebSocket 只发送前四个卡片和 total_sessions，其余会话保留在 Mac；临时容量测试会话已删除。
- 用户短按 BOOT 后真实串口记录 ACK_SENT ok=1；桥接端 alert 为 null，waiting 会话仍保留。最初一次按键反馈未与服务端状态一致，因此在稳定连接下重测后才确认。
- Host 使用同一 UI、协议和中文字体渲染，AddressSanitizer / UndefinedBehaviorSanitizer 检查通过。桥接回归测试 54 项通过。
- 退出时先在 aiohttp on_shutdown 关闭设备 WebSocket，避免等待活跃请求处理器才关闭连接；多个连接并发关闭，单个失联端最多等待 3 秒。新增活跃设备连接下退出测试。
- 修复后的桥接服务重启后，服务端在 8.8 秒内再次收到设备 hello，结果见 logs/agent-display-reconnect-server.json。连续 USB 复位后出现串口无输出和 ROM 连接失败；用户通过 PWR 重启及 USB 重插后确认界面恢复。此次恢复后的 USB 串口没有再复测，避免再次干扰设备。
- 用户提供的实机照片显示横屏中文卡片、连接状态、计时和溢出计数正常。服务重启恢复的会话显示问号；blog / api-server / notes 为模拟数据，验收完成后清理。

证据：logs/agent-display-build.log、logs/agent-display-flash.log、logs/agent-display-landscape.log、logs/agent-display-simulation.log、logs/agent-display-payload-check.log、logs/agent-display-ack-reconnect.log、logs/agent-display-bridge-tests.log。原始串口日志仅供本机检查，不公开分享。

0.1.0 阶段剩余：喇叭提示音、长按静音、KEY GPIO、温湿度、RTC、电量和恢复原备份。后续声音结果见下文；完整真实助手授权/工具链路仍待补验收，桥接服务尚未安装开机自启。

## 声音固件 0.2.0

2026-10-15，已加入独立音频任务、两种提醒音和 BOOT 长按静音。

- 最终应用 1,382,704 字节，编译通过；三段 Flash 均写入且设备哈希校验通过。
- 声音加入前的状态屏备份 1,572,864 字节已逐块核对设备 MD5。小智原始恢复备份也已扩展至同等范围，原始前缀 SHA256 和新增尾部读取校验均通过。
- 首次声音实测日志 AUDIO_READY；urgent 和 soft 均 SOUND_RESULT completed=1 code=0。用户确认“两种都听到了，音量合适”。
- 发现重开 I2S 时出现“channel has not been enabled yet”；已按驱动重配格式的要求先启动保持静音的 TX，再调用 codec open，最终版本已重新编译、烧录并发送测试音。
- 最终串口采集只捕获到启动加载日志，应用级输出没有持续送达；bridge 仍有活跃 0.2.0 设备连接，并成功发送手动试音。因此最终驱动修复的无报错日志尚未单独确认，不把消息发送成功等同于已听到声音。
- Host 的频率、幅度、淡入淡出、双声道和协议解析测试均通过（AddressSanitizer / UndefinedBehaviorSanitizer）；bridge 56 项回归测试通过。
- 显式本机试音不会修改真实会话、提醒状态或自动夜间静音设置，设备本地静音仍生效。普通提醒继续遵循全局声音序号和首帧静默规则。
- 完成卡片新增“耗时”前缀，缺少工具摘要时显示“本轮已结束”；运行卡片显示“暂未收到工具事件”，避免“等待事件”造成误解。

声音阶段证据：logs/agent-display-audio-build.log、logs/agent-display-audio-tests.log、logs/agent-display-before-audio-backup.log、logs/agent-display-audio-flash.log、logs/agent-display-audio-runtime.log、logs/agent-display-audio-final.log。原始恢复备份为 backups/xiaozhi-before-status-expanded-20261015.json。

本阶段核对的真实接入：Claude Code 11 个 handler，Codex 与 Gemini 均 0 个 handler。详情来自工具事件的安全摘要，不是模型文本或进度百分比。

用户确认长按 BOOT 后已切换到“静音”。随后手动 urgent 测试消息已送达 1 台设备，用户确认“没有声音”。再次长按后用户确认顶部显示“声音开”，手动 soft 测试消息已送达 1 台设备，用户确认“听到了，声音正常”。长按切换、静音拦截和恢复声音已通过实机验收；断电后的静音设置保存尚未完成实机验收。

## Agent 接入修复

2026-10-15，修复运行在 Mac 的事件适配、摘要和状态关联，设备固件保持 0.2.0，无需重新烧录。现已安装 Claude Code 11、Codex 8、Gemini 7 个 handler；Codex 本项目 hooks 的精确信任已保存，其他配置与 hooks 均保留。

桌面版 Codex 内核完成真实只读工具测试，工具退出成功，模型回复 BRIDGE_OK；设备协议的 WebSocket 快照出现 codex/running 与“执行命令”摘要。Gemini 标准事件样本通过真实中继到快照的完整链路，但本机未找到可运行的 Gemini CLI，尚未完成真实客户端验收。桥接回归测试 64 项通过。

详情及验收边界见 ../mac-bridge/docs/agents/codex.md 和 gemini.md，证据为 logs/agent-display-codex-live.json、logs/agent-display-agents-tests.log。用户观察桌面 [CX] 卡片仍待确认。


## 会话内容固件 0.3.0

2026-10-15，直接读取 Vibe Island 本机会话缓存，为现有状态补充会话标题、最近提问、回复片段和工具名。同一会话按规范化 ID 合并，缓存不控制授权和提醒；摘录不额外持久化。此前用户也已确认 Codex 桌面版的“[CX] 和摘要都出现了”。

- 74 项桥接测试通过；真实 C 解析、渲染和音频测试通过 ASan/UBSan，400×300 预览已查看。
- 应用为 1,586,976 字节，编译成功。写入 bootloader、分区表、应用后设备哈希校验通过，NVS 未写入。
- 升级前备份 before-agent_display-20261015-193059.json，覆盖 1,769,472 字节，每块设备 MD5 和本地 SHA256 均已验证。
- 原始小智恢复备份扩展为 xiaozhi-before-status-expanded-20261015-content.json；原始前缀 SHA256、当前 0.2.0 应用 SHA256 及新增未改写尾部均核对。旧 1,572,864 字节恢复备份不足以覆盖当前固件，应使用新的 content 备份。
- 服务端收到真实设备 fw=0.3.0，带内容的显示状态有三个会话。用户确认“这些内容都正常显示了”，三卡片、标题、提问、工具/回复已通过实机验收。

阶段证据：logs/agent-display-content-tests.log、logs/agent-display-content-render.log、logs/agent-display-content-build.log、logs/agent-display-before-content-backup.log、logs/agent-display-content-flash.log。未为本阶段额外播放测试音。

## 桥接自启和授权误报修复

2026-10-15，固件保持 0.3.0，未重新烧录或复位 USB。桥接已安装用户级 LaunchAgent com.suversal.agent-display，RunAtLoad、KeepAlive 和启用状态均已核对；安装文件与工作区 plist 一致，语法检查通过。

- 正常终止后自动恢复，2.1 秒内收到真实设备 fw=0.3.0 的 hello。随后模拟 SIGKILL，PID 从 96997 自动更换为 97679，端口仅由该托管进程监听，HTTP 返回 200，真实设备再次连接。未注销或重启 Mac，登录周期本身未实际演练。
- 用户报告没有授权弹窗却反复显示授权和响铃。旧状态含 Codex PermissionRequest 遗留等待；它是审批决定之前的权限检查，可由自动审核直接通过。整对象工具输入指纹也不一致，工具结束无法解除这些等待。
- Codex PermissionRequest 现按 permission_check 静默观察，不创建人工等待。恢复时定向移除 9 条旧等待并确认其关联提醒，不改变 Codex 审批策略，也不把确认提醒当作批准工具。其他 Agent 的等待及回答请求保留。
- 排查时临时暂停自动声音，部署后已逐字恢复原配置，默认安静时段仍为 23:00–08:00。并非靠全天静音掩盖误报。
- 78 项测试通过。重启后已收到 56 个真实工具开始/结束事件；审核事件结构样本经真实 zsh/curl 中继进入服务，保持 running、pending_waits=0、alert=null，声音序号 33→33，测试会话已移除。该样本不代表人工弹窗验收，未额外发送手动试音。
- 当前 Codex hooks 无法可靠确认人工审批弹窗，因此暂不生成 Codex 急促授权音；正常完成音保留。修复后是否仍有异常响铃尚无新的用户实机反馈。

证据：logs/agent-display-alert-tests.log、logs/agent-display-alert-fix-runtime.json、logs/agent-display-launchd-verification.json。维护与停用命令见 ../mac-bridge/docs/launchd.md。


## 浅色阅读界面 0.4.0

2026-10-15，按用户要求重新设计为白底黑字，去掉固定大标题，将仓库与会话标题合并；状态、工具和耗时集中显示，提问与回复自动换行。三会话时每卡最多四行对话，单、双会话自动展开。提醒为静态细边框，无整卡反色和闪烁。

- 主机预览原来与实屏黑白极性相反，现按 ST7305 0x21 和已观察实屏关系修正：位 1 为浅色、位 0 为文字。设备与预览使用相同 ui.c 和位图字体。
- 标题保持 100 字符，最近提问与回复上限增至 240 字符；768 字节的字段可容纳 240 个中文字符。UTF-8 换行不会拆开字符，保留凭据遮盖及只在内存和设备快照中使用摘录的约定。
- 79 项桥接测试通过，含较长摘录边界与遮盖，以及 0.4.0 试音协议的兼容检查；未对实机额外播放测试音。
- 同一 C 协议、界面、PCM 代码通过 ASan/UBSan；12 种场景包含三会话、双会话、展开、断线、静音、空闲、旧四卡片、完成/运行各两帧和长中英文输入，验证四行对话、浅色占比、边缘不越界、完成计时冻结与运行计时推进。
- 固件应用 1,588,048 字节，分区余量 62%。烧录前备份 1,769,472 字节，逐块设备 MD5 与本地 SHA256 通过；另核对备份中的 0.3.0 应用与 NVS。当前小智恢复备份覆盖范围仍足够，无需扩展。
- 0.4.0 写入 bootloader、分区表与应用后三段哈希均验证，NVS 不在写入计划。设备实际 hello=0.4.0，launchd 管理的 bridge 重启后 2.11 秒重连，实际源中四个会话具备标题和对话，最长回复摘录 240 字符。
- 用户实屏确认：“显示正常，清楚多了”。此次验收确认浅色、合并标题和换行显示；不扩大既有 Gemini、人工审批链路、声音持久化等验收范围。
- HTML 设计预览已通过本机浏览器切换与控制台检查，无错误；它展示固件实际字体和示例内容，不是实屏照片。

证据：logs/agent-display-light-render.log、logs/agent-display-light-bridge-tests.log、logs/agent-display-light-build.log、logs/agent-display-before-light-backup.log、logs/agent-display-before-light-backup-verified.json、logs/agent-display-light-flash.log、logs/agent-display-light-runtime.json。恢复 0.3.0 使用 backups/before-agent_display-20261015-201801.json。

## 多会话分页与状态修复 0.5.0

2026-10-15，保留已验收的浅色阅读布局，增加每页三张内容卡片、20 秒轮播、BOOT 短按翻页后停留 60 秒、按住约 1 秒松开暂停/恢复；长按约 2 秒仍切换静音。有提醒时短按优先确认，新的授权提醒自动定位到对应页并暂停翻页。设备卡片上限仍为四张，分页由 Mac 按连接管理，不持久化导航或额外对话内容。

- 90 项 bridge 测试通过，包括 128 会话的 43 页、页序稳定、独立连接、定时/暂停、提醒优先、旧设备、无额外声音序号和状态修复边界。
- 同一 C 协议、按键、UI、字体和 PCM 代码通过 ASan/UBSan，17 种渲染场景包含第二页、暂停、提醒和离线。按键覆盖去抖、短/中/长按、长按不重复触发和延迟轮询。浏览器已查看第二页模拟图，控制台无错误；预览仅含示例内容。
- 应用 1,589,552 字节，应用分区余量 62%。升级前备份 before-agent_display-20261015-204608.json 共 1,769,472 字节，逐块设备 MD5 和本地 SHA256 通过，另核对旧 0.4.0 应用与 NVS。原始小智 content 恢复备份仍足以覆盖全部新写入范围。
- bootloader、分区表和应用三段写入后哈希校验成功，NVS 未写入。真实设备 fw=0.5.0 已协商分页；没有追加串口复位或手动试音。
- 独立的已认证桌面 WebSocket 测试客户端读到六会话两页，全部可达；自动换页实测 20.01 秒，手动停留 60 秒、暂停协议均正常，声音序号 33→33。这条记录单独不证明物理按键。
- 用户随后确认“自动换页、短按翻页都正常”。重载前，真实设备连接记录到 4 次翻页请求和 17 次自动换页；自动轮播与短按翻页已通过实屏验收。用户再按约 1 秒、等待 20 秒并恢复后，确认“暂停和恢复都正常”，暂停/恢复也通过实屏验收。2 秒静音已有此前实屏验收，本版共享按键逻辑已回归。
- 用户照片中的“可能已中断”源于陈旧 hook 推断；同一会话的较新缓存显示实际仍运行或在等待输入。现在陈旧运行状态改为“状态待更新”，并仅用时间更晚的已知 processing / running_tool / waiting_for_input 校正显示，不能解除真实授权等待或生成提醒。用活动年龄显示代替不可靠的整轮耗时。
- 状态修复加载后，launchd 自动重启且设备在 2.09 秒内重新连接；真实运行会话已显示“运行中”，安静等待输入的会话正确显示“等待输入”。当前显示状态无“可能已中断”。活跃源从六会话增长为七会话时，真实设备自动协商为三页。

证据：logs/agent-display-paging-bridge-tests.log、logs/agent-display-paging-render.log、logs/agent-display-paging-build.log、logs/agent-display-before-paging-backup.log、logs/agent-display-before-paging-backup-verified.json、logs/agent-display-paging-flash.log、logs/agent-display-paging-live-bridge.json、logs/agent-display-paging-runtime.json、logs/agent-display-paging-acceptance.json。恢复 0.4.0 使用 backups/before-agent_display-20261015-204608.json；恢复脚本尚未实际执行。

## 运行会话优先排序

2026-10-15，用户要求正在运行的会话排在前面。此前分页固定连接时的顺序，完成卡片可能挡在后来运行的卡片前面；现在按 waiting、running、done、idle 分组，同组保持稳定，状态变化和新运行会话会及时前移。重排时保留当前页码、暂停和手动停留，待确认等待提醒持续定位到可见页。

93 项桥接测试通过，新增覆盖完成会话恢复运行、新运行会话加入、同组活动不洗牌、手动页码与暂停/停留不受重排影响，以及相同待确认提醒在重排后仍可见。仅更新桥接，未重新烧录、复位 USB 或试音。launchd 重载后真实 fw=0.5.0 设备在 4.59 秒内重连，轮播偏好保留。独立只读 WebSocket 客户端实际读到两页，状态依次为 running、running、idle / idle，完整排序核对通过；测试客户端随后关闭，最终只保留一台真实设备连接。未把协议核对称为新的实屏排序验收。

证据：logs/agent-display-priority-tests.log、logs/agent-display-priority-runtime.json。

## 取消完成提醒时长门槛

2026-10-15，用户要求每次任务完成都提醒一次。done_alert_min_seconds 默认值从 60 改为 0；每轮收到正常完成事件后产生一次柔和提醒，耗时不足一秒或缺少开始时间也可提醒，不伪造未知耗时。保留重复事件去重、23:00–08:00 静音、设备静音和重连首帧不补响；缓存等待输入不被当作完成事件。

96 项桥接测试通过，含短任务连续两轮各提醒一次、重复完成不重响、未知耗时、夜间静音，以及真实本机 webhook 到 WebSocket 的短任务提醒往返。本机配置原先没有显式时长门槛，已核对加载后的有效值为 0，无需修改私密配置文件。仅重载 launchd 桥接，真实 fw=0.5.0 设备在 2.06 秒内重连，翻页偏好保留，声音序号 35→35，未补播历史完成提醒。此次没有重新烧录、复位 USB 或追加实机试音；本次实际听音仍待下一次正常完成事件的用户反馈。

证据：logs/agent-display-every-completion-tests.log、logs/agent-display-every-completion-runtime.json。

## 源码目录整理

2026-10-15，固件源码目录改为 `firmware-status-display/`，Mac 桥接服务目录改为 `mac-bridge/`。文档、构建选择、主机验证脚本、私密头文件生成位置和 LaunchAgent 的 Python 路径已同步更新。

- 新目录下完整构建成功，应用仍为 1,589,552 字节。固件主程序、C 测试和桥接状态模块共 30 个文件与改名前逐字节一致；本轮构建产物没有重新烧录到设备。
- 96 项桥接测试及 ASan/UBSan 下的 17 种渲染场景通过；命令入口和 27 个文档本地链接检查通过。
- 备份脚本默认选择新固件目录，同时保留 `agent_display` 项目标识与 `before-agent_display-*.json` 文件名。临时目录中的模拟备份可被现有恢复脚本接受；设备调用均由测试替身处理，不代表实机恢复验收。
- Python 虚拟环境与可编辑安装中的绝对路径已修正。LaunchAgent 迁移时曾短暂加载失败，恢复服务后完成新路径切换；最终仅一个托管进程监听，真实设备重新连接并报告 0.5.0。已安装的 Claude Code 11、Codex 8、Gemini 7 个观察 handler 保留，配置、状态、日志与中继脚本继续使用原标识。

构建与回归日志见 `logs/directory-rename-firmware-build.log`、`logs/directory-rename-bridge-tests.log` 和 `logs/directory-rename-render-tests.log`。旧构建目录、虚拟环境路径修正前的文件和自启配置备份保存在本机 `.tools/directory-rename-*`，不上传到仓库。
