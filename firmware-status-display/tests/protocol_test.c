#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "protocol.h"
int main(void)
{
    display_snapshot_t s;
    const char *json = "{\"type\":\"snapshot\",\"v\":2,\"current_sound_seq\":103,\"sessions\":[],\"alert\":null}";
    assert(protocol_parse(json, strlen(json), &s));
    bool first = true;
    uint64_t last = 0;
    assert(!protocol_consume_sound(&s, &first, &last) && last == 103);
    s.has_alert = true;
    strcpy(s.alert_sound, "urgent");
    s.alert_sound_seq = 102;
    assert(!protocol_consume_sound(&s, &first, &last)); // Hidden older alert cannot replay.
    s.alert_sound_seq = s.current_sound_seq = 104;
    assert(protocol_consume_sound(&s, &first, &last));
    assert(!protocol_consume_sound(&s, &first, &last)); // Retransmission remains silent.
    first = true;
    s.alert_sound_seq = s.current_sound_seq = 106;
    assert(!protocol_consume_sound(&s, &first, &last)); // Reconnect establishes a new baseline.
    const char *bad = "{\"type\":\"snapshot\",\"v\":2,\"current_sound_seq\":1.5,\"sessions\":[],\"alert\":null}";
    assert(!protocol_parse(bad, strlen(bad), &s));
    const char *unknown = "{\"type\":\"snapshot\",\"v\":2,\"current_sound_seq\":0,\"sessions\":[{\"key\":\"test\",\"state\":\"done\",\"project\":\"中文项目\",\"turn_duration_seconds\":null}],\"alert\":null}";
    assert(protocol_parse(unknown, strlen(unknown), &s));
    assert(s.cards[0].turn_duration == -1);
    assert(!strcmp(s.cards[0].project, "中文项目"));
    const char *bounded = "{\"type\":\"snapshot\",\"v\":2,\"current_sound_seq\":0,\"sessions\":[{\"key\":\"test\",\"state\":\"idle\"}],\"total_sessions\":128,\"alert\":null}";
    assert(protocol_parse(bounded, strlen(bounded), &s));
    assert(s.card_count == 1 && s.total_sessions == 128);
    const char *paged = "{\"type\":\"snapshot\",\"v\":2,\"current_sound_seq\":0,\"sessions\":[{\"key\":\"tail\",\"state\":\"idle\"}],\"total_sessions\":7,\"page\":{\"index\":2,\"count\":3,\"size\":3,\"auto\":false,\"waiting\":false,\"hold_seconds\":60},\"alert\":null}";
    assert(protocol_parse(paged, strlen(paged), &s));
    assert(s.paged && s.page_index == 2 && s.page_count == 3 && !s.page_auto && s.page_hold_seconds == 60);
    char invalid_page[1024];
    strcpy(invalid_page, paged);
    char *index = strstr(invalid_page, "\"index\":2");
    index[strlen("\"index\":")] = '3';
    assert(!protocol_parse(invalid_page, strlen(invalid_page), &s));
    assert(protocol_parse(bounded, strlen(bounded), &s));
    assert(!s.paged && s.page_count == 1); // A reconnect to an older bridge is safe.
    const char *rich = "{\"type\":\"snapshot\",\"v\":2,\"current_sound_seq\":0,\"sessions\":[{\"key\":\"cx\",\"state\":\"running\",\"title\":\"检查屏幕功能\",\"user_preview\":\"显示会话内容\",\"assistant_preview\":\"正在检查\",\"current_tool\":\"Bash\",\"activity_age\":true}],\"alert\":null}";
    assert(protocol_parse(rich, strlen(rich), &s));
    assert(!strcmp(s.cards[0].title, "检查屏幕功能"));
    assert(!strcmp(s.cards[0].user_preview, "显示会话内容"));
    assert(!strcmp(s.cards[0].assistant_preview, "正在检查"));
    assert(!strcmp(s.cards[0].current_tool, "Bash") && s.cards[0].activity_age);
    char dialogue[721] = {0}, long_json[2048];
    for (int i = 0; i < 240; i++) memcpy(dialogue + i * 3, "中", 3);
    snprintf(long_json, sizeof(long_json), "{\"type\":\"snapshot\",\"v\":2,\"current_sound_seq\":0,\"sessions\":[{\"key\":\"long\",\"state\":\"running\",\"user_preview\":\"%s\",\"assistant_preview\":\"%s\"}],\"alert\":null}", dialogue, dialogue);
    assert(protocol_parse(long_json, strlen(long_json), &s));
    assert(!strcmp(s.cards[0].user_preview, dialogue));
    assert(!strcmp(s.cards[0].assistant_preview, dialogue));
    const char *bad_count = "{\"type\":\"snapshot\",\"v\":2,\"current_sound_seq\":0,\"sessions\":[{\"key\":\"test\",\"state\":\"idle\"}],\"total_sessions\":0,\"alert\":null}";
    assert(!protocol_parse(bad_count, strlen(bad_count), &s));
    tone_kind_t kind;
    char test_id[65];
    const char *test = "{\"type\":\"sound_test\",\"sound\":\"soft\",\"test_id\":\"manual-test\"}";
    assert(protocol_parse_sound_test(test, strlen(test), &kind, test_id));
    assert(kind == TONE_SOFT && !strcmp(test_id, "manual-test"));
    assert(!protocol_parse_sound_test(json, strlen(json), &kind, test_id));
    test = "{\"type\":\"sound_test\",\"sound\":\"bad\",\"test_id\":\"manual-test\"}";
    assert(!protocol_parse_sound_test(test, strlen(test), &kind, test_id));
    return 0;
}
