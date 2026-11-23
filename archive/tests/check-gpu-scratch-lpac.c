// SPDX-License-Identifier: BSD-2-Clause-Patent
// Actual normal-domain SID0/SID1 policy. Legacy SID0 tests stay separate.
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "GpuScratchContext.h"
struct model {
 uint32_t regs[0x40000/4];
 unsigned reads,writes,guards,delays,fail_read,fail_write,fail_guard,applied,busy;
 unsigned first_write_after_reads,slot1_reads,slot2_writes,slot2_verify_read;
 unsigned slot2_route_write,slot2_smr_write;
 unsigned corrupt_read,corrupt_mask,last_slot2_smr_read;
};
static uint32_t *reg(struct model*m,uint32_t a){assert(a>=0x3da0000 && a<0x3de0000 && !(a&3));return &m->regs[(a-0x3da0000)/4];}
static int read32(void*c,uint32_t a,uint32_t*v){
 struct model*m=c;if(++m->reads==m->fail_read)return 1;*v=*reg(m,a);
 if(m->reads==m->corrupt_read)*v^=m->corrupt_mask;
 if(a==0x3dc07f4 && m->busy)*v=1;
 if(a==0x3da0c04 && !*v)m->slot1_reads|=1;
 if(a==0x3da0804 && *v==0x80000000u)m->slot1_reads|=2;
 if(a==0x3da0c08 && m->slot2_writes==2 && !m->slot2_verify_read)m->slot2_verify_read=m->reads;
 if(a==0x3da0808 && m->slot2_writes==2)m->last_slot2_smr_read=m->reads;
 return 0;
}
static int read64(void*c,uint32_t a,uint64_t*v){uint32_t lo,hi;if(read32(c,a,&lo)||read32(c,a+4,&hi))return 1;*v=lo|((uint64_t)hi<<32);return 0;}
static int write32(void*c,uint32_t a,uint32_t v){
 struct model*m=c;unsigned fail=++m->writes==m->fail_write;
 if(!m->first_write_after_reads)m->first_write_after_reads=m->reads;
 // Independent hardware boundary: normal bank0 only; no secure SID2/bank3,
 // live GMU bank2, global, fault-clear or CP register is writable here.
 assert((a>=0x3dc0000 && a<=0x3dc003c)||a==0x3da1800||a==0x3da1000||
  a==0x3dc0618||a==0x3dc07f0||a==0x3da0804||a==0x3da0c04||a==0x3da0808||a==0x3da0c08);
 if(a==0x3da0c08 || a==0x3da0808){
  assert((*reg(m,0x3dc0000)&~0x1000u)==0x27 && m->slot1_reads==3);
  assert(*reg(m,0x3da0804)==0x80000000u && !*reg(m,0x3da0c04));
  if(a==0x3da0c08){assert(v==0 && !m->slot2_writes);m->slot2_route_write=m->writes;}
  else {assert(v==0x80000001u && m->slot2_writes==1 && !*reg(m,0x3da0c08));m->slot2_smr_write=m->writes;}
  if(fail && !m->applied)return 1;
  m->slot2_writes++;
 } else if(fail && !m->applied)return 1;
 *reg(m,a)=v;
 if(a==0x3dc0010)*reg(m,a)|=0x60;
 if(a==0x3dc0000)*reg(m,a)&=~0x1000u;
 return fail;
}
static int write64(void*c,uint32_t a,uint64_t v){return write32(c,a,(uint32_t)v)||write32(c,a+4,(uint32_t)(v>>32));}
static int delay(void*c,unsigned us){struct model*m=c;assert(us==10);m->delays++;return 0;}
static int guard(void*c){struct model*m=c;return ++m->guards==m->fail_guard;}
static void init(struct model*m){
 memset(m,0,sizeof *m);*reg(m,0x3da0020)=0x4c017e18;*reg(m,0x3da0024)=0x40000016;
 *reg(m,0x3da0028)=0x5511;*reg(m,0x3dc0004)=3;
 for(unsigned i=0;i<24;i++)*reg(m,0x3da0c00+4*i)=0x20000;
 *reg(m,0x3da0800)=0x80000005u;*reg(m,0x3da0c00)=2;*reg(m,0x3dc2000)=0x27;
}
static unsigned run(struct model*m,const ArmSmmu4KConfig*c,const ArmSmmu4KResult*b,struct hsc_result*r){
 const struct hgp_io io={m,read32,read64,write32,write64,delay,guard,0};return hsc_run_lpac(&io,c,b,r);
}
static void preserved(struct model*m){
 assert(*reg(m,0x3dc2000)==0x27 && *reg(m,0x3da0800)==0x80000005u && *reg(m,0x3da0c00)==2);
 assert(!*reg(m,0x3dc3000));
 for(unsigned slot=3;slot<24;slot++)assert(!*reg(m,0x3da0800+4*slot) && *reg(m,0x3da0c00+4*slot)==0x20000);
 // No installed SMR may match secure SID2, on success or partial failure.
 for(unsigned slot=0;slot<24;slot++)assert(!(*reg(m,0x3da0800+4*slot)&0x80000000u) ||
  (*reg(m,0x3da0800+4*slot)&0xffffu)!=2);
}
int main(void){
 struct model*m=malloc(sizeof *m);uint64_t*t=calloc(HSC_GPU_TABLE_PAGES,4096);assert(m && t);
 ArmSmmu4KRange ranges[HSC_GPU_RANGES];ArmSmmu4KResult built;
 assert(!hsc_pool_ranges(0x81000000,ranges) && !hsc_large_range(0x82000000,&ranges[4]) &&
  !hsc_gpu_only_ranges(0x83000000,&ranges[5]) && !hcc_ranges(0x84000000,&ranges[HSC_DATA_RANGES]));
 ArmSmmu4KConfig cfg={32,36,0x80000000,HSC_GPU_LEAF_PAGES};
 assert(!ArmSmmu4KBuild(&cfg,ranges,HSC_GPU_RANGES,t,HSC_GPU_TABLE_PAGES,&built));
 struct hsc_result r;unsigned cases=0;
 init(m);assert(!run(m,&cfg,&built,&r) && r.phase==5 && r.enabled && r.attached && r.retained && r.lpac && r.sid0_attached && r.lpac_attached);
 assert(r.sid0_smr==0x80000000u && !r.sid0_s2cr && r.lpac_smr==0x80000001u && !r.lpac_s2cr);
 assert(*reg(m,0x3da0804)==0x80000000u && !*reg(m,0x3da0c04) && *reg(m,0x3da0808)==0x80000001u && !*reg(m,0x3da0c08));
 preserved(m);cases++;
 unsigned reads=m->reads,writes=m->writes,guards=m->guards,preflight_reads=m->first_write_after_reads;
 unsigned route_write=m->slot2_route_write,smr_write=m->slot2_smr_write,verify_read=m->slot2_verify_read;
 unsigned final_smr_read=m->last_slot2_smr_read;
 assert(route_write && smr_write==route_write+1 && verify_read && guards==3);
 // The original wrapper remains SID0-only even with the extended result type.
 init(m);const struct hgp_io legacy={m,read32,read64,write32,write64,delay,guard,0};
 assert(!hsc_run(&legacy,&cfg,&built,&r) && r.attached && r.sid0_attached && !r.lpac && !r.lpac_attached && !m->slot2_writes);
 assert(!*reg(m,0x3da0808) && *reg(m,0x3da0c08)==0x20000);preserved(m);cases++;
 for(unsigned kind=0;kind<3;kind++)for(unsigned n=1;n<=(kind==0?reads:kind==1?writes:guards);n++)for(unsigned applied=0;applied<(kind==1?2u:1u);applied++){
  init(m);if(kind==0)m->fail_read=n;if(kind==1){m->fail_write=n;m->applied=applied;}if(kind==2)m->fail_guard=n;
  assert(run(m,&cfg,&built,&r) && r.retained && r.lpac && !r.attached);preserved(m);
  if(kind==0){assert(m->reads==n);if(n<=preflight_reads)assert(!m->writes && !r.attempted);}
  if(kind==1)assert(m->writes==n);
  if(kind==2)assert(m->guards==n);
  cases++;
 }
 // Failed store may already have installed a live route. Keep it pinned and
 // never claim verified attachment, clear faults, detach or free it.
 init(m);m->fail_write=smr_write;m->applied=1;
 assert(run(m,&cfg,&built,&r)==HSC_IO && r.retained && r.enabled && r.sid0_attached && !r.lpac_attached && !r.attached);
 assert(*reg(m,0x3da0808)==0x80000001u && !*reg(m,0x3da0c08));preserved(m);cases++;
 init(m);m->fail_read=verify_read;
 assert(run(m,&cfg,&built,&r) && r.retained && r.enabled && r.sid0_attached && !r.lpac_attached && !r.attached);
 assert(*reg(m,0x3da0808)==0x80000001u && !*reg(m,0x3da0c08));preserved(m);cases++;
 init(m);m->busy=1;assert(run(m,&cfg,&built,&r)==HSC_TIMEOUT && r.polls==100 && !r.enabled && r.retained && !m->slot2_writes);cases++;
 // Both immediate attachment readbacks and the final full survey must match
 // every bit. A later mismatch retains even the already verified LPAC route.
 const unsigned slot2_reads[]={verify_read,verify_read+1,final_smr_read,final_smr_read+1};
 for(unsigned stage=0;stage<4;stage++)for(unsigned bit=0;bit<32;bit++){
  init(m);m->corrupt_read=slot2_reads[stage];m->corrupt_mask=1u<<bit;
  assert(run(m,&cfg,&built,&r)==(stage<2?HSC_VERIFY:HSC_GUARD) && r.retained && !r.attached && r.sid0_attached);
  assert(r.lpac_attached==(stage>=2));preserved(m);cases++;
 }
 // Every bit of either supposedly empty slot2 register is an owner mismatch.
 for(unsigned field=0;field<2;field++)for(unsigned bit=0;bit<32;bit++){
  init(m);*reg(m,field?0x3da0c08:0x3da0808)^=1u<<bit;
  assert(run(m,&cfg,&built,&r)==HSC_GUARD && !r.attempted && !m->writes && r.retained);cases++;
 }
 // A preexisting secure SID2 must not be mistaken for LPAC SID1, regardless of
 // whether it routes to bank0, bank3 or FAULT. Do not steal another slot either.
 for(unsigned slot=2;slot<24;slot++)for(unsigned route=0;route<3;route++){
  init(m);*reg(m,0x3da0800+4*slot)=0x80000002u;*reg(m,0x3da0c00+4*slot)=route==0?0:route==1?3:0x20000;
  assert(run(m,&cfg,&built,&r)==HSC_GUARD && !m->writes && !r.attempted && r.retained);cases++;
 }
 for(unsigned bad=0;bad<2;bad++){
  init(m);const struct hgp_io io={m,read32,read64,write32,write64,delay,guard,0};
  assert(hsc_run_profile(&io,&cfg,&built,&r,bad?UINT32_MAX:2)==HSC_ARGUMENT && !m->reads && !m->writes);cases++;
 }
 printf("PASS: %u actual LPAC normal-domain cases; SID0+SID1 bank0, GMU SID5/bank2 preserved, secure SID2 absent/FAULT, every read/write/guard failure and applied partial write retained, exact empty slot2 required\n",cases);
 free(t);free(m);
}
