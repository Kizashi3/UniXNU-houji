/* SPDX-License-Identifier: MIT */
/* Actual backing/ownership code with explicit XNU/cache peers, not GPU emulation. */
#include "XnuMemoryFixture.h"
#include "NativeAdrenoMemory.h"
#include "NativeAdrenoPool.h"
#include "NativeAdrenoAllocationTrace.h"
static uint64_t allocationTime=0;
static uint64_t allocationNow(){allocationTime+=1000;return allocationTime;}
#include <cstdio>
#include <string>
#define CHECK(x) do {if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);std::exit(1);}}while(0)
static unsigned conversions=0,restores=0,reasserts=0;
static bool convert_fail=false,reassert_fail=false;
IOReturn NativeAdrenoQueryCpuPages(NativeAdrenoCpuState *out) {
    *out={};out->kernel_page_bytes=out->kernel_map_page_bytes=fixture.cpu_page_bytes;
    out->cpu_page_shift=fixture.cpu_page_bytes==16384?14:12;return fixture.cpu_status;
}
IOReturn NativeAdrenoMaintainOwnedPages(void *p,size_t bytes,NativeAdrenoCacheOperation) {
    CHECK(p && bytes && !(bytes&(fixture.cpu_page_bytes-1)));++fixture.cache_calls;
    return fixture.cache_fail_call==fixture.cache_calls?kIOReturnIOError:kIOReturnSuccess;
}
IOReturn NativeAdrenoSetPagesCacheMode(const NativeAdrenoPhysicalSpan *spans,size_t count,bool wc) {
    CHECK(count==1 && spans && !((spans[0].physical|spans[0].bytes)&(fixture.cpu_page_bytes-1)));
    if(wc)++conversions;else ++restores;return convert_fail?kIOReturnIOError:kIOReturnSuccess;
}
IOReturn NativeAdrenoReassertWriteCombined(const NativeAdrenoPhysicalSpan *spans,size_t count,uint32_t *reset) {
    CHECK(spans && count==1 && reset && !(spans[0].bytes&(fixture.cpu_page_bytes-1)));
    ++reasserts;return reassert_fail?kIOReturnIOError:kIOReturnSuccess;
}
IOReturn NativeAdrenoMaintainPhysicalPages(uint64_t,size_t,NativeAdrenoCacheOperation) {return kIOReturnSuccess;}

static void extentPolicy() {
    NativeAdrenoPoolExtents e;
    CHECK(!e.initialize(65536,8192) && e.initialize(16*4096,4096));
    size_t a,b,c,d;CHECK(e.take(4096,&a) && e.take(8192,&b) && e.take(4096,&c));
    CHECK(a==0 && b==4096 && c==12288 && e.used==16384);
    CHECK(e.give(b,8192) && e.take(4096,&d) && d==b); // smallest fitting hole
    CHECK(!e.give(d,4095) && !e.give(65536,4096));
    CHECK(e.give(d,4096) && !e.give(d,4096));
    CHECK(e.give(a,4096) && e.give(c,4096) && e.count==1 && e.used==0 && e.free[0].bytes==e.bytes);
    NativeAdrenoPoolExtents full;constexpr size_t pages=2*NativeAdrenoPoolExtents::Capacity+2;
    CHECK(full.initialize(pages*4096,4096));size_t offsets[pages];
    for(auto &v:offsets)CHECK(full.take(4096,&v));
    for(unsigned i=0;i<NativeAdrenoPoolExtents::Capacity;++i)CHECK(full.give(offsets[2*i],4096));
    const size_t used=full.used;
    CHECK(!full.give(offsets[pages-2],4096) && full.used==used); // full metadata retains ownership
    CHECK(full.give(offsets[1],4096)); // merge works with full metadata
    CHECK(full.give(offsets[pages-2],4096));
    // Fragmentation/reuse invariant: each page is either live or free exactly once.
    NativeAdrenoPoolExtents random;constexpr size_t n=128;
    CHECK(random.initialize(n*16384,16384));bool live[n]{};uint32_t seed=1234;
    for(unsigned iteration=0;iteration<4000;++iteration) {
        seed=seed*1664525u+1013904223u;
        if(seed&1) {size_t off;if(random.take(16384,&off)){CHECK(!live[off/16384]);live[off/16384]=true;}}
        else {size_t p=(seed>>8)%n;if(live[p]){CHECK(random.give(p*16384,16384));live[p]=false;}}
        bool seen[n]{};size_t freeBytes=0;
        for(unsigned i=0;i<random.count;++i)for(size_t j=0;j<random.free[i].bytes;j+=16384) {
            size_t p=(random.free[i].offset+j)/16384;CHECK(p<n && !live[p] && !seen[p]);seen[p]=true;freeBytes+=16384;
        }
        for(unsigned i=0;i<n;++i)CHECK(live[i]!=seen[i]);
        CHECK(freeBytes+random.used==random.bytes);
    }
}
int main(int argc,char **argv) {
    native_adreno_memory_now_us=allocationNow;
    CHECK(argc==2);std::string scenario=argv[1];fixture.cpu_page_bytes=TEST_CPU_PAGE;
    const size_t page=fixture.cpu_page_bytes,size=8*page;extentPolicy();
    // Arena growth must not grow a single BO or lose ownership above 256 MiB.
    NativeAdrenoPoolExtents large;constexpr size_t mib=1024u*1024u;size_t first,second,extra;
    CHECK(large.initialize(NativeAdrenoMemory::MaximumPoolBytes,page));
    CHECK(large.take(256*mib,&first) && large.take(256*mib,&second));
    CHECK(first==0 && second==256*mib && !large.take(page,&extra));
    CHECK(large.give(second,256*mib));
    for(unsigned i=0;i<4;++i)CHECK(large.take(64*mib,&extra) && extra==(256+64*i)*mib);
    CHECK(!large.take(page,&extra) && large.used==512*mib);
    NativeAdrenoMemory oversized;
    CHECK(oversized.allocate(257*mib,36,true,512*mib,true)==kIOReturnBadArgument && !fixture.created);
    fixture.next_physical=UINT64_C(1)<<35;
    if(scenario=="invalid") {
        CHECK(NativeAdrenoMemory::reservePool(31,size)==kIOReturnBadArgument);
        CHECK(NativeAdrenoMemory::reservePool(36,513u*1024u*1024u)==kIOReturnBadArgument);
        // Exercise the production request boundary without a 512 MiB host allocation.
        fixture.allocation_fail=true;
        CHECK(NativeAdrenoMemory::reservePool(36,512u*1024u*1024u)==kIOReturnNoMemory);
        fixture.allocation_fail=false;
        CHECK(NativeAdrenoMemory::reservePool(36,size+1)==kIOReturnBadArgument);
        fixture.cpu_status=kIOReturnUnsupported;
        CHECK(NativeAdrenoMemory::reservePool(36,size)==kIOReturnUnsupported && !fixture.created);
    } else if(scenario=="reserve-fail" || scenario=="reserve-retain") {
        fixture.mode=Paired;fixture.complete_fail=scenario=="reserve-retain";
        CHECK(NativeAdrenoMemory::reservePool(36,size)==kIOReturnUnsupported && !NativeAdrenoMemory::poolBytes());
        CHECK(fixture.completed==1 && fixture.released==(fixture.complete_fail?0u:1u));
        if(fixture.complete_fail)CHECK(NativeAdrenoMemory::reservePool(36,size)==kIOReturnBusy);
        else {fixture.mode=Contiguous;CHECK(!NativeAdrenoMemory::reservePool(36,size));}
    } else {
        CHECK(!NativeAdrenoMemory::reservePool(36,size) && NativeAdrenoMemory::poolBytes()==size);
        CHECK(fixture.segment_calls==8 && fixture.prepared==1);
        CHECK(NativeAdrenoMemory::reservePool(36,size)==kIOReturnBusy);
        if(scenario=="wc-fail") {
            convert_fail=true;CHECK(NativeAdrenoMemory::writeCombinePool()==kIOReturnIOError);
            CHECK(!NativeAdrenoMemory::poolBytes() && fixture.released==0 && fixture.completed==0);
            NativeAdrenoMemory fallback;CHECK(!fallback.allocate(page,36,true,page,true) && !fallback.pooled());CHECK(!fallback.release());
        } else {
            CHECK(!NativeAdrenoMemory::writeCombinePool() && !NativeAdrenoMemory::writeCombinePool() && conversions==1);
            if(scenario=="metadata") {
                fixture.metadata_fail_call=fixture.metadata_calls+2;NativeAdrenoMemory bad;
                CHECK(bad.allocate(4096,36,true,page,true)==kIOReturnNoMemory && !bad.backed() && !bad.quarantined());
                CHECK(fixture.metadata.empty());
                NativeAdrenoMemory whole;CHECK(!whole.allocate(size,36,true,size,true) && whole.pooled());CHECK(!whole.release());
            } else if(scenario=="reassert") {
                NativeAdrenoMemory bad;reassert_fail=true;
                CHECK(bad.allocate(4096,36,true,page,true)==kIOReturnIOError && bad.pooled() && bad.quarantined());
                CHECK(bad.release()==kIOReturnBusy);reassert_fail=false;
                NativeAdrenoMemory other;CHECK(!other.allocate(4096,36,true,page,true) && other.pooled());
                CHECK(other.spans()[0].physical!=bad.spans()[0].physical);CHECK(!other.release());
            } else if(scenario=="basic") {
                NativeAdrenoMemory a,b;CHECK(!a.allocate(4096,36,true,page,true) && !b.allocate(4096,36,false,page,true));
                CHECK(nativeAdrenoAllocationTrace.counters[NativeAdrenoAllocationTrace::Pool].calls==2);
                CHECK(nativeAdrenoAllocationTrace.counters[NativeAdrenoAllocationTrace::Pool].phase[2]>0 &&
                      nativeAdrenoAllocationTrace.counters[NativeAdrenoAllocationTrace::Pool].phase[3]>0);
                CHECK(a.pooled() && b.pooled() && a.backed() && a.writeCombined() && !a.descriptor());
                CHECK(a.ownedBytes()==page && a.bytes()==4096 && b.spans()[0].physical-a.spans()[0].physical==page);
                NativeAdrenoCpuView view{};CHECK(a.cpuView(&view) && view.bytes==page && view.count==1);
                for(size_t i=0;i<page;++i)CHECK(!static_cast<unsigned char *>(a.mapping())[i]);
                CHECK(!a.makeWriteCombined() && conversions==1 && !a.holdForDevice());
                CHECK(a.release()==kIOReturnBusy && !a.retireAfterQuiescence());
                void *address=a.mapping();std::memset(address,0x69,page);CHECK(!a.release());
                NativeAdrenoMemory reused;CHECK(!reused.allocate(4096,36,true,page,true) && reused.mapping()==address);
                for(size_t i=0;i<page;++i)CHECK(!static_cast<unsigned char *>(address)[i]);
                CHECK(!reused.release() && !b.release() && !restores && conversions==1 && reasserts==3);
                NativeAdrenoMemory whole,fallback;
                CHECK(!whole.allocate(size,36,true,size,true) && whole.pooled());
                CHECK(!fallback.allocate(page,36,false,page,true) && !fallback.pooled() && native_adreno_pool_stats[2]==1);
                CHECK(!fallback.release() && !whole.release());
                NativeAdrenoMemory imported;CHECK(!imported.importTask((void *)2,0x40000000,page,36,page) && !imported.pooled());CHECK(!imported.release());
                // Pool PA outside a narrower output width cannot be recycled for that client.
                NativeAdrenoMemory narrow;fixture.next_physical=0x20000000;
                CHECK(!narrow.allocate(4096,32,true,page,true) && !narrow.pooled());CHECK(!narrow.release());
                CHECK(NativeAdrenoMemory::poolBytes()==size && fixture.live.size()==1);
            } else CHECK(false);
        }
    }
    // Fixture teardown only. Real pool/quarantine survives until hardware reset.
    while(!fixture.live.empty())fixture.live.back()->release();
    while(!fixture.metadata.empty())fixtureMetadataFree(fixture.metadata.back());
    std::printf("PASS: CPU%uK BO pool %s (ownership/cache peers, no hardware)\n",TEST_CPU_PAGE/1024,scenario.c_str());
}
