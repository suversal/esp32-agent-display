#pragma once
#include <stddef.h>
#include <stdint.h>
#define TONE_SAMPLE_RATE 24000
typedef enum { TONE_NONE, TONE_URGENT, TONE_SOFT } tone_kind_t;
typedef struct { unsigned frequency, milliseconds; } tone_step_t;
tone_kind_t tone_kind(const char *sound);
const char *tone_name(tone_kind_t kind);
const tone_step_t *tone_pattern(tone_kind_t kind, size_t *count);
void tone_pcm(int16_t *stereo, size_t frames, unsigned frequency,
              uint32_t first_frame, uint32_t total_frames);
