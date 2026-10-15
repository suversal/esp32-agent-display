#include "tone.h"
#include <math.h>
#include <string.h>
tone_kind_t tone_kind(const char *s)
{
    if (s && !strcmp(s, "urgent")) return TONE_URGENT;
    if (s && !strcmp(s, "soft")) return TONE_SOFT;
    return TONE_NONE;
}
const char *tone_name(tone_kind_t kind)
{
    return kind == TONE_URGENT ? "urgent" : kind == TONE_SOFT ? "soft" : "none";
}
const tone_step_t *tone_pattern(tone_kind_t kind, size_t *count)
{
    static const tone_step_t urgent[] = {{880, 150}, {1175, 150}, {0, 80}, {880, 150}, {1175, 150}};
    static const tone_step_t soft[] = {{660, 120}, {880, 180}};
    *count = 0;
    if (kind == TONE_URGENT) { *count = 5; return urgent; }
    if (kind == TONE_SOFT) { *count = 2; return soft; }
    return NULL;
}
void tone_pcm(int16_t *stereo, size_t frames, unsigned frequency,
              uint32_t first, uint32_t total)
{
    const uint32_t ramp = TONE_SAMPLE_RATE / 200;
    for (size_t i = 0; i < frames; i++) {
        uint32_t position = first + i;
        int16_t sample = 0;
        if (frequency && position < total) {
            float gain = 1.0f;
            if (position < ramp) gain = (float)position / ramp;
            uint32_t remaining = total - 1 - position;
            if (remaining < ramp && (float)remaining / ramp < gain) gain = (float)remaining / ramp;
            float phase = 6.28318530718f * frequency * (position % TONE_SAMPLE_RATE) / TONE_SAMPLE_RATE;
            sample = (int16_t)(9000.0f * gain * sinf(phase));
        }
        stereo[2 * i] = stereo[2 * i + 1] = sample;
    }
}
