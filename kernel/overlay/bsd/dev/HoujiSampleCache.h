// SPDX-License-Identifier: MIT
// The caller serializes access and supplies memcpy/string declarations.
#ifndef HOUJI_SAMPLE_CACHE_H
#define HOUJI_SAMPLE_CACHE_H
enum { HoujiSampleSlots = 3, HoujiSampleBytes = 4096 };
struct HoujiSampleCache {
    char data[HoujiSampleSlots][HoujiSampleBytes];
    unsigned used[HoujiSampleSlots], dropped[HoujiSampleSlots];
    unsigned next, count;
};
static inline void houjiSampleBegin(struct HoujiSampleCache *cache) {
    unsigned slot = cache->next;
    cache->used[slot] = cache->dropped[slot] = 0;
    cache->next = (slot + 1) % HoujiSampleSlots;
    if (cache->count < HoujiSampleSlots) ++cache->count;
}
static inline void houjiSampleAppend(struct HoujiSampleCache *cache, const char *text, unsigned bytes) {
    if (!cache->count || !text || !bytes) return;
    unsigned slot = (cache->next + HoujiSampleSlots - 1) % HoujiSampleSlots;
    if (bytes > HoujiSampleBytes - cache->used[slot]) {
        cache->dropped[slot] = 1;
        return; // Never store a partial frame-pointer row.
    }
    memcpy(cache->data[slot] + cache->used[slot], text, bytes);
    cache->used[slot] += bytes;
}
static inline unsigned houjiSampleCopy(const struct HoujiSampleCache *cache, char *out, unsigned capacity) {
    static const char truncated[] = "SMP CACHE truncated: later thread rows omitted\n";
    if (!out) return 0;
    unsigned used = 0;
    unsigned first = (cache->next + HoujiSampleSlots - cache->count) % HoujiSampleSlots;
    for (unsigned i = 0; i < cache->count; ++i) {
        unsigned slot = (first + i) % HoujiSampleSlots;
        unsigned need = cache->used[slot] + (cache->dropped[slot] ? sizeof(truncated) - 1 : 0);
        if (need > capacity - used) break;
        memcpy(out + used, cache->data[slot], cache->used[slot]);
        used += cache->used[slot];
        if (cache->dropped[slot]) {
            memcpy(out + used, truncated, sizeof(truncated) - 1);
            used += sizeof(truncated) - 1;
        }
    }
    return used;
}
#endif
