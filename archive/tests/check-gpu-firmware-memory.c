// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include "GpuFirmwareMemory.h"
struct model {unsigned alloc,validate,publish,release,fail_alloc,fail_validate,fail_publish,fail_release;void *allocated[HFM_MAX+1];uint64_t pa[HFM_MAX+1];};
static int allocate(void*c,unsigned pages,uint64_t*pa,void**cpu) {
 struct model*m=c;unsigned n=m->alloc++;if(m->alloc==m->fail_alloc)return 1;
 assert(n<HFM_MAX+1 && pages<=HSC_LARGE_PAGES);assert(!posix_memalign(cpu,4096,pages*4096));m->allocated[n]=*cpu;m->pa[n]=*pa=0x80000000+0x800000*n;memset(*cpu,0xaa,pages*4096);return 0;
}
static int validate(void*c,uint64_t pa,void*cpu,unsigned pages,unsigned nc) {struct model*m=c;assert(pa && cpu && pages && nc<=1);return ++m->validate==m->fail_validate;}
static int publish(void*c,const struct hfm_allocation*a) {struct model*m=c;assert(a->pages && a->cpu && a->physical);return ++m->publish==m->fail_publish;}
static int release(void*c,uint64_t pa,void*cpu,unsigned pages) {struct model*m=c;m->release++;assert(cpu && pages);for(unsigned i=0;i<HFM_MAX+1;i++)if(m->pa[i]==pa){assert(cpu==m->allocated[i]);return m->release==m->fail_release;}assert(0);return 1;}
static void barrier(void*c){(*(unsigned*)c)++;}
static void destroy(struct model*m){for(unsigned i=0;i<HFM_MAX+1;i++)free(m->allocated[i]);}
int main(int argc,char**argv) {
 assert(argc==2);FILE*f=fopen(argv[1],"rb");assert(f);uint8_t*fw=malloc(HFM_FW_BYTES);assert(fread(fw,1,HFM_FW_BYTES,f)==HFM_FW_BYTES);assert(fgetc(f)==EOF);fclose(f);
 unsigned cases=0;
 for(unsigned kind=0;kind<=4;kind++)for(unsigned fault=0;fault<=HFM_MAX+1;fault++) {
  if(!kind && fault)continue;if(kind && !fault)continue;
  struct model m={0};if(kind==1)m.fail_alloc=fault;if(kind==2)m.fail_validate=fault;if(kind==3)m.fail_publish=fault;if(kind==4)m.fail_release=fault;
  const struct hfm_io io={&m,allocate,validate,publish,release};struct hfm_result r;
  unsigned code=hfm_prepare(&io,fw,HFM_FW_BYTES,&r);
  if(!kind || kind==4) {
   assert(!code && r.records==15 && r.count==HFM_MAX && r.reservations==5 && r.validated==HFM_ALL);
   assert(r.bytes_loaded==77808 && r.tcm_bytes_deferred==540 && r.hfi_queues==17 && r.hfi_initialized);
   assert(r.built.table_pages==6+3*HFM_WITH_SCRATCH && r.built.leaf_pages==139+HFM_WITH_SCRATCH*(2*HSC_POOL_PAGES+HSC_LARGE_PAGES) && r.audit.complete && r.audit.descriptor_reads==512*(6+3*HFM_WITH_SCRATCH));
   for(unsigned i=0;i<r.count;i++) {
    assert(r.ranges[i].permissions&ArmSmmu4KPrivileged);
    assert(!!(r.ranges[i].permissions&ArmSmmu4KExecute)==(i<4 || (HFM_WITH_SCRATCH && i==9)));
   }
   for(unsigned q=0;q<17;q++) {
    volatile uint32_t *head,*ring;unsigned rd,wr,barriers=0;
    struct ggh_io hfi={r.memory[5].cpu,GGH_BYTES,GGH_IOVA,&barriers,barrier};
    assert(!ggh_queue(&hfi,q,&head,&ring,&rd,&wr) && !rd && !wr && barriers==1);
    for(unsigned i=0;i<1024;i++)assert(!ring[i]);
   }
   code=hfm_release(&io,&r);assert((!code)==(!kind));
  } else assert(code);
  if(kind!=4)assert(!r.retained && r.released==r.allocated);
  else assert(r.retained && r.code==HFM_RELEASE);
  destroy(&m);cases++;
 }
 // Truncation never allocates; malformed opaque metadata cannot fabricate a RAM reservation.
 for(unsigned n=0;n<HFM_FW_BYTES;n++) {
  struct model m={0};struct hfm_result r;const struct hfm_io io={&m,allocate,validate,publish,release};
  assert(hfm_prepare(&io,fw,n,&r)==HFM_ARGUMENT && !m.alloc);cases++;
 }
 uint8_t before=fw[12];fw[12]^=1;
 struct model m={0};struct hfm_result r;const struct hfm_io io={&m,allocate,validate,publish,release};
 assert(hfm_prepare(&io,fw,HFM_FW_BYTES,&r)==HFM_PLAN && !m.alloc);fw[12]=before;cases++;
 free(fw);printf("PASS: %u firmware memory cases; actual pinned file, independent planners, all 17 HFI headers/rings, actual physical table audit, each allocation/attribute/publication/free failure\n",cases);
}
