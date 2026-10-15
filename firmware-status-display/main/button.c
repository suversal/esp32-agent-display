#include "button.h"
button_action_t button_update(button_state_t *s, bool down, int64_t now)
{
    if (down) {
        if (!s->down) { s->down = true; s->since = now; s->long_handled = false; }
        if (!s->long_handled && now - s->since >= 2000000) {
            s->long_handled = true;
            return BUTTON_MUTE;
        }
    } else if (s->down) {
        int64_t duration = now - s->since;
        bool handled = s->long_handled;
        s->down = false;
        if (!handled && duration >= 2000000) return BUTTON_MUTE;
        if (!handled && duration >= 700000) return BUTTON_PAUSE;
        if (!handled && duration >= 50000) return BUTTON_SHORT;
    }
    return BUTTON_NONE;
}
