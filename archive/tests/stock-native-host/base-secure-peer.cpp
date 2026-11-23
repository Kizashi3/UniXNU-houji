static bool secure_mode,firmware_mode;static int scm_boot=1;static void host_secure_checkpoint(const char*,unsigned);
#include <cstdint>
static void host_pmap_hook(uint32_t,unsigned);
static int nc_boot_value=1;static bool nc_boot_present=true;
#include <cstdint>
static void external_cache_hook(uintptr_t,unsigned);

#include "XnuMemoryFixture.h"
#include "NativeAdrenoMemory.h"
#include "NativeAdrenoCpuPagePolicy.h"
#include "NativeAdrenoABI.h"
#include <cstdio>
#include <map>
#include <set>
#define CHECK(x) do{if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);std::abort();}}while(0)
using vm_offset_t=uintptr_t;using ppnum_t=uint32_t;using UInt32=uint32_t;
constexpr unsigned VM_WIMG_MASK=0xf,VM_WIMG_DEFAULT=0,VM_WIMG_WCOMB=2,VM_WIMG_USE_DEFAULT=0;
static uint64_t cpu_tcr,cpu_ttbr0,cpu_ttbr1,cpu_sctlr,cpu_ctr;
static size_t page_size=PAGE_SIZE,map_page_bytes=PAGE_SIZE;
static void *kernel_map=reinterpret_cast<void*>(2);
static size_t vm_map_page_size(void *m){CHECK(m==kernel_map);return map_page_bytes;}
static unsigned preemption_depth,barriers;
static uint64_t now;
static void disable_preemption(){++preemption_depth;}
static void enable_preemption(){CHECK(preemption_depth);--preemption_depth;}
static uint64_t mach_absolute_time(){return ++now;}
struct CacheLine{uintptr_t address;unsigned operation;};
static std::vector<CacheLine> cache_lines;
static void cache_line(uintptr_t address,unsigned op){CHECK(preemption_depth && !(address&63));cache_lines.push_back({address,op});external_cache_hook(address,op);}
extern "C" {uint64_t gPhysBase=UINT64_C(0x800000000),gPhysSize=UINT64_C(0x800000000);}
extern "C" vm_offset_t phystokv(uint64_t pa){CHECK(pa>=gPhysBase && pa-gPhysBase<gPhysSize);return UINT64_C(0xffff000000000000)|pa;}
static std::map<ppnum_t,unsigned> attributes;
static std::vector<std::pair<ppnum_t,unsigned>> pmap_writes;
static unsigned attribute_write_fail;
extern "C" void pmap_set_cache_attributes(ppnum_t pn,unsigned attr){
 host_pmap_hook(pn,attr);pmap_writes.push_back({pn,attr});if(pmap_writes.size()!=attribute_write_fail)attributes[pn]=attr;
}
extern "C" unsigned pmap_cache_attributes(ppnum_t pn){return attributes[pn];}
/* SPDX-License-Identifier: MIT */
#include "NativeAdrenoMemory.h"
#include "NativeAdrenoCpuPagePolicy.h"
#include <kern/cpu_data.h>
#include <vm/vm_map.h>
#include <mach/vm_param.h>
#include <kern/clock.h>
#include <vm/memory_types.h>
extern "C" vm_offset_t phystokv(uint64_t pa);
extern "C" uint64_t gPhysBase,gPhysSize;   /* the physical range phystokv covers (the kernel's own DRAM); anything else panics in phystokv */
extern "C" void pmap_set_cache_attributes(ppnum_t pn,unsigned int cacheattr);
extern "C" unsigned int pmap_cache_attributes(ppnum_t pn);
/* Time and bytes of every CPU cache maintenance pass (the board page shows them per submission), and the pages user BOs made
 * write-combined: [0] ticks, [1] bytes, [2] longest pass in ticks, [3] passes, [4] write-combined pages now. */
extern "C" {volatile uint64_t native_adreno_cache_stats[5];}
/* Time spent checking and re-asserting write-combined page attributes (NativeAdrenoReassertWriteCombined), for the board page. */
extern "C" {volatile uint64_t native_adreno_reassert_ticks;}
static void noteMaintenance(uint64_t began,size_t bytes)
{
    const uint64_t ticks=mach_absolute_time()-began;
    __atomic_fetch_add(&native_adreno_cache_stats[0],ticks,__ATOMIC_RELAXED);
    __atomic_fetch_add(&native_adreno_cache_stats[1],bytes,__ATOMIC_RELAXED);
    __atomic_fetch_add(&native_adreno_cache_stats[3],1,__ATOMIC_RELAXED);
    uint64_t longest=__atomic_load_n(&native_adreno_cache_stats[2],__ATOMIC_RELAXED);
    while(ticks>longest && !__atomic_compare_exchange_n(&native_adreno_cache_stats[2],&longest,ticks,true,__ATOMIC_RELAXED,__ATOMIC_RELAXED)) {}
}

IOReturn NativeAdrenoQueryCpuPages(NativeAdrenoCpuState *out)
{
    if(!out)return kIOReturnBadArgument;
    *out={};
    disable_preemption();
    out->tcr=cpu_tcr;
    out->ttbr0=cpu_ttbr0;
    out->ttbr1=cpu_ttbr1;
    out->sctlr=cpu_sctlr;
    out->kernel_page_bytes=page_size;
    out->kernel_map_page_bytes=vm_map_page_size(kernel_map);
    enable_preemption();
    const bool native=NativeAdrenoCpuPageGeometry(PAGE_SIZE,out->kernel_page_bytes,
        out->kernel_map_page_bytes,out->tcr,out->sctlr,out->ttbr1,&out->cpu_page_shift);
    return native?kIOReturnSuccess:kIOReturnUnsupported;
}
IOReturn NativeAdrenoQueryCpu4K(NativeAdrenoCpuState *out)
{
    const IOReturn status=NativeAdrenoQueryCpuPages(out);
    return status?status:(out->kernel_page_bytes==4096?kIOReturnSuccess:kIOReturnUnsupported);
}
static IOReturn maintainOwnedPages(void *mapping,size_t bytes,NativeAdrenoCacheOperation op)
{
    /* Whole cache lines inside owned backing avoid IVAC corruption of a neighbour's dirty line.
     * No Apple coherent-I/O shortcut is used for these noncoherent DMA paths.
     * Pin this CPU while reading its CTR and issuing all cache operations. */
    if(!mapping || !bytes || (((uintptr_t)mapping|bytes)&4095) ||
        bytes>UINTPTR_MAX-(uintptr_t)mapping || op>NativeAdrenoInvalidate || op<NativeAdrenoClean)
        return kIOReturnBadArgument;
    disable_preemption();
    uint64_t ctr;ctr=cpu_ctr;
    size_t line=(size_t)4<<((ctr>>16)&15);
    if(line>4096) {enable_preemption();return kIOReturnUnsupported;}
    uintptr_t address=(uintptr_t)mapping,end=address+bytes;
    ++barriers;
    for(;address<end;address+=line) {
        if(op==NativeAdrenoClean)cache_line(address,0);
        else if(op==NativeAdrenoCleanInvalidate)cache_line(address,1);
        else cache_line(address,2);
    }
    ++barriers;
    enable_preemption();return kIOReturnSuccess;
}
IOReturn NativeAdrenoMaintainOwnedPages(void *mapping,size_t bytes,NativeAdrenoCacheOperation op)
{
    const uint64_t began=mach_absolute_time();
    const IOReturn status=maintainOwnedPages(mapping,bytes,op);
    if(!status)noteMaintenance(began,bytes);
    return status;
}
IOReturn NativeAdrenoMaintainPhysicalPages(uint64_t physical,size_t bytes,NativeAdrenoCacheOperation op)
{
    if(!physical || !bytes || ((physical|bytes)&4095) || physical>UINT64_MAX-bytes || op>NativeAdrenoInvalidate || op<NativeAdrenoClean)
        return kIOReturnBadArgument;
    const uint64_t began=mach_absolute_time();
    /* One barrier pair per run of up to 64 pages instead of per page (an imported 3048x2032 surface is 5952 pages): preemption stays off
     * for a bounded run, and the closing DSB on the issuing core completes every operation of that run. */
    for(size_t offset=0;offset<bytes;) {
        disable_preemption();
        uint64_t ctr;ctr=cpu_ctr;
        const size_t line=(size_t)4<<((ctr>>16)&15);
        if(line>4096) {enable_preemption();return kIOReturnUnsupported;}
        ++barriers;
        for(unsigned run=0;run<64 && offset<bytes;++run,offset+=4096) {
            /* A page outside the kernel's DRAM is device memory (the firmware framebuffer the display hand-off imports): the CPU maps it
             * uncached (kIOMapInhibitCache), no cache line of it exists to maintain, and phystokv would panic on it (int-080: illegal PA
             * 0xb8000000). */
            const uint64_t page=physical+offset;
            if(page<gPhysBase || page-gPhysBase>=gPhysSize)continue;
            const vm_offset_t alias=phystokv(page);
            if(!alias) {++barriers;enable_preemption();return kIOReturnUnsupported;}
            for(uintptr_t address=alias,end=alias+4096;address<end;address+=line) {
                if(op==NativeAdrenoClean)cache_line(address,0);
                else if(op==NativeAdrenoCleanInvalidate)cache_line(address,1);
                else cache_line(address,2);
            }
        }
        ++barriers;
        enable_preemption();
    }
    noteMaintenance(began,bytes);
    return kIOReturnSuccess;
}
/* A user BO's pages become Normal non-cacheable (write-combined) for every CPU mapping the pmap tracks: the kernel's own mapping and each
 * client view. The views did not get the cache mode their mapping asked for (int-070: Turnip's write-combine view left IB words in a CPU
 * cache line), but they do take the page's own attribute. That is the Linux msm model for its WC BOs: CPU writes reach DRAM, the GPU's
 * non-cacheable reads see them and CPU reads see GPU writes without per-submission maintenance. The physical aperture keeps its cacheable
 * mapping on the reference kernel; the candidate still requires live alias qualification.
 * Nothing writes through that alias, and the caller cleans and invalidates the pages first.
 * Before the pages go back to the VM they get the default attribute again. */
/* Validate the whole list before mutating any pmap page. These spans are
 * complete exclusive backing pages, not clipped 4 KiB GPU-visible ranges. */
static IOReturn cpuCacheSpans(const NativeAdrenoPhysicalSpan *spans,size_t count,
    NativeAdrenoCpuState *cpu,uint64_t *pages)
{
    if(!spans || !count || !cpu || !pages)return kIOReturnBadArgument;
    *pages=0;
    const IOReturn status=NativeAdrenoQueryCpuPages(cpu);if(status)return status;
    const uint64_t bytes=cpu->kernel_page_bytes,mask=bytes-1;
    for(size_t i=0;i<count;++i) {
        const NativeAdrenoPhysicalSpan &span=spans[i];
        if(!span.bytes || ((span.offset|span.physical|span.bytes)&mask) ||
            span.physical>UINT64_MAX-span.bytes || span.physical<gPhysBase ||
            span.physical+span.bytes-gPhysBase>gPhysSize ||
            (uint64_t)(ppnum_t)((span.physical+span.bytes-bytes)>>cpu->cpu_page_shift)!=
                ((span.physical+span.bytes-bytes)>>cpu->cpu_page_shift))return kIOReturnBadArgument;
        if(span.bytes/bytes>UINT64_MAX-*pages)return kIOReturnBadArgument;
        *pages+=span.bytes/bytes;
    }
    return kIOReturnSuccess;
}
IOReturn NativeAdrenoSetPagesCacheMode(const NativeAdrenoPhysicalSpan *spans,size_t count,bool write_combined)
{
    NativeAdrenoCpuState cpu{};uint64_t pages=0;
    IOReturn status=cpuCacheSpans(spans,count,&cpu,&pages);if(status)return status;
    const unsigned normal=VM_WIMG_DEFAULT&VM_WIMG_MASK;
    const unsigned wanted=write_combined?VM_WIMG_WCOMB:normal;
    /* Exclusive fresh IOBuffer backing must begin with its known default
     * attribute. Refuse unknown modes rather than claiming to restore them. */
    for(size_t i=0;i<count;++i)for(uint64_t offset=0;offset<spans[i].bytes;offset+=cpu.kernel_page_bytes) {
        const ppnum_t pn=(ppnum_t)((spans[i].physical+offset)>>cpu.cpu_page_shift);
        const unsigned current=pmap_cache_attributes(pn)&VM_WIMG_MASK;
        if(write_combined?current!=normal:(current!=normal && current!=VM_WIMG_WCOMB))return kIOReturnUnsupported;
    }
    for(size_t i=0;i<count;++i)for(uint64_t offset=0;offset<spans[i].bytes;offset+=cpu.kernel_page_bytes) {
        const ppnum_t pn=(ppnum_t)((spans[i].physical+offset)>>cpu.cpu_page_shift);
        pmap_set_cache_attributes(pn,write_combined?VM_WIMG_WCOMB:VM_WIMG_USE_DEFAULT);
        if((pmap_cache_attributes(pn)&VM_WIMG_MASK)!=wanted)return kIOReturnIOError;
    }
    if(write_combined)__atomic_fetch_add(&native_adreno_cache_stats[4],pages,__ATOMIC_RELAXED);
    else __atomic_fetch_sub(&native_adreno_cache_stats[4],pages,__ATOMIC_RELAXED);
    return kIOReturnSuccess;
}
IOReturn NativeAdrenoReassertWriteCombined(const NativeAdrenoPhysicalSpan *spans,size_t count,uint32_t *reset)
{
    if(!reset)return kIOReturnBadArgument;
    NativeAdrenoCpuState cpu{};uint64_t pages=0;
    IOReturn status=cpuCacheSpans(spans,count,&cpu,&pages);if(status)return status;
    const uint64_t began=mach_absolute_time();
    for(size_t i=0;i<count;++i)for(uint64_t offset=0;offset<spans[i].bytes;offset+=cpu.kernel_page_bytes) {
        const ppnum_t pn=(ppnum_t)((spans[i].physical+offset)>>cpu.cpu_page_shift);
        const unsigned current=pmap_cache_attributes(pn)&VM_WIMG_MASK;
        if(current!=VM_WIMG_WCOMB) {
            if(current!=(VM_WIMG_DEFAULT&VM_WIMG_MASK))return kIOReturnUnsupported;
            pmap_set_cache_attributes(pn,VM_WIMG_WCOMB);
            if((pmap_cache_attributes(pn)&VM_WIMG_MASK)!=VM_WIMG_WCOMB)return kIOReturnIOError;
            ++*reset;
        }
    }
    __atomic_fetch_add(&native_adreno_reassert_ticks,mach_absolute_time()-began,__ATOMIC_RELAXED);
    return kIOReturnSuccess;
}
/* SPDX-License-Identifier: MIT */
#include "NativeAdrenoMemory.h"
#include "NativeAdrenoCpuPagePolicy.h"
/* Where a call that never returns is stuck: the free/unmap/release path stores a stage number here, the board page shows it. */
extern "C" {volatile uint32_t native_adreno_trace_stage;}
#include <IOKit/IOBufferMemoryDescriptor.h>
#include <IOKit/IOLib.h>
#include <kern/task.h>

static bool outputWidth(unsigned bits)
{return bits==32 || bits==36 || bits==40 || bits==42 || bits==44 || bits==48;}
/* Where the last import stopped (10..19, 19 = done), and for a refused page the physical address and offset: the board log shows them. */
enum : IOReturn {kNativeAdrenoProtectionFailure=2};   /* KERN_PROTECTION_FAILURE, as prepare() reports a range that cannot be wired for writing */
extern "C" {volatile uint32_t native_adreno_pool_mib=0,native_adreno_pool_status=0;volatile uint32_t native_adreno_import_stage;volatile uint64_t native_adreno_import_fail_pa,native_adreno_import_fail_offset;}
/* Original diagnostic symbol names retained; this candidate has no BO pool. */
extern "C" {volatile uint32_t native_adreno_pool_stats[8];}
/* The pool's write-combine (writeCombinePool): bit 31 once tried, the low bits its status. */
extern "C" {volatile uint32_t native_adreno_pool_wc;}   /* [0] pool MiB, [1] BOs from the pool, [2] fell back, [3] MiB in use, [4] peak MiB, [5] scattered BOs, [6] their spans, [7] import spans */
/* Candidate: no shared suballocation. Every BO owns complete qualified CPU
 * pages; the logical GPU byte length remains separately 4 KiB granular. */
size_t NativeAdrenoMemory::poolBytes() {return 0;}
IOReturn NativeAdrenoMemory::writeCombinePool() {return kIOReturnUnsupported;}
IOReturn NativeAdrenoMemory::reservePool(unsigned,size_t) {return kIOReturnUnsupported;}
size_t NativeAdrenoMemory::backingBudget(size_t logical)
{
    NativeAdrenoCpuState cpu{};size_t owned=0;
    if(NativeAdrenoQueryCpuPages(&cpu)!=kIOReturnSuccess ||
        !NativeAdrenoRoundCpuBacking(logical,(size_t)cpu.kernel_page_bytes,&owned) ||
        owned>256u*1024u*1024u)return 0;
    return owned;
}
IOReturn NativeAdrenoMemory::allocate(size_t bytes,unsigned bits,bool contiguous,size_t budget,bool pooled)
{
    (void)pooled; /* First candidate deliberately falls back to exclusive BOs. */
    if(descriptor_ || imported_ || spans_ || owned_spans_ || quarantined_)return kIOReturnBusy;
    if(!bytes || (bytes&4095) || !outputWidth(bits) || !budget || budget>256u*1024u*1024u)
        return kIOReturnBadArgument;
    if(bytes>budget)return kIOReturnNoResources;
    NativeAdrenoCpuState cpu{};
    IOReturn status=NativeAdrenoQueryCpuPages(&cpu);if(status!=kIOReturnSuccess)return status;
    size_t owned=0;
    const size_t cpu_bytes=(size_t)cpu.kernel_page_bytes;
    if(!NativeAdrenoRoundCpuBacking(bytes,cpu_bytes,&owned) || owned>256u*1024u*1024u)return kIOReturnBadArgument;
    if(owned>budget)return kIOReturnNoResources;
    const uint64_t limit=UINT64_C(1)<<bits;
    IOOptionBits options=static_cast<IOOptionBits>(kIODirectionInOut)|static_cast<IOOptionBits>(kIOMemoryMapperNone);
    if(contiguous)options|=kIOMemoryPhysicallyContiguous;
    descriptor_=IOBufferMemoryDescriptor::inTaskWithPhysicalMask(kernel_task,options,owned,(limit-1)&~uint64_t(cpu_bytes-1));
    if(!descriptor_)return kIOReturnNoMemory;
    status=descriptor_->prepare();
    if(status!=kIOReturnSuccess) {descriptor_->release();descriptor_=nullptr;return status;}
    prepared_=true;bytes_=bytes;owned_bytes_=owned;cpu_page_bytes_=cpu_bytes;mapping_=descriptor_->getBytesNoCopy();
    status=kIOReturnUnsupported;
    if(!mapping_ || ((uintptr_t)mapping_&(cpu_bytes-1)) || owned>UINTPTR_MAX-(uintptr_t)mapping_ ||
        descriptor_->getLength()!=owned)goto failed;
    owned_span_capacity_=owned/cpu_bytes;span_capacity_=bytes/4096;
    owned_spans_=IONewData(NativeAdrenoPhysicalSpan,owned_span_capacity_);
    spans_=IONewData(NativeAdrenoPhysicalSpan,span_capacity_);
    if(!owned_spans_ || !spans_) {status=kIOReturnNoMemory;goto failed;}
    for(size_t offset=0;offset<owned;offset+=cpu_bytes) {
        IOByteCount length=0;
        const addr64_t physical=descriptor_->getPhysicalSegment(offset,&length,kIOMemoryMapperNone);
        if(!physical || (physical&(cpu_bytes-1)) || length<cpu_bytes || physical>=limit || cpu_bytes>limit-physical)
            {status=kIOReturnUnsupported;goto failed;}
        if(contiguous && offset && physical!=owned_spans_[0].physical+offset)
            {status=kIOReturnUnsupported;goto failed;}
        if(owned_span_count_ && physical==owned_spans_[owned_span_count_-1].physical+owned_spans_[owned_span_count_-1].bytes)
            owned_spans_[owned_span_count_-1].bytes+=cpu_bytes;
        else owned_spans_[owned_span_count_++]={offset,physical,cpu_bytes};
    }
    /* Clip only GPU-visible spans. Rounded tail is CPU-owned, zeroed and never
     * implicitly mapped into the GPU aperture or another BO's CPU view. */
    for(size_t i=0;i<owned_span_count_ && owned_spans_[i].offset<bytes;++i) {
        const auto &o=owned_spans_[i];
        const uint64_t length=o.bytes<bytes-o.offset?o.bytes:bytes-o.offset;
        spans_[span_count_++]={o.offset,o.physical,length};
    }
    bzero(mapping_,owned);
    status=NativeAdrenoMaintainOwnedPages(mapping_,owned,NativeAdrenoClean);
    if(status!=kIOReturnSuccess)goto failed;
    native_adreno_pool_stats[5]=native_adreno_pool_stats[5]+1;native_adreno_pool_stats[6]=native_adreno_pool_stats[6]+(uint32_t)span_count_;
    return kIOReturnSuccess;
failed:
    /* Metadata, full backing and descriptor remain owned on failed complete. */
    (void)release();return status;
}
/* An import holds the pages through a memory entry of its own (kIOMemoryPersistent), which references the VM object: the owner may unmap
 * its range while the GPU still uses it (Core Animation frees an image's Shmem once its no-copy buffer is released, before the runtime frees
 * the import), and the object then lives on until the import completes instead of being torn down under a wired UPL (int-233..235: the render
 * thread stuck in vm_deallocate). A range no memory entry can be made of is imported as before; [0] counts the persistent imports, [1] those. */
extern "C" {volatile uint32_t native_adreno_import_persistent[2];}
static IOMemoryDescriptor *importRange(uint64_t address,size_t bytes,IODirection direction,void *task)
{
    const IOOptionBits options=static_cast<IOOptionBits>(direction)|static_cast<IOOptionBits>(kIOMemoryMapperNone);
    IOMemoryDescriptor *range=IOMemoryDescriptor::withAddressRange(address,bytes,options|kIOMemoryPersistent,static_cast<task_t>(task));
    if(range) {native_adreno_import_persistent[0]=native_adreno_import_persistent[0]+1;return range;}
    range=IOMemoryDescriptor::withAddressRange(address,bytes,options,static_cast<task_t>(task));
    if(range)native_adreno_import_persistent[1]=native_adreno_import_persistent[1]+1;
    return range;
}
IOReturn NativeAdrenoMemory::importTask(void *task,uint64_t address,size_t bytes,unsigned bits,size_t budget)
{
    native_adreno_import_stage=10;
    if(descriptor_ || imported_ || spans_ || owned_spans_ || quarantined_)return kIOReturnBusy;
    native_adreno_import_stage=11;
    if(!task || !address || (address&4095) || !bytes || (bytes&4095) || address>UINT64_MAX-bytes || !outputWidth(bits) ||
        !budget || budget>256u*1024u*1024u)return kIOReturnBadArgument;
    native_adreno_import_stage=12;
    if(bytes>budget)return kIOReturnNoResources;
    NativeAdrenoCpuState cpu{};
    native_adreno_import_stage=13;
    IOReturn status=NativeAdrenoQueryCpuPages(&cpu);if(status!=kIOReturnSuccess)return status;
    const size_t cpu_bytes=(size_t)cpu.kernel_page_bytes;
    /* Partial CPU pages cannot establish the complete pinned range boundary. */
    if((address|bytes)&(cpu_bytes-1))return kIOReturnUnsupported;
    const uint64_t limit=UINT64_C(1)<<bits;
    imported_=importRange(address,bytes,kIODirectionInOut,task);
    native_adreno_import_stage=14;
    if(!imported_)return kIOReturnNoMemory;
    native_adreno_import_stage=15;
    status=imported_->prepare();
    if(status==kNativeAdrenoProtectionFailure) {
        /* Read-only memory of the owner (a mapped file, constant data): cannot be pinned for writing. Pin it for reading only; the GPU then maps it
         * read-only. Metal's no-copy buffers over such memory are only ever read by shaders. */
        imported_->release();imported_=nullptr;
        imported_=importRange(address,bytes,kIODirectionOut,task);
        if(!imported_)return kIOReturnNoMemory;
        status=imported_->prepare();
        if(status==kIOReturnSuccess)read_only_=true;
    }
    if(status!=kIOReturnSuccess) {imported_->release();imported_=nullptr;return status;}
    prepared_=true;bytes_=bytes;owned_bytes_=bytes;cpu_page_bytes_=cpu_bytes;
    status=kIOReturnUnsupported;
    native_adreno_import_stage=16;
    if(imported_->getLength()!=bytes)goto failed;
    native_adreno_import_stage=17;
    span_capacity_=bytes/4096;owned_span_capacity_=bytes/cpu_bytes;
    spans_=IONewData(NativeAdrenoPhysicalSpan,span_capacity_);
    owned_spans_=IONewData(NativeAdrenoPhysicalSpan,owned_span_capacity_);
    if(!spans_ || !owned_spans_) {status=kIOReturnNoMemory;goto failed;}
    for(size_t offset=0;offset<bytes;offset+=cpu_bytes) {
        IOByteCount length=0;
        const addr64_t physical=imported_->getPhysicalSegment(offset,&length,kIOMemoryMapperNone);
        if(!physical || (physical&(cpu_bytes-1)) || length<cpu_bytes || physical>=limit || cpu_bytes>limit-physical)
            {native_adreno_import_stage=18;native_adreno_import_fail_pa=physical;native_adreno_import_fail_offset=offset;
             status=kIOReturnUnsupported;goto failed;}
        if(span_count_ && physical==spans_[span_count_-1].physical+spans_[span_count_-1].bytes) {
            spans_[span_count_-1].bytes+=cpu_bytes;owned_spans_[owned_span_count_-1].bytes+=cpu_bytes;
        } else {
            spans_[span_count_++]={offset,physical,cpu_bytes};
            owned_spans_[owned_span_count_++]={offset,physical,cpu_bytes};
        }
    }
    native_adreno_import_stage=19;
    native_adreno_pool_stats[7]=native_adreno_pool_stats[7]+(uint32_t)span_count_;
    return kIOReturnSuccess;
failed:
    (void)release();return status;
}
IOReturn NativeAdrenoMemory::makeWriteCombined()
{
    if(!descriptor_ || imported_ || !prepared_ || quarantined_ || device_references_ || write_combined_ || !mapping_ || !span_count_)
        return kIOReturnNotReady;
    IOReturn status=NativeAdrenoMaintainOwnedPages(mapping_,owned_bytes_,NativeAdrenoCleanInvalidate);
    if(status)return status;
    /* Mark before mutation: a void pmap write plus failed readback has unknown
     * partial state and may never release these CPU pages back to the VM. */
    write_combined_=true;
    status=NativeAdrenoSetPagesCacheMode(owned_spans_,owned_span_count_,true);
    if(status) {quarantined_=true;return status;}
    return kIOReturnSuccess;
}
IOReturn NativeAdrenoMemory::release()
{
    native_adreno_trace_stage=30;
    if(device_references_ || quarantined_)return kIOReturnBusy;
    if(write_combined_) {
        /* The pages go back to the VM cacheable, as they came. */
        const IOReturn status=NativeAdrenoSetPagesCacheMode(owned_spans_,owned_span_count_,false);
        if(status) {quarantined_=true;return status;}
        write_combined_=false;
    }
    if(imported_) {
        if(prepared_) {
            IOReturn status=imported_->complete();
            if(status!=kIOReturnSuccess) {quarantined_=true;return status;}
            prepared_=false;
        }
        imported_->release();imported_=nullptr;
    }
    if(descriptor_) {
        if(prepared_) {
            native_adreno_trace_stage=31;
            IOReturn status=descriptor_->complete();
            native_adreno_trace_stage=32;
            if(status!=kIOReturnSuccess) {quarantined_=true;return status;}
            prepared_=false;
        }
        native_adreno_trace_stage=33;
        descriptor_->release();descriptor_=nullptr;
        native_adreno_trace_stage=34;
    }
    if(spans_)IODeleteData(spans_,NativeAdrenoPhysicalSpan,span_capacity_);
    if(owned_spans_)IODeleteData(owned_spans_,NativeAdrenoPhysicalSpan,owned_span_capacity_);
    mapping_=nullptr;spans_=nullptr;owned_spans_=nullptr;bytes_=span_count_=span_capacity_=0;
    owned_bytes_=owned_span_count_=owned_span_capacity_=cpu_page_bytes_=0;read_only_=false;
    return kIOReturnSuccess;
}
IOReturn NativeAdrenoMemory::holdForDevice()
{
    if(!backed() || !prepared_ || !span_count_ || quarantined_)return kIOReturnNotReady;
    if(device_references_==UINT32_MAX)return kIOReturnNoResources;
    ++device_references_;return kIOReturnSuccess;
}
IOReturn NativeAdrenoMemory::retireAfterQuiescence()
{
    if(!device_references_)return kIOReturnBadArgument;
    if(quarantined_)return kIOReturnNotReady;
    --device_references_;return kIOReturnSuccess;
}
IOReturn NativeAdrenoMemory::publishForDevice(size_t offset,size_t bytes,bool writes,bool include_write_combined)
{
    if(!backed() || !prepared_ || quarantined_)return kIOReturnNotReady;
    if(!bytes || ((offset|bytes)&4095) || offset>bytes_ || bytes>bytes_-offset)return kIOReturnBadArgument;
    if(imported_)return maintainImported(offset,bytes,writes?NativeAdrenoCleanInvalidate:NativeAdrenoClean);
    if(write_combined_)   /* no CPU mapping should cache these pages; if one does, reach its lines through the physical pages */
        return include_write_combined?maintainImported(offset,bytes,writes?NativeAdrenoCleanInvalidate:NativeAdrenoClean):kIOReturnSuccess;
    return NativeAdrenoMaintainOwnedPages(static_cast<unsigned char *>(mapping_)+offset,bytes,
        writes?NativeAdrenoCleanInvalidate:NativeAdrenoClean);
}
IOReturn NativeAdrenoMemory::acquireDeviceWrites(size_t offset,size_t bytes)
{
    if(!backed() || !prepared_ || quarantined_)return kIOReturnNotReady;
    if(!bytes || ((offset|bytes)&4095) || offset>bytes_ || bytes>bytes_-offset)return kIOReturnBadArgument;
    /* Imported pages may hold the owner's unrelated dirty lines next to the GPU's writes: clean as well as invalidate. */
    if(imported_)return maintainImported(offset,bytes,NativeAdrenoCleanInvalidate);
    if(write_combined_)return kIOReturnSuccess;
    return NativeAdrenoMaintainOwnedPages(static_cast<unsigned char *>(mapping_)+offset,bytes,NativeAdrenoInvalidate);
}
/* Imported pages have no kernel mapping here (and write-combined ones only a non-cacheable one); maintain each span's part of
 * [offset, offset+bytes) by physical address. */
IOReturn NativeAdrenoMemory::maintainImported(size_t offset,size_t bytes,NativeAdrenoCacheOperation op)
{
    for(size_t i=0;i<span_count_;++i) {
        const NativeAdrenoPhysicalSpan &span=spans_[i];
        const size_t begin=offset>span.offset?offset:span.offset;
        const size_t end=offset+bytes<span.offset+span.bytes?offset+bytes:span.offset+span.bytes;
        if(begin>=end)continue;
        const IOReturn status=NativeAdrenoMaintainPhysicalPages(span.physical+(begin-span.offset),end-begin,op);
        if(status)return status;
    }
    return kIOReturnSuccess;
}

#include <cassert>
#include <cstdint>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include <array>
#include <algorithm>

#include "GpuPowerOnlyHandoff.h"
extern "C" void fixture_record(unsigned char *);
extern "C" uint32_t fixture_register(uint32_t);
enum {OSNoRetain=0,kIOMapAnywhere=1,kIOMapReadOnly=2,kIOMapInhibitCache=4};
struct OSObject {virtual ~OSObject()=default;};
struct OSData:OSObject {
 const void *bytes=nullptr;unsigned length=0;
 const void *getBytesNoCopy(){return bytes;}unsigned getLength(){return length;}
};
struct IOMemoryMap {
 uint64_t va=0,length=0;unsigned index=0;
 uint64_t getVirtualAddress();uint64_t getLength(){return length;}
};
template<class T>struct OSSharedPtr {
 T *pointer=nullptr;OSSharedPtr()=default;OSSharedPtr(T*p,int):pointer(p){}
 explicit operator bool()const{return pointer!=nullptr;}T*operator->()const{return pointer;}
};
static OSData property;static OSObject wrong_type;
static bool chosen_present=true,property_present=true,property_type=true;
static unsigned chosen_lookups,chosen_releases,property_lookups,descriptors,descriptor_releases;
static unsigned map_calls,boot_calls,fail_alloc,fail_map,bad_mapping,bad_kind;
static int boot_value=1;static bool boot_present=true;
static std::vector<std::string> logs;
static std::vector<uint32_t> backing[6];static IOMemoryMap mappings[6];
static std::vector<unsigned> mapping_order;
static const uint64_t mock_base[]={0x170000,0x3d90000,0x3d7c000,0x3da0000,0x3d6c000,0x3d8c000};
static const uint64_t mock_size[]={0x4000,0x10000,0x4000,0x40000,0x10000,0x4000};
static uint32_t& word(uint32_t address){
 for(unsigned i=0;i<6;i++)if(address>=mock_base[i] && address-mock_base[i]<mock_size[i])return backing[i][(address-mock_base[i])/4];
 CHECK(false);return backing[0][0];
}
struct IODeviceMemory {
 unsigned index;
 static IODeviceMemory *withRange(uint64_t base,uint64_t bytes){
  unsigned i=0;for(;i<6;i++)if(base==mock_base[i] && bytes==mock_size[i])break;
  CHECK(i<6);mapping_order.push_back(i);if(fail_alloc==i+1)return nullptr;
  ++descriptors;return new IODeviceMemory{i};
 }
 IOMemoryMap *map(unsigned options){
  CHECK(options==(unsigned)(kIOMapAnywhere|kIOMapInhibitCache|(secure_mode?kIOMapReadOnly:((index==2 || index==3 || index==4 || index==5)?0:kIOMapReadOnly))));++map_calls;
  if(fail_map==index+1)return nullptr;static IOMemoryMap secure_maps[6];auto&m=secure_mode?secure_maps[index]:mappings[index];
  m.index=index;m.va=(uint64_t)(uintptr_t)backing[index].data();m.length=mock_size[index];
  if(bad_mapping==index+1){if(!bad_kind)m.va=0;if(bad_kind==1)m.va++;if(bad_kind==2)m.length--;if(bad_kind==3)m.va=UINT64_MAX-3;}
  return &m;
 }
 void release(){++descriptor_releases;delete this;}
};
static const char *gIODTPlane="IODeviceTree";
struct IORegistryEntry {
 static IORegistryEntry *fromPath(const char *path,const char *plane){
  CHECK(!strcmp(path,"/chosen") && plane==gIODTPlane);++chosen_lookups;
  static IORegistryEntry chosen;return chosen_present?&chosen:nullptr;
 }
 OSObject *getProperty(const char *key){CHECK(!strcmp(key,"houji,gpu-power-handoff"));++property_lookups;return !property_present?nullptr:property_type?&property:&wrong_type;}
 void release(){++chosen_releases;}
};
#define OSDynamicCast(type,value) dynamic_cast<type*>(value)
static bool PE_parse_boot_argn(const char*name,void*out,int bytes){if(!strcmp(name,"houji_gpu_scm_probe")){*(int*)out=scm_boot;return true;}if(!strcmp(name,"houji_gpu_fw_mem_probe")){*(int*)out=1;return true;}if(!strcmp(name,"houji_gpu_external_nc_probe")){CHECK(bytes==(int)sizeof(int));if(nc_boot_present)*(int*)out=nc_boot_value;return nc_boot_present;}
 CHECK(!strcmp(name,"houji_gpu_external_canary_probe") && bytes==sizeof(int));++boot_calls;
 if(boot_present)*(int*)out=boot_value;return boot_present;
}
static void IOLog(const char*,...);

static bool gRootEnabled=true,gLogEnabled=true,gReturnRecovery=true;
extern "C" void houji_ufs_checkpoint(const char*,unsigned);
static void IODelay(unsigned);
static void IOSleep(unsigned);
#define HOUJI_GPU_EXTERNAL_CANARY_PROBE_HOST_TEST 1
#include "HoujiGpuExternalCanaryProbe.inc"
struct Store{unsigned phase,wide;uint32_t address;uint64_t value;};
static std::vector<Store> stores;
static std::array<std::vector<unsigned char>,3> dram;
static unsigned map_accesses,fail_map_access,corrupt_store,owner_lost_store,clock_lost_store,at_calls,fail_at;
static unsigned checkpoint_calls,fail_commit,mutate_commit,damage_backup_commit,damage_prepared_commit,damage_prepared_sctlr;
static unsigned final_save_calls,panic_calls,mail_delay,mail_behavior,delay_calls,publication_count,invalidate_count,wrong_data,padding_damage,zero_damage,negative_wrong,apply_partial_dma;
static unsigned expose_data_reads,fail_cpu_cache,table_extra,table_bit,fail_cache_once,early_checkpoint_calls,early_post_clock_loss,early_owner_loss,no_submission_checkpoints,no_submission_failures,ns_post_clock_loss,ns_post_table_damage,ns_post_owner_loss;
static unsigned failure_holds,failure_hold_ms;
static unsigned fault_mail_bit,fault_stack_bit,fault_saved_seed;
static std::array<unsigned char,HPH_RECORD_BYTES+1> wire;static hph_record original;
struct SimulatedTerminalPanic{};
uint64_t IOMemoryMap::getVirtualAddress(){if(index>=2 && ++map_accesses==fail_map_access)return 0;return va;}
static void IOLog(const char*f,...){char b[2048];va_list ap;va_start(ap,f);int n=vsnprintf(b,sizeof(b),f,ap);va_end(ap);CHECK(n>=0 && (size_t)n<sizeof(b));logs.emplace_back(b);}

static unsigned alias_fault,bad_par_at,nc_shareability=0,alias_at_calls;
static unsigned change_alias_commit,change_attr_commit,change_alias_acquire,change_attr_acquire,nc_data_dc,nc_pretransition_lines,nc_barrier_calls;
static bool alias_wb=true,nc_no_cpu_dma_write;
static bool houjiGpuExternalAt(uint64_t va,bool write,uint64_t*par){
 CHECK(par);++at_calls;const bool alias=(va>>48)==0xffff;if(alias)++alias_at_calls;
 auto&p=gHoujiGpuExternalCanary;
 for(auto*d:fixture.live){
  uint64_t begin=alias?(UINT64_C(0xffff000000000000)|d->physical_base):(uint64_t)(uintptr_t)d->raw;
  if(va<begin || va-begin>=d->bytes)continue;
  uint64_t pa=d->physical_base+va-begin;unsigned attr=(alias && alias_wb)?0xff:attributes[(ppnum_t)(pa>>14)]==VM_WIMG_WCOMB?0x44:attributes[(ppnum_t)(pa>>14)]==VM_WIMG_DEFAULT?0xff:0;
  if(alias && alias_fault==1)attr=0;if(alias && alias_fault==2)attr=0x55;
  if(alias && alias_fault==4 && write)attr=attr==0xff?0x44:0xff;
  const unsigned share=attr==0x44?nc_shareability:3u;
  *par=((uint64_t)attr<<56)|(pa&UINT64_C(0x0000fffffffff000))|0x800|((uint64_t)share<<7);
  if(alias && alias_fault==3)*par^=UINT64_C(1)<<12;
  if(at_calls==fail_at)*par=1;if(at_calls==bad_par_at)*par^=UINT64_C(1)<<56;
  if(fail_cpu_cache && p.result.phase==GEC_PHASE_CPU_FINISH)cpu_ctr=UINT64_C(11)<<16;
  return true;
 }CHECK(false);return false;
}
static void host_pmap_hook(uint32_t pn,unsigned attr){
 if(firmware_mode){CHECK(attr==VM_WIMG_WCOMB);return;}auto&p=gHoujiGpuExternalCanary;CHECK(attr==VM_WIMG_WCOMB && !p.held_mask && !p.published_mask && stores.empty());
 for(auto*d:fixture.live)if((d->physical_base>>14)==pn){
  CHECK(pn!=(p.info[GECN_TABLE].pa>>14));
  unsigned lines=0;for(auto&c:cache_lines)if(c.address>=(uintptr_t)d->raw && c.address-(uintptr_t)d->raw<d->bytes && c.operation==1)++lines;
  CHECK(lines==256 && !preemption_depth);nc_pretransition_lines+=lines;
  for(auto&bo:p.bo)CHECK(!bo.deviceReferences());return;
 }CHECK(false);
}
static void external_cache_hook(uintptr_t address,unsigned op){
 auto&p=gHoujiGpuExternalCanary;auto&r=p.result;
 if(fail_cpu_cache && r.phase==GEC_PHASE_CPU_FINISH && !fail_cache_once++){cpu_ctr=UINT64_C(11)<<16;return;}
 for(unsigned i=0;i<3;i++){
  const auto&b=p.info[i];if(!b.allocated || address<b.va || address-b.va>=b.owned)continue;
  CHECK(!(address&63));
  if(i!=GECN_TABLE && p.bo[i].writeCombined()){++nc_data_dc;CHECK(false);}
  if(r.phase==GEC_PHASE_BACKUP_COMMIT){CHECK(!p.release_seen && r.publication.attempted && !r.publication.returned);if(address==b.va+b.owned-64){dram[i].assign((unsigned char*)b.va,(unsigned char*)b.va+b.owned);++publication_count;}}
  if(r.phase==GEC_PHASE_CPU_FINISH && op==2){CHECK(houjiGpuExternalIsolated() && p.cpu_access_allowed && p.cpu_finish_called && dram[i].size()==16384);if(address==b.va)memcpy((void*)b.va,dram[i].data(),dram[i].size());++invalidate_count;}
 }
}
static uint64_t device_walk(uint64_t iova){
 auto&p=gHoujiGpuExternalCanary;uint64_t pa=p.memory.owned.table_physical;
 CHECK(dram[0].size()==16384);
 for(unsigned level=1;level<=3;level++){
  CHECK(pa>=p.info[0].pa && pa-p.info[0].pa<12288);uint64_t d=0;
  memcpy(&d,dram[0].data()+pa-p.info[0].pa+8*((iova>>(39-9*level))&511),8);
  if(!d)return 0;CHECK((d&3)==3);if(level==3)return (d&UINT64_C(0x0000fffffffff000))|(iova&4095);pa=d&UINT64_C(0x0000fffffffff000);
 }CHECK(false);return 0;
}
static void finish_program(){
 auto&p=gHoujiGpuExternalCanary;auto&r=p.result;CHECK(p.release_seen && p.held_mask==7 && publication_count==3);
 CHECK(device_walk(0x60000000)==p.info[1].pa && device_walk(0x60000fff)==p.info[1].pa+4095 && !device_walk(0x60002000));
 CHECK(word(0x3da0800)==0x80000005 && word(0x3da0c00)==2 && (word(HGP_CB(0))&1));
 if(mail_behavior==3)return;
 uint32_t value=wrong_data?0xdeadbeef:0xa750cafe;memcpy(dram[1].data()+8,&value,4);
 // Peer performs the DMA store against NC memory itself. No invalidate hook copies it.
 if(p.memory_profile==GEC_MEMORY_NORMAL_NC){
  if(!nc_no_cpu_dma_write)memcpy((unsigned char*)p.memory.owned.data+8,&value,4);
  CHECK(((uint32_t*)p.memory.owned.data)[2]==(nc_no_cpu_dma_write?0:value));
 }else CHECK(((uint32_t*)p.memory.owned.data)[2]==0);++expose_data_reads;
 if(padding_damage){dram[1][4096]^=1;((unsigned char*)p.memory.owned.data)[4096]^=1;}
 if(zero_damage){dram[2][0]^=1;((unsigned char*)p.memory.zero_cpu)[0]^=1;}
 if(apply_partial_dma){word(0x3d71000)=0xa7500001;return;}
 const uint32_t mail[]={0xa7500003,0x7504cafe,0x86500071,0xa750cafe,0,0,0,0};
 for(unsigned i=0;i<8;i++)word(0x3d71000+4*i)=mail[i];
 if(mail_behavior==1)word(0x3d71000)=0xa750dead;if(mail_behavior==2)word(0x3d71004)^=1;
 if(mail_behavior==5)word(0x3d74f60)^=1;
 // Exact same fixed176B payload's precise negative BusFault path. The
 // CPU/DRAM peer still forces real native publication and invalidate.
 if(mail_behavior==4){
  word(0x3d71000)=0xa750dead;word(0x3d71018)=0x8200;word(0x3d7101c)=0x60002000;
  const uint32_t frame[]={0x10004000,0xa7500001,0x60002000,0xa750cafe,
    0xcef01234u^fault_saved_seed,0xdeadbeefu^fault_saved_seed,0x6e,0x01000000};
  for(unsigned i=0;i<8;i++)word(0x3d74f60+4*i)=frame[i];
  if(fault_mail_bit){unsigned bit=fault_mail_bit-1;word(0x3d71000+4*(bit/32))^=1u<<(bit%32);}
  if(fault_stack_bit){unsigned bit=fault_stack_bit-1;word(0x3d74f40+4*(bit/32))^=1u<<(bit%32);}
 }

 word(HGP_CB(0x58))=negative_wrong?4:2;word(HGP_CB(0x60))=negative_wrong?0x60003000:0x60002000;word(HGP_CB(0x64))=0;word(HGP_CB(0x68))=0;
 (void)r;
}
static void houjiGpuExternalReadBarrier(){++barriers;auto&p=gHoujiGpuExternalCanary;if(early_owner_loss && p.early_in_fresh && p.early_current==0)p.active=0;}
static void houjiGpuExternalWriteBarrier(){
 auto&p=gHoujiGpuExternalCanary;auto&r=p.result;CHECK(p.pending_barrier && p.held_mask==7 && r.backup_committed);
 uint64_t actual=word(p.last_address);if(p.last_wide)actual|=(uint64_t)word(p.last_address+4)<<32;CHECK(actual==p.last_value);
 stores.push_back({r.phase,p.last_wide,p.last_address,p.last_value});
 const int c=gie_control_index(p.last_address);if(c==8 && r.phase==GEC_PHASE_CONTROL)word(p.last_address)&=127;
 if(p.last_address==HGP_CB(0x58)){CHECK(p.last_value==2 && r.phase==GEC_PHASE_CLEAR_FAULT && houjiGpuExternalIsolated()==false);word(p.last_address)=0;}
 if(stores.size()==corrupt_store)word(p.last_address)^=1;
 if(stores.size()==owner_lost_store)p.active=0;if(stores.size()==clock_lost_store)word(0x171004)=0;
 if(p.last_address==0x3d7e000 && !p.last_value && !mail_delay)finish_program();
}
static void houjiGpuExternalFullBarrier(){++barriers;}

static void houjiGpuExternalNcPublishBarrier(){
 ++barriers;++nc_barrier_calls;auto&p=gHoujiGpuExternalCanary;auto&r=p.result;
 if(r.phase==GEC_PHASE_BACKUP_COMMIT){
  CHECK(!p.held_mask && !p.release_seen && p.memory_profile==GEC_MEMORY_NORMAL_NC);
  unsigned i=(p.nc_published&(1u<<GECN_DATA))?GECN_ZERO:GECN_DATA;
  CHECK(p.bo[i].writeCombined() && !p.bo[i].deviceReferences());
  dram[i].assign((unsigned char*)p.bo[i].mapping(),(unsigned char*)p.bo[i].mapping()+p.bo[i].ownedBytes());++publication_count;
 }else{
  CHECK(r.phase==GEC_PHASE_CPU_FINISH && p.cpu_access_allowed && houjiGpuExternalIsolated());
  CHECK(((uint32_t*)p.memory.owned.data)[2]==0);memcpy(dram[1].data(),p.memory.owned.data,16384);
 }
}
static void houjiGpuExternalNcAcquireBarrier(){
 ++barriers;++nc_barrier_calls;auto&p=gHoujiGpuExternalCanary;
 CHECK(p.result.phase==GEC_PHASE_CPU_FINISH && p.cpu_access_allowed && p.cpu_finish_called && houjiGpuExternalIsolated());
 if(change_alias_acquire)alias_wb=false;if(change_attr_acquire)attributes[(ppnum_t)(p.info[GECN_DATA].pa>>14)]=VM_WIMG_DEFAULT;
 // This is ordering only: deliberately no stale-WB-copy invalidation or memcpy.
}

static void IODelay(unsigned us){CHECK(us==10);++delay_calls;if(mail_delay && delay_calls==mail_delay)finish_program();}
static void IOSleep(unsigned ms){if(secure_mode){CHECK(ms==30);return;}
 const auto&p=gHoujiGpuExternalCanary;const auto&r=p.result;
 CHECK(ms==8000 && r.started && !r.safe_to_save && !p.active && p.phase==4 && logs.size()>=4);
 for(auto&b:p.bo)if(b.backed())CHECK(b.quarantined());
 for(unsigned i=0;i<4;i++){char prefix[32];snprintf(prefix,sizeof(prefix),"HOUJI GMU STOP%u ",i+1);CHECK(logs[logs.size()-4+i].rfind(prefix,0)==0);}
 ++failure_holds;failure_hold_ms+=ms;
}
extern "C" void houji_ufs_checkpoint(const char*label,unsigned stop){if(secure_mode){host_secure_checkpoint(label,stop);return;}
 auto&p=gHoujiGpuExternalCanary;auto&r=p.result;CHECK(stop==0 && p.in_commit && !p.fresh_ready && !p.pending_barrier && word(0x3d7e000)==1);
 if(strstr(label,"NO SUBMISSION")){
  const unsigned kind=strstr(label,"failure")?1u:0u;const auto&d=p.no_submission[2*kind];
  CHECK(p.core_called && !r.possible_execution && !p.release_seen && !p.reset_seen && !p.reset_writes && !r.qualification_lost && !r.barrier_uncertain && !p.early_owner_lost);
  CHECK(p.held_mask==7 && p.published_mask==7 && p.commit_returned==2 && d.attempted && d.returned && !d.raw_code && !d.code && d.gates==255 && d.memory_valid && d.table_crc==p.table_crc);
  CHECK(gec_state_qualified(&p.record,&p.memory,&r,&d.snapshot,1));
  for(auto&b:p.bo)CHECK(b.deviceReferences()==1 && !b.quarantined());
  for(auto&e:stores)CHECK(e.address!=0x3d7e000);
  if(!kind){CHECK(r.phase==GEC_PHASE_ROUTE && r.enabled && r.route_prepared && r.stream_attached && r.prepared_committed && stores.size()==80 && !r.code);++no_submission_checkpoints;}
  else {CHECK(!r.safe_to_save && !r.complete);++no_submission_failures;}
  if(ns_post_clock_loss)word(0x171004)=0;if(ns_post_table_damage)((uint64_t*)p.memory.owned.tables)[0]^=1;if(ns_post_owner_loss)p.active=0;return;
 }
 CHECK(!word(0x3da0800) && word(0x3da0c00)==0x20000);
 if(p.early_attempted && !p.core_called){
  CHECK(!(word(HGP_CB(0))&1));CHECK(strstr(label,"early") && !stores.size() && !r.started && !r.safe_to_save && !p.held_mask && !p.published_mask && !p.release_seen && !p.reset_seen && !p.commit_attempted && !p.early_owner_lost);
  CHECK(p.early_cold[0].attempted && p.early_cold[0].returned && !p.early_cold[0].code && !p.early_cold[0].recheck && p.early_cold[0].gates==255);
  for(auto&bo:p.bo)CHECK(!bo.deviceReferences());++early_checkpoint_calls;if(early_post_clock_loss)word(0x171004)=0;return;
 }
 CHECK(checkpoint_calls?word(HGP_CB(0))==0:(word(HGP_CB(0))&0x41u)==0);
 ++checkpoint_calls;if(checkpoint_calls==1)CHECK(strstr(label,"no MMIO store") && stores.empty());
 if(checkpoint_calls==2)CHECK(strstr(label,"no master released") && !p.release_seen && r.programmed_words==52);
 if(checkpoint_calls==3)CHECK(strstr(label,"CPU canary verified") && p.cpu_restored && r.positive && r.negative && r.context_retired);
 if(checkpoint_calls==change_alias_commit)alias_wb=!alias_wb;
 if(checkpoint_calls==change_attr_commit)attributes[(ppnum_t)(p.info[GECN_DATA].pa>>14)]=VM_WIMG_DEFAULT;
 if(checkpoint_calls==fail_commit)throw SimulatedTerminalPanic{};
 if(checkpoint_calls==mutate_commit)word(0x171004)=0;if(checkpoint_calls==damage_backup_commit)r.backup[0].value^=1;
 if(checkpoint_calls==damage_prepared_commit)word(gec_address(0))^=1;
 if(checkpoint_calls==damage_prepared_sctlr)word(HGP_CB(0))=2;
 if(checkpoint_calls==1 && table_extra){auto*t=(uint64_t*)p.memory.owned.tables;t[2*512+2]=t[2*512];}
 if(checkpoint_calls==1 && table_bit)((uint64_t*)p.memory.owned.tables)[0]^=1;
}
static void discardHostAfterReset(){while(!fixture.live.empty())fixture.live.back()->release();while(!fixture.metadata.empty())fixtureMetadataFree(fixture.metadata.back());}
static void reset(){
 discardHostAfterReset();memset((void*)&gHoujiGpuExternalCanary,0,sizeof(gHoujiGpuExternalCanary));
 nc_boot_value=1;nc_boot_present=true;gPhysBase=UINT64_C(0x800000000);gPhysSize=UINT64_C(0x800000000);alias_fault=bad_par_at=alias_at_calls=change_alias_commit=change_attr_commit=change_alias_acquire=change_attr_acquire=nc_data_dc=nc_pretransition_lines=nc_barrier_calls=0;nc_shareability=0;alias_wb=true;nc_no_cpu_dma_write=false;gHoujiGpuExternalCanaryOnce=0;
 fixture=MemoryFixture{};fixture.cpu_page_bytes=16384;fixture.next_physical=UINT64_C(0x8c5d10000);
 page_size=map_page_bytes=PAGE_SIZE;cpu_tcr=(UINT64_C(2)<<14)|(UINT64_C(1)<<30);cpu_ttbr0=0x30000000;cpu_ttbr1=0x30004000;cpu_sctlr=1;cpu_ctr=UINT64_C(4)<<16;
 attributes.clear();pmap_writes.clear();cache_lines.clear();attribute_write_fail=barriers=now=0;
 chosen_present=property_present=property_type=boot_present=true;boot_value=1;gRootEnabled=gLogEnabled=gReturnRecovery=true;
 chosen_lookups=chosen_releases=property_lookups=descriptors=descriptor_releases=map_calls=boot_calls=0;
 fail_alloc=fail_map=bad_mapping=bad_kind=map_accesses=fail_map_access=corrupt_store=owner_lost_store=clock_lost_store=at_calls=fail_at=0;
 checkpoint_calls=fail_commit=mutate_commit=damage_backup_commit=damage_prepared_commit=damage_prepared_sctlr=final_save_calls=panic_calls=0;
 mail_delay=mail_behavior=delay_calls=publication_count=invalidate_count=wrong_data=padding_damage=zero_damage=negative_wrong=apply_partial_dma=0;
 expose_data_reads=fail_cpu_cache=table_extra=table_bit=fail_cache_once=early_checkpoint_calls=early_post_clock_loss=early_owner_loss=0;no_submission_checkpoints=no_submission_failures=ns_post_clock_loss=ns_post_table_damage=ns_post_owner_loss=0;failure_holds=failure_hold_ms=fault_mail_bit=fault_stack_bit=fault_saved_seed=0;logs.clear();mapping_order.clear();stores.clear();for(auto&d:dram)d.clear();
 for(unsigned i=0;i<6;i++){backing[i].assign(mock_size[i]/4,0);mappings[i]={};}
 memcpy(wire.data()+1,&original,sizeof(original));property.bytes=wire.data()+1;property.length=HPH_RECORD_BYTES;
 for(unsigned i=0;i<HGB_REGS;i++)word(hgb_address(i))=fixture_register(hgb_address(i));
 for(unsigned i=0;i<HCW_REGS;i++)word(hcw_address(i))=fixture_register(hcw_address(i));
 for(unsigned i=0;i<24;i++){word(0x3da0800+4*i)=fixture_register(0x3da0800+4*i);word(0x3da0c00+4*i)=fixture_register(0x3da0c00+4*i);}
 for(unsigned i=0;i<22;i++)word(0x3dc0000+4096*i)=fixture_register(0x3dc0000+4096*i);
 word(0x3d7e600)=fixture_register(0x3d7e600);word(0x3d99144)=1;
 for(unsigned i=0;i<68;i++)word(gec_address(i))=i%3?0x13570000u+37*i:UINT32_MAX;
 for(unsigned i=0;i<9;i++)word(gie_control_address(i))=i%3?0x87650000u+37*i:UINT32_MAX;
 for(unsigned i=0;i<9;i++){word(gec_field_address(i))=0;if(i==5 || i==6)word(gec_field_address(i)+4)=0;}
 word(HGP_CB(4))=3;word(0x3da6008)=word(0x3da600c)=word(HGP_CB(0x58))=word(HGP_CB(0x60))=word(HGP_CB(0x64))=word(HGP_CB(0x68))=word(HGP_CB(0x7f4))=0;
}
static bool contract(){bool safe=houjiGpuExternalCanaryProbeOnce();if(safe)++final_save_calls;else ++panic_calls;CHECK(failure_holds==(!safe && gHoujiGpuExternalCanary.result.started?1u:0u) && failure_hold_ms==8000*failure_holds);return safe;}
static void once(bool safe){const auto n=stores.size(),lines=logs.size();const unsigned reads=gHoujiGpuExternalCanary.read_calls,created=fixture.created,holds=failure_holds;CHECK(houjiGpuExternalCanaryProbeOnce()==safe && stores.size()==n && logs.size()==lines && gHoujiGpuExternalCanary.read_calls==reads && fixture.created==created && failure_holds==holds);}

/* SPDX-License-Identifier: MIT */
#include "NativeAdrenoSha256.h"
#include <string.h>

static const uint32_t K[64]={
    0x428a2f98u,0x71374491u,0xb5c0fbcfu,0xe9b5dba5u,0x3956c25bu,0x59f111f1u,
    0x923f82a4u,0xab1c5ed5u,0xd807aa98u,0x12835b01u,0x243185beu,0x550c7dc3u,
    0x72be5d74u,0x80deb1feu,0x9bdc06a7u,0xc19bf174u,0xe49b69c1u,0xefbe4786u,
    0x0fc19dc6u,0x240ca1ccu,0x2de92c6fu,0x4a7484aau,0x5cb0a9dcu,0x76f988dau,
    0x983e5152u,0xa831c66du,0xb00327c8u,0xbf597fc7u,0xc6e00bf3u,0xd5a79147u,
    0x06ca6351u,0x14292967u,0x27b70a85u,0x2e1b2138u,0x4d2c6dfcu,0x53380d13u,
    0x650a7354u,0x766a0abbu,0x81c2c92eu,0x92722c85u,0xa2bfe8a1u,0xa81a664bu,
    0xc24b8b70u,0xc76c51a3u,0xd192e819u,0xd6990624u,0xf40e3585u,0x106aa070u,
    0x19a4c116u,0x1e376c08u,0x2748774cu,0x34b0bcb5u,0x391c0cb3u,0x4ed8aa4au,
    0x5b9cca4fu,0x682e6ff3u,0x748f82eeu,0x78a5636fu,0x84c87814u,0x8cc70208u,
    0x90befffau,0xa4506cebu,0xbef9a3f7u,0xc67178f2u};
static inline uint32_t rotr(uint32_t value,unsigned count)
{return (value>>count)|(value<<(32-count));}
static void compress(uint32_t state[8],const uint8_t block[64])
{
    uint32_t w[64];
    for(unsigned i=0;i<16;++i)
        w[i]=(uint32_t(block[i*4])<<24)|(uint32_t(block[i*4+1])<<16)|
            (uint32_t(block[i*4+2])<<8)|uint32_t(block[i*4+3]);
    for(unsigned i=16;i<64;++i) {
        const uint32_t s0=rotr(w[i-15],7)^rotr(w[i-15],18)^(w[i-15]>>3);
        const uint32_t s1=rotr(w[i-2],17)^rotr(w[i-2],19)^(w[i-2]>>10);
        w[i]=w[i-16]+s0+w[i-7]+s1;
    }
    uint32_t a=state[0],b=state[1],c=state[2],d=state[3];
    uint32_t e=state[4],f=state[5],g=state[6],h=state[7];
    for(unsigned i=0;i<64;++i) {
        const uint32_t s1=rotr(e,6)^rotr(e,11)^rotr(e,25);
        const uint32_t ch=(e&f)^(~e&g);
        const uint32_t t1=h+s1+ch+K[i]+w[i];
        const uint32_t s0=rotr(a,2)^rotr(a,13)^rotr(a,22);
        const uint32_t maj=(a&b)^(a&c)^(b&c);
        const uint32_t t2=s0+maj;
        h=g;g=f;f=e;e=d+t1;d=c;c=b;b=a;a=t1+t2;
    }
    state[0]+=a;state[1]+=b;state[2]+=c;state[3]+=d;
    state[4]+=e;state[5]+=f;state[6]+=g;state[7]+=h;
}
void NativeAdrenoSha256::hash(const uint8_t *bytes,size_t length,uint8_t digest[32])
{
    uint32_t state[8]={0x6a09e667u,0xbb67ae85u,0x3c6ef372u,0xa54ff53au,
        0x510e527fu,0x9b05688cu,0x1f83d9abu,0x5be0cd19u};
    size_t at=0;
    while(length-at>=64) {compress(state,bytes+at);at+=64;}
    uint8_t tail[64];
    const size_t rest=length-at;
    memset(tail,0,sizeof(tail));
    if(rest)memcpy(tail,bytes+at,rest);
    tail[rest]=0x80;
    if(rest>=56) {compress(state,tail);memset(tail,0,sizeof(tail));}
    const uint64_t bits=uint64_t(length)*8;
    for(unsigned i=0;i<8;++i)tail[63-i]=uint8_t(bits>>(8*i));
    compress(state,tail);
    for(unsigned i=0;i<8;++i) {
        digest[i*4]=uint8_t(state[i]>>24);digest[i*4+1]=uint8_t(state[i]>>16);
        digest[i*4+2]=uint8_t(state[i]>>8);digest[i*4+3]=uint8_t(state[i]);
    }
}

/* SPDX-License-Identifier: MIT */
#include "NativeAdrenoFirmware.h"
#include "NativeAdrenoSha256.h"
#include <string.h>
IOReturn NativeAdrenoFirmware::validate(const uint8_t *image,uint64_t length,
    const NativeAdrenoFirmwareRules *rules,NativeAdrenoFirmwareView *view)
{
    if(!view)return kIOReturnBadArgument;
    *view={};
    if(!rules || !image || !length || length!=rules->bytes ||
        length>uint64_t(SIZE_MAX))return kIOReturnBadArgument;
    uint8_t digest[32];
    NativeAdrenoSha256::hash(image,size_t(length),digest);
    if(memcmp(digest,rules->sha256,32))return kIOReturnIOError;
    view->bytes=image;view->length=size_t(length);
    memcpy(view->sha256,digest,32);
    return kIOReturnSuccess;
}

#define HOUJI_GPU_FIRMWARE_MEMORY_HOST_TEST 1
#include "HoujiGpuFirmwareMemoryProbe.inc"
static bool houjiFirmwareAt(uint64_t va,bool wr,uint64_t*par){return houjiGpuExternalAt(va,wr,par);}
static void houjiFirmwareBarrier(){++barriers;}
#define HOUJI_GPU_SECURE_CX_HOST_TEST 1
#include "HoujiGpuSecureCxProbe.inc"
static unsigned smc_calls,checkpoint_secure,fail_transport,mutate_smc,mutate_save,damage_owner,fail_secure_at;
static unsigned fail_secure_read,secure_reads,secure_at_calls,secure_saves,final_saves,profile,fail_observation_kind,test_address;
static std::vector<ggs_regs> host_frames;
static std::vector<unsigned char> immutable_gec,immutable_fw;
static bool houjiSecureCxAt(uint64_t va,bool wr,uint64_t*par){
 if(++secure_at_calls==fail_secure_at){*par=1;return true;}return houjiGpuExternalAt(va,wr,par);
}
static void houjiSecureCxReadBarrier(){++barriers;if(++secure_reads==fail_secure_read || (fail_observation_kind && gHoujiGpuSecureCx.observations[gHoujiGpuSecureCx.current_observation].kind==fail_observation_kind))gRootEnabled=false;}
static void host_secure_checkpoint(const char*label,unsigned stop){
 auto&p=gHoujiGpuSecureCx;CHECK(stop==0 && p.in_save && !p.in_observe && !p.lost && !p.scm.quarantined);
 CHECK(!memcmp(immutable_gec.data(),&gHoujiGpuExternalCanary,sizeof(gHoujiGpuExternalCanary)));
 CHECK(!memcmp(immutable_fw.data(),&gHoujiFirmwareMemory,sizeof(gHoujiFirmwareMemory)));
 if(smc_calls){unsigned raw=0,proof=0;for(auto&line:logs){if(line.find("POST_COLD_PENDING")!=std::string::npos)++raw;if(line.find("POST_COLD_PROVEN")!=std::string::npos)++proof;}CHECK(raw>=smc_calls && proof>=smc_calls);}
 ++secure_saves;++checkpoint_secure;if(strstr(label,"INIT returned"))++final_saves;
 if(checkpoint_secure==mutate_save)word(0x171004)=0;
}
static int houjiSecureCxSmc(ggs_regs*r){
 auto&p=gHoujiGpuSecureCx;CHECK(p.active && p.calls[p.call_count-1].ready && !p.lost);
 const auto&o=p.observations[p.calls[p.call_count-1].ready-1];CHECK(o.returned && !o.code && !o.recheck && o.gates==255 && o.lease_before && o.lease_after);
 CHECK(stores.size()==179 && !gHoujiGpuExternalCanary.active && !gHoujiFirmwareMemory.active);
 host_frames.push_back(*r);++smc_calls;
 for(unsigned i=0;i<8;i++)r->x[i]=UINT64_C(0xabcd123400000000)+i;
 r->x[0]=0;r->x[1]=1;
 if(profile==1 && smc_calls==1){r->x[0]=1;r->x[6]=UINT64_C(0xfeedbeef12345678);}
 if(profile==2 && smc_calls==1)r->x[0]=(uint64_t)(int64_t)-12;
 if(profile==3)r->x[0]=1;
 if(profile==4)r->x[0]=(uint64_t)(int64_t)-12;
 if(profile==5)r->x[0]=2;
 if(profile==6)r->x[0]=3;
 if(profile==7)r->x[0]=UINT64_C(0x100000000);
 if(profile==8 && smc_calls==1)r->x[1]=UINT64_C(0x100000001);
 if(profile==9 && smc_calls==2)r->x[1]=0;
 if(profile==10 && smc_calls==3)r->x[0]=UINT64_C(0xffffffffffffffff);
 if(profile==11 && smc_calls==1)r->x[0]=UINT64_C(0xfffffff4);
 if(smc_calls==mutate_smc)word(HGP_CB(0x20))=4096;
 if(smc_calls==damage_owner)gReturnRecovery=false;
 return smc_calls==fail_transport?1:0;
}
static void setup(){
 secure_mode=firmware_mode=false;fixture_record((unsigned char*)&original);reset();memset((void*)&gHoujiFirmwareMemory,0,sizeof(gHoujiFirmwareMemory));gHoujiFirmwareMemoryOnce=0;
 memset((void*)&gHoujiGpuSecureCx,0,sizeof(gHoujiGpuSecureCx));gHoujiGpuSecureCxOnce=0;
 CHECK(contract());firmware_mode=true;CHECK(houjiGpuFirmwareMemoryProbeOnce());firmware_mode=false;
 secure_mode=true;scm_boot=1;smc_calls=checkpoint_secure=fail_transport=mutate_smc=mutate_save=damage_owner=fail_secure_at=fail_secure_read=secure_reads=secure_at_calls=secure_saves=final_saves=profile=fail_observation_kind=test_address=0;host_frames.clear();
 immutable_gec.assign((unsigned char*)&gHoujiGpuExternalCanary,(unsigned char*)&gHoujiGpuExternalCanary+sizeof(gHoujiGpuExternalCanary));
 immutable_fw.assign((unsigned char*)&gHoujiFirmwareMemory,(unsigned char*)&gHoujiFirmwareMemory+sizeof(gHoujiFirmwareMemory));
}
static void unchanged(){CHECK(!memcmp(immutable_gec.data(),&gHoujiGpuExternalCanary,sizeof(gHoujiGpuExternalCanary)));CHECK(!memcmp(immutable_fw.data(),&gHoujiFirmwareMemory,sizeof(gHoujiFirmwareMemory)));CHECK(stores.size()==179 && fixture.live.size()==12 && !fixture.released);}
static void bad(){bool safe=houjiGpuSecureCxProbeOnce();if(safe || gHoujiGpuSecureCx.complete || final_saves)fprintf(stderr,"Unexpected safe: profile=%u address=%x smcs=%u saves=%u final=%u\n",profile,test_address,smc_calls,secure_saves,final_saves);CHECK(!safe && !gHoujiGpuSecureCx.complete && !final_saves);unchanged();unsigned count=smc_calls,saves=secure_saves;CHECK(!houjiGpuSecureCxProbeOnce() && smc_calls==count && secure_saves==saves);}
int main(){unsigned cases=0;
 setup();CHECK(houjiGpuSecureCxProbeOnce());auto&p=gHoujiGpuSecureCx;CHECK(p.complete && !p.active && !p.lost && !p.scm.quarantined && p.scm.init_succeeded && smc_calls==3 && secure_saves==4 && final_saves==1 && p.actual_calls==p.returned_calls && p.report_saved && p.report_returned);
 CHECK(host_frames[0].x[0]==0xc2000601 && host_frames[0].x[2]==0x02000601 && host_frames[1].x[0]==0x42000601 && host_frames[1].x[2]==0x02002801 && host_frames[2].x[0]==0x42002801 && host_frames[2].x[2]==11);
 for(auto&r:host_frames)CHECK(r.x[1]==1 && !r.x[3] && !r.x[4] && !r.x[5] && !r.x[6] && !r.x[7]);
 CHECK(p.calls[2].output.x[7]==UINT64_C(0xabcd123400000007));unchanged();const unsigned observations=p.observation_count,ats=secure_at_calls,reads=secure_reads;CHECK(houjiGpuSecureCxProbeOnce() && smc_calls==3 && p.observation_count==observations);++cases;
 for(int arg:{0,2,-1}){setup();scm_boot=arg;if(!arg)CHECK(houjiGpuSecureCxProbeOnce());else CHECK(!houjiGpuSecureCxProbeOnce());CHECK(!smc_calls && !secure_saves);unchanged();++cases;}
 for(unsigned mode=1;mode<=11;mode++){setup();profile=mode;if(mode==1 || mode==2 || mode==11){CHECK(houjiGpuSecureCxProbeOnce() && p.complete && smc_calls==4);if(mode==1)CHECK(host_frames[1].x[0]==1 && host_frames[1].x[6]==UINT64_C(0xfeedbeef12345678));else CHECK(host_frames[1].x[0]==0xc2000601 && !host_frames[1].x[6]);unchanged();}else bad();++cases;}
 for(unsigned i=1;i<=3;i++){setup();fail_transport=i;bad();CHECK(p.scm.quarantined && smc_calls==i);++cases;setup();mutate_smc=i;bad();CHECK(smc_calls==i && p.lost && p.calls[i-1].post && !p.calls[i-1].post_ok);++cases;setup();damage_owner=i;CHECK(!houjiGpuSecureCxProbeOnce() && !p.complete && smc_calls==i && !final_saves);++cases;}
 for(unsigned i=1;i<=3;i++){setup();mutate_save=i;bad();CHECK(smc_calls==i-1);++cases;}
 // Boundary peers refuse each AT position in the first complete lease; all
 // other input snapshots are actual successful Native prep, never fake tokens.
 for(unsigned n:{1u,2u,15u,16u,17u,48u,49u,128u,512u,704u}){setup();fail_secure_at=n;bad();CHECK(!smc_calls);++cases;}
 for(unsigned n:{1u,2u,8u,9u,32u,64u,128u,256u}){setup();fail_secure_read=n;CHECK(!houjiGpuSecureCxProbeOnce() && !smc_calls && !final_saves && !p.complete);++cases;}
 for(unsigned field=0;field<9;field++){setup();if(field==0)gHoujiGpuExternalCanary.result.safe_to_save=0;if(field==1)gHoujiGpuExternalCanary.memory_profile=0;if(field==2)gHoujiGpuExternalCanary.active=1;if(field==3)gHoujiFirmwareMemory.active=1;if(field==4)gHoujiFirmwareMemory.complete=0;if(field==5)gHoujiFirmwareMemory.bo[5].holdForDevice();if(field==6)gHoujiGpuExternalCanary.bo[1].quarantine();if(field==7)attributes[(ppnum_t)(gHoujiGpuExternalCanary.info[1].pa>>14)]=VM_WIMG_DEFAULT;if(field==8)gHoujiFirmwareMemory.info[5].read_par[0]^=1;
  CHECK(!houjiGpuSecureCxProbeOnce() && !smc_calls && !secure_saves && !p.complete);++cases;}
 for(unsigned window=1;window<=4;window++){setup();fail_alloc=window;bad();CHECK(!smc_calls);++cases;setup();fail_map=window;bad();CHECK(!smc_calls);++cases;}
 for(unsigned kind=0;kind<3;kind++)for(unsigned n=0;n<(kind==2?22u:24u);n++){setup();word(kind==0?0x3da0800+4*n:kind==1?0x3da0c00+4*n:0x3dc0000+4096*n)=kind==0?0x80000005:kind==1?2:1;bad();CHECK(!smc_calls);++cases;}
 for(uint32_t address:{0x3d7e000u,0x3d7e070u,0x3d7e600u,HGP_CB(4),0x3da6008u,0x3da600cu,HGP_CB(0x20),HGP_CB(0x24),HGP_CB(0x28),HGP_CB(0x2c),HGP_CB(0x58),0x171004u,0x171010u,0x171018u,0x3d99144u}){setup();test_address=address;word(address)^=address==HGP_CB(0x58)?2u:1u;bad();CHECK(!smc_calls);++cases;}
 setup();fail_observation_kind=4;bad();CHECK(smc_calls==3 && !p.report_saved && !p.report_returned && !final_saves);++cases;
 setup();fail_observation_kind=5;CHECK(!houjiGpuSecureCxProbeOnce() && final_saves==1 && p.report_saved && !p.report_returned && !p.complete && p.lost && smc_calls==3);unchanged();++cases;
 setup();mutate_save=4;CHECK(!houjiGpuSecureCxProbeOnce() && final_saves==1 && p.report_saved && !p.report_returned && !p.complete && p.lost);unchanged();++cases;
 // Malformed ownership cannot exploit cross-graph metadata. Test the small
 // lease helper directly as these intentionally replace frozen old metadata.
 setup();{auto&f=gHoujiFirmwareMemory;f.info[0].pa=gHoujiGpuExternalCanary.info[0].pa;CHECK(!houjiGpuSecureCxProbeOnce() && !smc_calls);++cases;}
 setup();{auto&f=gHoujiFirmwareMemory;f.info[0].va=gHoujiGpuExternalCanary.info[0].va;CHECK(!houjiGpuSecureCxProbeOnce() && !smc_calls);++cases;}
 setup();{
  auto&f=gHoujiFirmwareMemory;const uint64_t pa=gHoujiGpuExternalCanary.info[2].pa;auto&b=f.info[7];auto&bo=f.bo[7];
  b.pa=pa;bo.descriptor()->physical_base=pa;const_cast<NativeAdrenoPhysicalSpan*>(bo.spans())[0].physical=pa;const_cast<NativeAdrenoPhysicalSpan*>(bo.ownedSpans())[0].physical=pa;
  for(unsigned row=0;row<4;row++){const uint64_t mask=UINT64_C(0x0000fffffffff000),page=pa+4096*row;b.read_par[row]=(b.read_par[row]&~mask)|page;b.write_par[row]=(b.write_par[row]&~mask)|page;b.alias_read_par[row]=(b.alias_read_par[row]&~mask)|page;b.alias_write_par[row]=(b.alias_write_par[row]&~mask)|page;}
  CHECK(houjiSecureCxBo(bo,b,0,true,false,7,b.read_par,b.write_par,b.alias_read_par,b.alias_write_par));
  CHECK(!houjiSecureCxLease() && !houjiGpuSecureCxProbeOnce() && !smc_calls);++cases;
 }
 setup();word(HGP_CB(0x20))=4096;bad();CHECK(!smc_calls);++cases;
 printf("PASS: %u secure-CX actual Native/ggs host profiles (ASan/UBSan), baseline3fixedSMC/%uobservations/%uAT/%uRO; all BOs retained, old owners byte-identical, no new GPU MMIO stores, no real SMC/firmware execution\n",cases,observations,ats,reads);secure_mode=false;discardHostAfterReset();
}
