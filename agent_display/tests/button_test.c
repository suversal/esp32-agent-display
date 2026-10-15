#include <assert.h>
#include "button.h"
int main(void)
{
    button_state_t s = {0};
    assert(button_update(&s, true, 0) == BUTTON_NONE);
    assert(button_update(&s, false, 20000) == BUTTON_NONE); // Contact bounce.
    assert(button_update(&s, true, 100000) == BUTTON_NONE);
    assert(button_update(&s, false, 200000) == BUTTON_SHORT);
    assert(button_update(&s, false, 250000) == BUTTON_NONE); // One release, one action.
    assert(button_update(&s, true, 300000) == BUTTON_NONE);
    assert(button_update(&s, true, 1300000) == BUTTON_NONE); // Pause acts only on release.
    assert(button_update(&s, false, 1400000) == BUTTON_PAUSE);
    assert(button_update(&s, true, 2000000) == BUTTON_NONE);
    assert(button_update(&s, true, 3999999) == BUTTON_NONE);
    assert(button_update(&s, true, 4000000) == BUTTON_MUTE);
    assert(button_update(&s, true, 6000000) == BUTTON_NONE);
    assert(button_update(&s, false, 7000000) == BUTTON_NONE); // Never also ack/page/pause.
    assert(button_update(&s, true, 8000000) == BUTTON_NONE);
    assert(button_update(&s, false, 8100000) == BUTTON_SHORT); // Works after a long hold.
    assert(button_update(&s, true, 9000000) == BUTTON_NONE);
    assert(button_update(&s, false, 11200000) == BUTTON_MUTE); // A delayed poll cannot become a pause.
    return 0;
}
