/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * TSENS v2 format: Linux drivers/thermal/qcom/tsens-v2.c. The step-wise
 * cooling approach also appears in data-a-live/wsl/pandora_cpu.c.
 * Thresholds here are houji policy, not SM8850 sensor addresses/trips.
 */
#ifndef HOUJI_THERMAL_POLICY_H
#define HOUJI_THERMAL_POLICY_H
#include <stdint.h>
struct HoujiThermalPolicy { unsigned cap, cool; bool ready, limited; };
static inline bool houjiTsensDecode(uint32_t raw, int *deciC) {
    if (!deciC || !(raw & (1u << 21))) return false;
    int value = (int)(raw & 0xfff);
    if (value & 0x800) value -= 0x1000;
    if (value < -400 || value > 1500) return false;
    *deciC = value;
    return true;
}
struct HoujiTsensSample { uint32_t raw; unsigned reads; bool timeout; };
/* TSENS drops VALID while updating a sample. MiCode's get_temp_tsens_valid
 * waits for it with a 20 ms bound. Never substitute an old temperature or
 * interpret the temperature bits of an invalid sample. Caller owns the wait.
 */
template<class Read, class Clock, class Pause>
static bool houjiTsensRead(Read read, Clock now, Pause pause, uint64_t deadline,
    int *deciC, HoujiTsensSample *sample) {
    if (!deciC || !sample) return false;
    *sample={};
    for (;;) {
        sample->raw=read();++sample->reads;
        if (sample->raw & (1u<<21)) return houjiTsensDecode(sample->raw,deciC);
        if (now()>=deadline) { sample->timeout=true;return false; }
        pause();
    }
}
/* Called at 100 ms intervals. Invalid/missing sensors immediately select
 * the lowest factory OPP. A cool first valid sample admits the full range.
 * Above the trip remove one OPP per sample; below trip-5 C restore at most
 * one OPP per second. At 110 C use the lowest OPP immediately. */
static inline unsigned houjiThermalChoose(HoujiThermalPolicy *p,
    unsigned levels, bool valid, int deciC, int trip) {
    if (!p || !levels) return 0;
    if (!valid) { p->cap=1; p->cool=0; p->limited=true; return 1; }
    if (!p->ready) {
        p->ready=true;
        if (!p->limited && deciC<trip) p->cap=levels;
    }
    if (!p->cap) p->cap=1;
    if (p->cap>levels) p->cap=levels;
    if (deciC>=1100) { p->cap=1; p->cool=0; }
    else if (deciC>=trip) { if(p->cap>1)--p->cap; p->cool=0; }
    else if (deciC<trip-50) {
        if (++p->cool>=10) { if(p->cap<levels)++p->cap; p->cool=0; }
    } else p->cool=0;
    return p->cap;
}
#endif
