// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <assert.h>
#include <stdio.h>
#include "../native/power/factory-dvfs-runtime/HoujiGpuGovernorPolicy.h"

int main() {
 const unsigned expected[]={231000,310000,366000,422000,500000,578000,
  629000,680000,720000,770000,834000,903000};
 static_assert(sizeof expected/sizeof *expected==HCO_COUNT,"factory table changed");
 for(unsigned i=0;i<HCO_COUNT;i++)assert(hco_opp(i+1)->khz==expected[i]);
 assert(hco_opp(1)->arc_vote==0x00340201 && hco_opp(1)->bw_index==1);
 assert(hco_opp(HCO_BOOT_LEVEL)->khz==500000);
 assert(hco_opp(HCO_BOOT_LEVEL)->arc_vote==0x00500305 && hco_opp(HCO_BOOT_LEVEL)->bw_index==5);
 assert(!hco_opp(0) && !hco_opp(HCO_COUNT+1));
 assert(hco_at_least(UINT64_MAX,HCO_COUNT)==HCO_COUNT);
 // Exercise every factory cap: sustained work reaches the cap, then genuine
 // idle must return to the floor. No intermediate decision escapes the cap.
 for(unsigned cap=1;cap<=HCO_COUNT;cap++) {
  HoujiGpuGovernorPolicy p={};unsigned cur=1;
  for(unsigned i=0;i<24;i++) {
   cur=houjiGpuChoose(&p,cur,cap,1000,1,0,0,3);
   assert(cur>=1 && cur<=cap);
  }
  assert(cur==cap);
  for(unsigned i=0;i<100;i++) {
   cur=houjiGpuChoose(&p,cur,cap,0,0,0,0,0);
   assert(cur>=1 && cur<=cap);
  }
  assert(cur==1);
 }
 // A reduced external cap takes effect even with recent heavy load.
 HoujiGpuGovernorPolicy p={1000,1,0,0,0};
 assert(houjiGpuChoose(&p,HCO_COUNT,5,1000,1,1,1,8)==5);
 // Touch/wake floors and missing/invalid requests are independent of load.
 p={};assert(houjiGpuChoose(&p,1,HCO_COUNT,0,1,1,0,0)>=8);
 p={};assert(houjiGpuChoose(&p,1,HCO_COUNT,0,1,0,1,0)>=6);
 p={};assert(houjiGpuChoose(&p,1,3,0,1,1,1,0)==3);
 assert(!houjiGpuChoose(nullptr,1,HCO_COUNT,10,1,0,0,0));
 assert(!houjiGpuChoose(&p,0,HCO_COUNT,10,1,0,0,0));
 assert(!houjiGpuChoose(&p,1,0,10,1,0,0,0));
 // One transient low sample must not downshift a loaded high OPP.
 p={1000,1,0,0,0};
 assert(houjiGpuChoose(&p,HCO_COUNT,HCO_COUNT,0,1,0,0,0)==HCO_COUNT);
 puts("PASS: 12 exact OPPs; 12 cap/load/idle traces; boost/cap precedence; invalid requests");
}
