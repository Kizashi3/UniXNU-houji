// SPDX-License-Identifier: BSD-2-Clause-Patent
#define GG_HOST_TEST 1
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "GpuSecureContext.h"
struct model {uint32_t regs[0x40000/4];unsigned reads,writes,guards,fail_read,fail_write,fail_guard,applied,mode;};
static uint32_t *reg(struct model*m,uint32_t a){assert(a>=0x3da0000 && a<0x3de0000 && !(a&3));return m->regs+(a-0x3da0000)/4;}
static int read32(void*c,uint32_t a,uint32_t*v){struct model*m=c;if(++m->reads==m->fail_read)return 1;*v=*reg(m,a);if(a==0x3dc37f4 && m->mode==1)*v=1;return 0;}
static int read64(void*c,uint32_t a,uint64_t*v){uint32_t lo,hi;if(read32(c,a,&lo) || read32(c,a+4,&hi))return 1;*v=lo|((uint64_t)hi<<32);return 0;}
static int write32(void*c,uint32_t a,uint32_t v){struct model*m=c;unsigned failure=++m->writes==m->fail_write;if(failure && !m->applied)return 1;
 assert((a>=0x3dc3000 && a<=0x3dc303c) || a==0x3da180c || a==0x3da100c || a==0x3dc3618 || a==0x3dc37f0 || a==0x3da0808 || a==0x3da0c08);
 *reg(m,a)=v;if(a==0x3dc3010)*reg(m,a)|=0x60;if(a==0x3dc3000)*reg(m,a)&=~0x1000u;return failure;}
static int write64(void*c,uint32_t a,uint64_t v){return write32(c,a,(uint32_t)v) || write32(c,a+4,(uint32_t)(v>>32));}
static int delay(void*c,unsigned us){(void)c;assert(us==10);return 0;}
static int guard(void*c){struct model*m=c;return ++m->guards==m->fail_guard;}
static void init(struct model*m){memset(m,0,sizeof(*m));*reg(m,0x3da0020)=0x4c017e18;*reg(m,0x3da0024)=0x40000016;*reg(m,0x3da0028)=0x5511;*reg(m,0x3dc3004)=3;
 for(unsigned i=0;i<24;i++)*reg(m,0x3da0c00+4*i)=0x20000;*reg(m,0x3da0800)=0x80000005;*reg(m,0x3da0c00)=2;*reg(m,0x3da0804)=0x80000000;*reg(m,0x3da0c04)=0;*reg(m,0x3dc0000)=*reg(m,0x3dc2000)=0x27;}
static unsigned run(struct model*m,const ArmSmmu4KConfig*cfg,const ArmSmmu4KResult*b,struct hsc_result*r){struct hgp_io io={m,read32,read64,write32,write64,delay,guard,0};return hse_run(&io,cfg,b,r);}
int main(void){struct model*m=malloc(sizeof(*m));uint64_t*t=calloc(HSE_TABLE_PAGES,4096);assert(m&&t);
 ArmSmmu4KConfig cfg={32,36,0x81000000,HSE_PAGES};ArmSmmu4KRange range={HSE_IOVA,0x90000000,HSE_BYTES,11,0,3};ArmSmmu4KResult built;assert(!ArmSmmu4KBuild(&cfg,&range,1,t,HSE_TABLE_PAGES,&built));assert(built.table_pages==4 && built.leaf_pages==893);
 struct hsc_result r;unsigned cases=0;init(m);assert(!run(m,&cfg,&built,&r) && r.attached && r.phase==5 && r.retained);unsigned reads=m->reads,writes=m->writes,guards=m->guards;cases++;
 assert(*reg(m,0x3dc0000)==0x27 && *reg(m,0x3dc2000)==0x27 && *reg(m,0x3da0800)==0x80000005 && *reg(m,0x3da0804)==0x80000000);
 for(unsigned kind=0;kind<3;kind++)for(unsigned n=1;n<=(kind==0?reads:kind==1?writes:guards);n++)for(unsigned applied=0;applied<(kind==1?2u:1u);applied++){
  init(m);if(kind==0)m->fail_read=n;if(kind==1){m->fail_write=n;m->applied=applied;}if(kind==2)m->fail_guard=n;
  assert(run(m,&cfg,&built,&r) && r.retained);assert(*reg(m,0x3dc0000)==0x27 && *reg(m,0x3dc2000)==0x27 && *reg(m,0x3da0800)==0x80000005 && *reg(m,0x3da0804)==0x80000000);cases++;
 }
 init(m);m->mode=1;assert(run(m,&cfg,&built,&r)==HSC_TIMEOUT && r.polls==100 && !r.enabled);cases++;
 uint32_t corrupt[]={0x3da0020,0x3da0048,0x3da0808,0x3da0c08,0x3dc1000,0x3dc2000,0x3dc3004,0x3dc3058};
 for(unsigned i=0;i<8;i++){init(m);*reg(m,corrupt[i])^=1u<<(i==7?3:0);assert(run(m,&cfg,&built,&r) && !r.attempted && !m->writes);cases++;}
 for(unsigned page=0;page<HSE_PAGES;page++){
  uint64_t address=HSE_IOVA+4096*page,pa=cfg.table_physical,entry=0;
  for(unsigned level=1;level<=3;level++){unsigned index=(address>>(39-9*level))&(level==1?3u:511u);assert(pa>=cfg.table_physical && pa-cfg.table_physical<4*4096);entry=t[(pa-cfg.table_physical)/8+index];assert((entry&3)==3);pa=entry&UINT64_C(0x0000fffffffff000);}
  assert(pa==0x90000000+4096*page && ((entry>>6)&3)==0 && ((entry>>53)&3)==3 && ((entry>>2)&7)==0);cases++;
 }
 const uint64_t holes[]={HSE_IOVA-4096u,HSE_IOVA+HSE_BYTES,0x61000000,0x61100000};
 for(unsigned hole=0;hole<4;hole++){uint64_t pa=cfg.table_physical;unsigned absent=0;for(unsigned level=1;level<=3;level++){unsigned index=(holes[hole]>>(39-9*level))&(level==1?3u:511u);uint64_t entry=t[(pa-cfg.table_physical)/8+index];if(!(entry&1)){absent=1;break;}pa=entry&UINT64_C(0x0000fffffffff000);}assert(absent);cases++;}
 uint32_t q[]={0x01000b14,1,0,0,0x1007,5,0,5,0,HSE_BYTES,0};assert(hse_request(q,11));cases++;
 for(unsigned i=0;i<11;i++)for(unsigned bit=0;bit<32;bit++){q[i]^=1u<<bit;assert(hse_request(q,11)==(i==0 && bit>=20));q[i]^=1u<<bit;cases++;}
 void*control;assert(!posix_memalign(&control,16384,16384));struct hsm_memory memory={0x90000000,0x80000000,control};struct ggs_regs frame;
 assert(!hse_table_frame(&memory,cfg.table_physical,&frame));uint32_t *v=control;uint64_t*c=control;
 assert(frame.x[0]==0x42000c16 && frame.x[1]==0x1117 && frame.x[2]==0x80000080 && frame.x[5]==0x80000000 && c[16]==cfg.table_physical && c[17]==16384 && c[2]==48);
 assert(v[48]==3 && v[64]==3 && v[65]==6 && v[70]==10 && v[71]==4);for(unsigned i=72;i<4096;i++)assert(!v[i]);cases++;
 for(unsigned bit=0;bit<14;bit++){assert(hse_table_frame(&memory,cfg.table_physical^(1u<<bit),&frame));cases++;}
 assert(hse_table_frame(&memory,memory.data,&frame) && hse_table_frame(&memory,memory.control,&frame));cases++;
 free(control);free(t);free(m);printf("PASS: %u secure-context cases; full893leaf and boundary walks, fixed HLOS-RW/CP-R table share, exact captured secure request, every MMIO/guard failure, bank0/2 preserved, no CP/data access\n",cases);
}
