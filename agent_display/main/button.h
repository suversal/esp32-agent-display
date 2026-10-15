#pragma once
#include <stdbool.h>
#include <stdint.h>
typedef enum { BUTTON_NONE, BUTTON_SHORT, BUTTON_PAUSE, BUTTON_MUTE } button_action_t;
typedef struct { bool down, long_handled; int64_t since; } button_state_t;
button_action_t button_update(button_state_t *state, bool down, int64_t now_us);
