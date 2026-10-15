#include <inttypes.h>
#include <stdio.h>

#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "u8g2_st7305.h"

static const char *TAG = "hello_screen";
static u8g2_st7305_t display;

static void draw_centered(u8g2_t *canvas, int baseline, const char *text)
{
    const int width = u8g2_GetDisplayWidth(canvas);
    const int text_width = u8g2_GetStrWidth(canvas, text);
    u8g2_DrawStr(canvas, (width - text_width) / 2, baseline, text);
}

void app_main(void)
{
    u8g2_st7305_config_t config = u8g2_st7305_default_config();
    config.rotation = U8G2_R1;
    config.tile_buf_height = U8G2_ST7305_TILE_BUF_FULL;
    ESP_ERROR_CHECK(u8g2_st7305_init(&display, &config));

    u8g2_t *canvas = u8g2_st7305_get_u8g2(&display);
    ESP_LOGI(TAG, "DEMO_STARTED display=%ux%u", u8g2_GetDisplayWidth(canvas),
             u8g2_GetDisplayHeight(canvas));

    TickType_t last_wake = xTaskGetTickCount();
    uint32_t counter = 0;
    while (true) {
        char text[32];
        u8g2_ClearBuffer(canvas);
        u8g2_SetDrawColor(canvas, 1);
        u8g2_DrawFrame(canvas, 10, 10, 380, 280);

        u8g2_SetFont(canvas, u8g2_font_helvB24_tf);
        draw_centered(canvas, 65, "HELLO ESP32!");

        u8g2_SetFont(canvas, u8g2_font_logisoso50_tn);
        snprintf(text, sizeof(text), "%" PRIu32, counter);
        draw_centered(canvas, 170, text);

        u8g2_SetFont(canvas, u8g2_font_helvR14_tf);
        draw_centered(canvas, 208, "My first screen program");
        u8g2_DrawHLine(canvas, 25, 234, 350);

        u8g2_SetFont(canvas, u8g2_font_6x13_tf);
        draw_centered(canvas, 260, "Counter updates every second");
        draw_centered(canvas, 278, "ESP32-S3 / 4.2 inch RLCD");

        u8g2_SendBuffer(canvas);
        ESP_LOGI(TAG, "FRAME_OK counter=%" PRIu32 " uptime_ms=%" PRIi64,
                 counter, esp_timer_get_time() / 1000);
        counter++;
        xTaskDelayUntil(&last_wake, pdMS_TO_TICKS(1000));
    }
}
