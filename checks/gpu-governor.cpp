// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <assert.h>
#include <stdio.h>
#include "../kernel/overlay/iokit/Kernel/houji-ufs-root/HoujiGpuGovernorPolicy.h"

int main() {
 const unsigned expected[]={231000,310000,366000,422000,500000,578000,
  629000,680000,720000,770000,834000,903000};
 static_assert(sizeof expected/sizeof *expected==HCO_COUNT,"factory table changed");
 for(unsigned i=0;i<HCO_COUNT;i++)assert(hco_opp(i+1)->khz==expected[i]);
 assert(hco_opp(1)->arc_vote==0x00340201 && hco_opp(1)->bw_index==1);
 assert(hco_opp(HCO_BOOT_LEVEL)->khz==500000);
 assert(hco_opp(HCO_BOOT_LEVEL)->arc_vote==0x00500305 && hco_opp(HCO_BOOT_LEVEL)->bw_index==5);
 assert(!hco_opp(0) && !hco_opp(HCO_COUNT+1));
 assert(hco_cap_mhz(0)==HCO_DEFAULT_CAP);
 assert(!hco_cap_mhz(230) && !hco_cap_mhz(904) && !hco_cap_mhz(UINT32_MAX));
 for(unsigned mhz=231;mhz<=903;++mhz){
  unsigned cap=hco_cap_mhz(mhz);assert(cap && hco_opp(cap)->khz<=mhz*1000);
  assert(cap==HCO_COUNT || hco_opp(cap+1)->khz>mhz*1000);
 }
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
 // Input gives bounded headroom, not a permanent maximum-frequency vote.
 p={};unsigned interactive=houjiGpuChoose(&p,1,HCO_COUNT,0,1,1,0,0);
 assert(interactive<HCO_COUNT && hco_opp(interactive)->khz>=hco_opp(HCO_COUNT)->khz*3/5);
 p={};assert(houjiGpuChoose(&p,1,HCO_COUNT,0,1,0,1,0)>=6);
 p={};assert(houjiGpuChoose(&p,1,3,0,1,1,1,0)==3);
 assert(!houjiGpuChoose(nullptr,1,HCO_COUNT,10,1,0,0,0));
 assert(!houjiGpuChoose(&p,0,HCO_COUNT,10,1,0,0,0));
 assert(!houjiGpuChoose(&p,1,0,10,1,0,0,0));
 for(unsigned cap=1;cap<=HCO_COUNT;cap++){
  // Sustained input with genuinely idle GPU must still return to idle.
  p={};unsigned cur=cap;
  for(unsigned i=0;i<100;i++)cur=houjiGpuChoose(&p,cur,cap,0,0,1,0,0);
  assert(cur==1);
  // A light interactive workload does not pin the top OPP; it can still
  // recover the full cap immediately under real sustained demand.
  for(unsigned i=0;i<100;i++)cur=houjiGpuChoose(&p,cur,cap,70,1,1,0,0);
  assert(cur>=1 && cur<=cap);
  if(cap==HCO_COUNT)assert(cur<HCO_COUNT);
  for(unsigned i=0;i<24;i++)cur=houjiGpuChoose(&p,cur,cap,1000,1,1,0,3);
  assert(cur==cap);
 }
 // One transient low sample must not downshift a loaded high OPP.
 p={1000,1,0,0,0};
 assert(houjiGpuChoose(&p,HCO_COUNT,HCO_COUNT,0,1,0,0,0)==HCO_COUNT);
 // A single 80% busy burst after long idle needs immediate headroom even
 // without a touch event; the old EWMA alone held this at 231 MHz.
 p={0,1,0,5,0};
 assert(houjiGpuChoose(&p,1,HCO_COUNT,800,1,0,0,0)>1);
 for(unsigned n=0;n<100000;n++)(void)houjiGpuChoose(&p,1,HCO_COUNT,0,0,0,0,0);
 assert(p.quiet==5);
 puts("PASS: 12 OPPs; all MHz ceilings; cap/load/idle and sustained-touch traces; burst response; thermal cap precedence");
}
