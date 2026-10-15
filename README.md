# ESP32 屏幕与语音助手

本项目将 AI 编程助手的会话状态、最近提问和回复显示在微雪 ESP32-S3-RLCD-4.2 上，并提供翻页、完成提示音和 BOOT 提醒确认。Mac 上的 Python 桥接服务通过局域网 WebSocket 向设备发送状态；屏幕上的确认只处理提醒，不会批准编程助手的工具操作。

源码包含 `agent_display/` 状态屏固件、`agent-display/` Mac 桥接服务、`hello_screen/` 入门屏幕示例，以及 `scripts/` 构建、备份和烧录工具。Waveshare 官方驱动作为 Git 子模块固定到已验证的版本。

## 获取源码与准备环境

```sh
git clone --recurse-submodules https://github.com/suversal/esp32-agent-display.git
cd esp32-agent-display
```

已经克隆但没有驱动时，执行 `git submodule update --init --recursive`。

现有构建脚本使用项目内的 ESP-IDF 5.5.2 和工具目录。在 macOS 上准备：

```sh
mkdir -p .tools
git clone --branch v5.5.2 --recursive https://github.com/espressif/esp-idf.git .tools/esp-idf
IDF_TOOLS_PATH="$PWD/.tools/idf-tools" bash .tools/esp-idf/install.sh esp32s3
python3.13 -m venv .tools/serial-venv
.tools/serial-venv/bin/python -m pip install esptool
python3.13 -m venv agent-display/.venv
agent-display/.venv/bin/python -m pip install -r agent-display/bridge/requirements.lock
agent-display/.venv/bin/python -m pip install --no-deps -e agent-display/bridge
```

先按 [桥接服务说明](agent-display/README.md) 启动服务并生成本机配置，再按 [固件说明](agent_display/README.md) 生成私密头文件、构建与备份。首次使用也可以复制 `agent_display/main/secrets.example.h` 为同目录的 `secrets.h`，填入自己的网络和桥接配置。Python 路径和串口名称应按实际环境调整；launchd 配置中的绝对路径是原开发机示例，安装前需要修改。

公开仓库只保存源码、文档和依赖版本。工具链、虚拟环境、编译产物、私密头文件、设备闪存备份、下载固件和原始日志均已排除。下文是原开发设备的历史记录，其中提到的 `backups/`、`logs/` 和 `firmware/` 文件仅在原开发机保存，克隆仓库不会获得这些文件；恢复自己的设备必须使用自己的备份。当前未提供预编译发布包。

## 当前设备：AI 编程状态屏

2026-10-15 已切换到独立状态屏固件。设备横屏 400×300，已完成烧录校验、原 WiFi 配置复用、mDNS / WebSocket 连接、中文多会话状态与 BOOT 确认提醒的实机验证。用户确认横屏排版正常。

当前固件为 0.5.0，采用白底黑字布局，仓库与会话标题合并，提问和回复自动换行。横屏三张内容卡片，只有一两个会话时自动展开。超过一屏时每 20 秒自动换页，BOOT 短按翻页后停留 60 秒，按住约 1 秒松开暂停/恢复，长按约 2 秒仍切换静音；有提醒时短按优先确认。用户已确认浅色显示清楚，以及“自动换页、短按翻页都正常”。两种声音、音量、静音和恢复声音此前已由用户实机确认。固件说明见 [agent_display/README.md](agent_display/README.md)，Mac 桥接服务见 [agent-display/README.md](agent-display/README.md)。温湿度、RTC 和电量尚未接入。

Mac 端已追加 Codex 8 和 Gemini 7 个观察 handler，并修复文件摘要及工具事件关联。Codex 桌面版内核完成真实只读工具测试，运行状态与“执行命令”摘要进入设备协议快照；74 项桥接测试通过。Gemini 尚待真实 CLI 验收，桌面旧聊天是否加载新增 hooks 以实际使用反馈为准。详情见 [Codex 接入记录](agent-display/docs/agents/codex.md)。

桥接已配置登录自启与进程退出后的自动重启，维护方式见 [launchd 说明](agent-display/docs/launchd.md)。Codex 自动审核被误判为人工授权的问题已修复，旧误报会定向清理。陈旧运行状态改为“状态待更新”，并由较新的 Vibe Island 运行/等待输入信息校正，不再推断“可能已中断”；真实等待与提醒保留。分页已按状态分组，将运行会话放到已完成、空闲会话之前，待处理等待仍优先，同组顺序保持稳定。当前 96 项桥接测试、17 种 C 渲染场景通过，0.5.0 已完成烧录、重连和自动/短按翻页实屏验收。

内容固件覆盖范围扩大，小智恢复备份更新为 `backups/xiaozhi-before-status-expanded-20261015-content.json`，对应 1,769,472 字节；原始前缀及新增尾部已验证，包含设备原配置，覆盖 0.5.0 全部写入范围。恢复 0.4.0 使用 `backups/before-agent_display-20261015-204608.json`，恢复 0.3.0 使用 `backups/before-agent_display-20261015-201801.json`，恢复 0.2.0 使用 `backups/before-agent_display-20261015-193059.json`。恢复入口为 `scripts/restore_status_backup.py`，实际恢复操作尚未执行。

## 小智 AI 语音助手

使用官方 v2.4.2 的 `waveshare-esp32-s3-rlcd-4.2` 专用固件，已完成下载、发布方 SHA-256 校验以及芯片和闪存配置检查。

此前已烧录完成，设备端哈希校验通过。首次刷写后停在下载模式，经完整重启后，用户已确认配网界面和语音播报正常，并已联网、在小智控制台添加设备。当前设备已替换为上面的状态屏固件。

实机语音验收已完成：用户确认唤醒、语音识别、喇叭回答以及连续对话均正常。验收依据为用户实际操作反馈。

联网后由小智官方服务完成语音识别、AI 回答和语音合成。板子负责收音、播放与显示。配套喇叭接背面的 SPK 接口；不需要 SD 卡。

固件安装状态见 `firmware/xiaozhi-v2.4.2/installation.json`，详细烧录记录见 `logs/xiaozhi-flash.log`。固件写入、配网绑定和实际语音对话是三个独立的验收步骤。

首次使用：

1. 固件启动后，用手机连接设备发出的 `Xiaozhi-xxxxxx` 热点。
2. 如果没有自动弹出配网页面，打开 `http://192.168.4.1`。
3. 选择家中可用的 2.4 GHz Wi-Fi，直接在配网页面输入密码，点击 Connect。
4. 连接互联网后，在 [小智控制面板](https://xiaozhi.me/) 注册或登录，使用设备播报/显示的 6 位验证码添加设备。
5. 说“你好，小智”，随后问一个问题，确认它听懂并通过喇叭回答。

Wi-Fi 密码和设备验证码直接填在对应页面，不写入这份说明。

重新烧录小智固件：

```sh
.tools/serial-venv/bin/python scripts/install_xiaozhi.py
```

若无法自动进入下载模式，先长按 PWR 关机，再保持按住 BOOT、短按 PWR 开机，等待两秒后松开 BOOT。装着电池时，单纯拔插 USB 不一定会重新上电。BOOT 与 KEY 的日常功能由固件定义，进入下载模式则是在重新上电时读取 BOOT。串口名称变化时需要调整安装脚本中的端口。

已手动进入下载模式时执行：

```sh
.tools/serial-venv/bin/python scripts/install_xiaozhi.py --before no-reset
```

恢复官方出厂程序仍使用 `scripts/restore_factory.py`。小智镜像较大，恢复脚本会选用已保存的完整官方出厂镜像，而不使用旧的小范围备份。出厂恢复会清除小智配置，恢复脚本尚未实机执行。

参考：[微雪小智 AI 教程](https://docs.waveshare.net/ESP32-S3-RLCD-4.2/XiaoZhi_AI/) · [本次固件发布](https://github.com/78/xiaozhi-esp32/releases/tag/v2.4.2)

## 保留的第一个屏幕测试程序

适用设备：微雪 ESP32-S3-RLCD-4.2（16 MB Flash、8 MB PSRAM）。

屏幕横向显示 `HELLO ESP32!`，中央计数每秒增加一次。重新开机后从 0 开始。这个示例无需配网或 SD 卡。

## 本次验收

- ESP-IDF v5.5.2 编译成功，应用固件大小 262736 字节。
- 引导程序、分区表和应用均已烧录，设备端校验通过。
- 用户已确认屏幕显示正常，数字持续增加。
- USB 串口暂未捕获到运行输出，当前实机显示验收依据用户确认；未据此声称日志检查通过。
- 烧录前保存了前 384 KiB 原始字节，覆盖本次写入的全部扇区；设备分块校验及本地 SHA-256 校验通过。
- 恢复脚本已准备，尚未执行恢复。

## 文件位置

- `hello_screen/main/main.c`：显示文字与计数的程序。
- `vendor/waveshare`：官方屏幕驱动，固定在提交 `eb1f63427d735a22b9c30e22fa63ebddae1834d3`。
- `.tools`：ESP-IDF v5.5.2、编译器及独立 Python 环境。
- `logs`：编译、备份、烧录和实机运行记录。
- `backups`：首次烧录前保存的原始闪存区域及校验记录。

## 修改和重新烧录

在这个目录中执行：

```sh
bash scripts/idf.sh build
bash scripts/idf.sh -p /dev/cu.usbmodem1101 -b 115200 flash
```

USB 端口名称可能随插拔而变化，重新连接后应先确认设备端口。

查看实机输出：

```sh
.tools/serial-venv/bin/python scripts/capture_serial.py --seconds 15
```

## 恢复出厂程序

```sh
.tools/serial-venv/bin/python scripts/restore_factory.py
```

最初的 384 KiB 备份覆盖计数测试程序的全部改写区域，包含引导程序、分区表和新应用所占区域。它不是整片 16 MB 闪存的镜像，不能单独恢复小智大固件覆盖后的全部出厂内容。当前恢复脚本会选择已保存的完整官方出厂镜像，并先核对长度和 SHA-256。

只在这次示例的改写范围内使用该备份恢复；如果以后烧录其他程序、擦除整片闪存，或修改更多地址，应重新做对应备份。

## 参考资料

- [微雪板子专用文档](https://docs.waveshare.net/ESP32-S3-RLCD-4.2/ESP-IDF/)
- [官方代码仓库](https://github.com/waveshareteam/ESP32-S3-RLCD-4.2)
- [乐鑫 ESP-IDF 文档](https://docs.espressif.com/projects/esp-idf/zh_CN/v5.5.2/esp32s3/index.html)
