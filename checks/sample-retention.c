// SPDX-License-Identifier: MIT
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../kernel/overlay/bsd/dev/HoujiSampleCache.h"
int main(void) {
    struct HoujiSampleCache cache = {0};
    char out[13000], row[4096];
    memset(row, 'x', sizeof(row));
    assert(houjiSampleCopy(&cache, out, sizeof(out)) == 0);
    for (unsigned i = 0; i < 9; ++i) {
        houjiSampleBegin(&cache);
        char id[32];int n = snprintf(id, sizeof(id), "SMP capture=%u\n", i);
        houjiSampleAppend(&cache, id, (unsigned)n);
        houjiSampleAppend(&cache, row, sizeof(row)); // Refuse whole row, retain header.
    }
    unsigned length = houjiSampleCopy(&cache, out, sizeof(out));out[length]=0;
    assert(!strstr(out, "capture=5") && strstr(out, "capture=6") && strstr(out, "capture=7") && strstr(out, "capture=8"));
    assert(strstr(out, "truncated") && !strchr(out,'x'));
    for (unsigned cap = 0; cap < sizeof(out); ++cap) {
        memset(out, 0xa5, sizeof(out));
        unsigned copied = houjiSampleCopy(&cache, out, cap);
        assert(copied <= cap);
        for (unsigned i = copied; i < sizeof(out); ++i) assert((unsigned char)out[i] == 0xa5);
    }
    memset(&cache, 0, sizeof(cache));
    for (unsigned i=0;i<HoujiSampleSlots;++i) {
        houjiSampleBegin(&cache);houjiSampleAppend(&cache,row,sizeof(row));
    }
    assert(houjiSampleCopy(&cache,out,sizeof(out))==HoujiSampleSlots*HoujiSampleBytes);
    puts("PASS: actual retained-stack ring, wrap ordering, whole-row truncation and all output bounds; no process sampling emulation");
}
