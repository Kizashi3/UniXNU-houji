/* SPDX-License-Identifier: MIT */
/* Deliberately small authored host doubles, not original XNU headers or ABI. */
#ifndef NATIVE_ADRENO_XNU_MEMORY_FIXTURE_H
#define NATIVE_ADRENO_XNU_MEMORY_FIXTURE_H
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <algorithm>
#include <vector>
using IOReturn=int;
using IOOptionBits=unsigned;
using IOByteCount=size_t;
using addr64_t=uint64_t;
constexpr IOReturn kIOReturnSuccess=0,kIOReturnBadArgument=1,kIOReturnBusy=2,
 kIOReturnNoResources=3,kIOReturnNoMemory=4,kIOReturnUnsupported=5,
 kIOReturnNotReady=6,kIOReturnIOError=7,kIOReturnTimeout=8;
constexpr unsigned kIODirectionOut=2,kIODirectionInOut=3,kIOMemoryMapperNone=0x800,kIOMemoryPhysicallyContiguous=0x10;
inline void *kernel_task=reinterpret_cast<void *>(1);
using task_t=void *;
using IODirection=unsigned;
constexpr unsigned kIOMemoryPersistent=0x100000;
constexpr unsigned kIOMemoryTypePhysical64=0x400000;
struct IOAddressRange {uint64_t address,length;};
/* ScatterUnlessContiguous: what the tablet does, one physical page per span unless the caller asked for contiguous memory. */
enum SegmentMode {Contiguous,Scattered,ZeroPhysical,UnalignedPhysical,ShortSegment,HighPhysical,Paired,ScatterUnlessContiguous};
class IOBufferMemoryDescriptor;
class IOMemoryDescriptor;
struct MemoryFixture {
    unsigned created=0,prepared=0,completed=0,released=0,cache_calls=0,segment_calls=0;
    size_t cpu_page_bytes=4096;
    unsigned allocation_fail_count=0,contiguous_attempts=0;
    unsigned metadata_calls=0,metadata_fail_call=0;
    bool allocation_fail=false,prepare_fail=false,complete_fail=false,metadata_fail=false;
    bool write_protected_imports=false;   /* user ranges that can only be pinned for reading: prepare() of a writable one reports KERN_PROTECTION_FAILURE */
    bool null_mapping=false,unaligned_mapping=false,wrong_length=false;
    unsigned cache_fail_call=0;
    uint64_t next_physical=0x30000000;
    size_t contiguous_limit=0;   /* nonzero: physically contiguous requests above this many bytes fail (a fragmented tablet) */
    unsigned imported=0,imports_live=0,imports_released=0;
    std::vector<IOMemoryDescriptor *> imported_live;
    std::vector<size_t> allocation_bytes,allocation_alignments;
    std::vector<uint64_t> allocation_masks;
    unsigned views_created=0,views_released=0,view_retain_calls=0;
    bool view_fail=false;
    std::vector<IOMemoryDescriptor *> view_live;
    unsigned physical_calls=0;size_t physical_bytes=0;   /* NativeAdrenoMaintainPhysicalPages doubles */
    IOReturn cpu_status=kIOReturnSuccess;
    SegmentMode mode=Contiguous;
    std::vector<IOBufferMemoryDescriptor *> live;
    std::vector<void *> metadata;
    std::vector<unsigned> cache_operations;
};
inline MemoryFixture fixture;
inline void *fixtureMetadata(size_t bytes) {
    ++fixture.metadata_calls;
    if(fixture.metadata_fail || fixture.metadata_calls==fixture.metadata_fail_call)return nullptr;
    void *p=std::calloc(1,bytes);if(p)fixture.metadata.push_back(p);return p;
}
inline void fixtureMetadataFree(void *p) {
    auto at=std::find(fixture.metadata.begin(),fixture.metadata.end(),p);
    if(at==fixture.metadata.end())std::abort();fixture.metadata.erase(at);std::free(p);
}
#define IONewZero(type,count) static_cast<type *>(fixtureMetadata(sizeof(type)*(count)))
#define IONewData(type,count) static_cast<type *>(fixtureMetadata(sizeof(type)*(count)))
#define IODeleteData(ptr,type,count) do {fixtureMetadataFree(ptr);ptr=nullptr;}while(0)
class IOBufferMemoryDescriptor {
public:
    void *raw=nullptr;
    size_t bytes=0;
    uint64_t mask=0;
    uint64_t physical_base=0;
    bool contiguous=false;
    static IOBufferMemoryDescriptor *inTaskWithPhysicalMask(void *task,unsigned options,size_t bytes,uint64_t mask) {
        if(task!=kernel_task || !(options&kIOMemoryMapperNone))std::abort();
        if(options&kIOMemoryPhysicallyContiguous)++fixture.contiguous_attempts;
        if(fixture.allocation_fail)return nullptr;
        if(fixture.allocation_fail_count) {--fixture.allocation_fail_count;return nullptr;}
        if(fixture.contiguous_limit && (options&kIOMemoryPhysicallyContiguous) && bytes>fixture.contiguous_limit)return nullptr;
        auto *d=new IOBufferMemoryDescriptor;
        d->bytes=bytes;d->mask=mask;d->physical_base=(fixture.next_physical+fixture.cpu_page_bytes-1)&~(uint64_t)(fixture.cpu_page_bytes-1);d->contiguous=options&kIOMemoryPhysicallyContiguous;
        fixture.allocation_bytes.push_back(bytes);fixture.allocation_alignments.push_back(fixture.cpu_page_bytes);fixture.allocation_masks.push_back(mask);
        fixture.next_physical=d->physical_base+2*bytes+0x10000;
        if(posix_memalign(&d->raw,fixture.cpu_page_bytes,bytes+fixture.cpu_page_bytes))std::abort();
        std::memset(d->raw,0xa5,bytes+fixture.cpu_page_bytes);++fixture.created;fixture.live.push_back(d);return d;
    }
    IOReturn prepare() {++fixture.prepared;return fixture.prepare_fail?kIOReturnIOError:kIOReturnSuccess;}
    IOReturn complete() {++fixture.completed;return fixture.complete_fail?kIOReturnIOError:kIOReturnSuccess;}
    void release() {
        ++fixture.released;auto at=std::find(fixture.live.begin(),fixture.live.end(),this);
        if(at==fixture.live.end())std::abort();fixture.live.erase(at);std::free(raw);delete this;
    }
    void *getBytesNoCopy() {return fixture.null_mapping?nullptr:static_cast<char *>(raw)+(fixture.unaligned_mapping?8:0);}
    size_t getLength() {return bytes+(fixture.wrong_length?fixture.cpu_page_bytes:0);}
    uint64_t getPhysicalSegment(size_t offset,size_t *length,unsigned options) {
        if((offset&4095) || offset>=bytes || options!=kIOMemoryMapperNone)std::abort();
        ++fixture.segment_calls;*length=bytes-offset;
        uint64_t base=physical_base,physical=base+offset;
        if(fixture.mode==Scattered || (fixture.mode==ScatterUnlessContiguous && !contiguous)) {
            const size_t page=fixture.cpu_page_bytes;
            physical=base+2*(offset&~(page-1))+(offset&(page-1));
            *length=page-(offset&(page-1));
        }
        if(fixture.mode==Paired)physical=base+offset+((offset/(2*fixture.cpu_page_bytes))*fixture.cpu_page_bytes);
        if(offset==fixture.cpu_page_bytes) {
            if(fixture.mode==ZeroPhysical)physical=0;
            if(fixture.mode==UnalignedPhysical)++physical;
            if(fixture.mode==ShortSegment)*length=fixture.cpu_page_bytes-1;
            if(fixture.mode==HighPhysical)physical=(mask|4095)+1;
        }
        return physical;
    }
};
/* A user range pinned with withAddressRange/prepare: pages at a fixed physical stride (every other page), so imports are scattered. */
class IOMemoryDescriptor {
public:
    uint64_t address=0,bytes=0,physical_base=0;unsigned options=0,references=1;
    bool is_view=false;std::vector<IOAddressRange> ranges;
    static IOMemoryDescriptor *withAddressRanges(const IOAddressRange *ranges,unsigned count,unsigned options,task_t task) {
        if(!ranges || !count || task || !(options&kIOMemoryTypePhysical64))std::abort();
        if(fixture.view_fail)return nullptr;
        auto *d=new IOMemoryDescriptor;d->options=options;d->is_view=true;d->ranges.assign(ranges,ranges+count);for(unsigned i=0;i<count;i++)d->bytes+=ranges[i].length;
        ++fixture.views_created;fixture.view_live.push_back(d);return d;
    }
    void retain(){++references;++fixture.view_retain_calls;}
    static IOMemoryDescriptor *withAddressRange(uint64_t address,uint64_t bytes,unsigned options,task_t task) {
        if(!task || task==kernel_task || !(options&kIOMemoryMapperNone))std::abort();
        if(fixture.allocation_fail)return nullptr;
        auto *d=new IOMemoryDescriptor;d->options=options;d->address=address;d->bytes=bytes;d->physical_base=(fixture.next_physical+fixture.cpu_page_bytes-1)&~(uint64_t)(fixture.cpu_page_bytes-1);
        fixture.next_physical=d->physical_base+2*bytes+0x10000;++fixture.imported;++fixture.imports_live;fixture.imported_live.push_back(d);return d;
    }
    IOReturn prepare() {++fixture.prepared;if(fixture.write_protected_imports && (options&1))return 2;return fixture.prepare_fail?kIOReturnIOError:kIOReturnSuccess;}
    IOReturn complete() {++fixture.completed;return fixture.complete_fail?kIOReturnIOError:kIOReturnSuccess;}
    void release() {if(!--references){if(is_view){++fixture.views_released;auto at=std::find(fixture.view_live.begin(),fixture.view_live.end(),this);if(at==fixture.view_live.end())std::abort();fixture.view_live.erase(at);}else{--fixture.imports_live;++fixture.imports_released;auto at=std::find(fixture.imported_live.begin(),fixture.imported_live.end(),this);if(at==fixture.imported_live.end())std::abort();fixture.imported_live.erase(at);}delete this;}}
    uint64_t getLength() {return bytes;}
    uint64_t getPhysicalSegment(size_t offset,size_t *length,unsigned options) {
        if((offset&4095) || offset>=bytes || options!=kIOMemoryMapperNone)std::abort();
        ++fixture.segment_calls;const size_t page=fixture.cpu_page_bytes;*length=page-(offset&(page-1));
        uint64_t physical=physical_base+2*(offset&~(page-1))+(offset&(page-1));
        if(offset==page){if(fixture.mode==ZeroPhysical)physical=0;if(fixture.mode==UnalignedPhysical)++physical;if(fixture.mode==ShortSegment)*length=page-1;if(fixture.mode==HighPhysical)physical=UINT64_C(1)<<48;}
        return physical;
    }
};
#endif
