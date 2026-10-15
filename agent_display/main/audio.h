#pragma once
#include <stdbool.h>
#include "esp_err.h"
#include "tone.h"
esp_err_t audio_start(void);
void audio_sync_alert(const char *alert_id);
bool audio_request(tone_kind_t kind, uint64_t sequence, bool manual);
void audio_cancel(void);
esp_err_t audio_toggle_mute(void);
