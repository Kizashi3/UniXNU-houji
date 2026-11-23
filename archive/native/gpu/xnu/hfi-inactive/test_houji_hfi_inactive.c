/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#define _POSIX_C_SOURCE 200112L
#include "houji_hfi_inactive.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum {HFM_ALLOC_ERROR=3,HFM_MAPPING_ERROR=4,HFM_RELEASE_ERROR=7};
static unsigned checks;
#define CHECK(e) do {++checks;if(!(e)){fprintf(stderr,"FAIL %s:%u: %s\n",__FILE__,__LINE__,#e);abort();}}while(0)
struct Buffer {void *cpu,*reported_cpu;uint64_t pa,reported_pa;size_t logical,owned;unsigned nc,released,attr_changed;};
struct Model {
    HhiStorage storage;
    struct Buffer bo[9];
    unsigned alloc_calls,validate_calls,publish_calls,release_calls;
    unsigned fail_alloc,fail_validate,fail_publish;
    uint32_t fail_release_slots;
    unsigned partial_allocate,partial_validate,reentrant,reentry_checks;
    unsigned bad_output_kind,bad_output_at;
    unsigned corrupt_publish,corrupt_slot,corrupt_offset;
    unsigned release_order[64],release_count;
};
static HhiCallbacks callbacks(struct Model *);
static HhiSummary summary(struct Model *m) {
    HhiSummary s;CHECK(hhi_summary(&m->storage,sizeof m->storage,&s,sizeof s)==HHI_OK);return s;
}
static HhiRow row(struct Model *m,unsigned i) {
    HhiRow r;CHECK(hhi_row(&m->storage,sizeof m->storage,i,&r,sizeof r)==HHI_OK);return r;
}
static void reenter(struct Model *m) {
    if(!m->reentrant)return;
    HhiSummary s;HhiRow r;uint32_t code=0xfeed;
    CHECK(hhi_summary(&m->storage,sizeof m->storage,&s,sizeof s)==HHI_BUSY);
    CHECK(hhi_row(&m->storage,sizeof m->storage,0,&r,sizeof r)==HHI_BUSY);
    CHECK(hhi_prepare(&m->storage,sizeof m->storage,NULL,0,&code)==HHI_BUSY);
    CHECK(hhi_release(&m->storage,sizeof m->storage,&code)==HHI_BUSY);
    CHECK(hhi_verify_contents(&m->storage,sizeof m->storage,NULL,0,&code)==HHI_BUSY);
    HhiCallbacks io=callbacks(m);CHECK(hhi_init(&m->storage,sizeof m->storage,&io,sizeof io)==HHI_BUSY);
    CHECK(code==0xfeed);++m->reentry_checks;
}
static int alloc(void *c,uint32_t pages,uint64_t *pa,void **cpu) {
    struct Model *m=c;const unsigned i=m->alloc_calls++;CHECK(i<9 && pages && !*pa && !*cpu);reenter(m);
    if(m->fail_alloc==i+1 && !m->partial_allocate)return 1;
    struct Buffer *b=&m->bo[i];b->logical=(size_t)pages*4096;b->owned=(b->logical+16383)&~(size_t)16383;
    CHECK(!posix_memalign(&b->cpu,16384,b->owned));memset(b->cpu,0,b->owned);
    b->pa=UINT64_C(0x800000000)+(uint64_t)i*0x100000;b->reported_pa=b->pa;b->reported_cpu=b->cpu;
    if(m->bad_output_at==i+1)switch(m->bad_output_kind) {
        case 1:b->reported_pa=0;break;
        case 2:b->reported_cpu=NULL;break;
        case 3:b->reported_pa+=1;break;
        case 4:b->reported_cpu=(unsigned char*)b->cpu+1;break;
        case 5:b->reported_pa=UINT64_C(1)<<36;break;
        case 6:b->reported_pa=m->bo[0].pa;break;
        case 7:b->reported_cpu=m->bo[0].cpu;break;
        case 8:b->reported_pa=m->bo[0].pa;b->reported_cpu=m->bo[0].cpu;break;
        default:CHECK(0);
    }
    *pa=b->reported_pa;*cpu=b->reported_cpu;
    return m->fail_alloc==i+1;
}
static unsigned find(struct Model *m,uint64_t pa,void *cpu,uint32_t pages) {
    for(unsigned i=0;i<9;++i)if(m->bo[i].reported_pa==pa && m->bo[i].reported_cpu==cpu && m->bo[i].logical==(size_t)pages*4096)return i;
    CHECK(0);return 0;
}
static int validate(void *c,uint64_t pa,void *cpu,uint32_t pages,uint32_t nc) {
    struct Model *m=c;unsigned i=find(m,pa,cpu,pages);CHECK(!m->bo[i].released && nc<=1);reenter(m);
    m->bo[i].nc=nc;++m->validate_calls;
    if(nc)m->bo[i].attr_changed=1; /* models a partial CPU attribute mutation */
    return m->fail_validate==m->validate_calls;
}
static int publish(void *c,const HhiAllocation *a) {
    struct Model *m=c;unsigned i=find(m,a->physical,a->cpu,a->gpu4k_pages);CHECK(!a->reserved && !m->bo[i].released);reenter(m);
    CHECK(a->normal_nc==m->bo[i].nc);++m->publish_calls;
    if(m->corrupt_publish==m->publish_calls) {
        CHECK(m->corrupt_slot<8 && m->corrupt_offset<m->bo[m->corrupt_slot].logical);
        ((unsigned char*)m->bo[m->corrupt_slot].cpu)[m->corrupt_offset]^=1;
    }
    return m->fail_publish==m->publish_calls;
}
static int release(void *c,uint64_t pa,void *cpu,uint32_t pages) {
    struct Model *m=c;unsigned i=9;
    while(i){--i;if(m->bo[i].cpu && !m->bo[i].released && m->bo[i].reported_pa==pa && m->bo[i].reported_cpu==cpu && m->bo[i].logical==(size_t)pages*4096)break;}
    CHECK(m->bo[i].cpu && !m->bo[i].released && m->release_count<64);reenter(m);
    ++m->release_calls;m->release_order[m->release_count++]=i;
    if(m->fail_release_slots&(1u<<i))return 1;
    m->bo[i].attr_changed=0;m->bo[i].released=1;free(m->bo[i].cpu);
    /* Intentionally keep the stale address in the host ledger, like upstream;
     * every access site must first establish !released. */
    return 0;
}
static HhiCallbacks callbacks(struct Model *m) {
    const HhiCallbacks io={HHI_ABI_VERSION,0,m,alloc,validate,publish,release};return io;
}
static void init(struct Model *m) {
    HhiCallbacks io=callbacks(m);CHECK(hhi_init(&m->storage,sizeof m->storage,&io,sizeof io)==HHI_OK);
}
static uint32_t prepare(struct Model *m,const uint8_t *fw) {
    uint32_t code=0xffffffff;CHECK(hhi_prepare(&m->storage,sizeof m->storage,fw,HHI_FIRMWARE_BYTES,&code)==HHI_OK);return code;
}
static void finish(struct Model *m) {
    /* Used only by the host harness for an allocation whose callback violated
     * the no-transfer-on-failure contract. The bridge never fabricates a free. */
    for(unsigned i=0;i<9;++i)if(m->bo[i].cpu && !m->bo[i].released){free(m->bo[i].cpu);m->bo[i].released=1;}
}
static void rejected_api(const uint8_t *fw) {
    struct Model m={0};HhiCallbacks io=callbacks(&m);HhiSummary s;HhiRow r;uint32_t code=99;
    CHECK(sizeof(HhiStorage)==HHI_STORAGE_BYTES && _Alignof(HhiStorage)==HHI_STORAGE_ALIGNMENT);
    CHECK(hhi_actual_state_size()<=HHI_STORAGE_BYTES && hhi_actual_state_alignment()==HHI_STORAGE_ALIGNMENT);
    CHECK(hhi_storage_size()==sizeof m.storage && hhi_storage_alignment()==_Alignof(HhiStorage));
    CHECK(hhi_summary(&m.storage,sizeof m.storage,&s,sizeof s)==HHI_UNINITIALIZED);
    CHECK(hhi_prepare(&m.storage,sizeof m.storage,fw,HHI_FIRMWARE_BYTES,&code)==HHI_UNINITIALIZED);
    CHECK(hhi_release(&m.storage,sizeof m.storage,&code)==HHI_UNINITIALIZED);
    CHECK(hhi_verify_contents(&m.storage,sizeof m.storage,fw,HHI_FIRMWARE_BYTES,&code)==HHI_UNINITIALIZED);
    CHECK(hhi_init(NULL,sizeof m.storage,&io,sizeof io)==HHI_ARGUMENT);
    CHECK(hhi_init(&m.storage,sizeof m.storage-1,&io,sizeof io)==HHI_ARGUMENT);
    CHECK(hhi_init(&m.storage,sizeof m.storage+1,&io,sizeof io)==HHI_ARGUMENT);
    unsigned char unaligned[HHI_STORAGE_BYTES+16];
    uintptr_t aligned=((uintptr_t)unaligned+15)&~(uintptr_t)15;
    CHECK(hhi_init((void*)(aligned+1),HHI_STORAGE_BYTES,&io,sizeof io)==HHI_ALIGNMENT);
    CHECK(hhi_init(&m.storage,sizeof m.storage,NULL,sizeof io)==HHI_ARGUMENT);
    CHECK(hhi_init(&m.storage,sizeof m.storage,&io,sizeof io-1)==HHI_ARGUMENT);
    HhiStorage nonzero;memset(&nonzero,0xa5,sizeof nonzero);
    CHECK(hhi_init(&nonzero,sizeof nonzero,&io,sizeof io)==HHI_UNINITIALIZED);
    CHECK(hhi_init(&m.storage,sizeof m.storage,(const HhiCallbacks*)(aligned+1),sizeof io)==HHI_ALIGNMENT);
    ++io.abi_version;CHECK(hhi_init(&m.storage,sizeof m.storage,&io,sizeof io)==HHI_ARGUMENT);io.abi_version=HHI_ABI_VERSION;
    io.reserved=1;CHECK(hhi_init(&m.storage,sizeof m.storage,&io,sizeof io)==HHI_ARGUMENT);io.reserved=0;
    HhiCallbacks bad=io;bad.allocate=NULL;CHECK(hhi_init(&m.storage,sizeof m.storage,&bad,sizeof bad)==HHI_ARGUMENT);
    bad=io;bad.validate=NULL;CHECK(hhi_init(&m.storage,sizeof m.storage,&bad,sizeof bad)==HHI_ARGUMENT);
    bad=io;bad.publish=NULL;CHECK(hhi_init(&m.storage,sizeof m.storage,&bad,sizeof bad)==HHI_ARGUMENT);
    bad=io;bad.release=NULL;CHECK(hhi_init(&m.storage,sizeof m.storage,&bad,sizeof bad)==HHI_ARGUMENT);
    init(&m);CHECK(hhi_init(&m.storage,sizeof m.storage,&io,sizeof io)==HHI_ALREADY_PREPARED);
    CHECK(hhi_release(&m.storage,sizeof m.storage,&code)==HHI_NOT_PREPARED);
    CHECK(hhi_verify_contents(&m.storage,sizeof m.storage,fw,HHI_FIRMWARE_BYTES,&code)==HHI_NOT_PREPARED);
    CHECK(hhi_prepare(&m.storage,sizeof m.storage,fw,HHI_FIRMWARE_BYTES-1,&code)==HHI_ARGUMENT);
    CHECK(hhi_prepare(&m.storage,sizeof m.storage,NULL,HHI_FIRMWARE_BYTES,&code)==HHI_ARGUMENT);
    CHECK(hhi_prepare(&m.storage,sizeof m.storage,fw,HHI_FIRMWARE_BYTES,NULL)==HHI_ARGUMENT);
    CHECK(hhi_prepare(&m.storage,sizeof m.storage,fw,HHI_FIRMWARE_BYTES,(uint32_t*)m.storage.bytes)==HHI_ARGUMENT);
    CHECK(hhi_summary(&m.storage,sizeof m.storage,&s,sizeof s-1)==HHI_ARGUMENT);
    CHECK(hhi_summary(&m.storage,sizeof m.storage,(HhiSummary*)m.storage.bytes,sizeof s)==HHI_ARGUMENT);
    CHECK(hhi_row(&m.storage,sizeof m.storage,9,&r,sizeof r)==HHI_ARGUMENT);
    CHECK(hhi_row(&m.storage,sizeof m.storage,0,&r,sizeof r-1)==HHI_ARGUMENT);
    unsigned char output[sizeof(HhiSummary)+16];uintptr_t output_aligned=((uintptr_t)output+15)&~(uintptr_t)15;
    CHECK(hhi_summary(&m.storage,sizeof m.storage,(HhiSummary*)(output_aligned+1),sizeof s)==HHI_ALIGNMENT);
    CHECK(hhi_row(&m.storage,sizeof m.storage,0,(HhiRow*)(output_aligned+1),sizeof r)==HHI_ALIGNMENT);
    CHECK(hhi_prepare(&m.storage,sizeof m.storage,fw,HHI_FIRMWARE_BYTES,(uint32_t*)(output_aligned+1))==HHI_ALIGNMENT);
    CHECK(hhi_release(&m.storage,sizeof m.storage,(uint32_t*)(output_aligned+1))==HHI_ALIGNMENT);
    CHECK(hhi_release(&m.storage,sizeof m.storage,(uint32_t*)m.storage.bytes)==HHI_ARGUMENT);
    CHECK(code==99 && !m.alloc_calls && !summary(&m).prepare_called);
}
static void baseline(const uint8_t *fw) {
    struct Model m={0};init(&m);m.reentrant=1;CHECK(!prepare(&m,fw));HhiSummary s=summary(&m);
    CHECK(!s.hfm_code && !s.first_prepare_error && s.records==15 && s.reservations==5 && s.count==8);
    CHECK(s.allocated==0x1ff && s.validated==0x1ff && !s.released && s.retained==0x1ff);
    CHECK(s.bytes_loaded==77808 && s.tcm_bytes_deferred==540 && s.hfi_queues==17 && s.hfi_initialized==1 && s.published==1);
    CHECK(s.input_bits==32 && s.output_bits==36 && s.leaf_budget==2048 && s.start_level==1 && !s.upper_region);
    CHECK(!s.build_status && !s.audit_status && s.built_table_pages==6 && s.built_leaf_pages==139 && s.audit_complete==1);
    CHECK(s.audit_table_pages==6 && s.audit_leaf_pages==139 && s.audit_descriptor_reads==3072);
    CHECK(s.allocate_trace.calls==9 && s.validate_trace.calls==9 && s.publish_trace.calls==9 && !s.release_trace.calls);
    static const uint32_t pages[9]={19,27,19,37,2,18,16,1,10};
    static const uint32_t iovas[9]={0x4000,0x100000,0x200000,0x300000,0x60000000,0x60010000,0x60030000,0x60040000,0};
    size_t total=0,owned=0;
    for(unsigned i=0;i<9;++i) {
        HhiRow r=row(&m,i);CHECK(r.index==i && r.planned && r.allocated && r.validated && r.retained && !r.released);
        CHECK(r.allocation.gpu4k_pages==pages[i] && r.allocation.iova==iovas[i] && !r.allocation.reserved);
        CHECK(r.allocation.physical==m.bo[i].pa && r.allocation.cpu==m.bo[i].cpu);
        CHECK(r.allocation.normal_nc==(i>=5 && i<=7));total+=m.bo[i].logical;owned+=m.bo[i].owned;
        for(size_t j=m.bo[i].logical;j<m.bo[i].owned;++j)CHECK(((const unsigned char*)m.bo[i].cpu)[j]==0);
        if(i<8)CHECK(r.range_initialized && !r.is_table && r.range.iova==iovas[i] && r.range.physical==m.bo[i].pa &&
            r.range.bytes==m.bo[i].logical && r.range.permissions==(i<4?15u:11u) && r.range.writeback==(i<5) && r.range.shareability==3);
        else {CHECK(r.is_table && !r.range_initialized);for(size_t j=6*4096;j<m.bo[i].logical;++j)CHECK(((const unsigned char*)m.bo[i].cpu)[j]==0);}
    }
    CHECK(total==610304 && owned==671744 && s.root_physical==m.bo[8].pa && s.table_physical==m.bo[8].pa);
    CHECK(!memcmp(m.bo[0].cpu,fw+684,77808));
    uint32_t verified=99;
    CHECK(hhi_verify_contents(&m.storage,sizeof m.storage,fw,HHI_FIRMWARE_BYTES,&verified)==HHI_OK && !verified);
    CHECK(hhi_verify_contents(&m.storage,sizeof m.storage,fw,HHI_FIRMWARE_BYTES,(uint32_t*)m.bo[5].cpu)==HHI_ARGUMENT);
    const uint32_t *hfi=m.bo[5].cpu;CHECK(hfi[1]==210 && hfi[2]==6 && hfi[3]==12 && hfi[4]==17 && hfi[5]==17);
    for(unsigned q=0;q<17;++q) {
        const uint32_t *h=hfi+6+12*q;CHECK(h[0]==1 && h[1]==0x60010000+848+4096*q && h[3]==1024 && !h[10] && !h[11]);
        const uint32_t *ring=(const uint32_t*)((const unsigned char*)hfi+848)+q*1024;for(unsigned j=0;j<1024;++j)CHECK(!ring[j]);
    }
    uint32_t code=33;HhiCallbacks io=callbacks(&m);
    CHECK(hhi_prepare(&m.storage,sizeof m.storage,fw,HHI_FIRMWARE_BYTES,&code)==HHI_ALREADY_PREPARED && code==33);
    CHECK(hhi_init(&m.storage,sizeof m.storage,&io,sizeof io)==HHI_OWNERS_REMAIN);
    HhiStorage copied;memcpy(&copied,&m.storage,sizeof copied);HhiSummary copied_summary;
    CHECK(hhi_summary(&copied,sizeof copied,&copied_summary,sizeof copied_summary)==HHI_UNINITIALIZED);
    CHECK(hhi_release(&copied,sizeof copied,&code)==HHI_UNINITIALIZED);
    CHECK(hhi_init(&copied,sizeof copied,&io,sizeof io)==HHI_UNINITIALIZED);
    CHECK(hhi_release(&m.storage,sizeof m.storage,&code)==HHI_OK && !code);
    verified=99;CHECK(hhi_verify_contents(&m.storage,sizeof m.storage,fw,HHI_FIRMWARE_BYTES,&verified)==HHI_NOT_PREPARED && verified==99);
    s=summary(&m);CHECK(s.released==0x1ff && !s.retained && m.release_calls==9 && m.reentry_checks==36);
    for(unsigned i=0;i<9;++i){CHECK(m.release_order[i]==8-i);HhiRow r=row(&m,i);CHECK(r.released && !r.retained && r.allocation.cpu==m.bo[i].cpu);}
    CHECK(hhi_release(&m.storage,sizeof m.storage,&code)==HHI_OK && m.release_calls==9);
    CHECK(hhi_init(&m.storage,sizeof m.storage,&io,sizeof io)==HHI_OK && !summary(&m).allocated);
}
static void callback_failures(const uint8_t *fw) {
    for(unsigned kind=0;kind<3;++kind)for(unsigned at=1;at<=9;++at) {
        struct Model m={0};init(&m);if(kind==0)m.fail_alloc=at;else if(kind==1)m.fail_validate=at;else m.fail_publish=at;
        CHECK(prepare(&m,fw)==(kind==0?HFM_ALLOC_ERROR:HFM_MAPPING_ERROR));HhiSummary s=summary(&m);
        const unsigned n=kind==0?at-1:kind==1?at:9,mask=(1u<<n)-1;
        CHECK(s.allocated==mask && s.released==mask && !s.retained && m.release_calls==n);
        CHECK(s.validated==(kind==1?((1u<<(at-1))-1):mask));
        CHECK(s.first_prepare_error==(kind==0?HFM_ALLOC_ERROR:HFM_MAPPING_ERROR));
        uint32_t verified=99;CHECK(hhi_verify_contents(&m.storage,sizeof m.storage,fw,HHI_FIRMWARE_BYTES,&verified)==HHI_NOT_PREPARED && verified==99);
        CHECK(!s.published && s.publish_trace.calls==(kind==2?at:0));
        CHECK(s.allocate_trace.failure_mask==(kind==0?(1u<<(at-1)):0));
        CHECK(s.validate_trace.failure_mask==(kind==1?(1u<<(at-1)):0));
        CHECK(s.publish_trace.failure_mask==(kind==2?(1u<<(at-1)):0));
        for(unsigned i=0;i<n;++i)CHECK(m.release_order[i]==n-1-i && !m.bo[i].attr_changed);
        uint32_t out=55;CHECK(hhi_prepare(&m.storage,sizeof m.storage,fw,HHI_FIRMWARE_BYTES,&out)==HHI_ALREADY_PREPARED && out==55);
        CHECK(hhi_release(&m.storage,sizeof m.storage,&out)==HHI_OK && m.release_calls==n);finish(&m);
    }
    for(unsigned at=0;at<9;++at) {
        struct Model m={0};init(&m);CHECK(!prepare(&m,fw));m.fail_release_slots=1u<<at;uint32_t code=0;
        CHECK(hhi_release(&m.storage,sizeof m.storage,&code)==HHI_OK && code==HFM_RELEASE_ERROR);HhiSummary s=summary(&m);
        CHECK(s.retained==(1u<<at) && s.released==(0x1ffu^(1u<<at)) && s.release_trace.failure_mask==(1u<<at));
        CHECK(!s.first_prepare_error && !s.prepare_return_code && !m.bo[at].released);
        const unsigned calls=m.release_calls;m.fail_release_slots=0;CHECK(hhi_release(&m.storage,sizeof m.storage,&code)==HHI_OK);
        s=summary(&m);CHECK(code==HFM_RELEASE_ERROR && !s.retained && s.released==0x1ff && m.release_calls==calls+1 && m.release_order[calls]==at);finish(&m);
    }
    {struct Model m={0};init(&m);CHECK(!prepare(&m,fw));m.fail_release_slots=(1u<<2)|(1u<<7);uint32_t code;
     CHECK(hhi_release(&m.storage,sizeof m.storage,&code)==HHI_OK);CHECK(summary(&m).retained==m.fail_release_slots);
     m.fail_release_slots=0;CHECK(hhi_release(&m.storage,sizeof m.storage,&code)==HHI_OK);
     CHECK(m.release_order[9]==7 && m.release_order[10]==2 && !summary(&m).retained);finish(&m);}
    {struct Model m={0};init(&m);m.fail_validate=6;m.fail_release_slots=1u<<5;CHECK(prepare(&m,fw)==HFM_RELEASE_ERROR);
     HhiSummary s=summary(&m);CHECK(s.first_prepare_error==HFM_MAPPING_ERROR && s.prepare_return_code==HFM_RELEASE_ERROR && s.retained==(1u<<5));
     CHECK(m.bo[5].attr_changed && !m.bo[5].released);m.fail_release_slots=0;uint32_t code;CHECK(hhi_release(&m.storage,sizeof m.storage,&code)==HHI_OK);
     CHECK(!summary(&m).retained && !m.bo[5].attr_changed);finish(&m);}
    {struct Model m={0};init(&m);m.fail_alloc=3;m.partial_allocate=1;CHECK(prepare(&m,fw)==HFM_ALLOC_ERROR);HhiSummary s=summary(&m);
     CHECK(s.allocated==3 && s.released==3 && !s.retained && s.uncertain_allocate_outputs==4 && !m.bo[2].released);
     HhiRow r=row(&m,2);CHECK(!r.allocated && !r.released && !r.retained && r.allocation.cpu==m.bo[2].cpu);
     HhiCallbacks io=callbacks(&m);CHECK(hhi_init(&m.storage,sizeof m.storage,&io,sizeof io)==HHI_OWNERS_REMAIN);finish(&m);}
}
static void malformed(const uint8_t *fw) {
    uint8_t *bad=malloc(HHI_FIRMWARE_BYTES);CHECK(bad);memcpy(bad,fw,HHI_FIRMWARE_BYTES);bad[12]^=1;
    struct Model m={0};init(&m);CHECK(prepare(&m,bad)==2);HhiSummary s=summary(&m);CHECK(!s.allocated && !s.retained && !m.alloc_calls && s.first_prepare_error==2);free(bad);
}
static void malformed_success_outputs(const uint8_t *fw) {
    for(unsigned kind=1;kind<=8;++kind) {
        struct Model m={0};init(&m);m.bad_output_kind=kind;m.bad_output_at=3;
        CHECK(prepare(&m,fw)==HFM_MAPPING_ERROR);HhiSummary s=summary(&m);
        CHECK(s.allocated==7 && s.validated==3 && s.released==7 && !s.retained && s.first_prepare_error==HFM_MAPPING_ERROR);
        CHECK(s.release_trace.attempted_mask==7 && s.release_trace.success_mask==7 && s.release_trace.calls==3);
        CHECK(m.release_order[0]==2 && m.release_order[1]==1 && m.release_order[2]==0);
        finish(&m);
    }
}
static void content_result(struct Model *m,const uint8_t *fw,unsigned expected) {
    HhiStorage before;memcpy(&before,&m->storage,sizeof before);
    const unsigned calls=m->alloc_calls+m->validate_calls+m->publish_calls+m->release_calls;
    uint32_t code=99;CHECK(hhi_verify_contents(&m->storage,sizeof m->storage,fw,HHI_FIRMWARE_BYTES,&code)==HHI_OK && code==expected);
    CHECK(!memcmp(&before,&m->storage,sizeof before));
    CHECK(calls==m->alloc_calls+m->validate_calls+m->publish_calls+m->release_calls);
}
static void content_corruption(const uint8_t *fw) {
    /* Exercise every publication boundary after payload/queue initialization.
     * The original table audit passes these data-only mutations. The verifier
     * must detect them without repairing memory or invoking any callback. */
    static const struct {unsigned slot,offset,code;} changes[]={
        {0,0,2},{0,77807,2},{0,77808,3},{1,0,3},{2,19*4096-1,3},
        {3,37*4096-1,3},{4,2*4096-1,3},{5,0,4},{5,848,4},
        {5,0x12000-1,4},{6,0,5},{6,0x10000-1,5},{7,0,6},{7,4095,6}};
    for(unsigned boundary=1;boundary<=9;++boundary)for(size_t i=0;i<sizeof changes/sizeof changes[0];++i) {
        struct Model m={0};init(&m);m.corrupt_publish=boundary;m.corrupt_slot=changes[i].slot;m.corrupt_offset=changes[i].offset;
        CHECK(!prepare(&m,fw));content_result(&m,fw,changes[i].code);
        const struct Buffer *b=&m.bo[changes[i].slot];const unsigned char changed=((const unsigned char*)b->cpu)[changes[i].offset];
        content_result(&m,fw,changes[i].code);CHECK(((const unsigned char*)b->cpu)[changes[i].offset]==changed);finish(&m);
    }
    struct Model m={0};init(&m);CHECK(!prepare(&m,fw));content_result(&m,fw,0);
    uint32_t code=99;
    CHECK(hhi_verify_contents(&m.storage,sizeof m.storage,NULL,HHI_FIRMWARE_BYTES,&code)==HHI_ARGUMENT);
    CHECK(hhi_verify_contents(&m.storage,sizeof m.storage,fw,HHI_FIRMWARE_BYTES-1,&code)==HHI_ARGUMENT);
    CHECK(hhi_verify_contents(&m.storage,sizeof m.storage,fw,HHI_FIRMWARE_BYTES,NULL)==HHI_ARGUMENT);
    CHECK(hhi_verify_contents(&m.storage,sizeof m.storage,fw,HHI_FIRMWARE_BYTES,(uint32_t*)m.storage.bytes)==HHI_ARGUMENT);
    CHECK(hhi_verify_contents(&m.storage,sizeof m.storage,fw,HHI_FIRMWARE_BYTES,(uint32_t*)(void*)(fw+1))==HHI_ALIGNMENT);
    CHECK(hhi_verify_contents(&m.storage,sizeof m.storage,fw,HHI_FIRMWARE_BYTES,(uint32_t*)(void*)(fw+4))==HHI_ARGUMENT);
    CHECK(code==99);
    /* All 210 table/header words, each ring boundary, both logical pad areas. */
    unsigned char *hfi=m.bo[5].cpu;
    for(unsigned word=0;word<210;++word) {
        hfi[word*4]^=1;content_result(&m,fw,4);hfi[word*4]^=1;
    }
    for(unsigned q=0;q<17;++q)for(unsigned edge=0;edge<2;++edge) {
        const unsigned offset=848+4096*q+(edge?4095:0);
        hfi[offset]^=1;content_result(&m,fw,4);hfi[offset]^=1;
    }
    const unsigned padding[]={840,847,848+17*4096,0x12000-1};
    for(size_t i=0;i<sizeof padding/sizeof padding[0];++i) {
        hfi[padding[i]]^=1;content_result(&m,fw,4);hfi[padding[i]]^=1;
    }
    content_result(&m,fw,0);
    uint8_t *bad=malloc(HHI_FIRMWARE_BYTES);CHECK(bad);memcpy(bad,fw,HHI_FIRMWARE_BYTES);bad[12]^=1;
    content_result(&m,bad,1);free(bad);
    m.fail_release_slots=0x1ff;CHECK(hhi_release(&m.storage,sizeof m.storage,&code)==HHI_OK);
    code=99;CHECK(hhi_verify_contents(&m.storage,sizeof m.storage,fw,HHI_FIRMWARE_BYTES,&code)==HHI_NOT_PREPARED && code==99);finish(&m);
}
int main(int argc,char **argv) {
    CHECK(argc==2);FILE *f=fopen(argv[1],"rb");CHECK(f);uint8_t *fw=malloc(HHI_FIRMWARE_BYTES);CHECK(fw);
    CHECK(fread(fw,1,HHI_FIRMWARE_BYTES,f)==HHI_FIRMWARE_BYTES && fgetc(f)==EOF);CHECK(!fclose(f));
    rejected_api(fw);baseline(fw);callback_failures(fw);malformed(fw);malformed_success_outputs(fw);content_corruption(fw);free(fw);
    printf("PASS: %u checks; C ABI, state=%zu/%zu align=%zu; exact 9 BO/8 ranges/6 tables/139 leaves/17 queues, callback failures, release retries and reentrancy\n",checks,hhi_actual_state_size(),hhi_storage_size(),hhi_actual_state_alignment());return 0;
}
