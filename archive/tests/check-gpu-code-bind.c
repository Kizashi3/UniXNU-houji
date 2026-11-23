// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "GpuCodeBind.h"
struct model {unsigned reads,writes,guards,fail_read,fail_write,fail_guard,apply,enabled,corrupt;uint32_t base[4];};
static int guard(void*c){struct model*m=c;return ++m->guards==m->fail_guard;}
static int read32(void*c,uint32_t a,uint32_t*v){struct model*m=c;if(++m->reads==m->fail_read)return 1;if(a==0x3d02020){*v=m->enabled;return 0;}for(unsigned i=0;i<4;i++)if(a==hcb_address(i)){*v=m->base[i]^(m->corrupt?1:0);return 0;}assert(0);return 1;}
static int write32(void*c,uint32_t a,uint32_t v){struct model*m=c;unsigned failure=++m->writes==m->fail_write;if(failure && !m->apply)return 1;for(unsigned i=0;i<4;i++)if(a==hcb_address(i)){assert(v==hcb_value(i));m->base[i]=v;return failure;}assert(0);return 1;}
static unsigned run(struct model*m,struct hcb_result*r){struct hcb_io io={m,read32,write32,guard};return hcb_run(&io,r);}
int main(void){struct model m={0};struct hcb_result r;unsigned cases=0;assert(!run(&m,&r) && r.phase==6 && r.attempted==15 && r.verified==15 && r.retained && !m.enabled && m.writes==4);cases++;
 unsigned reads=m.reads,writes=m.writes,guards=m.guards;
 for(unsigned type=0;type<3;type++)for(unsigned n=1;n<=(type==0?reads:type==1?writes:guards);n++)for(unsigned apply=0;apply<(type==1?2u:1u);apply++){
  memset(&m,0,sizeof(m));m.apply=apply;if(type==0)m.fail_read=n;if(type==1)m.fail_write=n;if(type==2)m.fail_guard=n;assert(run(&m,&r) && r.retained && !m.enabled);cases++;
 }
 memset(&m,0,sizeof(m));m.enabled=1;assert(run(&m,&r)==HCB_GUARD && !m.writes);cases++;
 memset(&m,0,sizeof(m));m.corrupt=1;assert(run(&m,&r)==HCB_VERIFY && m.writes==1 && !r.verified);cases++;
 printf("PASS: %u fixed SQE/AQE base-binding cases; four exact addresses/readbacks, SQE stays disabled, every read/write/guard failure and partial side effect retains backing; no CP command/enable/trust/PAS operation\n",cases);
}
