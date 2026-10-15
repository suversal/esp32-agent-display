# 原型通信协议 v2

所有消息为 UTF-8 JSON 文本帧。连接地址为 ws://MAC_HOST:8787/ws?token=CONFIG_TOKEN，token 只存于本地配置和设备配置。

bridge 连接成功后发送完整 snapshot。发生状态变化时再次发送，空闲时每 30 秒发送一次。设备使用 WebSocket ping/pong 检测连接。

设备快照只发送排序后的前四个会话，新增 total_sessions 表示总会话数，用于显示溢出计数。这样会话增多不会让设备下载和解析全部会话。本机 /state 仍返回完整状态；旧快照没有 total_sessions 时，设备以 sessions 数量作为总数。

~~~json
{
  "type": "snapshot",
  "v": 2,
  "server_time": 1800000000,
  "tz_offset": 28800,
  "current_sound_seq": 103,
  "sessions": [
    {
      "key": "claude-code:session",
      "agent": "claude-code",
      "project": "blog",
      "state": "waiting",
      "label": "授权待确认",
      "detail": "执行命令",
      "elapsed": 12,
      "turn_duration_seconds": null,
      "stale": false
    }
  ],
  "alert": {
    "alert_id": "a-example",
    "session_key": "claude-code:session",
    "wait_id": "w-example",
    "kind": "waiting",
    "text": "blog 授权待确认",
    "sound": "urgent",
    "sound_seq": 103,
    "sound_at": 1800000000,
    "created_at": 1800000000,
    "acked": false
  }
}
~~~

sessions 按 waiting、running、done、idle 排序，同组中最近有事件的在前。elapsed 是进入当前状态的秒数；turn_duration_seconds 是整轮耗时，未知时为 null。设备不得将 unknown 当成零耗时。

0.3.0 添加兼容的可选字段：title（会话标题）、user_preview（最近提问摘录）、assistant_preview（最近回复摘录）、current_tool（工具名）、client（来源客户端）。这些字段只用于显示，不进入原生状态持久化。activity_age=true 时 elapsed 表示上次活动至今的秒数，界面显示“多久前”，不作为运行耗时。缺少这些字段时使用旧卡片排版。有标题时新固件显示三张四行卡片，溢出计数按三张计算；传输上限仍为四个会话。

alert 是单条未确认提醒，waiting 优先于 done，同组取最新。没有提醒时为 null。高亮通过 session_key 关联。

声音消费规则：

1. 连接后首帧不播放，以顶层 current_sound_seq 初始化 last_seen_sound_seq，即使 alert 为 null。
2. 后续帧只有在 alert.sound_seq 大于之前的 last_seen_sound_seq 且 sound 不为 none 时才播放。
3. 每次收到快照都将 last_seen_sound_seq 更新为 current_sound_seq；本地静音时也更新。
4. 连接断开后，下一次连接重新走首帧规则。断线期间的声音不补播。

这使被更高优先级提醒遮住的声音不会在用户稍后确认其他提醒时补播。恢复的旧提醒音型为 none。普通快照补发不会让设备重响。

设备发送：

~~~json
{"type": "hello", "fw": "0.1.0"}
{"type": "ack", "alert_id": "a-example"}
{"type": "status", "temp_c": 24.1, "rh": 56}
~~~

ack 只确认提醒，不解除待处理授权，也不会返回任何授权决定。温湿度、电量状态是可选信息。

当前原型的模拟接口只接受标准事件的白名单字段。工具输入只在适配时计算指纹和安全摘要；原始输入不进入状态、日志或设备协议。
