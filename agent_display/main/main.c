#include <inttypes.h>
#include "board_pins.h"
#include "audio.h"
#include "button.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "model.h"
#include "net.h"
#include "ui.h"
#include "u8g2_st7305.h"
static u8g2_st7305_t display;
void app_main(void)
{
    model_init();
    u8g2_st7305_config_t config = u8g2_st7305_default_config();
    config.rotation = U8G2_R1;
    config.tile_buf_height = U8G2_ST7305_TILE_BUF_FULL;
    ESP_ERROR_CHECK(u8g2_st7305_init(&display, &config));
    u8g2_t *canvas = u8g2_st7305_get_u8g2(&display);
    ESP_LOGI("agent_display", "DISPLAY_READY width=%u height=%u fw=%s",
             u8g2_GetDisplayWidth(canvas), u8g2_GetDisplayHeight(canvas), FW_VERSION);
    gpio_config_t button = {.pin_bit_mask = 1ULL << ACK_BUTTON_GPIO,
                           .mode = GPIO_MODE_INPUT, .pull_up_en = GPIO_PULLUP_ENABLE};
    ESP_ERROR_CHECK(gpio_config(&button));
    esp_err_t err = audio_start();
    if (err != ESP_OK) ESP_LOGE("agent_display", "AUDIO_START_FAILED code=%d", (int)err);
    err = net_start();
    if (err != ESP_OK) ESP_LOGE("agent_display", "NETWORK_INIT_FAILED code=%d", (int)err);
    uint32_t last_revision = UINT32_MAX;
    int64_t last_draw = -1000000;
    button_state_t button_state = {0};
    while (true) {
        static display_model_t model;
        model_read(&model);
        int64_t now = esp_timer_get_time();
        if (model.revision != last_revision || now - last_draw >= 1000000) {
            uint32_t age = model.has_snapshot ? (now - model.received_us) / 1000000 : 0;
            ui_draw(canvas, &model.snapshot, model.wifi_configured, model.wifi_connected,
                    model.bridge_connected, model.has_snapshot, age, model.audio_ready, model.muted);
            u8g2_SendBuffer(canvas);
            last_revision = model.revision;
            last_draw = now;
        }
        button_action_t action = button_update(&button_state, !gpio_get_level(ACK_BUTTON_GPIO), now);
        if (action == BUTTON_MUTE) audio_toggle_mute();
        else if (action == BUTTON_PAUSE && model.bridge_connected && model.snapshot.paged && model.snapshot.page_count > 1)
            net_page(true);
        else if (action == BUTTON_SHORT) {
            audio_cancel();
            if (model.bridge_connected && model.snapshot.has_alert) net_ack(model.snapshot.alert_id);
            else if (model.bridge_connected && model.snapshot.paged && model.snapshot.page_count > 1) net_page(false);
        }
        vTaskDelay(pdMS_TO_TICKS(25));
    }
}
