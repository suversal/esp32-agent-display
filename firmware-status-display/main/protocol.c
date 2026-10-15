#include "protocol.h"
#include <limits.h>
#include <math.h>
#include <string.h>
#include "cJSON.h"

static const cJSON *field(const cJSON *o, const char *key)
{
    return cJSON_GetObjectItemCaseSensitive(o, key);
}
static bool integer(const cJSON *v, double min, double max)
{
    return cJSON_IsNumber(v) && isfinite(v->valuedouble) &&
           v->valuedouble >= min && v->valuedouble <= max &&
           floor(v->valuedouble) == v->valuedouble;
}
static void string_field(const cJSON *o, const char *key, char *out, size_t capacity)
{
    const cJSON *v = field(o, key);
    if (!cJSON_IsString(v)) return;
    size_t len = strlen(v->valuestring);
    if (len >= capacity) {
        len = capacity - 1;
        while (len && ((unsigned char)v->valuestring[len] & 0xc0) == 0x80) len--;
    }
    memcpy(out, v->valuestring, len);
    out[len] = 0;
}
bool protocol_parse(const char *json, size_t length, display_snapshot_t *out)
{
    if (!json || !out || !length || length > 65536) return false;
    cJSON *root = cJSON_ParseWithLength(json, length);
    if (!root) return false;
    const cJSON *type = field(root, "type"), *version = field(root, "v");
    const cJSON *sessions = field(root, "sessions"), *seq = field(root, "current_sound_seq");
    bool ok = cJSON_IsString(type) && !strcmp(type->valuestring, "snapshot") &&
              integer(version, 2, 2) && cJSON_IsArray(sessions) &&
              integer(seq, 0, 9007199254740991.0);
    if (!ok) goto done;
    memset(out, 0, sizeof(*out));
    out->page_count = 1;
    out->page_auto = true;
    out->current_sound_seq = (uint64_t)seq->valuedouble;
    const cJSON *time = field(root, "server_time"), *tz = field(root, "tz_offset");
    if (integer(time, 1, 4102444800.0)) out->server_time = (int64_t)time->valuedouble;
    if (integer(tz, -86400, 86400)) out->tz_offset = (int32_t)tz->valuedouble;
    out->total_sessions = cJSON_GetArraySize(sessions);
    out->card_count = out->total_sessions < CARD_LIMIT ? out->total_sessions : CARD_LIMIT;
    const cJSON *total = field(root, "total_sessions");
    if (total) {
        if (!integer(total, out->total_sessions, 1024)) {
            ok = false;
            goto done;
        }
        out->total_sessions = (size_t)total->valuedouble;
    }
    const cJSON *page = field(root, "page");
    if (page) {
        const cJSON *index = field(page, "index"), *count = field(page, "count"), *size = field(page, "size");
        const cJSON *auto_page = field(page, "auto"), *waiting = field(page, "waiting"), *hold = field(page, "hold_seconds");
        if (!cJSON_IsObject(page) || !integer(count, 1, 1024) || !integer(index, 0, count->valuedouble - 1) ||
            !integer(size, 3, CARD_LIMIT) || !cJSON_IsBool(auto_page) || !cJSON_IsBool(waiting) ||
            !integer(hold, 0, 3600)) { ok = false; goto done; }
        size_t per_page = (size_t)size->valuedouble;
        size_t expected = (out->total_sessions + per_page - 1) / per_page;
        if (!expected) expected = 1;
        if (count->valuedouble != expected || cJSON_GetArraySize(sessions) > per_page) { ok = false; goto done; }
        out->paged = true;
        out->page_index = (uint16_t)index->valuedouble;
        out->page_count = (uint16_t)count->valuedouble;
        out->page_auto = cJSON_IsTrue(auto_page);
        out->page_waiting = cJSON_IsTrue(waiting);
        out->page_hold_seconds = (uint16_t)hold->valuedouble;
    }
    for (size_t i = 0; i < out->card_count; i++) {
        display_card_t *c = &out->cards[i];
        const cJSON *s = cJSON_GetArrayItem(sessions, i);
        string_field(s, "key", c->key, sizeof(c->key));
        string_field(s, "agent", c->agent, sizeof(c->agent));
        string_field(s, "project", c->project, sizeof(c->project));
        string_field(s, "state", c->state, sizeof(c->state));
        string_field(s, "label", c->label, sizeof(c->label));
        string_field(s, "detail", c->detail, sizeof(c->detail));
        string_field(s, "title", c->title, sizeof(c->title));
        string_field(s, "user_preview", c->user_preview, sizeof(c->user_preview));
        string_field(s, "assistant_preview", c->assistant_preview, sizeof(c->assistant_preview));
        string_field(s, "current_tool", c->current_tool, sizeof(c->current_tool));
        c->activity_age = cJSON_IsTrue(field(s, "activity_age"));
        if (!c->key[0] || (strcmp(c->state, "waiting") && strcmp(c->state, "running") &&
                          strcmp(c->state, "done") && strcmp(c->state, "idle"))) {
            ok = false;
            goto done;
        }
        const cJSON *elapsed = field(s, "elapsed"), *duration = field(s, "turn_duration_seconds");
        if (integer(elapsed, 0, UINT32_MAX)) c->elapsed = (uint32_t)elapsed->valuedouble;
        c->turn_duration = integer(duration, 0, INT32_MAX) ? (int32_t)duration->valuedouble : -1;
        c->stale = cJSON_IsTrue(field(s, "stale"));
    }
    const cJSON *alert = field(root, "alert");
    if (cJSON_IsObject(alert)) {
        string_field(alert, "alert_id", out->alert_id, sizeof(out->alert_id));
        string_field(alert, "session_key", out->alert_key, sizeof(out->alert_key));
        string_field(alert, "sound", out->alert_sound, sizeof(out->alert_sound));
        const cJSON *aseq = field(alert, "sound_seq");
        if (!out->alert_id[0] || !out->alert_key[0] ||
            !integer(aseq, 0, seq->valuedouble)) {
            ok = false;
            goto done;
        }
        out->has_alert = !cJSON_IsTrue(field(alert, "acked"));
        out->alert_sound_seq = (uint64_t)aseq->valuedouble;
    } else if (!cJSON_IsNull(alert)) ok = false;
done:
    cJSON_Delete(root);
    return ok;
}
bool protocol_consume_sound(const display_snapshot_t *s, bool *first, uint64_t *last)
{
    bool play = !*first && s->has_alert && s->alert_sound_seq > *last &&
                (!strcmp(s->alert_sound, "urgent") || !strcmp(s->alert_sound, "soft"));
    *first = false;
    *last = s->current_sound_seq;
    return play;
}
bool protocol_parse_sound_test(const char *json, size_t length, tone_kind_t *kind, char test_id[65])
{
    if (!json || length > 1024) return false;
    cJSON *root = cJSON_ParseWithLength(json, length);
    if (!root) return false;
    const cJSON *type = field(root, "type"), *sound = field(root, "sound"), *id = field(root, "test_id");
    bool ok = cJSON_IsString(type) && !strcmp(type->valuestring, "sound_test") &&
              cJSON_IsString(sound) && cJSON_IsString(id) && id->valuestring[0] &&
              strlen(id->valuestring) <= 64 && tone_kind(sound->valuestring) != TONE_NONE;
    if (ok) {
        *kind = tone_kind(sound->valuestring);
        string_field(root, "test_id", test_id, 65);
    }
    cJSON_Delete(root);
    return ok;
}
