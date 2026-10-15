#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "tone.h"
#define CARD_LIMIT 4
typedef struct {
    char key[1152], agent[32], project[96], state[16], label[64], detail[160];
    char title[320], user_preview[768], assistant_preview[768], current_tool[128];
    uint32_t elapsed;
    int32_t turn_duration;
    bool stale, activity_age;
} display_card_t;
typedef struct {
    display_card_t cards[CARD_LIMIT];
    size_t card_count, total_sessions;
    bool paged, page_auto, page_waiting;
    uint16_t page_index, page_count, page_hold_seconds;
    int64_t server_time;
    int32_t tz_offset;
    uint64_t current_sound_seq;
    bool has_alert;
    char alert_id[65], alert_key[1152], alert_sound[16];
    uint64_t alert_sound_seq;
} display_snapshot_t;
bool protocol_parse(const char *json, size_t length, display_snapshot_t *out);
bool protocol_consume_sound(const display_snapshot_t *snapshot, bool *first,
                            uint64_t *last_seen);
bool protocol_parse_sound_test(const char *json, size_t length, tone_kind_t *kind, char test_id[65]);
