#pragma once
#include "protocol.h"
#include "u8g2.h"
void ui_draw(u8g2_t *canvas, const display_snapshot_t *snapshot, bool configured,
             bool wifi, bool bridge, bool has_snapshot, uint32_t seconds_since,
             bool audio_ready, bool muted);
