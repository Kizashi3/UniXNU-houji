// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include "GpuSmmuPrepare.h"
struct model {void *memory[2];uint64_t pa[2];unsigned alloc,validate,release,mode;};
static int allocate(void *cookie,unsigned pages,uint64_t *pa,void **cpu) {
  struct model *m=cookie;unsigned i=m->alloc++;
  assert(i<2 && pages==(i?1u:3u));
  if(m->mode==1+i)return 1;
  m->pa[i]=i?UINT64_C(0x88888000):UINT64_C(0x89999000);
  assert(!posix_memalign(&m->memory[i],4096,pages*4096));
  memset(m->memory[i],0xaa,pages*4096);*cpu=m->memory[i];
  if(m->mode==5 && !i)m->pa[i]++;
  if(m->mode==6 && i)m->pa[i]=m->pa[0]+4096;
  if(m->mode==7 && i)m->pa[i]=UINT64_C(1)<<36;
  if(m->mode==8 && i)*cpu=m->memory[0];
  *pa=m->pa[i];return 0;
}
static int validate(void *cookie,uint64_t pa,void *cpu,unsigned pages) {
  struct model *m=cookie;unsigned i=m->validate++;
  assert(i<2 && cpu==m->memory[i] && pa==m->pa[i] && pages==(i?1u:3u));
  return m->mode==3+i;
}
static int release(void *cookie,uint64_t pa,unsigned pages) {
  struct model *m=cookie;unsigned i=pages==1?1:0;m->release++;
  assert(pa==m->pa[i] && m->memory[i]);
  return m->mode==(i?9u:10u);
}
int main(void) {
  struct hgt_result r;unsigned cases=0;
  for(unsigned mode=0;mode<=10;mode++) {
    struct model m={0};m.mode=mode;
    const struct hgt_io io={&m,allocate,validate,release};
    unsigned result=hgt_prepare(&io,&r);
    if(!mode) {
      assert(result==HGT_OK && r.allocated==3 && r.validated==3 && r.released==3 && !r.retained);
      assert(r.table_pages==3 && r.leaf_pages==1 && r.descriptor_reads==1536);
      assert(((uint32_t *)m.memory[1])[0]==0x7504cafe);
    } else {
      assert(result!=HGT_OK);
      if(mode==1)assert(!r.allocated && !m.release);
      else if(mode==2)assert(r.allocated==1 && r.released==1 && m.release==1);
      else if(mode<=8)assert(r.allocated==3 && r.released==3 && !r.retained);
      else assert(result==HGT_FREE && r.retained==(mode==9?2u:1u));
    }
    for(unsigned i=0;i<2;i++)free(m.memory[i]);cases++;
  }
  uint64_t good=UINT64_C(0xff00000088888380);
  assert(hgt_page_attributes(good,0x88888000));cases++;
  for(unsigned bit=0;bit<64;bit++) {
    if(bit!=0 && !(bit>=7 && bit<=8) && !(bit>=12 && bit<=47) && bit<56)continue;
    assert(!hgt_page_attributes(good^(UINT64_C(1)<<bit),0x88888000));cases++;
  }
  assert(hgt_prepare(0,&r)==HGT_ARGUMENT);cases++;
  struct model m={0};struct hgt_owned owned={0};
  const struct hgt_io io={&m,allocate,validate,release};
  assert(hgt_prepare_owned(&io,&r,&owned)==HGT_OK && !m.release && r.retained==3);
  assert(owned.tables==m.memory[0] && owned.data==m.memory[1] && owned.built.leaf_pages==1);
  assert(!release(&m,owned.data_physical,1) && !release(&m,owned.table_physical,3));
  free(m.memory[0]);free(m.memory[1]);cases++;
  puts("PASS: actual native4K builder/1536-descriptor audit; allocator/mapping/36-bit/alias/free failures, PAR physical/cache/shareability refusal; no SMMU I/O");
  printf("%u cases\n",cases);
}
