// SPDX-License-Identifier: BSD-2-Clause-Patent
#define GG_HOST_TEST 1
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "GpuSecureMemory.h"
struct model {void *control;unsigned calls,prepared,published,revoked,checkpoints,guards,fail_call,fail_prepare,fail_publish,fail_revoke,fail_checkpoint,fail_guard,missing,mode;};
static int guard(void*c,unsigned op){struct model*m=c;assert(op==GGS_INIT);return ++m->guards!=m->fail_guard;}
static int delay(void*c,unsigned ms){(void)c;assert(ms==30);return 0;}
static uint64_t le(const uint8_t*p,unsigned bytes){uint64_t v=0;for(unsigned i=0;i<bytes;i++)v|=(uint64_t)p[i]<<(8*i);return v;}
static int call(void*c,struct ggs_regs*r){struct model*m=c;unsigned n=++m->calls;
 if(n<=6){assert(r->x[0]==0x42000601 && r->x[1]==1 && r->x[2]==hsm_query_id(n-1));for(unsigned i=3;i<8;i++)assert(!r->x[i]);}
 else {
  assert(m->prepared && m->published && m->revoked && m->checkpoints==1);
  assert(r->x[0]==0x42000c16 && r->x[1]==0x1117 && r->x[2]==0x80000080 && r->x[3]==16 && r->x[4]==0x800000c0 && r->x[5]==0x80000000 && !r->x[6] && !r->x[7]);
  const uint8_t*p=m->control;assert(le(p,8)==4 && le(p+8,8)==0x80000100 && le(p+16,8)==24);
  for(unsigned i=24;i<128;i++)assert(!p[i]);assert(le(p+128,8)==0x90000000 && le(p+136,8)==0x400000);
  assert(le(p+192,4)==3 && le(p+256,4)==10 && le(p+260,4)==6);
  for(unsigned i=264;i<16384;i++)assert(!p[i]);
 }
 if(n==m->fail_call){if(m->mode==0)return 1;r->x[0]=m->mode==1?2:(uint64_t)-1;r->x[1]=0;return 0;}
 *r=(struct ggs_regs){{0,n<=6?(n==m->missing?0:1):0,0,0,0,0,0,0}};if(m->mode==3 && n==7)r->x[1]=(uint64_t)-22;return 0;}
static int prepare(void*c,struct hsm_memory*m){struct model*f=c;f->prepared++;*m=(struct hsm_memory){0x90000000,0x80000000,f->control};return f->fail_prepare;}
static int publish(void*c,const struct hsm_memory*m){struct model*f=c;assert(hsm_valid_memory(m));f->published++;return f->fail_publish;}
static int revoke(void*c,const struct hsm_memory*m){struct model*f=c;assert(f->published && m->data==0x90000000);f->revoked++;return f->fail_revoke;}
static int checkpoint(void*c,const struct hsm_result*r){struct model*f=c;assert(r->revoked && (r->phase==3 || (r->phase==5 && r->owned)));return ++f->checkpoints==f->fail_checkpoint;}
static unsigned run(struct model*m,struct ggs_state*s,struct hsm_result*r){struct hsm_io io={{m,call,delay,guard},prepare,revoke,publish,checkpoint};return hsm_run(&io,s,r);}
static void init(struct model*m,struct ggs_state*s,void*control){memset(m,0,sizeof(*m));m->control=control;memset(control,0xaa,16384);*s=(struct ggs_state){.convention_verified=1,.init_succeeded=1};}
int main(void){void*control;assert(!posix_memalign(&control,16384,16384));struct model m;struct ggs_state s;struct hsm_result r;unsigned cases=0;
 init(&m,&s,control);assert(!run(&m,&s,&r) && r.owned && r.retained && r.calls==7 && r.available==63 && r.queried==63 && m.checkpoints==2);unsigned guards=m.guards;cases++;
 for(unsigned failure=1;failure<=7;failure++)for(unsigned mode=0;mode<3;mode++){
  init(&m,&s,control);m.fail_call=failure;m.mode=mode;assert(run(&m,&s,&r) && !r.owned && r.retained && m.calls==failure);
  assert(r.attempted==(failure==7) && r.result_valid==(mode!=0));assert(!m.prepared || failure==7);cases++;
 }
 for(unsigned missing=1;missing<=6;missing++){
  init(&m,&s,control);m.missing=missing;unsigned code=run(&m,&s,&r);assert((code==0)==(missing!=1));
  assert(!!r.owned==(missing!=1) && (r.available&(1u<<(missing-1)))==0);cases++;
 }
 for(unsigned kind=0;kind<5;kind++){
  init(&m,&s,control);if(kind==0)m.fail_prepare=1;if(kind==1)m.fail_publish=1;if(kind==2)m.fail_revoke=1;if(kind==3)m.fail_checkpoint=1;if(kind==4)m.fail_checkpoint=2;
  assert(run(&m,&s,&r) && r.retained && r.attempted==(kind==4) && r.owned==(kind==4));cases++;
 }
 for(unsigned n=1;n<=guards;n++){init(&m,&s,control);m.fail_guard=n;assert(run(&m,&s,&r) && !r.attempted && r.retained);cases++;}
 init(&m,&s,control);m.mode=3;assert(run(&m,&s,&r)==HSM_ASSIGN && r.attempted && !r.owned && r.status_a1==(uint64_t)-22);cases++;
 for(unsigned gate=0;gate<3;gate++) {init(&m,&s,control);if(gate==0)s.convention_verified=0;if(gate==1)s.init_succeeded=0;if(gate==2)s.quarantined=1;assert(run(&m,&s,&r)==HSM_GUARD && !m.calls);cases++;}
 struct hsm_memory memory={0x90000000,0x80000000,control};struct ggs_regs frame;
 for(unsigned bit=0;bit<16;bit++){memory.data^=1u<<bit;assert(hsm_assign_frame(&memory,&frame));memory.data^=1u<<bit;cases++;}
 for(unsigned bit=0;bit<14;bit++){memory.control^=1u<<bit;assert(hsm_assign_frame(&memory,&frame));memory.control^=1u<<bit;cases++;}
 memory.data=(UINT64_C(1)<<36)-65536;assert(hsm_assign_frame(&memory,&frame));cases++;
 memory.data=0x80000000;assert(hsm_assign_frame(&memory,&frame));cases++;
 memory.data=0x90000000;memory.control_cpu=(uint8_t*)control+8;assert(hsm_assign_frame(&memory,&frame));cases++;
 memory.control_cpu=(void*)(UINTPTR_MAX&~(uintptr_t)16383);assert(hsm_assign_frame(&memory,&frame));cases++;
 free(control);printf("PASS: %u fixed secure ownership cases; independent seven-argument descriptor oracle, query availability, every failing call/guard/lifetime stage, full raw status, no data pointer or fake secure ACK\n",cases);
}
