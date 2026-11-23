/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef HOUJI_DVFS_POLICY_H
#define HOUJI_DVFS_POLICY_H
#include <stdint.h>
/* Interaction headroom for houji's four validated domains. A global touch
 * or render stream must not pin every performance domain at its factory cap:
 * r242 reached the CPU thermal limit while that policy was active. Keep a
 * 60% floor only during touch/render activity on recently busy domains,
 * and release it after 12 quiet samples (240 ms). Without an interaction,
 * use measured load alone: the old unconditional 50% performance-domain
 * floor kept background work at high frequency after all UI hints expired.
 * Stock houji perf profiles distinguish bounded launch/resume and scroll
 * hints; this is the same separation, not a port of Android's WALT/EAS or
 * Xiaomi's PMIC-based skin-temperature policy (see docs/stock-power.md).
 * Actual demand can still select the full factory range.
 * This chooses indices only; board code still validates and votes the LUT. */
static inline unsigned houjiDvfsInteractiveFloor(const uint32_t *khz,unsigned n,
 unsigned busy,bool performance,bool touch,bool frame,unsigned *quiet) {
 if(!n)return 0;
 *quiet=busy<100?(*quiet<12?*quiet+1:12):0;
 bool active=*quiet<12;
 unsigned pct=frame && active?60:0;
 if(performance && active && touch)pct=60;
 unsigned floor=0;while(floor+1<n && (uint64_t)khz[floor]*100<(uint64_t)khz[n-1]*pct)++floor;
 return floor;
}
/* Immediate rise; four genuinely low windows before falling. Holding the
 * current level must not clear the low-window count (ishtar fix 2033). */
static inline unsigned houjiDvfsChoose(const uint32_t *khz,unsigned n,unsigned cur,
 unsigned busy,unsigned floor,unsigned *low) {
 if(!n)return 0;
 if(cur>=n)cur=n-1;if(floor>=n)floor=n-1;if(busy>1000)busy=1000;
 unsigned want=n-1;
 if(busy<900){uint64_t need=(uint64_t)khz[cur]*busy*125/100000;
  want=floor;while(want+1<n && khz[want]<need)++want;}
 if(want>cur){*low=0;return want;}
 if(want==cur){*low=0;return cur;}
 if(++*low<4)return cur;
 *low=0;return want;
}
#endif
