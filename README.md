# ESP32 AI 编程助手状态屏

把 Claude Code、Codex 等编程助手的运行状态放到桌面小屏上：正在做什么、最近问了什么、回复到哪里，抬头就能看到。任务完成时播放提示音，会话较多时自动翻页，也可以用设备上的 BOOT 键操作。

适用硬件为微雪 **ESP32-S3-RLCD-4.2**（16 MB Flash、8 MB PSRAM），横屏分辨率 400×300。当前使用的自研状态屏固件是 **0.5.0**，Mac 桥接服务负责收集会话信息，通过局域网 WebSocket 发送到设备。

## 测试过哪些固件

这个工作区保留了屏幕测试、语音助手和状态屏的开发过程。本项目的自研固件源码分为 `hello_screen/` 和 `firmware-status-display/` 两个工程。

| 固件 | 用途与测试情况 | 代码或镜像位置 |
| --- | --- | --- |
| AI 编程助手状态屏 0.5.0 | 当前正在使用；显示会话、翻页、按键和声音已实机验证 | [firmware-status-display/](firmware-status-display/)，自研源码 |
| HELLO ESP32 屏幕测试 | 显示文字和每秒递增计数；已实机验证 | [hello_screen/](hello_screen/)，自研源码 |
| 小智 AI 语音助手 v2.4.2 | 此前使用过；配网、唤醒、语音识别、喇叭回答和连续对话已确认 | [官方固件发布页](https://github.com/78/xiaozhi-esp32/releases/tag/v2.4.2)；本机下载目录为 `firmware/xiaozhi-v2.4.2/`，未入库 |
| 微雪官方出厂程序 | 保存为恢复用途，恢复脚本尚未实机执行 | [官方固件目录](https://github.com/waveshareteam/ESP32-S3-RLCD-4.2/tree/eb1f63427d735a22b9c30e22fa63ebddae1834d3/03_Firmware)；本机镜像目录为 `firmware/waveshare-factory/`，未入库 |

状态屏的 0.1.0～0.5.0 是同一个工程的迭代版本，共用 `firmware-status-display/`。各版改了什么、当时测到了哪一步，以及小智与屏幕测试的操作记录，见 [固件测试与恢复记录](docs/firmware-history.md)。本仓库首次提交已是 0.5.0，旧版没有分别保存为源码目录或发布包。

## 当前状态屏怎么用

屏幕采用白底黑字布局，显示仓库与会话标题、运行状态、工具、耗时，以及最近提问和回复片段。内容卡片每页最多三个，只有一两个会话时自动展开；会话较多时每 20 秒轮播，待处理等待和运行中的会话优先显示。

| BOOT 操作 | 效果 |
| --- | --- |
| 短按 | 有提醒时先确认提醒；没有提醒时翻到下一页，并停留 60 秒 |
| 按住约 1 秒后松开 | 暂停或恢复自动轮播 |
| 长按约 2 秒 | 切换声音开关 |

每轮任务收到正常完成事件后提醒一次，短任务也会提醒；重复事件不会重复响。默认夜间静音为 Mac 本地时间 23:00–08:00，设备静音也会拦截提示音。BOOT 确认只清除屏幕提醒，不会批准编程助手的工具操作。

当前助手接入情况：

| 助手 | 已有验证 |
| --- | --- |
| Claude Code | 已收到真实 hooks 事件；完整工具与人工授权链路仍待补验收 |
| Codex | 真实桌面版工具任务的状态与摘要已进入设备显示；当前无法可靠识别人工审批弹窗，因此不触发 Codex 急促授权音 |
| Gemini CLI | 已验证事件样本经 hooks 中继到设备协议的链路；真实 CLI 尚未验收 |

会话标题和对话片段来自本机 Vibe Island 缓存，可在桥接配置中关闭。摘录会遮盖常见凭据并限制长度，保留在内存和设备快照中，不额外写入状态文件或日志。KEY 按键、温湿度、RTC 和电量尚未接入。

## 目录说明

```text
firmware-status-display/  ESP32 状态屏固件源码，当前为 0.5.0
mac-bridge/               Mac 桥接服务、助手 hooks、接入文档与测试
hello_screen/             最初的文字与计数屏幕测试固件
scripts/                  配置生成、构建、备份、烧录与验证工具
vendor/waveshare/         固定版本的微雪官方驱动与示例，Git 子模块
designs/                  状态屏 HTML 设计预览
docs/                     固件测试与恢复记录
```

`mac-bridge/` 在 Mac 上运行，不能烧录到设备。`scripts/`、`designs/` 和 `docs/` 是配套工具与资料；`vendor/` 中的上游示例也不代表本项目已逐一测试。

## 获取源码与准备环境

```sh
git clone --recurse-submodules https://github.com/suversal/esp32-agent-display.git
cd esp32-agent-display
```

已经克隆但没有驱动时，执行 `git submodule update --init --recursive`。

现有脚本按 macOS、Python 3.13 和 ESP-IDF 5.5.2 配置，在项目内保存独立工具环境：

```sh
mkdir -p .tools
git clone --branch v5.5.2 --recursive https://github.com/espressif/esp-idf.git .tools/esp-idf
IDF_TOOLS_PATH="$PWD/.tools/idf-tools" bash .tools/esp-idf/install.sh esp32s3
python3.13 -m venv .tools/serial-venv
.tools/serial-venv/bin/python -m pip install esptool
python3.13 -m venv mac-bridge/.venv
mac-bridge/.venv/bin/python -m pip install -r mac-bridge/bridge/requirements.lock
mac-bridge/.venv/bin/python -m pip install --no-deps -e mac-bridge/bridge
```

### 启动 Mac 桥接服务

Mac 和设备需要处于可以互相访问的局域网，设备使用 2.4 GHz Wi-Fi。从仓库根目录执行：

```sh
cd mac-bridge
.venv/bin/python -m bridge
```

首次启动会生成 `~/.config/agent-display/config.toml` 和随机 token。已经用 launchd 托管服务的机器直接使用现有服务，避免重复启动。助手 hooks 的安装与卸载、会话内容设置和登录自启方式，见 [Mac 桥接服务说明](mac-bridge/README.md)。

### 构建当前状态屏

保持桥接服务运行，另开终端，在仓库根目录生成设备私密配置并构建：

```sh
python3.13 scripts/configure_agent_display.py
IDF_PROJECT=firmware-status-display bash scripts/idf.sh build
```

也可以复制 `firmware-status-display/main/secrets.example.h` 为同目录的 `secrets.h`，填入自己的 Wi-Fi 和桥接配置。空 SSID 表示尝试复用设备上已有的小智 Wi-Fi 配置。私密头文件不会提交到 Git。

构建脚本的默认工程仍为 `hello_screen`，因此构建状态屏时要显式指定 `IDF_PROJECT=firmware-status-display`。只想构建最初的屏幕测试时，使用：

```sh
IDF_PROJECT=hello_screen bash scripts/idf.sh build
```

首次烧录前需要备份设备中将被覆盖的全部区域并核对校验值，再使用对应工程的烧录步骤。状态屏的完整备份、烧录和恢复流程见 [固件说明](firmware-status-display/README.md)；小智与屏幕测试的历史操作见 [测试与恢复记录](docs/firmware-history.md)。Python 路径、串口名称和 launchd 配置中的绝对路径需要按实际机器调整。

## 验证与文件范围

当前代码已通过 96 项桥接测试，以及启用 AddressSanitizer / UndefinedBehaviorSanitizer 的 C 协议、声音、按键测试和 17 种渲染场景。状态屏的横屏显示、联网、自动与手动翻页、暂停/恢复及声音操作有实机记录，具体范围见 [设备端验证记录](firmware-status-display/verification.md)。主机预览和事件样本测试不能代替真实设备、真实助手客户端的验收。

公开仓库保存源码、文档和依赖版本。`.tools/`、虚拟环境、`build/`、私密头文件、下载固件、设备备份和原始日志均已排除；当前没有预编译发布包。历史记录中引用的 `firmware/`、`backups/` 和 `logs/` 文件只在原开发机保存，克隆仓库不会获得这些文件，恢复自己的设备必须使用自己的备份。

## 更多资料

- [状态屏固件、引脚与构建说明](firmware-status-display/README.md)
- [Mac 桥接服务与 hooks](mac-bridge/README.md)
- [固件测试、版本与恢复记录](docs/firmware-history.md)
- [微雪板子专用文档](https://docs.waveshare.net/ESP32-S3-RLCD-4.2/ESP-IDF/)
- [微雪官方代码仓库](https://github.com/waveshareteam/ESP32-S3-RLCD-4.2)
- [微雪小智 AI 教程](https://docs.waveshare.net/ESP32-S3-RLCD-4.2/XiaoZhi_AI/)
- [ESP-IDF 5.5.2 文档](https://docs.espressif.com/projects/esp-idf/zh_CN/v5.5.2/esp32s3/index.html)
