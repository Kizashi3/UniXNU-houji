// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include "GpuCachePublish.h"
struct model {
  struct hgt_owned *owned;
  unsigned line,validates,cleans,barriers,fail_validate,fail_clean,fail_barrier,mutate;
};
static int validate(void *c,uint64_t pa,void *cpu,unsigned pages) {
  struct model *m=c;unsigned i=++m->validates;
  assert(!m->cleans && !m->barriers && i<=2);
  assert(pa==(i==1?m->owned->table_physical:m->owned->data_physical));
  assert(cpu==(i==1?m->owned->tables:m->owned->data) && pages==(i==1?3u:1u));
  return m->fail_validate==i;
}
static int clean(void *c,uintptr_t address) {
  struct model *m=c;unsigned i=m->cleans++;
  assert(m->validates==2 && !m->barriers);
  uintptr_t expected=i<12288/m->line?(uintptr_t)m->owned->tables+i*m->line:
    (uintptr_t)m->owned->data+(i-12288/m->line)*m->line;
  assert(address==expected && i<16384/m->line);
  if(m->cleans==16384/m->line) {
    if(m->mutate==1)((uint64_t *)m->owned->tables)[0]^=1;
    if(m->mutate==2)((uint32_t *)m->owned->data)[800]^=1;
  }
  return m->fail_clean==m->cleans;
}
static int barrier(void *c) {
  struct model *m=c;assert(m->cleans==16384/m->line && !m->barriers);
  m->barriers++;return m->fail_barrier;
}
static unsigned run(struct model *m,unsigned log,struct hgc_result *r) {
  const struct hgc_io io={m,validate,clean,barrier};m->line=4u<<log;
  return hgc_publish(&io,m->owned,(uint64_t)log<<16,r);
}
static void fill(struct hgt_owned *o) {
  memset(o->data,0,4096);((uint32_t *)o->data)[0]=0x7504cafe;((uint32_t *)o->data)[1]=0x86500071;
  assert(!ArmSmmu4KBuild(&o->config,&o->range,1,o->tables,3,&o->built));
}
int main(void) {
  struct hgt_owned o={0};assert(!posix_memalign(&o.tables,4096,12288));
  assert(!posix_memalign(&o.data,4096,4096));
  o.table_physical=0x89999000;o.data_physical=0x88888000;
  o.config=(ArmSmmu4KConfig){32,36,o.table_physical,1};
  o.range=(ArmSmmu4KRange){0x60000000,o.data_physical,4096,3,1,3};fill(&o);
  struct hgc_result r;unsigned cases=0;
  for(unsigned log=0;log<16;log++) {
    struct model m={.owned=&o};unsigned result=run(&m,log,&r);
    if(log<2 || log>10)assert(result==HGC_ARGUMENT && !m.validates && !m.cleans);
    else assert(!result && r.cleaned_lines==16384/m.line && r.barriers==1 &&
      r.audits==2 && r.descriptor_reads==3072 && r.validated==3);
    cases++;
  }
  for(unsigned fail=1;fail<=2;fail++) {
    struct model m={.owned=&o,.fail_validate=fail};
    assert(run(&m,4,&r)==HGC_VALIDATE && !m.cleans && !m.barriers);cases++;
  }
  for(unsigned fail=1;fail<=256;fail++) {
    struct model m={.owned=&o,.fail_clean=fail};
    assert(run(&m,4,&r)==HGC_CLEAN && r.cleaned_lines==fail-1 && !m.barriers);cases++;
  }
  struct model m={.owned=&o,.fail_barrier=1};
  assert(run(&m,4,&r)==HGC_BARRIER && !r.barriers && r.audits==1);cases++;
  for(unsigned mutate=1;mutate<=2;mutate++) {
    m=(struct model){.owned=&o,.mutate=mutate};
    assert(run(&m,4,&r)==HGC_CONTENT && r.barriers==1 && r.audits==2);fill(&o);cases++;
  }
  for(unsigned i=0;i<1024;i++) {
    ((uint32_t *)o.data)[i]^=1;m=(struct model){.owned=&o};
    assert(run(&m,4,&r)==HGC_CONTENT && !m.cleans);
    ((uint32_t *)o.data)[i]^=1;cases++;
  }
  for(unsigned field=0;field<11;field++) {
    struct hgt_owned bad=o;
    switch(field) {
      case 0:bad.tables=0;break;
      case 1:bad.data=bad.tables;break;
      case 2:bad.table_physical++;break;
      case 3:bad.data_physical=bad.table_physical+4096;break;
      case 4:bad.config.input_bits=48;break;
      case 5:bad.config.output_bits=48;break;
      case 6:bad.config.leaf_budget=2;break;
      case 7:bad.built.upper_region=1;break;
      case 8:bad.range.permissions|=ArmSmmu4KExecute;break;
      case 9:bad.range.writeback=0;break;
      case 10:bad.data_physical=UINT64_C(1)<<36;break;
    }
    m=(struct model){.owned=&bad};assert(run(&m,4,&r)==HGC_ARGUMENT && !m.validates);cases++;
  }
  assert(hgc_publish(0,&o,0,&r)==HGC_ARGUMENT);cases++;
  free(o.tables);free(o.data);
  printf("PASS: %u cases; exact owned cache-line coverage, geometry, failed maintenance, full descriptor/data integrity before and after publication; no device DMA claim\n",cases);
}
