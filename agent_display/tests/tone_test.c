#include <assert.h>
#include <math.h>
#include <stdlib.h>
#include "tone.h"
int main(void)
{
    size_t count;
    const tone_step_t *urgent = tone_pattern(TONE_URGENT, &count);
    assert(count == 5 && urgent[0].frequency == 880 && urgent[3].frequency == 880);
    assert(urgent[1].frequency == 1175 && urgent[4].frequency == 1175);
    const tone_step_t *soft = tone_pattern(TONE_SOFT, &count);
    assert(count == 2 && soft[0].frequency == 660 && soft[1].frequency == 880);
    assert(soft[0].milliseconds + soft[1].milliseconds == 300);
    assert(tone_kind("none") == TONE_NONE && tone_kind("urgent") == TONE_URGENT);
    const unsigned frequencies[] = {660, 880, 1175};
    int16_t *pcm = calloc(24000 * 2, sizeof(*pcm));
    assert(pcm);
    for (unsigned f = 0; f < 3; f++) {
        tone_pcm(pcm, 24000, frequencies[f], 0, 24000);
        unsigned crossings = 0;
        for (size_t i = 1; i < 24000; i++) {
            assert(pcm[2*i] == pcm[2*i+1] && abs(pcm[2*i]) <= 9000);
            if (pcm[2*i-2] <= 0 && pcm[2*i] > 0) crossings++;
        }
        assert(abs((int)crossings - (int)frequencies[f]) <= 1);
        assert(pcm[0] == 0 && pcm[23999*2] == 0);
    }
    tone_pcm(pcm, 24000, 0, 0, 24000);
    for (size_t i = 0; i < 24000 * 2; i++) assert(pcm[i] == 0);
    free(pcm);
    return 0;
}
