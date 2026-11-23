// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <assert.h>
#include <stdio.h>
#include "GpuSmmuPlatform.h"
struct model {unsigned reads,guards,fail_read,fail_guard,changed,foreign,seen[3];};
static int read32(void *c,uint32_t a,uint32_t *v) {
  struct model *m=c;if(++m->reads==m->fail_read)return 1;
  switch(a) {
    case 0x3da0020:*v=0x4c017e18;return 0;
    case 0x3da0024:*v=0x40000016;return 0;
    case 0x3da0028:*v=0x5511;return 0;
    case 0x3da0048:*v=0;return 0;
    case HGP_CB(0x4):case 0x3da6008:case 0x3da600c: {
      unsigned i=a==HGP_CB(0x4)?0:(a==0x3da6008?1:2);m->seen[i]++;
      *v=0x123400+i;
      if(m->changed==i+1 && m->seen[i]==2)*v^=1;
      return 0;
    }
    default:break;
  }
  if(a>=0x3da0800 && a<0x3da0860 && !(a&3)) {
    *v=(m->foreign && m->guards>=2)?0x80000005:0;return 0;
  }
  if(a>=0x3da0c00 && a<0x3da0c60 && !(a&3)){*v=0x20000;return 0;}
  if(a>=0x3dc0000 && a<=0x3dd5000 && !(a&4095)){*v=0x3fdde71e;return 0;}
  assert(0);return 1;
}
static int guard(void *c) {struct model *m=c;return ++m->guards==m->fail_guard;}
static unsigned run(struct model *m,struct hgs_result *r) {
  const struct hgp_io io={.cookie=m,.read32=read32,.power_guard=guard};
  // NO write, wide-read, delay or filesystem callback exists in this test.
  return hgs_snapshot(&io,r);
}
int main(void) {
  struct model m={0};struct hgs_result r;unsigned cases=0;
  assert(!run(&m,&r) && r.stable && r.reads==228 && m.guards==3);
  assert(r.actlr==0x123400 && r.prr_low==0x123401 && r.prr_high==0x123402);cases++;
  for(unsigned i=1;i<=228;i++) {
    m=(struct model){.fail_read=i};assert(run(&m,&r)==HGP_IO && !r.stable);cases++;
  }
  for(unsigned i=1;i<=3;i++) {
    m=(struct model){.fail_guard=i};assert(run(&m,&r)==HGP_GUARD && !r.stable);cases++;
    m=(struct model){.changed=i};assert(run(&m,&r)==HGP_GUARD && !r.stable);cases++;
  }
  m=(struct model){.foreign=1};assert(run(&m,&r)==HGP_GUARD && !r.stable);cases++;
  assert(hgs_snapshot(0,&r)==HGP_ARGUMENT);cases++;
  printf("PASS: %u cases; platform observation only, 3 full cold-owner surveys, every read/guard failure and unstable values refused\n",cases);
}
