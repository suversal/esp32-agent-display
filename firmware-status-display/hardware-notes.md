# 声音硬件与初始化记录

2026-10-15，固件 0.2.0。

引脚取自固定的 Waveshare 官方提交 eb1f63427d735a22b9c30e22fa63ebddae1834d3，文件 `02_Example/XiaoZhi/XiaoZhiCode_V2.1.0/main/boards/waveshare-s3-rlcd-4.2/config.h`，board_pins.h 留有出处。

| 用途 | GPIO / 参数 |
| --- | --- |
| I2C SDA / SCL | 13 / 14 |
| I2S MCLK / BCLK / WS / DOUT | 16 / 9 / 45 / 8 |
| 喇叭 PA 使能 | 46，正向 |
| ES8311 地址 | 7 位 0x18；codec 接口使用 8 位 0x30 |
| 音频 | 24kHz，16 位，双声道相同 PCM，Philips I2S，MCLK 256 倍 |
| 确认提醒 / 静音 | BOOT，GPIO0 |

采用 [esp_codec_dev 1.5.6](https://components.espressif.com/components/espressif/esp_codec_dev/versions/1.5.6/readme)，参考本地 ESP-IDF 5.5.2 的 `examples/peripherals/i2s/i2s_codec/i2s_es8311/main/i2s_es8311_example.c`。只初始化播放 TX，不启用麦克风或 ES7210。

音量为 65，用户已确认两种音都听到、音量合适。PCM 峰值 9000，首尾各 5ms 淡入淡出；授权音是 880Hz / 1175Hz 各 150ms，两组间隔 80ms；完成音是 660Hz 120ms / 880Hz 180ms。

先探测 codec，初始化失败时显示声音未就绪并记录错误。待播队列最多一条，只保留最新声音；每 10ms 的 PCM 块检查取消标记，静音、ack、授权解除和断线可停止旧声音。

播放前清零 DMA；结束后排空 DMA，再静音和关闭 codec、PA 与 TX。实机发现驱动重开已停用的 TX 时仍先调用 disable，因此重开前先启动保持静音的 TX，再交给 codec 配置。

静音保存在 NVS 的 `firmware-status-display/muted`；保留原 `wifi` 命名空间，不擦除 NVS。
