/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#include <assert.h>
#include <stdio.h>
#include "../kernel/overlay/iokit/Kernel/houji-ufs-root/GpuDesktopPerfProfile.h"
int main(void) {
 uint32_t old[HHP_PERF_WORDS], full[HHP_PERF_WORDS];
 assert(!hhp_perf(old) && !hup_perf(full));
 assert(full[0]==13 && full[1]==old[1]);
 for(unsigned i=2;i<5;i++)assert(full[i]==old[i]);
 for(unsigned level=1;level<=HCO_COUNT;level++){
  const struct HoujiGpuOpp *opp=hco_opp(level);unsigned at=2+level*3;
  assert(full[at]==opp->arc_vote && full[at+1]==0xffffffffu && full[at+2]==opp->khz);
 }
 for(unsigned i=2+(HCO_COUNT+1)*3;i<50;i++)assert(!full[i]);
 for(unsigned i=50;i<HHP_PERF_WORDS;i++)assert(full[i]==old[i]);
 assert(full[2+HCO_BOOT_LEVEL*3]==0x00500305u);
 assert(full[4+HCO_BOOT_LEVEL*3]==500000u);
 puts("PASS: full HFI GPU table, matched 500MHz boot vote, unchanged CX/GMU entries and padding");
}
