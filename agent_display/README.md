# ESP32 状态屏固件 0.5.0

适用于 Waveshare ESP32-S3-RLCD-4.2，基于 ESP-IDF 5.5.2。独立状态屏固件，升级不写入保存 WiFi 和静音设置的 NVS。

这一版保留已获用户确认的横屏 400×300 白底黑字阅读布局。顶部只留连接、会话数、声音和时钟。仓库与会话标题合并，下一行显示状态、工具和耗时；提问与回复按真实字体宽度换行。三个会话同屏时每张最多四行对话，只有一两个会话时自动展开；没有内容字段时兼容四张紧凑状态卡片。授权提醒使用静态细边框，确认只处理提醒，不批准工具操作。

会话超过一屏时，底部显示页码，默认每 20 秒轮播。BOOT 短按翻下一页，手动翻页后停留 60 秒再轮播；有待确认提醒时，短按优先确认，再按才翻页。按住约 1 秒后松开，暂停或恢复轮播；长按约 2 秒切换静音。新的授权提醒会定位到对应页并停留到提醒被确认。桥接按页发送，设备仍只保留最多四张卡片。会话按待处理等待、运行中、已完成、空闲分组，运行状态变化会调整顺序，同一状态内保持稳定，不因每条工具事件洗牌；手动选择的页码与暂停状态保留。用户已确认“自动换页、短按翻页都正常”，并单独确认“暂停和恢复都正常”。

原生运行事件超过 15 分钟未更新时，显示“状态待更新”，不再推断“可能已中断”。同一会话有更新的 Vibe Island 运行或等待输入信息时，用它校正陈旧的运行状态；真实授权等待、提醒和声音仍由原生事件控制。

标题最长 100 字符，提问与回复片段各最长 240 字符，仍经过凭据遮盖，仅来自已有缓存中的最近内容。截断处显示省略标记，不扫描历史或持久化对话摘录。设备使用 12px 中文字体；主机预览已按实际 ST7305 反相极性校正。可切换的设计预览位于 [状态屏分页版.html](../designs/status-screen-light/状态屏分页版.html)，使用真实固件渲染的示例数据。

声音提醒已接入板载 ES8311 和喇叭，在独立任务中播放。授权提醒是两组急促双音，每轮任务收到正常完成事件后播放一次柔和双音，不设 60 秒时长门槛；重复完成事件不重复响。BOOT 短按确认提醒，长按约 2 秒切换静音，状态保存在 NVS，顶部显示“声音开”或“静音”。KEY 按键、电量、温湿度和 RTC 尚未接入。

首帧不响，普通重发不重响，静音时也消费声音序号，重连与被遮住的旧提醒不补响。确认提醒、授权解除、断线或进入静音时取消旧声音。自动夜间静音仍由 Mac bridge 控制，默认 23:00–08:00。

显式手动试音：

~~~sh
agent-display/.venv/bin/python agent-display/bridge/test_sound.py
~~~

这个本机测试会播放两种声音，即使处于自动夜间静音时段；设备本地静音仍然生效。它不修改静音时段、真实会话或提醒状态，兼容已连接的 0.2.0 / 0.3.0 / 0.4.0 / 0.5.0 设备。

## 构建与烧录

Mac 桥接服务见 [agent-display/README.md](../agent-display/README.md)。Mac 和设备需要处于可以互相访问的局域网。

~~~sh
# 从已有 bridge 配置生成私密头文件，token 和网络地址不会打印。
/opt/homebrew/bin/python3.13 scripts/configure_agent_display.py
# 已有私密头文件时，只有显式 --force 才会覆盖。
IDF_PROJECT=agent_display bash scripts/idf.sh build
/opt/homebrew/bin/python3.13 scripts/check_agent_display.py
.tools/serial-venv/bin/python scripts/backup_project_flash.py --project agent_display
.tools/serial-venv/bin/python scripts/flash_agent_display.py
.tools/serial-venv/bin/python scripts/observe_agent_display.py --reset --seconds 25
agent-display/.venv/bin/python agent-display/bridge/simulate.py
~~~

`IDF_PROJECT` 默认仍为 `hello_screen`。首次烧录必须有足够覆盖范围、SHA256 校验通过的备份。烧录脚本只允许写 bootloader、分区表和 0x20000 的应用。

默认从小智 WiFi 管理器的 NVS `wifi` 命名空间读取 `ssid/password`，找不到时检查编号 1–9 的配置，使用第一个有效配置。WiFi 驱动使用 RAM 存储，NVS 初始化失败时不擦除分区。需要手动配网时，在 `main/secrets.h` 中设置 `WIFI_SSID` 和 `WIFI_PASSWORD` 后重新编译；空 SSID 表示复用小智保存的配置。

桥接服务优先通过 Mac 的 mDNS 主机名定位；失败时使用生成配置时的局域网 IP。Mac IP 改变且 mDNS 不可用时，需要重新生成私密配置并烧录。

BOOT 接 GPIO0，运行中短按确认提醒或翻页，按住约 1 秒后松开暂停/恢复轮播，长按约 2 秒切换静音；一次操作只触发一种动作。暂停状态在同一次设备运行中的桥接重连后保留，断电后恢复默认轮播。上电时按住 BOOT 会进入下载模式。KEY 的 GPIO 尚未验证，因此当前使用 BOOT。

## 回到烧录前的小智

优先恢复此次备份，它保存实际设备配置及所有被本工程覆盖的区域：

~~~sh
.tools/serial-venv/bin/python scripts/restore_status_backup.py backups/xiaozhi-before-status-expanded-20261015-content.json
~~~

0.5.0 升级前备份为 backups/before-agent_display-20261015-204608.json，可恢复原来的 0.4.0 界面；备份逐块核对设备 MD5，并额外核对旧应用与 NVS 的 SHA256。恢复 0.3.0 使用 backups/before-agent_display-20261015-201801.json。

0.3.0 增加中文小字号字体时，应用覆盖范围扩大，因此小智恢复备份更新至 1,769,472 字节；已再次核对它足以覆盖 0.5.0 的全部写入范围：原始前缀核对 SHA256，新增尾部在首次写入前读取并逐块校验；另核对当时设备中 0.2.0 应用的 SHA256，确认其改写范围位于旧恢复前缀内。其余 Flash 区域保留。`backups/before-agent_display-20261015-193059.json` 用于恢复升级前的 0.2.0 状态屏；`backups/before-agent_display-20261015-013656.json` 用于恢复 0.1.0。官方合并镜像重刷脚本仍在 `scripts/install_xiaozhi.py`，但会覆盖配置。恢复脚本尚待真实恢复测试。

私密文件 `main/secrets.h`、`build/`、`backups/` 和原始串口日志包含设备或本机配置，勿公开分享。

## 验证边界

`check_agent_display.py` 用设备同一份协议、PCM 生成、按键、UI 代码和字体测试，并开启 AddressSanitizer / UndefinedBehaviorSanitizer。它验证内容字段、首帧静默、去重、被遮住提醒不补响、重连基线、未知耗时、中文，以及 660/880/1175Hz 的实际波形、幅度、淡入淡出和左右声道一致。另外覆盖 17 种 UI 场景，检查浅色像素占比、四行对话、UTF-8 换行、边界、计时、页码、暂停、提醒和离线；按键覆盖去抖、短按、约 1 秒与 2 秒操作不重复触发。bridge 回归测试已通过 96 项。

预览不证明物理屏幕方向、对比度或按键。编译、Flash 校验、真实联网、实际屏幕和真实助手事件分别记录；Codex/Gemini 模拟状态不代表它们的真实 hook 已验收。

本次实际结果见 [verification.md](verification.md)。当前 bridge 已由 launchd 托管，查看和重启方式见 [launchd 说明](../agent-display/docs/launchd.md)。旧的 check_device_reconnect.py 面向非托管进程，不用于当前服务。

## 引脚与组件来源

- 显示驱动与引脚采用本地 Waveshare 官方示例 `11_U8G2_Test/components/u8g2_st7305`：MOSI12、SCLK11、DC5、CS40、RST41，SPI3；`U8G2_R1` 的逻辑分辨率为 400×300，与已验证的 hello_screen 一致。
- [Waveshare 官方设备文档](https://docs.waveshare.net/ESP32-S3-RLCD-4.2/)。
- [Espressif WebSocket client 1.8.0](https://components.espressif.com/components/espressif/esp_websocket_client/versions/1.8.0/readme)，接收缓冲与连续帧都重组后解析，最多 64KiB；回调内不 stop/destroy。
- [Espressif mDNS 1.14.0](https://components.espressif.com/components/espressif/mdns/versions/1.14.0/readme)。
- [Espressif esp_codec_dev 1.5.6](https://components.espressif.com/components/espressif/esp_codec_dev/versions/1.5.6/readme)。音频引脚和初始化方式见 [hardware-notes.md](hardware-notes.md)。
- [小智 v2.4.2 组件声明](https://raw.githubusercontent.com/78/xiaozhi-esp32/v2.4.2/main/idf_component.yml)及 [WiFi 管理组件](https://components.espressif.com/components/78/esp-wifi-connect/versions/3.3.1/readme)。
