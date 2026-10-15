#include "ui.h"
#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

// The board driver enables ST7305 inversion (0x21): a set bit is light on
// the physical panel. Keep preview polarity and these semantic colors aligned.
#define PAPER 1
#define INK 0
#define LINE_HEIGHT 13
#define BODY_X 30

static size_t codepoint_bytes(const char *text)
{
    unsigned char c = (unsigned char)*text;
    size_t n = c < 0x80 ? 1 : (c & 0xe0) == 0xc0 ? 2 : (c & 0xf0) == 0xe0 ? 3 : (c & 0xf8) == 0xf0 ? 4 : 1;
    for (size_t i = 1; i < n; i++) if (!text[i] || ((unsigned char)text[i] & 0xc0) != 0x80) return 1;
    return n;
}

static void fit(u8g2_t *u, int x, int y, int width, const char *text)
{
    if (width <= 0 || !text[0]) return;
    char copy[512];
    size_t n = strlen(text);
    bool clipped = n >= sizeof(copy);
    if (clipped) {
        n = sizeof(copy) - 1;
        while (n && ((unsigned char)text[n] & 0xc0) == 0x80) n--;
    }
    memcpy(copy, text, n);
    copy[n] = 0;
    while (n && u8g2_GetUTF8Width(u, copy) + (clipped ? 12 : 0) > width) {
        do { n--; } while (n && ((unsigned char)copy[n] & 0xc0) == 0x80);
        copy[n] = 0;
        clipped = true;
    }
    u8g2_DrawUTF8(u, x, y, copy);
    if (clipped && width >= 12) u8g2_DrawStr(u, x + u8g2_GetUTF8Width(u, copy), y, "..");
}

// Measure with the actual device font, preserve UTF-8 boundaries, and prefer
// a nearby Latin word boundary. The returned pointer always makes progress.
static const char *next_line(u8g2_t *u, const char *text, int width, char line[256])
{
    size_t n = 0, space = 0;
    while (text[n] && text[n] != '\n') {
        size_t bytes = codepoint_bytes(text + n);
        if (n + bytes >= 256) break;
        memcpy(line + n, text + n, bytes);
        line[n + bytes] = 0;
        if (u8g2_GetUTF8Width(u, line) > width) break;
        if (text[n] == ' ') space = n;
        n += bytes;
    }
    if (text[n] && text[n] != '\n' && space && space > n / 2) n = space;
    if (!n && text[0] && text[0] != '\n') n = codepoint_bytes(text);
    memcpy(line, text, n);
    line[n] = 0;
    const char *rest = text + n;
    while (*rest == ' ' || *rest == '\n' || *rest == '\r') rest++;
    return rest;
}

static int wrapped(u8g2_t *u, int x, int y, int width, int rows, const char *text, bool draw)
{
    int used = 0;
    while (*text && used < rows) {
        char line[256];
        const char *rest = next_line(u, text, width, line);
        if (draw) {
            if (used == rows - 1 && *rest) {
                // Force a visible truncation mark even when this line fit exactly.
                size_t n = strlen(line);
                if (n > sizeof(line) - 4) n = sizeof(line) - 4;
                while (n && ((unsigned char)line[n] & 0xc0) == 0x80) n--;
                memcpy(line + n, "...", 4);
            }
            fit(u, x, y + used * LINE_HEIGHT, width, line);
        }
        used++;
        text = rest;
    }
    return used;
}

static void duration(char *out, size_t size, uint32_t sec)
{
    if (sec >= 3600) snprintf(out, size, "%" PRIu32 "h%02" PRIu32 "m", sec / 3600, sec / 60 % 60);
    else snprintf(out, size, "%" PRIu32 "m%02" PRIu32 "s", sec / 60, sec % 60);
}

static void elapsed_text(const display_card_t *c, uint32_t age, char out[64])
{
    uint64_t seconds = (uint64_t)c->elapsed + age;
    if (c->activity_age) {
        if (seconds < 60) strcpy(out, "刚刚更新");
        else if (seconds < 3600) snprintf(out, 64, "%llu分钟前", (unsigned long long)(seconds / 60));
        else snprintf(out, 64, "%llu小时前", (unsigned long long)(seconds / 3600));
    } else if (!strcmp(c->state, "done")) {
        if (c->turn_duration >= 0) {
            char time[32];
            duration(time, sizeof(time), c->turn_duration);
            snprintf(out, 64, "耗时 %s", time);
        } else strcpy(out, "耗时未知");
    } else duration(out, 64, seconds > UINT32_MAX ? UINT32_MAX : seconds);
}

static void clock_text(const display_snapshot_t *s, uint32_t age, char clock[8], char date[40])
{
    strcpy(clock, "--:--");
    strcpy(date, "等待时间同步");
    if (!s->server_time) return;
    time_t now = (time_t)(s->server_time + s->tz_offset + age);
    struct tm tm;
    gmtime_r(&now, &tm);
    strftime(clock, 8, "%H:%M", &tm);
    strftime(date, 40, "%Y-%m-%d", &tm);
}

static void card(u8g2_t *u, const display_card_t *c, int width, int y, int height,
                 bool alert, uint32_t age)
{
    const char *tag = !strcmp(c->agent, "claude-code") ? "CC" :
                      !strcmp(c->agent, "codex") ? "CX" :
                      !strcmp(c->agent, "gemini") ? "GM" : "AI";
    bool waiting = !strcmp(c->state, "waiting");
    u8g2_SetDrawColor(u, INK);
    // A small agent tab and a thin rule replace filled/reversed cards.
    u8g2_DrawBox(u, 7, y + 1, 22, 14);
    u8g2_SetDrawColor(u, PAPER);
    u8g2_SetFont(u, u8g2_font_6x10_tf);
    u8g2_DrawStr(u, 12, y + 12, tag);
    u8g2_SetDrawColor(u, INK);
    u8g2_SetFont(u, u8g2_font_wqy12_t_gb2312);
    if (c->title[0] && strcmp(c->title, c->project)) {
        int project_width = u8g2_GetUTF8Width(u, c->project);
        if (project_width > width / 3) project_width = width / 3;
        fit(u, 36, y + 13, project_width, c->project);
        u8g2_DrawStr(u, 42 + project_width, y + 13, "/");
        fit(u, 55 + project_width, y + 13, width - project_width - 65, c->title);
    } else fit(u, 36, y + 13, width - 46, c->project);

    char elapsed[64], label[96], tool[320];
    elapsed_text(c, age, elapsed);
    int elapsed_width = u8g2_GetUTF8Width(u, elapsed);
    int elapsed_x = width - 8 - elapsed_width;
    snprintf(label, sizeof(label), "%s%s%s", waiting ? "! " : "",
             c->label[0] ? c->label : c->state, c->stale ? " ?" : "");
    int label_width = u8g2_GetUTF8Width(u, label);
    if (label_width > 100) label_width = 100;
    fit(u, 9, y + 27, label_width, label);
    if ((c->current_tool[0] || c->detail[0]) &&
        (c->user_preview[0] || c->assistant_preview[0]) && (!strcmp(c->state, "running") || waiting)) {
        snprintf(tool, sizeof(tool), "%s%s%s", c->current_tool,
                 c->current_tool[0] && c->detail[0] ? " / " : "", c->detail);
        int tx = 19 + label_width;
        u8g2_DrawVLine(u, tx - 5, y + 18, 9);
        fit(u, tx, y + 27, elapsed_x - tx - 10, tool);
    }
    fit(u, elapsed_x, y + 27, elapsed_width, elapsed);

    int rows = (height - 32) / LINE_HEIGHT;
    int text_width = width - BODY_X - 9;
    int body_y = y + 40;
    const char *question = c->user_preview;
    const char *answer = c->assistant_preview;
    if (!answer[0] && !question[0]) answer = c->detail[0] ? c->detail : "暂未收到对话内容";
    int question_need = wrapped(u, BODY_X, body_y, text_width, rows, question, false);
    int answer_need = wrapped(u, BODY_X, body_y, text_width, rows, answer, false);
    int question_rows = rows - (answer_need < rows / 2 ? answer_need : rows / 2);
    if (question_rows > question_need) question_rows = question_need;
    if (question_rows) {
        u8g2_DrawUTF8(u, 9, body_y, "你");
        wrapped(u, BODY_X, body_y, text_width, question_rows, question, true);
    }
    if (answer_need && rows > question_rows) {
        int answer_y = body_y + question_rows * LINE_HEIGHT;
        u8g2_DrawUTF8(u, 9, answer_y, c->assistant_preview[0] ? "答" : "·");
        wrapped(u, BODY_X, answer_y, text_width, rows - question_rows, answer, true);
    } else if (!answer[0] && question_rows < rows) {
        fit(u, BODY_X, body_y + question_rows * LINE_HEIGHT, text_width, "等待助手回复");
    }
    if (alert) {
        // Static, compact highlight: no blinking or large black background.
        u8g2_DrawFrame(u, 3, y - 1, width - 6, height);
        u8g2_DrawFrame(u, 4, y, width - 8, height - 2);
    }
    u8g2_DrawHLine(u, 8, y + height + 1, width - 16);
}

void ui_draw(u8g2_t *u, const display_snapshot_t *s, bool configured,
             bool wifi, bool bridge, bool has_snapshot, uint32_t age, bool audio_ready, bool muted)
{
    int width = u8g2_GetDisplayWidth(u), height = u8g2_GetDisplayHeight(u);
    char clock[8], date[40], text[96];
    clock_text(s, age, clock, date);
    u8g2_ClearBuffer(u);
    u8g2_SetDrawColor(u, PAPER);
    u8g2_DrawBox(u, 0, 0, width, height);
    u8g2_SetDrawColor(u, INK);
    u8g2_SetFontMode(u, 1);
    u8g2_SetFont(u, u8g2_font_wqy12_t_gb2312);
    u8g2_DrawDisc(u, 9, 9, 2, U8G2_DRAW_ALL);
    u8g2_DrawUTF8(u, 17, 14, bridge ? "已连接" : wifi ? "连接中" : "离线");
    if (has_snapshot) {
        snprintf(text, sizeof(text), "%u个会话", (unsigned)s->total_sessions);
        u8g2_DrawUTF8(u, 70, 14, text);
    }
    const char *sound = muted ? "静音" : audio_ready ? "声音开" : "声音准备中";
    int sound_width = u8g2_GetUTF8Width(u, sound);
    u8g2_DrawUTF8(u, width - 52 - sound_width, 14, sound);
    u8g2_DrawStr(u, width - 39, 14, clock);
    u8g2_DrawHLine(u, 8, 19, width - 16);

    size_t visible = 0;
    if (has_snapshot && s->card_count) {
        bool rich = false;
        for (size_t i = 0; i < s->card_count; i++)
            if (s->cards[i].title[0] || s->cards[i].user_preview[0] || s->cards[i].assistant_preview[0]) rich = true;
        size_t limit = rich ? 3 : CARD_LIMIT;
        visible = s->card_count < limit ? s->card_count : limit;
        int stride = (height - 38) / (int)visible;
        for (size_t i = 0; i < visible; i++)
            card(u, &s->cards[i], width, 24 + i * stride, stride - 2,
                 s->has_alert && !strcmp(s->cards[i].key, s->alert_key), age);
    } else {
        u8g2_SetFont(u, u8g2_font_logisoso50_tn);
        u8g2_DrawStr(u, (width - u8g2_GetStrWidth(u, clock)) / 2, height / 2 - 5, clock);
        u8g2_SetFont(u, u8g2_font_wqy12_t_gb2312);
        u8g2_DrawUTF8(u, (width - u8g2_GetUTF8Width(u, date)) / 2, height / 2 + 22, date);
        const char *message = bridge ? "等待新的编程会话" : "正在连接状态服务";
        u8g2_SetFont(u, u8g2_font_wqy16_t_gb2312);
        u8g2_DrawUTF8(u, (width - u8g2_GetUTF8Width(u, message)) / 2, height / 2 + 56, message);
    }
    u8g2_SetFont(u, u8g2_font_wqy12_t_gb2312);
    const char *footer = !configured ? "未找到 WiFi 配置" : !wifi ? "WiFi 重连中 · 显示上次状态" :
                         !bridge ? "服务重连中 · 显示上次状态" :
                         s->has_alert ? "短按 BOOT 确认提醒" : "长按 BOOT 切换声音";
    char count[80] = "";
    if (s->paged && s->page_count > 1) {
        uint32_t hold = age < s->page_hold_seconds ? s->page_hold_seconds - age : 0;
        char mode[48];
        if (!bridge) strcpy(mode, "离线");
        else if (s->page_waiting) strcpy(mode, "待确认");
        else if (!s->page_auto) strcpy(mode, "已暂停");
        else if (hold) snprintf(mode, sizeof(mode), "停留%lus", (unsigned long)hold);
        else strcpy(mode, "自动");
        snprintf(count, sizeof(count), "%u/%u页 %s", (unsigned)s->page_index + 1, (unsigned)s->page_count, mode);
        if (configured && wifi && bridge && !s->has_alert)
            footer = s->page_auto ? "BOOT短按翻页 · 1秒暂停" : "BOOT短按翻页 · 1秒轮播";
    } else if (visible && s->total_sessions > visible)
        snprintf(count, sizeof(count), "还有%u个会话", (unsigned)(s->total_sessions - visible));
    int count_width = u8g2_GetUTF8Width(u, count);
    fit(u, 8, height - 4, width - 24 - count_width, footer);
    u8g2_DrawUTF8(u, width - 8 - count_width, height - 4, count);
}
