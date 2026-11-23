
#include "XnuMemoryFixture.h"
#include "NativeAdrenoMemory.h"
#include <cstdio>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"line%d %s\n",__LINE__,#x);abort();}}while(0)
static uintptr_t cached_at;static uint64_t physical_at;static size_t length;static unsigned calls;
IOReturn NativeAdrenoQueryCpuPages(NativeAdrenoCpuState*out){*out={};out->kernel_page_bytes=out->kernel_map_page_bytes=fixture.cpu_page_bytes;out->cpu_page_shift=14;return 0;}
IOReturn NativeAdrenoQueryCpu4K(NativeAdrenoCpuState*){return kIOReturnUnsupported;}
IOReturn NativeAdrenoMaintainOwnedPages(void*p,size_t n,NativeAdrenoCacheOperation){CHECK(p && n && !(((uintptr_t)p|n)&16383));cached_at=(uintptr_t)p;length=n;++calls;return 0;}
IOReturn NativeAdrenoMaintainPhysicalPages(uint64_t p,size_t n,NativeAdrenoCacheOperation){CHECK(p && n && !((p|n)&16383));physical_at=p;length=n;++calls;return 0;}
IOReturn NativeAdrenoSetPagesCacheMode(const NativeAdrenoPhysicalSpan*s,size_t n,bool){CHECK(s&&n);return 0;}
IOReturn NativeAdrenoReassertWriteCombined(const NativeAdrenoPhysicalSpan*,size_t,uint32_t*out){*out=0;return 0;}
#include "NativeAdrenoMemory.cpp"
int main(){fixture.cpu_page_bytes=16384;unsigned cases=0;
 {NativeAdrenoMemory bo;CHECK(!bo.allocate(32768,36,true,32768,false));calls=0;CHECK(!bo.publishForDevice(4096,4096,false) && calls==1 && cached_at==(uintptr_t)bo.mapping() && length==16384);++cases;
 CHECK(!bo.acquireDeviceWrites(16384,4096) && cached_at==(uintptr_t)bo.mapping()+16384 && length==16384);++cases;
 calls=0;CHECK(bo.publishForDevice(32768,4096,false)==kIOReturnBadArgument && !calls);++cases;CHECK(!bo.release());}
 {NativeAdrenoMemory bo;CHECK(!bo.allocate(4096,36,true,16384,false));calls=0;CHECK(!bo.publishForDevice(0,4096,false) && length==16384 && calls==1);++cases;
 CHECK(!bo.makeWriteCombined());calls=0;CHECK(!bo.publishForDevice(0,4096,true,true) && length==16384 && physical_at==bo.ownedSpans()[0].physical && calls==1);++cases;CHECK(!bo.release());}
 {NativeAdrenoMemory bo;CHECK(!bo.importTask(reinterpret_cast<void*>(2),0x40000000,32768,36,32768));calls=0;CHECK(!bo.publishForDevice(4096,4096,false) && calls==1 && length==16384 && physical_at==bo.ownedSpans()[0].physical);++cases;
 CHECK(!bo.acquireDeviceWrites(20480,4096) && length==16384 && physical_at==bo.ownedSpans()[1].physical);++cases;CHECK(!bo.release());}
 CHECK(fixture.live.empty() && fixture.metadata.empty() && !fixture.imports_live);printf("PASS %u actual NativeMemory CPU16K partial-range ownership/cache boundary cases; IOKit/cache peers only, no GPU emulation\n",cases);}
