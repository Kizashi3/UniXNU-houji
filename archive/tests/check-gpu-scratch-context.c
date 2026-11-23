// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include "GpuScratchContext.h"
#include "vendor/ArmSmmu4K/ArmSmmu4KAudit.h"
struct model {uint32_t regs[0x40000/4];unsigned reads,writes,guards,delays,fail_read,fail_write,fail_guard,applied,mode;};
static uint32_t *reg(struct model*m,uint32_t a){assert(a>=0x3da0000 && a<0x3de0000 && !(a&3));return m->regs+(a-0x3da0000)/4;}
static int read32(void*c,uint32_t a,uint32_t*v){struct model*m=c;if(++m->reads==m->fail_read)return 1;*v=*reg(m,a);if(a==0x3dc07f4 && m->mode==1)*v=1;return 0;}
static int read64(void*c,uint32_t a,uint64_t*v){uint32_t lo,hi;if(read32(c,a,&lo) || read32(c,a+4,&hi))return 1;*v=lo|((uint64_t)hi<<32);return 0;}
static int write32(void*c,uint32_t a,uint32_t v){struct model*m=c;unsigned failure=++m->writes==m->fail_write;if(failure && !m->applied)return 1;
 // An independent register boundary oracle: bank2, globals and CP unavailable.
 int allowed=(a>=0x3dc0000 && a<=0x3dc003c) || a==0x3da1800 || a==0x3da1000 || a==0x3dc0618 || a==0x3dc07f0 || a==0x3da0804 || a==0x3da0c04;
 assert(allowed);*reg(m,a)=v;if(a==0x3dc0010)*reg(m,a)|=0x60;if(a==0x3dc0000)*reg(m,a)&=~0x1000u;return failure;}
static int write64(void*c,uint32_t a,uint64_t v){return write32(c,a,(uint32_t)v) || write32(c,a+4,(uint32_t)(v>>32));}
static int delay(void*c,unsigned us){struct model*m=c;assert(us==10);m->delays++;return 0;}
static int guard(void*c){struct model*m=c;return ++m->guards==m->fail_guard;}
static void init(struct model*m){memset(m,0,sizeof(*m));*reg(m,0x3da0020)=0x4c017e18;*reg(m,0x3da0024)=0x40000016;*reg(m,0x3da0028)=0x5511;*reg(m,0x3dc0004)=3;
 for(unsigned i=0;i<24;i++)*reg(m,0x3da0c00+4*i)=0x20000;*reg(m,0x3da0800)=0x80000005u;*reg(m,0x3da0c00)=2;*reg(m,0x3dc2000)=0x27;}
static unsigned run(struct model*m,const ArmSmmu4KConfig*cfg,const ArmSmmu4KResult*built,struct hsc_result*r){const struct hgp_io io={m,read32,read64,write32,write64,delay,guard,0};return hsc_run(&io,cfg,built,r);}
int main(void){
 struct model*m=malloc(sizeof(*m));assert(m);uint64_t*t=calloc(3,4096);assert(t);
 ArmSmmu4KConfig cfg={32,36,0x80000000,HSC_POOL_PAGES};ArmSmmu4KRange ranges[HSC_CLASSES];ArmSmmu4KResult built;
 assert(!hsc_pool_ranges(0x81000000,ranges));assert(!ArmSmmu4KBuild(&cfg,ranges,HSC_CLASSES,t,3,&built));struct hsc_result r;unsigned cases=0;
 for(unsigned cls=0;cls<HSC_CLASSES;cls++) {
  unsigned expected[]={1,9,3,11};assert(ranges[cls].permissions==expected[cls]);
  uint64_t table=cfg.table_physical,entry=0,iova=ranges[cls].iova;
  for(unsigned level=1;level<=3;level++) {
   unsigned index=(unsigned)((iova>>(39-9*level))&(level==1?3u:511u));
   assert(table>=cfg.table_physical && table-cfg.table_physical<3*4096);
   entry=t[(table-cfg.table_physical)/8+index];assert((entry&3)==3);table=entry&UINT64_C(0x0000fffffffff000);
  }
  assert(((entry>>6)&3)==3-cls && ((entry>>53)&3)==3 && table==ranges[cls].physical);cases++;
 }
 init(m);assert(!run(m,&cfg,&built,&r) && r.phase==5 && r.enabled && r.attached && r.retained);
 assert(*reg(m,0x3dc2000)==0x27 && *reg(m,0x3da0800)==0x80000005u && *reg(m,0x3da0c00)==2);
 unsigned reads=m->reads,writes=m->writes,guards=m->guards;cases++;
 for(unsigned kind=0;kind<3;kind++)for(unsigned n=1;n<=(kind==0?reads:kind==1?writes:guards);n++)for(unsigned applied=0;applied<(kind==1?2u:1u);applied++) {
  init(m);if(kind==0)m->fail_read=n;if(kind==1){m->fail_write=n;m->applied=applied;}if(kind==2)m->fail_guard=n;
  assert(run(m,&cfg,&built,&r) && r.retained);assert(*reg(m,0x3dc2000)==0x27 && *reg(m,0x3da0800)==0x80000005u && *reg(m,0x3da0c00)==2);cases++;
 }
 init(m);m->mode=1;assert(run(m,&cfg,&built,&r)==HSC_TIMEOUT && r.polls==100 && !r.enabled && r.retained);cases++;
 const uint32_t corrupt[]={0x3da0020,0x3da0048,0x3da0808,0x3da0c08,0x3dc1000,0x3dc2000,0x3dc0004,0x3dc0058};
 for(unsigned i=0;i<sizeof(corrupt)/sizeof(corrupt[0]);i++){init(m);*reg(m,corrupt[i])^=1u<<(i==7?3:0);assert(run(m,&cfg,&built,&r) && !r.attempted && !m->writes);cases++;}
 uint32_t request[]={0x00900b14,1,0,0,0x33f,2,0,2,0,4096,0};assert(hsc_scratch_request(request,11));cases++;
 for(unsigned i=0;i<11;i++)for(unsigned bit=0;bit<32;bit++){request[i]^=1u<<bit;assert(hsc_scratch_request(request,11)==(i==0 && bit>=20));request[i]^=1u<<bit;cases++;}
 assert(!hsc_scratch_request(request,10) && !hsc_scratch_request(0,11));cases++;
 // Full extended graph: a separate contiguous 4MiB privilege-only NC/NX
 // shared context, not an alias of the small arena or GMU-only address.
 free(t);t=calloc(HSC_LARGE_TABLE_PAGES,4096);assert(t);
 ArmSmmu4KRange extended[HSC_CLASSES+1];assert(!hsc_pool_ranges(0x81000000,extended));
 assert(!hsc_large_range(0x82000000,&extended[HSC_CLASSES]));
 cfg=(ArmSmmu4KConfig){32,36,0x80000000,HSC_LARGE_LEAF_PAGES};
 assert(!ArmSmmu4KBuild(&cfg,extended,HSC_CLASSES+1,t,HSC_LARGE_TABLE_PAGES,&built));
 assert(built.table_pages==HSC_LARGE_TABLE_PAGES && built.leaf_pages==HSC_LARGE_LEAF_PAGES);
 init(m);assert(!run(m,&cfg,&built,&r) && r.attached && r.phase==5);cases++;
 for(unsigned page=0;page<HSC_LARGE_PAGES;page++) {
  uint64_t table=cfg.table_physical,entry=0,iova=HSC_LARGE_IOVA+4096*page;
  for(unsigned level=1;level<=3;level++) {
   unsigned index=(unsigned)((iova>>(39-9*level))&(level==1?3u:511u));
   assert(table>=cfg.table_physical && table-cfg.table_physical<HSC_LARGE_TABLE_PAGES*4096);
   entry=t[(table-cfg.table_physical)/8+index];assert((entry&3)==3);table=entry&UINT64_C(0x0000fffffffff000);
  }
  assert(((entry>>6)&3)==0 && ((entry>>53)&3)==3 && ((entry>>2)&7)==0 && table==0x82000000+4096*page);cases++;
 }
 for(unsigned hole=0;hole<2;hole++) {
  uint64_t iova=hole?HSC_LARGE_IOVA+HSC_LARGE_BYTES:HSC_GMU_ONLY_IOVA,table=cfg.table_physical;unsigned absent=0;
  for(unsigned level=1;level<=3;level++) {
   unsigned index=(unsigned)((iova>>(39-9*level))&(level==1?3u:511u));uint64_t entry=t[(table-cfg.table_physical)/8+index];
   if(!(entry&1)){absent=1;break;}table=entry&UINT64_C(0x0000fffffffff000);
  }
  assert(absent);cases++;
 }
 // Current graph includes a physically distinct GPU-only pool. Verify every
 // raw leaf class and ensure the GMU-only address still has no GPU leaf.
 free(t);t=calloc(HSC_DATA_TABLE_PAGES,4096);assert(t);
 ArmSmmu4KRange current[HSC_DATA_RANGES];assert(!hsc_pool_ranges(0x81000000,current));
 assert(!hsc_large_range(0x82000000,&current[HSC_CLASSES]));
 assert(!hsc_gpu_only_ranges(0x83000000,&current[HSC_CLASSES+1]));
 cfg=(ArmSmmu4KConfig){32,36,0x80000000,HSC_DATA_LEAF_PAGES};
 assert(!ArmSmmu4KBuild(&cfg,current,HSC_DATA_RANGES,t,HSC_DATA_TABLE_PAGES,&built));
 assert(built.table_pages==6 && built.leaf_pages==1536);init(m);assert(!run(m,&cfg,&built,&r) && r.attached);cases++;
 for(unsigned page=0;page<HSC_POOL_PAGES;page++) {
  uint64_t table=cfg.table_physical,entry=0,address=HSC_GPU_ONLY_IOVA+4096*page;
  for(unsigned level=1;level<=3;level++) {
   unsigned index=(address>>(39-9*level))&(level==1?3u:511u);assert(table>=cfg.table_physical && table-cfg.table_physical<6*4096);
   entry=t[(table-cfg.table_physical)/8+index];assert((entry&3)==3);table=entry&UINT64_C(0x0000fffffffff000);
  }
  assert(table==0x83000000+4096*page && ((entry>>6)&3)==3-page/(HSC_CLASS_BYTES/4096) && ((entry>>53)&3)==3);cases++;
 }
 // Current sparse code profile has seven tables and1567 owned leaves.
 free(t);t=calloc(HSC_GPU_TABLE_PAGES,4096);assert(t);ArmSmmu4KRange code_ranges[HSC_GPU_RANGES];
 assert(!hsc_pool_ranges(0x81000000,code_ranges) && !hsc_large_range(0x82000000,&code_ranges[4]) &&
  !hsc_gpu_only_ranges(0x83000000,&code_ranges[5]) && !hcc_ranges(0x84000000,&code_ranges[HSC_DATA_RANGES]));
 cfg=(ArmSmmu4KConfig){32,36,0x80000000,HSC_GPU_LEAF_PAGES};
 assert(!ArmSmmu4KBuild(&cfg,code_ranges,HSC_GPU_RANGES,t,HSC_GPU_TABLE_PAGES,&built));
 init(m);assert(!run(m,&cfg,&built,&r) && r.attached && r.phase==5 && r.retained);cases++;
 printf("PASS: %u GPU scratch context cases; real three/five/six/seven-page graphs, bank0/SID0 only, bank2 preserved, every read/write side effect/guard failure, bounded TLB wait, exact captured resource contract\n",cases);
 free(t);free(m);
}
