// Host preview uses the same u8g2 buffer, fonts, rotation, and ui.c as the device.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ui.h"
static const u8x8_display_info_t info = {
    .tile_width = 38, .tile_height = 50, .pixel_width = 300, .pixel_height = 400,
};
static uint8_t callback(u8x8_t *u, uint8_t msg, uint8_t arg, void *data)
{
    (void)arg; (void)data;
    if (msg == U8X8_MSG_DISPLAY_SETUP_MEMORY) u8x8_d_helper_display_setup_memory(u, &info);
    return 1;
}
int main(int argc, char **argv)
{
    if (argc < 3 || argc > 5) return 2;
    FILE *input = fopen(argv[1], "rb");
    if (!input) return 2;
    char json[65537];
    size_t length = fread(json, 1, 65536, input);
    fclose(input);
    display_snapshot_t s;
    if (!protocol_parse(json, length, &s)) return 3;
    u8g2_t u;
    uint8_t buffer[38 * 50 * 8] = {0};
    u8g2_SetupDisplay(&u, callback, u8x8_cad_empty, callback, callback);
    u8g2_SetupBuffer(&u, buffer, 50, u8g2_ll_hvline_vertical_top_lsb, U8G2_R1);
    uint32_t age = argc >= 4 ? (uint32_t)strtoul(argv[3], NULL, 10) : 0;
    bool offline = argc >= 5 && !strcmp(argv[4], "offline");
    bool muted = argc >= 5 && !strcmp(argv[4], "muted");
    ui_draw(&u, &s, true, !offline, !offline, true, age, true, muted);
    FILE *output = fopen(argv[2], "wb");
    if (!output) return 2;
    fprintf(output, "P5\n400 300\n255\n");
    for (int y = 0; y < 300; y++) for (int x = 0; x < 400; x++) {
        // u8g2 R1 maps logical (x,y) to the physical buffer (299-y,x).
        int px = 299 - y, py = x;
        // ST7305 0x21 polarity, matching the user's physical panel.
        uint8_t pixel = (buffer[py / 8 * 304 + px] >> (py % 8)) & 1 ? 255 : 0;
        fwrite(&pixel, 1, 1, output);
    }
    fclose(output);
    return 0;
}
