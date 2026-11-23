/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef HOUJI_GPU_GOVERNOR_POLICY_H
#define HOUJI_GPU_GOVERNOR_POLICY_H
#include "HoujiGpuFactoryOpp.h"
struct HoujiGpuGovernorPolicy {unsigned filtered,ready,low,quiet,reason;};
// A new contact burst can prewarm an idle GPU before its first command.
// Consume each burst once, including while already active; never renew a
// deadline from repeated polls or accept stale/future input timestamps.
static inline bool houjiGpuArmTouchWake(uint64_t now,uint64_t burst,bool idle,
 uint64_t *seen,uint64_t *until) {
 if(!seen || !until || !burst || burst>now || burst<=*seen)return false;
 *seen=burst;
 if(!idle || now-burst>=50000 || burst>UINT64_MAX-50000)return false;
 *until=burst+50000;return true;
}
/* Policy only: no clocks, voltages, hardware access or scheduler calls here.
 * About 55% utilisation leaves room for the next interactive frame. Rising
 * load acts immediately; four low samples precede a fall of at most two OPPs.
 * The caller updates its current level only after the HFI ACK succeeds. */
static inline unsigned houjiGpuChoose(struct HoujiGpuGovernorPolicy *p,
 unsigned cur,unsigned cap,unsigned busy,unsigned active,unsigned touch,
 unsigned wake,unsigned queued) {
 if(!p || !hco_opp(cur) || !cap || cap>HCO_COUNT)return 0;
 if(busy>1000)busy=1000;
 if(!p->ready){p->ready=1;p->filtered=busy;}
 else p->filtered=(p->filtered*3+busy)/4;
 if(cur>cap){p->low=0;p->reason=6;return cap;}
 // A new frame after idle must not wait for the EWMA to catch up. Keep the
 // filtered value for the falling edge, but react to rising load this window.
 unsigned load=busy>p->filtered?busy:p->filtered;
 uint64_t need=(uint64_t)hco_opp(cur)->khz*load/550;
 if(busy>=900 && need<(uint64_t)hco_opp(cur)->khz*3/2)
  need=(uint64_t)hco_opp(cur)->khz*3/2;
 if(queued>=2 && busy>=500)need=need*5/4;
 unsigned want=hco_at_least(need,cap),floor=1;p->reason=1;
 // A touch is latency headroom, not proof of a saturated GPU. r242 spent
 // over half its sampled time requesting the top OPP with this floor=cap.
 // Keep the floor proportional to the allowed factory range while active;
 // measured demand and the existing wake path can still request the cap.
 if(touch && (active || queued)){
  floor=hco_at_least((uint64_t)hco_opp(cap)->khz*3/5,cap);p->reason=2;
 }
 // Bit 1 is a short input prewarm; it uses the existing 60% interaction
 // headroom without requiring a frame already in flight. Bit 0 retains the
 // upstream work-after-idle boost. All levels remain under the thermal cap.
 if(wake&2){unsigned f=hco_at_least((uint64_t)hco_opp(cap)->khz*3/5,cap);
  if(f>floor)floor=f;p->reason=7;}
 if(wake&1){uint64_t khz=(uint64_t)hco_opp(cur)->khz*2;
  unsigned f=hco_at_least(khz>578000?khz:578000,cap);if(f>floor)floor=f;p->reason=3;}
 if(queued){unsigned f=hco_at_least(500000,cap);if(f>floor)floor=f;}
 if(want<floor)want=floor;
 if(!active && !queued && !wake){
  if(p->quiet<5)++p->quiet;
  if(p->quiet>=5){want=1;p->reason=4;}
 }else p->quiet=0;
 if(want>cur){p->low=0;return want;}
 if(want==cur){p->low=0;return cur;}
 if(++p->low<4)return cur;
 p->low=0;return want+2<cur?cur-2:want;
}
#endif
