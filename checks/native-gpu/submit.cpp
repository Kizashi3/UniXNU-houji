/* SPDX-License-Identifier: MIT */
/* Real VM, ring and execbuf code over two software register peers. */
#include "XnuMemoryFixture.h"
#include "NativeAdrenoSubmit.h"
#include "NativeAdrenoUserClient.h"
#include "AdrenoPM4.h"
#include "HoujiGpuAddressLayout.h"
#include "HoujiGpuCanaryRanges.h"
extern "C" volatile uint32_t native_adreno_io_coherent;
extern "C" uint64_t native_adreno_vm_alias_paths[2];
extern "C" void houji_test_seal_arena(const ArmSmmu4KLiveArena *);
extern "C" int houji_test_check_sealed_arena(const ArmSmmu4KLiveArena *);
extern "C" unsigned houji_test_seal_failure(void);
#include <cstdio>
#include <cstring>
#include <vector>
#define CHECK(x) do {if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);std::exit(1);}}while(0)
#define SMMU_BYTES 0x40000
#define CB 0x22000
extern "C" int proc_selfpid(void){return 1;}
IOReturn NativeAdrenoQueryCpuPages(NativeAdrenoCpuState *out)
{CHECK(out);*out={};out->kernel_page_bytes=out->kernel_map_page_bytes=fixture.cpu_page_bytes;out->cpu_page_shift=fixture.cpu_page_bytes==16384?14:12;out->sctlr=1;out->ttbr1=0x30000000;out->tcr=fixture.cpu_page_bytes==16384?(UINT64_C(2)<<14|UINT64_C(1)<<30):(UINT64_C(2)<<30);return kIOReturnSuccess;}
IOReturn NativeAdrenoQueryCpu4K(NativeAdrenoCpuState *out)
{IOReturn status=NativeAdrenoQueryCpuPages(out);return status?status:out->cpu_page_shift==12?kIOReturnSuccess:kIOReturnUnsupported;}
IOReturn NativeAdrenoMaintainOwnedPages(void *mapping,size_t bytes,NativeAdrenoCacheOperation op)
{
    CHECK(mapping && bytes && !(((uintptr_t)mapping|bytes)&4095));
    CHECK(op==NativeAdrenoClean || op==NativeAdrenoCleanInvalidate || op==NativeAdrenoInvalidate);
    ++fixture.cache_calls;
    return fixture.cache_calls==fixture.cache_fail_call?kIOReturnIOError:kIOReturnSuccess;
}
/* SMMUv2 register peer. */
static uint32_t mmio[SMMU_BYTES/4];
static struct {unsigned calls,fail_call,after,tlbi,sync;bool fail_sync;unsigned page_tlbi,asid_tlbi,all_tlbi;} mf;
static ArmSmmu4KIo smmuio;
static ArmSmmu4KStreamState streams;
static ArmSmmu4KStream routes[2]={{2,0},{4,1}};
static ArmSmmu4KStreamResult route_result;
static ArmSmmu4KContextConfig context;
static ArmSmmu4KContextImage context_image;
static int mevent(void){return ++mf.calls==mf.fail_call;}
static int mread32(void *c,size_t at,uint32_t *v)
{CHECK(c==&mf && at%4==0 && at<=SMMU_BYTES-4);if(mevent())return 1;*v=mmio[at/4];return 0;}
static int mread64(void *c,size_t at,uint64_t *v)
{CHECK(c==&mf && at%8==0 && at<=SMMU_BYTES-8);if(mevent())return 1;std::memcpy(v,mmio+at/4,8);return 0;}
static int mwrite32(void *c,size_t at,uint32_t v)
{CHECK(c==&mf && at%4==0 && at<=SMMU_BYTES-4);int f=mevent();if(f && !mf.after)return 1;
 if(at==CB+0x7f0){++mf.sync;if(mf.fail_sync)return 1;}
 if(at==CB+0x610 || at==CB+0x618)++mf.tlbi;
 if(at==CB+0x610)++mf.asid_tlbi;if(at==CB+0x618)++mf.all_tlbi;
 mmio[at/4]=v;return f;}
static int mwrite64(void *c,size_t at,uint64_t v){CHECK(c==&mf && at==CB+0x620);++mf.tlbi;++mf.page_tlbi;std::memcpy(mmio+at/4,&v,8);return mevent();}
static int mbarrier(void *c){CHECK(c==&mf);return mevent();}
/* CP register peer. */
struct CpPeer {
    std::vector<uint32_t> regs;
    std::vector<uint32_t> writes;
    unsigned publish=0,acquire=0,barriers=0,fail_publish=0,fail_acquire=0,fail_barrier=0;
    CpPeer():regs(0x10000,0){}
};
static CpPeer cp;
static uint64_t clock_us=0;
static int cwrite(void *c,uint32_t reg,uint32_t v)
{CHECK(c==&cp && reg<cp.regs.size());cp.regs[reg]=v;cp.writes.push_back(reg);return 0;}
static int cread(void *c,uint32_t reg,uint32_t *v)
{CHECK(c==&cp && v && reg<cp.regs.size());*v=cp.regs[reg];return 0;}
static int cbarrier(void *c){CHECK(c==&cp);++cp.barriers;return cp.barriers==cp.fail_barrier;}
static int cpublish(void *,const volatile uint32_t *,size_t);
static int cacquire(void *c,volatile uint32_t *w,size_t bytes)
{CHECK(c==&cp && w && bytes==4096);++cp.acquire;return cp.acquire==cp.fail_acquire;}
static uint64_t cnow(void *c){CHECK(c==&cp);return clock_us;}
static int cidle(void *c){CHECK(c==&cp);clock_us+=1000;return 0;}
struct Path {
    NativeAdrenoMemory tables,object;
    ArmSmmu4KLiveArena arena;
    ArmSmmu4KLiveState state{};
    ArmSmmu4KLiveVisibility visibility;
    NativeAdrenoVm vm;
    NativeAdrenoRing ring;
    NativeAdrenoSubmit submit;
    uint64_t handle=0;
};
static uint32_t ringmem[8192],fencemem[1024];
/* Execute the production board's full packet gate against ring.cpp's output.
 * Only MMIO/owner predicates are peers; no GPU behavior is emulated. */
static constexpr uint32_t HHR_WORDS=8192,HHR_BYTES=32768,HHR_SCRATCH=0x107f00;
static bool enforce_board_gate=false;
static bool native_adreno_board_running(){return true;}
static bool houjiApiInOperation(){return true;}
static int houjiSubmitGuard(){return 0;}
static volatile uint32_t *houjiCpCpu(){return ringmem;}
static void houjiStockFullBarrier(){}
static uint32_t hhr_pkt7(uint32_t op,uint32_t n){uint32_t h=0;CHECK(AdrenoPM4Type7(op,n,&h)==AdrenoPM4Success);return h;}
static struct {
    struct {uint32_t seq=0;uint32_t lastSubmitted(){return seq;}} ring;
    unsigned published=0,pending=0,end=0,iteration=0,expected_end=0;
} gHoujiSubmit;
static struct {unsigned publishes=0;} gHoujiProvider;
#include "board-publish.inc"
static int cpublish(void *c,const volatile uint32_t *w,size_t bytes)
{CHECK(c==&cp && w && bytes==HHR_BYTES);++cp.publish;
 if(cp.publish==cp.fail_publish)return 1;
 return enforce_board_gate?houjiProviderPublish(w,bytes):0;}
static std::vector<uint64_t> dram_reads;
static uint64_t reassert_fail_physical;
static IOReturn reassert_failure;
static NativeAdrenoRingIo ringio{&cp,cwrite,cread,cbarrier};
static NativeAdrenoRingCache ringcache{&cp,cpublish,cacquire};
static NativeAdrenoRingClock ringclock{&cp,cnow,cidle};
static void smmuReset(void)
{
    std::memset(mmio,0,sizeof(mmio));mf={};streams=(ArmSmmu4KStreamState){};
    smmuio=(ArmSmmu4KIo){&mf,SMMU_BYTES,mread32,mread64,mwrite32,mwrite64,mbarrier};
    mmio[0x20/4]=(1u<<30)|(1u<<27)|(4u<<9)|8;
    mmio[0x24/4]=0x40000010;mmio[0x28/4]=0x1433;mmio[0]=0x436;
    for(unsigned i=0;i<8;++i)mmio[(0xc00+4*i)/4]=0x20000;
    mmio[0x800/4]=1u<<31|9;mmio[0xc00/4]=3;
}
static int exposed(Path &p,bool write_combined=false,bool full_aperture=false,bool per_page_tlb=true)
{
    fixture.cpu_page_bytes=TEST_CPU_PAGE;
    smmuReset();cp=CpPeer{};clock_us=0;
    std::memset(ringmem,0xef,sizeof(ringmem));std::memset(fencemem,0,sizeof(fencemem));
    const size_t table_bytes=full_aperture?HOUJI_GPU_TABLE_OWNED_PAGES*4096:32*4096;
    if(p.tables.allocate(table_bytes,40,true,table_bytes))return kIOReturnNoMemory;
    if(NativeAdrenoPrepareSmmuMemory(&p.tables,32,full_aperture?36:40,full_aperture?0:0x800000,
        full_aperture?HOUJI_GPU_APERTURE:65536,0,full_aperture?HOUJI_GPU_APERTURE/4096:16,&p.arena,&p.state,&p.visibility))
        return kIOReturnBadArgument;
    context=(ArmSmmu4KContextConfig){.lower=&p.arena.config,.upper=nullptr,
        .lower_tables=&p.state.tables,.upper_tables=nullptr,
        .id0=mmio[0x20/4],.id2=mmio[0x28/4],.asid=1,.coherent_walk=1,
        .stall_on_fault=0,.continue_after_fault=1,.polling_faults=0};
    ArmSmmu4KContextConfig actual=context;
    CHECK(ArmSmmu4KEncodeContext(&actual,&context_image)==ArmSmmu4KSuccess);
    mmio[0x1008/4]=context_image.cbar;mmio[0x1808/4]=context_image.cba2r;
    mmio[CB/4]=context_image.sctlr;mmio[(CB+0x10)/4]=context_image.tcr2;mmio[(CB+0x30)/4]=context_image.tcr;
    std::memcpy(mmio+(CB+0x20)/4,&context_image.ttbr0,8);
    std::memcpy(mmio+(CB+0x28)/4,&context_image.ttbr1,8);
    mmio[(CB+0x38)/4]=context_image.mair0;
    if(ArmSmmu4KAttachStreams(&smmuio,&streams,routes,2,2,&context,&route_result))return kIOReturnBadArgument;
    NativeAdrenoVmRegion lower={&p.tables,&p.arena,&p.state};
    if(p.vm.attachSeeded(&smmuio,&context,&streams,&lower,nullptr,full_aperture?256:32,1000,nullptr,0,nullptr,0,per_page_tlb))return kIOReturnBadArgument;
    const size_t object_bytes=full_aperture?4096:8192;
    if(p.object.allocate(object_bytes,40,false,NativeAdrenoMemory::backingBudget(object_bytes)))return kIOReturnNoMemory;
    if(write_combined && p.object.makeWriteCombined())return kIOReturnNoMemory;
    if(p.vm.map(&p.object,0,0x800000,3,0,2,&p.handle))return kIOReturnBadArgument;
    if(p.ring.attach(&ringio,&ringcache,ringmem,sizeof(ringmem),0x100000,fencemem,sizeof(fencemem),0x108000))
        return kIOReturnBadArgument;
    return p.submit.attach(&p.vm,&p.ring);
}
int main()
{
    #include "vm-alias.inc"
    #include "coherence.inc"
    #include "unmap-tlb.inc"
    /* r228: a high canary was prepended to lower boot ranges. Mapping itself
     * succeeded, then the real whole-graph audit rejected the unsorted list.
     * Exercise the board's metadata insertion with the actual live transaction
     * and audit, including the final 4K leaf; each unmap restores every byte. */
    {
        Path p;CHECK(exposed(p,false,true)==kIOReturnSuccess);
        CHECK(p.vm.unmap(p.handle)==kIOReturnSuccess);
        CHECK(p.submit.detach()==kIOReturnSuccess && p.vm.detach()==kIOReturnSuccess);
        ArmSmmu4KRange boot[12]{},after[13]{};ArmSmmu4KLiveResult result{};
        for(unsigned i=0;i<12;++i){
            boot[i]={0x60000000+UINT64_C(0x10000)*i,p.object.spans()[0].physical,4096,3,0,2};
            CHECK(ArmSmmu4KLiveUpdate(&p.arena,&p.state,&smmuio,2,&context,&p.visibility,
                boot,i,&boot[i],1,1000,&result)==ArmSmmu4KSuccess);
        }
        std::vector<unsigned char> original(p.tables.bytes());
        std::memcpy(original.data(),p.tables.mapping(),original.size());
        for(uint64_t va:{UINT64_C(0x40000000),UINT64_C(0x80000000),UINT64_C(0xc0000000),HOUJI_GPU_APERTURE-4096}){
            ArmSmmu4KRange change={va,p.object.spans()[0].physical,4096,3,0,2};
            CHECK(houjiGpuCanaryRanges(boot,12,&change,after,13));
            CHECK(!houjiGpuCanaryRanges(boot,12,&change,after,12));
            CHECK(ArmSmmu4KLiveUpdate(&p.arena,&p.state,&smmuio,2,&context,&p.visibility,
                boot,12,&change,1,1000,&result)==ArmSmmu4KSuccess);
            ArmSmmu4KRange former[13];former[0]=change;
            for(unsigned i=0;i<12;++i)former[i+1]=boot[i];
            CHECK(ArmSmmu4KLiveAudit(&p.arena,&p.state,former,13,&result)==
                (va<boot[0].iova?ArmSmmu4KSuccess:ArmSmmu4KOverlap));
            CHECK(ArmSmmu4KLiveAudit(&p.arena,&p.state,after,13,&result)==ArmSmmu4KSuccess);
            CHECK(ArmSmmu4KLiveUpdate(&p.arena,&p.state,&smmuio,2,&context,&p.visibility,
                after,13,&change,0,1000,&result)==ArmSmmu4KSuccess);
            CHECK(ArmSmmu4KLiveAudit(&p.arena,&p.state,boot,12,&result)==ArmSmmu4KSuccess);
            CHECK(!p.state.poisoned && !std::memcmp(original.data(),p.tables.mapping(),original.size()));
        }
        for(unsigned count=12;count;--count){
            const ArmSmmu4KRange change=boot[count-1];
            CHECK(ArmSmmu4KLiveUpdate(&p.arena,&p.state,&smmuio,2,&context,&p.visibility,
                boot,count,&change,0,1000,&result)==ArmSmmu4KSuccess);
        }
        std::puts("PASS: canary insertion reproduces old high-VA audit failure and restores sorted whole-graph map/unmap (host peers)");
    }
    /* Actual production VM/SMMU code over register peers: bit 31, the second
     * high L2 root and the final leaf must map/unmap without truncation.
     * Boundary failures must leave the previous topology/generation intact. */
    {
        Path p;CHECK(exposed(p,false,true)==kIOReturnSuccess);
        CHECK(p.state.tables.table_pages==HOUJI_GPU_TABLE_USED_PAGES);
        CHECK(p.arena.capacity_pages==HOUJI_GPU_TABLE_OWNED_PAGES);
        CHECK(p.arena.bytes==HOUJI_GPU_APERTURE && p.arena.config.input_bits==32);
        CHECK(p.arena.config.output_bits==36);
        CHECK(p.vm.unmap(p.handle)==kIOReturnSuccess);
        const uint64_t addresses[]={HOUJI_GPU_RENDER_START,UINT64_C(0xc0000000),HOUJI_GPU_APERTURE-4096};
        for(uint64_t va:addresses){
            uint64_t h=0;
            CHECK(p.vm.map(&p.object,0,va,3,0,2,&h)==kIOReturnSuccess && h);
            CHECK(p.vm.auditLive()==kIOReturnSuccess && p.state.tables.leaf_pages==1);
            CHECK(p.vm.unmap(h)==kIOReturnSuccess && p.state.tables.leaf_pages==0);
        }
        const auto generation=p.state.generation;
        for(uint64_t va:{HOUJI_GPU_APERTURE,UINT64_MAX-UINT64_C(4095)}){
            uint64_t h=0;
            CHECK(p.vm.map(&p.object,0,va,3,0,2,&h)!=kIOReturnSuccess);
            CHECK(p.state.generation==generation && !p.state.poisoned);
        }
        NativeAdrenoMemory crossing;
        CHECK(crossing.allocate(8192,40,false,NativeAdrenoMemory::backingBudget(8192))==kIOReturnSuccess);
        uint64_t h=0;
        CHECK(p.vm.map(&crossing,0,HOUJI_GPU_APERTURE-4096,3,0,2,&h)!=kIOReturnSuccess);
        CHECK(p.state.generation==generation && !p.state.poisoned);
        CHECK(p.vm.auditLive()==kIOReturnSuccess);
        CHECK(p.submit.detach()==kIOReturnSuccess);
        std::puts("PASS: 4 GiB SMMU topology, high-address map/unmap and overflow rejection (host peers)");
    }
    /* One validated indirect-buffer submission with exact ring bytes. */
    {
        Path p;CHECK(exposed(p)==kIOReturnSuccess);
        NativeAdrenoSubmitBuffer buffer{p.handle,0x800000,4096};
        uint32_t fence=0;
        /* Mandatory cache maintenance remains; no redundant submit TLBIALL. */
        static_cast<volatile uint32_t *>(p.object.mapping())[0]=0x70970001u;
        const unsigned cache_calls=fixture.cache_calls;
        mmio[(CB+0x618)/4]=0xffffffffu;
        CHECK(p.submit.submit(&buffer,1,0,&fence)==kIOReturnSuccess && fence==1);
        CHECK(fixture.cache_calls==cache_calls+1 && mmio[(CB+0x618)/4]==0xffffffffu);
        CHECK(native_adreno_coherence[0]==1 && native_adreno_coherence[1]==0x70970001u &&
            native_adreno_coherence[2]==~0u && native_adreno_coherence[3]==~0u);   /* no board DRAM reader installed */
        CHECK(cp.writes.back()==0x0807 && cp.regs[0x0807]==11+4+31);
        CHECK((ringmem[11]>>16&0x7fu)==0x3f && (ringmem[11]&0x3fffu)==3);
        CHECK(ringmem[12]==0x800000 && ringmem[13]==0 && ringmem[14]==1024);
        CHECK(p.object.deviceReferences()==2); /* mapping + job */
        CHECK(p.submit.outstanding()==1 && p.submit.stats().references_held==1);
        CHECK(p.submit.detach()==kIOReturnBusy);
        uint32_t observed=0;
        CHECK(p.ring.wait(1,&ringclock,1000,&observed)==NativeAdrenoRingFenceTimeout);
        CHECK(p.submit.wait(1,&ringclock,1000)==kIOReturnTimeout && p.submit.stats().timeouts==1);
        fencemem[1]=1;
        CHECK(p.submit.wait(1,&ringclock,1000)==kIOReturnSuccess);
        CHECK(p.submit.outstanding()==0 && p.submit.stats().completed==1);
        CHECK(p.object.deviceReferences()==1 && p.submit.stats().references_retired==1);
        CHECK(p.submit.wait(1,&ringclock,1000)==kIOReturnSuccess); /* retired job: the ring says the CP passed it */
        CHECK(p.submit.wait(2,&ringclock,1000)==kIOReturnBadArgument); /* never submitted */
        /* With a board DRAM reader, the sample reads the IB's physical page (before and after the maintenance). */
        native_adreno_dram_read32=[](uint64_t physical,uint32_t *value) {
            dram_reads.push_back(physical);*value=0xd00d0000u|uint32_t(dram_reads.size());return 0;};
        const unsigned tlbis=mf.tlbi,syncs=mf.sync;
        for(unsigned n=2;n<=65;++n){
            const unsigned maintenance=fixture.cache_calls;
            CHECK(p.submit.submit(&buffer,1,0,&fence)==kIOReturnSuccess && fence==n);
            CHECK(fixture.cache_calls==maintenance+1);
            CHECK(dram_reads.size()==(n==65?2u:0u));
            fencemem[1]=n;CHECK(!p.submit.wait(n,&ringclock,1000));
        }
        CHECK(mf.tlbi==tlbis && mf.sync==syncs);
        CHECK(dram_reads.size()==2 && dram_reads[0]==p.object.spans()[0].physical && dram_reads[1]==dram_reads[0]);
        CHECK(native_adreno_coherence[0]==65 && native_adreno_coherence[2]==0xd00d0001u && native_adreno_coherence[3]==0xd00d0002u);
        CHECK(native_adreno_coherence[4]==2 && native_adreno_coherence[5]==0x70970001u && native_adreno_coherence[6]==~0u);   /* first differing sample kept */
        native_adreno_dram_read32=nullptr;
        CHECK(p.submit.detach()==kIOReturnSuccess);
    }
    /* int-100: a write-combined BO is not maintained while the IB audit finds no dirty line; a dirty line or a failed audit ends the
     * trust, and that submission already maintains every BO through its physical pages. */
    {
        Path p;CHECK(exposed(p,true)==kIOReturnSuccess);
        NativeAdrenoSubmitBuffer buffer{p.handle,0x800000,4096};
        static std::vector<uint64_t> audited;static uint32_t dirty_lines,fail;
        audited.clear();dirty_lines=0;fail=0;
        native_adreno_line_audit=[](uint64_t physical,size_t bytes,uint32_t *dirty,uint32_t *stale) {
            audited.push_back(physical);audited.push_back(bytes);
            if(fail)return 1;
            *dirty+=dirty_lines;*stale+=1;return 0;};
        const uint32_t submissions=native_adreno_wc_audit[0],lines=native_adreno_wc_audit[1];
        const unsigned physical=fixture.physical_calls,owned=fixture.cache_calls;
        uint32_t fence=0;
        CHECK(p.submit.submit(&buffer,1,0,&fence)==kIOReturnSuccess && fence==1);
        CHECK(audited.size()==2 && audited[0]==p.object.spans()[0].physical && audited[1]==4096);
        CHECK(native_adreno_wc_audit[0]==submissions+1 && native_adreno_wc_audit[1]==lines+64 && native_adreno_wc_distrusted==0);
        CHECK(fixture.physical_calls==physical && fixture.cache_calls==owned && p.vm.writeCombinedTrusted());   /* no maintenance */
        fencemem[1]=1;CHECK(p.submit.wait(1,&ringclock,1000)==kIOReturnSuccess);
        dirty_lines=2;
        CHECK(p.submit.submit(&buffer,1,0,&fence)==kIOReturnSuccess && fence==2);
        CHECK(!p.vm.writeCombinedTrusted() && native_adreno_wc_distrusted==native_adreno_coherence[0]);
        CHECK(fixture.physical_calls>physical);   /* this submission maintained the write-combined BO */
        const size_t calls=audited.size();
        fencemem[1]=2;CHECK(p.submit.wait(2,&ringclock,1000)==kIOReturnSuccess);
        CHECK(p.submit.submit(&buffer,1,0,&fence)==kIOReturnSuccess && audited.size()==calls);   /* no audit once distrusted */
        fencemem[1]=3;CHECK(p.submit.wait(3,&ringclock,1000)==kIOReturnSuccess);
        CHECK(p.submit.detach()==kIOReturnSuccess);
    }
    /* The audit compares the first 16 submissions after attach, then every eighth (17, 25, ...); the re-assertion runs at each. */
    {
        Path p;CHECK(exposed(p,true)==kIOReturnSuccess);
        NativeAdrenoSubmitBuffer buffer{p.handle,0x800000,4096};
        static unsigned calls;calls=0;
        native_adreno_line_audit=[](uint64_t,size_t,uint32_t *,uint32_t *stale) {++calls;*stale+=0;return 0;};
        const uint32_t submissions=native_adreno_wc_audit[0];
        for(uint32_t n=1;n<=24;++n) {
            uint32_t fence=0;
            CHECK(p.submit.submit(&buffer,1,0,&fence)==kIOReturnSuccess && fence==n);
            fencemem[1]=n;CHECK(p.submit.wait(n,&ringclock,1000)==kIOReturnSuccess);
        }
        CHECK(calls==17 && native_adreno_wc_audit[0]==submissions+17 && p.vm.writeCombinedTrusted());
        native_adreno_line_audit=nullptr;
        CHECK(p.submit.detach()==kIOReturnSuccess);
    }
    {
        Path p;CHECK(exposed(p,true)==kIOReturnSuccess);
        NativeAdrenoSubmitBuffer buffer{p.handle,0x800000,4096};
        native_adreno_line_audit=[](uint64_t,size_t,uint32_t *,uint32_t *) {return 1;};
        uint32_t fence=0;
        CHECK(p.submit.submit(&buffer,1,0,&fence)==kIOReturnSuccess && fence==1);
        CHECK(!p.vm.writeCombinedTrusted() && native_adreno_wc_audit[4]==kIOReturnIOError);
        native_adreno_line_audit=nullptr;native_adreno_wc_distrusted=0;
        fencemem[1]=1;CHECK(p.submit.wait(1,&ringclock,1000)==kIOReturnSuccess);
        CHECK(p.submit.detach()==kIOReturnSuccess);
    }
    /* Refusals precede references, ring bytes and WPTR updates. */
    {
        Path p;CHECK(exposed(p)==kIOReturnSuccess);
        const uint32_t wptr=cp.regs[0x0807];
        uint32_t fence=0;
        CHECK(p.submit.submit(nullptr,1,0,&fence)==kIOReturnBadArgument);
        NativeAdrenoSubmitBuffer zero[1]={{p.handle,0x800000,0}};
        CHECK(p.submit.submit(zero,1,0,&fence)==kIOReturnBadArgument);
        NativeAdrenoSubmitBuffer unaligned[1]={{p.handle,0x800000,4098}};
        CHECK(p.submit.submit(unaligned,1,0,&fence)==kIOReturnBadArgument);
        NativeAdrenoSubmitBuffer wrong[1]={{p.handle,0x802000,4096}};
        CHECK(p.submit.submit(wrong,1,0,&fence)==kIOReturnBadArgument);
        NativeAdrenoSubmitBuffer overrun[1]={{p.handle,0x800000,8192+4}};
        CHECK(p.submit.submit(overrun,1,0,&fence)==kIOReturnBadArgument);
        NativeAdrenoSubmitBuffer unknown[1]={{p.handle+7,0x800000,4096}};
        CHECK(p.submit.submit(unknown,1,0,&fence)==kIOReturnBadArgument);
        NativeAdrenoSubmitBuffer many[NativeAdrenoSubmitMaxBuffers+1];
        for(auto &b:many)b={p.handle,0x800000,4096};
        CHECK(p.submit.submit(many,NativeAdrenoSubmitMaxBuffers+1,0,&fence)==kIOReturnBadArgument);
        CHECK(p.object.deviceReferences()==1 && cp.regs[0x0807]==wptr && p.submit.outstanding()==0);
        /* Duplicate buffers share one device reference. */
        NativeAdrenoSubmitBuffer twice[2]={{p.handle,0x800000,4096},{p.handle,0x800000,4096}};
        CHECK(p.submit.submit(twice,2,0,&fence)==kIOReturnSuccess);
        CHECK(p.object.deviceReferences()==2 && cp.regs[0x0807]==11+8+31);
        fencemem[1]=1;
        CHECK(p.submit.wait(1,&ringclock,100)==kIOReturnSuccess && p.object.deviceReferences()==1);
        CHECK(p.submit.detach()==kIOReturnSuccess);
    }
    /* Eight queued jobs may coexist before any completion. A full queue
     * refuses the ninth without publishing it; retiring a prefix permits
     * another submit while the remaining fences and BO references survive. */
    {
        Path p;CHECK(!exposed(p));
        NativeAdrenoSubmitBuffer buffer{p.handle,0x800000,4096};uint32_t fence=0;
        for(unsigned i=1;i<=8;++i){CHECK(!p.submit.submit(&buffer,1,i,&fence));CHECK(fence==i);}
        CHECK(p.submit.outstanding()==8 && p.object.deviceReferences()==9);
        auto writes=cp.writes.size();
        CHECK(p.submit.submit(&buffer,1,9,&fence)==kIOReturnBusy && fence==0);
        CHECK(cp.writes.size()==writes && p.object.deviceReferences()==9);
        fencemem[1]=3;CHECK(!p.submit.wait(3,&ringclock,100));
        CHECK(p.submit.outstanding()==7 && p.object.deviceReferences()==8); // wait retires its target; submit sweeps the prefix
        CHECK(!p.submit.submit(&buffer,1,9,&fence) && fence==9);
        CHECK(p.submit.outstanding()==6);
        fencemem[1]=9;CHECK(!p.submit.waitAll(&ringclock,100));
        CHECK(!p.submit.outstanding() && p.object.deviceReferences()==1);
    }
    /* A commit that poisons the ring retains every reference and disables execbuf. */
    {
        Path p;CHECK(exposed(p)==kIOReturnSuccess);
        cp.fail_publish=cp.publish+1;
        NativeAdrenoSubmitBuffer buffer{p.handle,0x800000,4096};
        uint32_t fence=0;
        CHECK(p.submit.submit(&buffer,1,0,&fence)==kIOReturnIOError);
        CHECK(!fence && p.submit.poisoned() && p.ring.poisoned());
        CHECK(p.submit.outstanding()==1 && p.submit.stats().poisoned_jobs==1);
        CHECK(p.object.deviceReferences()==2); /* never retired */
        CHECK(p.submit.detach()==kIOReturnBusy && p.submit.wait(1,&ringclock,10)==kIOReturnNotReady);
        CHECK(p.ring.detach()==kIOReturnBusy && p.vm.detach()==kIOReturnBusy);
        CHECK(p.object.release()==kIOReturnBusy);
    }
    /* Mandatory cache-attribute failures must never reach publication, even
     * when the optional diagnostic audit would return Unsupported. */
    for(bool other_target:{false,true})for(IOReturn failure:{kIOReturnUnsupported,kIOReturnIOError,kIOReturnNotReady}) {
        Path p;CHECK(!exposed(p,true));
        NativeAdrenoMemory other;uint64_t other_handle=0;
        CHECK(!other.allocate(4096,40,false,NativeAdrenoMemory::backingBudget(4096)));
        CHECK(!other.makeWriteCombined() && !p.vm.map(&other,0,0x804000,3,0,2,&other_handle));
        reassert_fail_physical=(other_target?other:p.object).ownedSpans()[0].physical;
        reassert_failure=failure;
        const auto writes=cp.writes.size(),samples=dram_reads.size();
        const auto maintenance=fixture.cache_calls,mmio_calls=mf.calls;
        const auto retired=p.submit.stats().references_retired;
        NativeAdrenoSubmitBuffer buffer{p.handle,0x800000,4096};uint32_t fence=99;
        CHECK(p.submit.submit(&buffer,1,0,&fence)==failure && !fence);
        CHECK(p.submit.poisoned() && p.submit.outstanding()==1 && p.submit.stats().poisoned_jobs==1);
        CHECK((other_target?other:p.object).quarantined());
        CHECK(p.object.deviceReferences()==2 && other.deviceReferences()==1);
        CHECK(p.submit.stats().references_retired==retired && !p.submit.stats().submissions);
        CHECK(cp.writes.size()==writes && dram_reads.size()==samples && mf.calls==mmio_calls);
        CHECK(fixture.cache_calls==maintenance && !p.vm.writeCombinedTrusted());
        CHECK(p.submit.detach()==kIOReturnBusy && p.object.release()==kIOReturnBusy);
    }
    reassert_fail_physical=0;reassert_failure=kIOReturnSuccess;
    /* Address reuse must invalidate before releasing the old backing. A
     * synchronization failure quarantines it and forbids a later submit. */
    for(bool fail:{false,true}) {
        Path p;CHECK(!exposed(p));
        const unsigned tlbis=mf.tlbi,syncs=mf.sync;
        const auto physical=p.object.spans()[0].physical;
        mf.fail_sync=fail;
        const IOReturn removed=p.vm.unmap(p.handle);
        CHECK(mf.tlbi>tlbis && mf.sync>syncs);
        if(fail){
            CHECK(removed && p.vm.poisoned() && p.object.quarantined());
            CHECK(p.object.deviceReferences()==1 && p.object.release()==kIOReturnBusy);
            NativeAdrenoSubmitBuffer buffer{p.handle,0x800000,4096};uint32_t fence=99;
            const auto writes=cp.writes.size();
            CHECK(p.submit.submit(&buffer,1,0,&fence)!=kIOReturnSuccess && !fence);
            CHECK(cp.writes.size()==writes);
        }else{
            CHECK(!removed && p.object.deviceReferences()==0 && !p.object.release());
            CHECK(!p.object.allocate(8192,40,false,NativeAdrenoMemory::backingBudget(8192)));
            CHECK(p.object.spans()[0].physical!=physical);
            uint64_t next=0;CHECK(!p.vm.map(&p.object,0,0x800000,3,0,2,&next) && next!=p.handle);
            NativeAdrenoSubmitBuffer buffer{next,0x800000,4096};uint32_t fence=0;
            CHECK(!p.submit.submit(&buffer,1,0,&fence));
            fencemem[1]=fence;CHECK(!p.submit.wait(fence,&ringclock,1000));
        }
    }
    /* A refused attach leaves both peers untouched. */
    {
        Path p;NativeAdrenoRing ring;NativeAdrenoSubmit submit;
        CHECK(submit.attach(nullptr,&ring)==kIOReturnBadArgument);
        CHECK(submit.attach(&p.vm,nullptr)==kIOReturnBadArgument);
        CHECK(submit.detach()==kIOReturnNotReady);
        CHECK(submit.submit(nullptr,1,0,nullptr)==kIOReturnBadArgument);
    }
    /* A full batch keeps all 128 distinct objects pinned through its fence.
     * Verify every IB and the tail in the capture, including a ring wrap;
     * there is one publication per batch, never eight implicit sub-jobs. */
    {
        Path p;CHECK(!exposed(p,false,true));
        NativeAdrenoMemory objects[NativeAdrenoSubmitMaxBuffers];
        NativeAdrenoSubmitBuffer buffers[NativeAdrenoSubmitMaxBuffers];
        for(unsigned i=0;i<NativeAdrenoSubmitMaxBuffers;++i){
            CHECK(!objects[i].allocate(4096,40,false,NativeAdrenoMemory::backingBudget(4096)));
            uint64_t handle=0,va=0x90000000+UINT64_C(4096)*i;
            CHECK(!p.vm.map(&objects[i],0,va,3,0,2,&handle));
            buffers[i]={handle,va,4096};
        }
        enforce_board_gate=true;gHoujiProvider.publishes=0;
        for(unsigned j=1;j<=16;++j){
            const auto publications=cp.publish;const uint32_t begin=cp.regs[0x0807];
            gHoujiSubmit={};gHoujiSubmit.ring.seq=j-1;gHoujiSubmit.end=begin;
            uint32_t fence=0;CHECK(!p.submit.submit(buffers,NativeAdrenoSubmitMaxBuffers,0,&fence) && fence==j);
            CHECK(cp.publish==publications+1 && p.submit.outstanding()==1);
            const volatile uint32_t *log=native_adreno_ring_log[(native_adreno_ring_log_count-1)&3];
            CHECK(log[0]==j && log[1]==begin && log[3]==554 && log[2]==((begin+554)&8191));
            for(unsigned k=0;k<554;++k)CHECK(log[4+k]==ringmem[(begin+k)&8191]);
            for(unsigned i=0;i<NativeAdrenoSubmitMaxBuffers;++i){
                CHECK(objects[i].deviceReferences()==2);
                CHECK(log[4+11+4*i]==0x70bf8003 && log[4+12+4*i]==buffers[i].iova);
                CHECK(log[4+13+4*i]==0 && log[4+14+4*i]==1024);
                CHECK(p.vm.unmap(buffers[i].handle)==kIOReturnBusy);
            }
            CHECK(log[4+553]==0x100);
            CHECK(gHoujiSubmit.published && gHoujiProvider.publishes==j);
            // A corrupted final tail word or an over-limit frame must fail
            // before publication, even beyond the old 112-word capture.
            auto *bad=native_adreno_ring_log[(native_adreno_ring_log_count-1)&3];
            gHoujiSubmit.published=0;bad[4+553]=0;
            CHECK(houjiProviderPublish(ringmem,sizeof(ringmem))==1 && !gHoujiSubmit.published);
            bad[4+553]=0x100;bad[3]=558;bad[2]=(begin+558)&8191;
            CHECK(houjiProviderPublish(ringmem,sizeof(ringmem))==1 && !gHoujiSubmit.published);
            bad[3]=554;bad[2]=(begin+554)&8191;
            fencemem[1]=j;CHECK(!p.submit.wait(j,&ringclock,100));
            cp.regs[0x0806]=cp.regs[0x0807];
            for(auto &object:objects)CHECK(object.deviceReferences()==1);
        }
        enforce_board_gate=false;
        for(unsigned i=0;i<NativeAdrenoSubmitMaxBuffers;++i)CHECK(!p.vm.unmap(buffers[i].handle));
        CHECK(!p.submit.detach());
        std::puts("PASS: 128 distinct IB references, single publication, complete packet capture, wrap and fence retirement (host peers)");
    }
    /* Exercise both wire sizes through the real dispatcher: malformed batch
     * records cannot touch ring bytes or reply, and old 16-IB clients retain
     * their exact ABI. Resolve every entry before holding a device reference. */
    {
        Path p;CHECK(!exposed(p,false,true));NativeAdrenoUserClient client;
        CHECK(!client.open(NativeAdrenoAbiVersion,&p.vm,&p.submit,&p.ring,32,36,true));
        NativeAdrenoAbiParams params{};CHECK(!client.query(&params));
        CHECK(params.flags&NativeAdrenoParamsSubmitBatch);
        NativeAdrenoAbiBoAlloc alloc{4096,12,0};NativeAdrenoAbiBoAllocReply object{};
        CHECK(!client.allocBo(&alloc,&object));
        NativeAdrenoAbiBoMap map{object.handle,0x900000,3,0,2,0};NativeAdrenoAbiBoMapReply mapped{};
        CHECK(!client.mapBo(&map,&mapped));
        NativeAdrenoAbiSubmitBatch batch{};batch.buffer_count=128;
        for(auto &b:batch.buffers)b={object.handle,0x900000,4096};
        NativeAdrenoAbiSubmitReply reply{0x12345678};const auto writes=cp.writes.size();
        CHECK(client.dispatch(NativeAdrenoMethodSubmitBatch,&batch,sizeof(batch)-1,&reply,sizeof(reply),&ringclock)==kIOReturnBadArgument);
        CHECK(client.dispatch(NativeAdrenoMethodSubmit,&batch,sizeof(batch),&reply,sizeof(reply),&ringclock)==kIOReturnBadArgument);
        CHECK(client.dispatch(NativeAdrenoMethodSubmit,&batch,sizeof(NativeAdrenoAbiSubmit),&reply,sizeof(reply),&ringclock)==kIOReturnBadArgument);
        batch.buffers[127].handle=UINT64_MAX;
        CHECK(client.dispatch(NativeAdrenoMethodSubmitBatch,&batch,sizeof(batch),&reply,sizeof(reply),&ringclock)==kIOReturnBadArgument);
        CHECK(reply.fence==0x12345678 && cp.writes.size()==writes && !p.submit.outstanding());
        batch.buffers[127].handle=object.handle;
        CHECK(!client.dispatch(NativeAdrenoMethodSubmitBatch,&batch,sizeof(batch),&reply,sizeof(reply),&ringclock) && reply.fence==1);
        NativeAdrenoAbiBoFree release{object.handle};CHECK(client.freeBo(&release)==kIOReturnBusy);
        fencemem[1]=1;CHECK(!p.submit.wait(1,&ringclock,100));cp.regs[0x0806]=cp.regs[0x0807];
        batch.buffer_count=16;
        CHECK(!client.dispatch(NativeAdrenoMethodSubmit,&batch,sizeof(NativeAdrenoAbiSubmit),&reply,sizeof(reply),&ringclock) && reply.fence==2);
        fencemem[1]=2;CHECK(!p.submit.wait(2,&ringclock,100));
        CHECK(!client.freeBo(&release) && !client.close() && !p.submit.detach());
        std::puts("PASS: negotiated 128-IB and legacy 16-IB dispatch, exact wire sizes, rejected late invalid handles and retained fence ownership");
    }
    // Real client allocation, handle lookup and teardown with XNU memory peers.
    #include "handles.inc"
    // Pool pages follow the same real CPU lease, job/fence and TLBSYNC retirement.
    {
        fixture.mode=Contiguous;fixture.contiguous_limit=0;
        Path p;CHECK(!exposed(p,false,true));
        CHECK(!NativeAdrenoMemory::reservePool(36,16*TEST_CPU_PAGE));
        CHECK(!NativeAdrenoMemory::writeCombinePool());
        NativeAdrenoUserClient client;
        CHECK(!client.open(NativeAdrenoAbiVersion,&p.vm,&p.submit,&p.ring,32,36,true));
        // Exhaust the real pool, then model fragmented XNU memory. Optional
        // contiguity must not start a failing physical-memory search. An
        // explicit contiguous request still has to honor that requirement.
        {
            NativeAdrenoMemory occupied;
            CHECK(!occupied.allocate(16*TEST_CPU_PAGE,36,true,16*TEST_CPU_PAGE,true) && occupied.pooled());
            fixture.mode=ScatterUnlessContiguous;fixture.contiguous_limit=TEST_CPU_PAGE;
            const auto attempts=fixture.contiguous_attempts;
            NativeAdrenoAbiBoAlloc large{1024*1024,12,0};NativeAdrenoAbiBoAllocReply reply{};
            CHECK(!client.allocBo(&large,&reply));
            auto *fallback=client.memoryOf(reply.handle);
            CHECK(fallback && !fallback->pooled() && fallback->spanCount()==1024*1024/TEST_CPU_PAGE);
            CHECK(fixture.contiguous_attempts==attempts);
            NativeAdrenoAbiBoFree drop{reply.handle};CHECK(!client.freeBo(&drop));
            large.contiguous=1;reply={};
            CHECK(client.allocBo(&large,&reply)==kIOReturnNoMemory && !reply.handle);
            CHECK(fixture.contiguous_attempts==attempts+1);
            CHECK(!occupied.release());fixture.mode=Contiguous;fixture.contiguous_limit=0;
            std::puts("PASS: exhausted pool uses scattered backing without optional contiguous search; explicit contiguity retained");
        }
        NativeAdrenoAbiBoAlloc alloc{4096,12,0};NativeAdrenoAbiBoAllocReply object{};
        CHECK(!client.allocBo(&alloc,&object));auto *memory=client.memoryOf(object.handle);
        CHECK(memory && memory->pooled());const uint64_t physical=memory->spans()[0].physical;
        NativeAdrenoAbiBoCpuMap view{object.handle};NativeAdrenoAbiBoCpuMapReply cpu{};
        CHECK(!client.cpuMap(&view,&cpu) && cpu.bytes==TEST_CPU_PAGE);
        NativeAdrenoAbiBoFree free{object.handle};CHECK(client.freeBo(&free)==kIOReturnBusy);
        NativeAdrenoAbiBoCpuUnmap unview{object.handle,cpu.token,0};CHECK(!client.cpuUnmap(&unview));
        NativeAdrenoAbiBoMap map{object.handle,0x900000,3,0,2,0};NativeAdrenoAbiBoMapReply mapped{};
        CHECK(!client.mapBo(&map,&mapped));
        NativeAdrenoAbiSubmit job{};job.buffer_count=1;job.buffers[0]={object.handle,0x900000,4096};NativeAdrenoAbiSubmitReply submitted{};
        CHECK(!client.submit(&job,&submitted,&ringclock) && client.freeBo(&free)==kIOReturnBusy);
        fencemem[1]=(uint32_t)submitted.fence;CHECK(!p.submit.wait((uint32_t)submitted.fence,&ringclock,100));
        cp.regs[0x0806]=cp.regs[0x0807];CHECK(!client.freeBo(&free));
        CHECK(!client.allocBo(&alloc,&object) && client.memoryOf(object.handle)->spans()[0].physical==physical);
        map.handle=object.handle;CHECK(!client.mapBo(&map,&mapped));free.handle=object.handle;
        mf.fail_sync=true;CHECK(client.freeBo(&free)!=kIOReturnSuccess);
        CHECK(client.memoryOf(object.handle)->backed() && client.memoryOf(object.handle)->deviceReferences());
        NativeAdrenoMemory other;CHECK(!other.allocate(4096,36,true,TEST_CPU_PAGE,true));
        CHECK(other.spans()[0].physical!=physical && !other.release());
        // Failed unmap poisons the path; real kernel keeps the object until reset.
        std::puts("PASS: pooled BO CPU lease/fence/TLBSYNC ownership and failed-unmap non-reuse; no GPU");
    }
    // Fixture-only disposal, including quarantined allocations. Production
    // quarantine is retained until independent hardware reset, never here.
    while(!fixture.live.empty())fixture.live.back()->release();
    while(!fixture.metadata.empty())fixtureMetadataFree(fixture.metadata.back());
    std::printf("PASS: CPU%uK actual Submit/VM/SMMU: sampling, cache maintenance, no submit TLBI, synchronized reuse, failed-unmap quarantine, bounds and fence lifetime (ASAN/UBSAN); no GPU\n",TEST_CPU_PAGE/1024);
}
/* Physical-page maintenance (imported BOs): record it; no host page is touched. */
/* Host double: the page attribute change of user BOs has no host equivalent (no host page is touched). */
IOReturn NativeAdrenoSetPagesCacheMode(const NativeAdrenoPhysicalSpan *spans,size_t count,bool){return spans && count?kIOReturnSuccess:kIOReturnBadArgument;}
IOReturn NativeAdrenoReassertWriteCombined(const NativeAdrenoPhysicalSpan *spans,size_t count,uint32_t *reset)
{if(!spans || !count || !reset)return kIOReturnBadArgument;
 return spans[0].physical==reassert_fail_physical?reassert_failure:kIOReturnSuccess;}
IOReturn NativeAdrenoMaintainPhysicalPages(uint64_t physical,size_t bytes,NativeAdrenoCacheOperation op)
{
    if(!physical || !bytes || ((physical|bytes)&4095) || op>NativeAdrenoInvalidate)std::abort();
    ++fixture.physical_calls;fixture.physical_bytes+=bytes;return kIOReturnSuccess;
}
