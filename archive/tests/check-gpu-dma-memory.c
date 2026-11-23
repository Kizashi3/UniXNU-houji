// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "GpuDmaMemory.h"
struct model {struct hgt_owned owned;uint32_t device[1024];unsigned line,invalidated,cleaned,barriers,step,fail_step;};
static int invalidate(void*c,uintptr_t at) {
  struct model*m=c;if(++m->step==m->fail_step)return 1;
  assert(m->barriers==1 && !m->cleaned);
  assert(at==(uintptr_t)m->owned.data+m->invalidated*m->line);
  memcpy((void*)at,(char*)m->device+m->invalidated*m->line,m->line);m->invalidated++;return 0;
}
static int clean(void*c,uintptr_t at) {
  struct model*m=c;if(++m->step==m->fail_step)return 1;
  assert(m->barriers==2 && m->invalidated==4096/m->line);
  assert(at==(uintptr_t)m->owned.data+m->cleaned*m->line);
  memcpy((char*)m->device+m->cleaned*m->line,(void*)at,m->line);m->cleaned++;return 0;
}
static int barrier(void*c){struct model*m=c;if(++m->step==m->fail_step)return 1;m->barriers++;return 0;}
static void fill(struct model*m,void*page) {
  memset(m,0,sizeof(*m));m->owned.data=page;m->line=64;memset(page,0,4096);
  ((uint32_t*)page)[0]=0x7504cafe;((uint32_t*)page)[1]=0x86500071;
  memcpy(m->device,page,4096);m->device[2]=0xa750cafe;
}
static int run(struct model*m,struct hga_cpu_result*r){struct hga_cpu_io io={m,m->line,invalidate,clean,barrier};return hga_cpu_finish(&io,&m->owned,r);}
int main(void) {
  void*page=0;assert(!posix_memalign(&page,4096,4096));struct model m;struct hga_cpu_result r;unsigned cases=0;
  fill(&m,page);assert(!run(&m,&r) && r.verified && r.restored && r.observed==0xa750cafe);
  assert(r.invalidated==64 && r.cleaned==64 && r.barriers==3 && !m.device[2]);unsigned steps=m.step;cases++;
  for(unsigned i=1;i<=steps;i++){fill(&m,page);m.fail_step=i;assert(run(&m,&r) && !r.restored);cases++;}
  for(unsigned i=0;i<1024;i++){fill(&m,page);m.device[i]^=1;assert(run(&m,&r) && !r.verified && !m.cleaned);cases++;}
  for(unsigned line=16;line<=4096;line*=2){fill(&m,page);m.line=line;assert(!run(&m,&r) && r.invalidated==4096/line);cases++;}
  const unsigned invalid[]={0,4,8,24,8192};
  for(unsigned i=0;i<5;i++){fill(&m,page);m.line=invalid[i];assert(run(&m,&r) && !m.step);cases++;}
  free(page);printf("PASS: %u cases; actual CPU IVAC/marker verification/restore policy, all maintenance failures, every data word corruption, checked owned line geometry\n",cases);
}
