#include <stdbool.h>
#include <stdatomic.h>
#include <string.h>
#include <stdio.h>
#include <inttypes.h>
#include "audio.h"
#include "board_pins.h"
#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "driver/i2s_std.h"
#include "esp_check.h"
#include "esp_codec_dev.h"
#include "esp_codec_dev_defaults.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "model.h"
#include "nvs.h"
#include "nvs_flash.h"

#define CHUNK_FRAMES 240
#define DMA_BUFFERS 4
static const char *TAG = "agent_audio";
typedef struct { tone_kind_t kind; uint64_t sequence; unsigned generation; bool manual; } sound_request_t;
static QueueHandle_t queue;
static SemaphoreHandle_t control;
static atomic_uint generation;
static atomic_bool muted, ready, failed;
static char selected_alert[65];
static i2c_master_bus_handle_t i2c;
static i2s_chan_handle_t tx;
static esp_codec_dev_handle_t codec;
static const audio_codec_data_if_t *data_if;
static const audio_codec_ctrl_if_t *ctrl_if;
static const audio_codec_gpio_if_t *gpio_if;
static const audio_codec_if_t *codec_if;
static esp_codec_dev_sample_info_t format = {
    .sample_rate = TONE_SAMPLE_RATE, .channel = 2, .channel_mask = 3, .bits_per_sample = 16,
};
static const int16_t silence[CHUNK_FRAMES * 2 * DMA_BUFFERS] = {0};
static void publish(void) { model_audio(atomic_load(&ready), atomic_load(&muted)); }
void audio_cancel(void)
{
    if (!queue || !control) return;
    xSemaphoreTake(control, portMAX_DELAY);
    atomic_fetch_add(&generation, 1);
    xQueueReset(queue);
    xSemaphoreGive(control);
}
void audio_sync_alert(const char *id)
{
    if (!control) return;
    xSemaphoreTake(control, portMAX_DELAY);
    if (strcmp(selected_alert, id ? id : "")) {
        snprintf(selected_alert, sizeof(selected_alert), "%s", id ? id : "");
        atomic_fetch_add(&generation, 1);
        xQueueReset(queue);
    }
    xSemaphoreGive(control);
}
bool audio_request(tone_kind_t kind, uint64_t sequence, bool manual)
{
    if (!queue || kind == TONE_NONE || atomic_load(&failed)) return false;
    xSemaphoreTake(control, portMAX_DELAY);
    if (atomic_load(&muted)) {
        xSemaphoreGive(control);
        ESP_LOGI(TAG, "SOUND_SKIPPED reason=muted seq=%" PRIu64, sequence);
        return false;
    }
    sound_request_t message = {kind, sequence, atomic_fetch_add(&generation, 1) + 1, manual};
    xQueueOverwrite(queue, &message);
    xSemaphoreGive(control);
    return true;
}
esp_err_t audio_toggle_mute(void)
{
    bool value = !atomic_load(&muted);
    atomic_store(&muted, value);
    audio_cancel();
    publish();
    nvs_handle_t handle;
    esp_err_t err = nvs_open("agent_display", NVS_READWRITE, &handle);
    if (err == ESP_OK) {
        err = nvs_set_u8(handle, "muted", value);
        if (err == ESP_OK) err = nvs_commit(handle);
        nvs_close(handle);
    }
    ESP_LOGI(TAG, "AUDIO_MUTE enabled=%u saved=%u", value, err == ESP_OK);
    return err;
}
static esp_err_t hardware_init(void)
{
    i2c_master_bus_config_t bus = {
        .i2c_port = I2C_NUM_0, .sda_io_num = AUDIO_I2C_SDA, .scl_io_num = AUDIO_I2C_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT, .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    ESP_RETURN_ON_ERROR(i2c_new_master_bus(&bus, &i2c), TAG, "I2C init");
    ESP_RETURN_ON_ERROR(i2c_master_probe(i2c, ES8311_CODEC_DEFAULT_ADDR >> 1, 100), TAG, "codec probe");
    i2s_chan_config_t channel = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    channel.auto_clear = true;
    channel.dma_desc_num = DMA_BUFFERS;
    channel.dma_frame_num = CHUNK_FRAMES;
    ESP_RETURN_ON_ERROR(i2s_new_channel(&channel, &tx, NULL), TAG, "I2S channel");
    i2s_std_config_t std = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(TONE_SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {.mclk = AUDIO_I2S_MCLK, .bclk = AUDIO_I2S_BCLK, .ws = AUDIO_I2S_WS,
                     .dout = AUDIO_I2S_DOUT, .din = I2S_GPIO_UNUSED},
    };
    ESP_RETURN_ON_ERROR(i2s_channel_init_std_mode(tx, &std), TAG, "I2S format");
    ESP_RETURN_ON_ERROR(i2s_channel_enable(tx), TAG, "I2S enable");
    audio_codec_i2c_cfg_t ctrl = {.port = I2C_NUM_0, .addr = ES8311_CODEC_DEFAULT_ADDR, .bus_handle = i2c};
    audio_codec_i2s_cfg_t data = {.port = I2S_NUM_0, .tx_handle = tx};
    ctrl_if = audio_codec_new_i2c_ctrl(&ctrl);
    data_if = audio_codec_new_i2s_data(&data);
    gpio_if = audio_codec_new_gpio();
    if (!ctrl_if || !data_if || !gpio_if) return ESP_ERR_NO_MEM;
    es8311_codec_cfg_t chip = {
        .ctrl_if = ctrl_if, .gpio_if = gpio_if, .codec_mode = ESP_CODEC_DEV_WORK_MODE_DAC,
        .pa_pin = AUDIO_PA_GPIO, .pa_reverted = false, .use_mclk = true, .mclk_div = 256,
        .hw_gain = {.pa_voltage = 5.0f, .codec_dac_voltage = 3.3f},
    };
    codec_if = es8311_codec_new(&chip);
    if (!codec_if) return ESP_FAIL;
    esp_codec_dev_cfg_t device = {.dev_type = ESP_CODEC_DEV_TYPE_OUT, .codec_if = codec_if, .data_if = data_if};
    codec = esp_codec_dev_new(&device);
    if (!codec) return ESP_ERR_NO_MEM;
    if (esp_codec_dev_open(codec, &format) != ESP_CODEC_DEV_OK ||
        esp_codec_dev_set_out_vol(codec, 65) != ESP_CODEC_DEV_OK ||
        esp_codec_dev_set_out_mute(codec, true) != ESP_CODEC_DEV_OK ||
        esp_codec_dev_close(codec) != ESP_CODEC_DEV_OK) return ESP_FAIL;
    return ESP_OK;
}
static bool current(const sound_request_t *request)
{
    return request->generation == atomic_load(&generation) && !atomic_load(&muted);
}
static esp_err_t write_pcm(const int16_t *pcm, size_t frames)
{
    size_t sent = 0, bytes = frames * 2 * sizeof(*pcm);
    esp_err_t err = i2s_channel_write(tx, pcm, bytes, &sent, 100);
    return err == ESP_OK && sent != bytes ? ESP_FAIL : err;
}
static esp_err_t play(const sound_request_t *request, bool *completed)
{
    *completed = false;
    if (!current(request)) return ESP_OK;
    // esp_codec_dev 1.5.6 reconfigures by stopping TX before setting its format.
    // close() left TX disabled; start it muted so that reconfiguration is valid.
    esp_err_t err = i2s_channel_enable(tx);
    if (err != ESP_OK) return err;
    if (esp_codec_dev_open(codec, &format) != ESP_CODEC_DEV_OK) {
        i2s_channel_disable(tx);
        esp_codec_dev_close(codec);
        return ESP_FAIL;
    }
    err = i2s_channel_disable(tx);
    size_t loaded = 0;
    if (err == ESP_OK) err = i2s_channel_preload_data(tx, silence, sizeof(silence), &loaded);
    if (err == ESP_OK && loaded != sizeof(silence)) err = ESP_FAIL;
    if (err == ESP_OK) err = i2s_channel_enable(tx);
    if (err == ESP_OK && current(request) &&
        esp_codec_dev_set_out_mute(codec, false) != ESP_CODEC_DEV_OK) err = ESP_FAIL;
    size_t count;
    const tone_step_t *steps = tone_pattern(request->kind, &count);
    int16_t pcm[CHUNK_FRAMES * 2];
    bool cancelled = false;
    for (size_t step = 0; step < count && err == ESP_OK; step++) {
        uint32_t total = steps[step].milliseconds * TONE_SAMPLE_RATE / 1000;
        for (uint32_t offset = 0; offset < total; offset += CHUNK_FRAMES) {
            if (!current(request)) { cancelled = true; break; }
            size_t frames = total - offset < CHUNK_FRAMES ? total - offset : CHUNK_FRAMES;
            tone_pcm(pcm, frames, steps[step].frequency, offset, total);
            err = write_pcm(pcm, frames);
            if (err != ESP_OK) break;
        }
        if (cancelled) break;
    }
    if (err == ESP_OK && !cancelled) {
        memset(pcm, 0, sizeof(pcm));
        err = write_pcm(pcm, CHUNK_FRAMES);
        for (int i = 0; i < DMA_BUFFERS + 2 && err == ESP_OK; i++) {
            if (!current(request)) { cancelled = true; break; }
            vTaskDelay(pdMS_TO_TICKS(10));
        }
        *completed = err == ESP_OK && !cancelled;
    }
    esp_codec_dev_set_out_mute(codec, true);
    if (esp_codec_dev_close(codec) != ESP_CODEC_DEV_OK && err == ESP_OK) err = ESP_FAIL;
    return err;
}
static void audio_task(void *arg)
{
    (void)arg;
    esp_err_t err = hardware_init();
    if (err != ESP_OK) {
        atomic_store(&failed, true);
        audio_cancel();
        if (codec) esp_codec_dev_close(codec);
        gpio_set_level(AUDIO_PA_GPIO, 0);
        publish();
        ESP_LOGE(TAG, "AUDIO_INIT_FAILED code=%d", (int)err);
        vTaskDelete(NULL);
        return;
    }
    atomic_store(&ready, true);
    publish();
    ESP_LOGI(TAG, "AUDIO_READY sample_rate=%d volume=65 muted=%u", TONE_SAMPLE_RATE, atomic_load(&muted));
    sound_request_t request;
    while (true) {
        if (xQueueReceive(queue, &request, portMAX_DELAY) != pdTRUE || !current(&request)) continue;
        ESP_LOGI(TAG, "SOUND_STARTED kind=%s seq=%" PRIu64 " manual=%u",
                 tone_name(request.kind), request.sequence, request.manual);
        bool completed;
        err = play(&request, &completed);
        ESP_LOGI(TAG, "SOUND_RESULT kind=%s completed=%u code=%d seq=%" PRIu64,
                 tone_name(request.kind), completed, (int)err, request.sequence);
        if (err != ESP_OK) {
            atomic_store(&failed, true);
            atomic_store(&ready, false);
            audio_cancel();
            publish();
            ESP_LOGE(TAG, "AUDIO_WRITE_FAILED code=%d", (int)err);
            vTaskDelete(NULL);
        }
    }
}
esp_err_t audio_start(void)
{
    queue = xQueueCreate(1, sizeof(sound_request_t));
    control = xSemaphoreCreateMutex();
    if (!queue || !control) return ESP_ERR_NO_MEM;
    esp_err_t err = nvs_flash_init();
    if (err == ESP_OK) {
        nvs_handle_t handle;
        if (nvs_open("agent_display", NVS_READONLY, &handle) == ESP_OK) {
            uint8_t value = 0;
            if (nvs_get_u8(handle, "muted", &value) == ESP_OK) atomic_store(&muted, value != 0);
            nvs_close(handle);
        }
    }
    publish();
    return xTaskCreate(audio_task, "agent_audio", 6144, NULL, 3, NULL) == pdPASS ? ESP_OK : ESP_ERR_NO_MEM;
}
