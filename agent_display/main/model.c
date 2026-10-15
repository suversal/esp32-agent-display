#include "model.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
static SemaphoreHandle_t mutex;
static display_model_t model;
void model_init(void)
{
    mutex = xSemaphoreCreateMutex();
    configASSERT(mutex);
}
void model_audio(bool ready, bool muted)
{
    xSemaphoreTake(mutex, portMAX_DELAY);
    if (model.audio_ready != ready || model.muted != muted) model.revision++;
    model.audio_ready = ready;
    model.muted = muted;
    xSemaphoreGive(mutex);
}
void model_read(display_model_t *out)
{
    xSemaphoreTake(mutex, portMAX_DELAY);
    *out = model;
    xSemaphoreGive(mutex);
}
void model_network(bool configured, bool wifi, bool bridge)
{
    xSemaphoreTake(mutex, portMAX_DELAY);
    if (configured != model.wifi_configured || wifi != model.wifi_connected ||
        bridge != model.bridge_connected) model.revision++;
    model.wifi_configured = configured;
    model.wifi_connected = wifi;
    model.bridge_connected = bridge;
    xSemaphoreGive(mutex);
}
void model_snapshot(const display_snapshot_t *snapshot)
{
    xSemaphoreTake(mutex, portMAX_DELAY);
    model.snapshot = *snapshot;
    model.has_snapshot = true;
    model.received_us = esp_timer_get_time();
    model.revision++;
    xSemaphoreGive(mutex);
}
