#pragma once
#include "protocol.h"
typedef struct {
    display_snapshot_t snapshot;
    bool wifi_configured, wifi_connected, bridge_connected, has_snapshot;
    bool audio_ready, muted;
    int64_t received_us;
    uint32_t revision;
} display_model_t;
void model_init(void);
void model_read(display_model_t *out);
void model_network(bool configured, bool wifi, bool bridge);
void model_snapshot(const display_snapshot_t *snapshot);
void model_audio(bool ready, bool muted);
