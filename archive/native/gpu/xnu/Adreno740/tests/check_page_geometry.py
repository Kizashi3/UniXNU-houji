#!/usr/bin/env python3
"""Actual Memory/CPU/Publish/UserClient BO-view paths with 4K and 16K CPU VM peers.

Only XNU/IOKit and architectural MRS/DC/DSB boundaries are replaced. Production
allocation, span clipping, pmap page-number math, cache/retention and BO-view
code is compiled unchanged. No kernel, plugin, GPU or device is built/accessed.
"""
from pathlib import Path
import re, subprocess, tempfile
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent

def function(source, signature):
    a=source.index(signature);brace=source.index('{',a);i=brace+1;depth=1
    while depth:
        depth+=(source[i]=='{')-(source[i]=='}');i+=1
    return source[a:i]

cpu_map=function((ROOT/'NativeAdrenoUserClient.cpp').read_text(),
 'IOReturn NativeAdrenoUserClient::cpuMap(')
cpu_unmap=function((ROOT/'NativeAdrenoUserClient.cpp').read_text(),
 'IOReturn NativeAdrenoUserClient::cpuUnmap(')
cpu=(ROOT/'NativeAdrenoCpu.cpp').read_text()
for field,reg in [('tcr','tcr_el1'),('ttbr0','ttbr0_el1'),('ttbr1','ttbr1_el1'),('sctlr','sctlr_el1')]:
    old=f'__asm__ volatile("mrs %0, {reg}" : "=r"(out->{field}));'
    assert old in cpu
    cpu=cpu.replace(old,f'out->{field}=cpu_{field};')
old='__asm__ volatile("mrs %0, ctr_el0":"=r"(ctr));'
assert cpu.count(old)==2;cpu=cpu.replace(old,'ctr=cpu_ctr;')
for op,value in [('cvac',0),('civac',1),('ivac',2)]:
    old=f'__asm__ volatile("dc {op}, %0"::"r"(address):"memory");'
    assert cpu.count(old)==2;cpu=cpu.replace(old,f'cache_line(address,{value});')
cpu=cpu.replace('__asm__ volatile("dsb sy":::"memory");','++barriers;')
assert '__asm__' not in cpu
memory=(ROOT/'NativeAdrenoMemory.cpp').read_text()
assert '__asm__' not in memory
publish=function((ROOT/'NativeAdrenoPublish.cpp').read_text(),
 'IOReturn AGXDeviceUserClient::clientMemoryForType(')
# BO boundary only: the unchanged Scanout and Mailbox special memory types
# are unrelated to owned BO spans and require the complete IOService framework.
start=publish.index('    if(type==NativeAdrenoScanoutType)')
end=publish.index('    native_adreno_view_diag[0]',start)
assert 'if(type==NativeAdrenoMailboxType)' in publish[start:end]
publish=publish[:start]+publish[end:]

prefix=r'''
#include "XnuMemoryFixture.h"
#include "NativeAdrenoMemory.h"
#include "NativeAdrenoCpuPagePolicy.h"
#include "NativeAdrenoABI.h"
#include <cstdio>
#include <map>
#include <set>
#define CHECK(x) do{if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);std::abort();}}while(0)
using vm_offset_t=uintptr_t;using ppnum_t=uint32_t;using UInt32=uint32_t;
constexpr IOReturn kIOReturnNotFound=9;
constexpr unsigned kIOMapAnywhere=1,kIOMapInhibitCache=2;
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
static void cache_line(uintptr_t address,unsigned op){CHECK(preemption_depth && !(address&63));cache_lines.push_back({address,op});}
extern "C" {uint64_t gPhysBase=0x10000000,gPhysSize=0x100000000;}
extern "C" vm_offset_t phystokv(uint64_t pa){CHECK(pa>=gPhysBase && pa-gPhysBase<gPhysSize);return pa;}
static std::map<ppnum_t,unsigned> attributes;
static std::vector<std::pair<ppnum_t,unsigned>> pmap_writes;
static unsigned attribute_write_fail;
extern "C" void pmap_set_cache_attributes(ppnum_t pn,unsigned attr){
 pmap_writes.push_back({pn,attr});if(pmap_writes.size()!=attribute_write_fail)attributes[pn]=attr;
}
extern "C" unsigned pmap_cache_attributes(ppnum_t pn){return attributes[pn];}
'''
view_prefix=r'''
/* The method bodies below are extracted unchanged from the candidate. The
 * surrounding entry lookup is a host owner peer, not a replacement method. */
class NativeAdrenoUserClient {
public:
 struct Entry {NativeAdrenoMemory memory;uint64_t handle=91;uint32_t token=7,mapping_leases=0;bool unreleasable=false;};
 Entry entry;bool open_=true;
 Entry *find(uint64_t handle){return handle==entry.handle?&entry:nullptr;}
 IOReturn cpuMap(const NativeAdrenoAbiBoCpuMap*,NativeAdrenoAbiBoCpuMapReply*);
 IOReturn cpuUnmap(const NativeAdrenoAbiBoCpuUnmap*);
};
struct CoreFixture{NativeAdrenoMemory *memory=nullptr;uint32_t token=7;NativeAdrenoMemory *memoryForToken(uint32_t t){return t==token?memory:nullptr;}};
static struct{void*lock=reinterpret_cast<void*>(3);}g;
static unsigned locks;
static void IOLockLock(void*p){CHECK(p==g.lock && !locks);++locks;}
static void IOLockUnlock(void*p){CHECK(p==g.lock && locks==1);--locks;}
static volatile uint32_t native_adreno_view_diag[6];
class AGXDeviceUserClient {
 struct View {uint32_t token;IOMemoryDescriptor *descriptor;};
 enum{MaxViews=4};View *views_=nullptr;
public:
 bool live_=true;CoreFixture *core_=nullptr;
 IOReturn clientMemoryForType(UInt32,IOOptionBits*,IOMemoryDescriptor**);
 void discardViews(){if(views_){for(auto&v:*reinterpret_cast<View(*)[MaxViews]>(views_))if(v.descriptor)v.descriptor->release();fixtureMetadataFree(views_);views_=nullptr;}}
};
'''
main=r'''
static void reset(){
 CHECK(fixture.live.empty() && fixture.imported_live.empty() && fixture.view_live.empty() && fixture.metadata.empty() && !locks && !preemption_depth);
 fixture=MemoryFixture{};fixture.cpu_page_bytes=PAGE_SIZE;
 page_size=map_page_bytes=PAGE_SIZE;cpu_tcr=PAGE_SIZE==16384?(UINT64_C(2)<<14|UINT64_C(1)<<30):(UINT64_C(2)<<30);
 cpu_ttbr0=0x30000000;cpu_ttbr1=0x30004000;cpu_sctlr=1;cpu_ctr=UINT64_C(4)<<16;
 attributes.clear();pmap_writes.clear();cache_lines.clear();attribute_write_fail=barriers=0;
}
static unsigned shift(){return PAGE_SIZE==16384?14:12;}
static std::set<ppnum_t> pageNumbers(const NativeAdrenoMemory&m){
 std::set<ppnum_t> result;for(size_t i=0;i<m.ownedSpanCount();i++)for(size_t at=0;at<m.ownedSpans()[i].bytes;at+=PAGE_SIZE)result.insert((ppnum_t)((m.ownedSpans()[i].physical+at)>>shift()));return result;
}
static void discardAfterQuarantine(){
 // HOST FIXTURE ONLY: no production cleanup or reset authorization is inferred.
 while(!fixture.live.empty())fixture.live.back()->release();
 while(!fixture.imported_live.empty())fixture.imported_live.back()->release();
 while(!fixture.metadata.empty())fixtureMetadataFree(fixture.metadata.back());
}
static unsigned queries(){unsigned cases=0;
 reset();NativeAdrenoCpuState s{};CHECK(!NativeAdrenoQueryCpuPages(&s) && s.cpu_page_shift==shift() && s.kernel_page_bytes==PAGE_SIZE && s.kernel_map_page_bytes==PAGE_SIZE);
 CHECK(NativeAdrenoQueryCpu4K(&s)==(PAGE_SIZE==4096?kIOReturnSuccess:kIOReturnUnsupported));CHECK(NativeAdrenoQueryCpuPages(nullptr)==kIOReturnBadArgument);cases+=3;
 for(unsigned bad=0;bad<7;bad++){
  reset();if(!bad)page_size=PAGE_SIZE==4096?16384:4096;if(bad==1)map_page_bytes=PAGE_SIZE==4096?16384:4096;
  if(bad==2)cpu_tcr^=UINT64_C(1)<<14;if(bad==3)cpu_tcr^=UINT64_C(1)<<30;if(bad==4)cpu_sctlr=0;if(bad==5)cpu_ttbr1=0;if(bad==6)cpu_ttbr1=PAGE_SIZE-1;
  CHECK(NativeAdrenoQueryCpuPages(&s)==kIOReturnUnsupported && !s.cpu_page_shift && !preemption_depth);
  NativeAdrenoMemory m;CHECK(!NativeAdrenoMemory::backingBudget(4096) && m.allocate(4096,36,false,16384)==kIOReturnUnsupported && !fixture.created);cases++;
 }
 reset();size_t rounded=0;CHECK(!NativeAdrenoRoundCpuBacking(SIZE_MAX-4095,PAGE_SIZE,&rounded)==(PAGE_SIZE==16384));
 CHECK(!NativeAdrenoRoundCpuBacking(4097,PAGE_SIZE,&rounded));CHECK(!NativeAdrenoMemory::backingBudget(256u*1024u*1024u+4096));cases+=3;return cases;
}
static unsigned allocations(){unsigned cases=0;
 for(unsigned mode:{Contiguous,Scattered,Paired})for(size_t logical:{4096u,8192u,12288u,16384u,20480u,28672u,36864u})for(unsigned bits:{32u,36u,48u}){
  reset();fixture.mode=(SegmentMode)mode;NativeAdrenoMemory m;size_t owned=(logical+PAGE_SIZE-1)&~(size_t)(PAGE_SIZE-1);
  CHECK(NativeAdrenoMemory::backingBudget(logical)==owned);
  CHECK(!m.allocate(logical,bits,mode==Contiguous,owned,true) && m.bytes()==logical && m.ownedBytes()==owned && m.cpuPageBytes()==PAGE_SIZE);
  CHECK(fixture.created==1 && fixture.allocation_bytes[0]==owned && fixture.segment_calls==owned/PAGE_SIZE && !(fixture.allocation_masks[0]&(PAGE_SIZE-1)));
  CHECK(!((uintptr_t)m.mapping()&(PAGE_SIZE-1)) && m.descriptor()->getLength()==owned);
  size_t visible=0,backing=0;for(size_t i=0;i<m.spanCount();i++){CHECK(m.spans()[i].offset==visible && !(m.spans()[i].bytes&4095));visible+=m.spans()[i].bytes;}
  for(size_t i=0;i<m.ownedSpanCount();i++){CHECK(m.ownedSpans()[i].offset==backing && !((m.ownedSpans()[i].physical|m.ownedSpans()[i].bytes)&(PAGE_SIZE-1)));backing+=m.ownedSpans()[i].bytes;}
  CHECK(visible==logical && backing==owned);
  auto*bytes=(unsigned char*)m.mapping();for(size_t i=0;i<owned;i++)CHECK(!bytes[i]);CHECK(bytes[owned]==0xa5);
  auto pages=pageNumbers(m);CHECK(pages.size()==owned/PAGE_SIZE);CHECK(!m.makeWriteCombined());
  CHECK(pmap_writes.size()==pages.size());for(auto w:pmap_writes)CHECK(pages.count(w.first) && w.second==VM_WIMG_WCOMB);
  CHECK(!m.publishForDevice(0,4096,false) && !m.acquireDeviceWrites(0,4096));
  CHECK(m.publishForDevice(logical,4096,false)==kIOReturnBadArgument);
  CHECK(!m.holdForDevice() && m.release()==kIOReturnBusy && !fixture.completed && !m.retireAfterQuiescence());
  CHECK(!m.release() && fixture.completed==1 && fixture.released==1 && !m.ownedBytes() && !m.ownedSpans());
  CHECK(pmap_writes.size()==2*pages.size());for(auto pn:pages)CHECK(attributes[pn]==VM_WIMG_DEFAULT);cases++;
 }
 reset();fixture.next_physical=(UINT64_C(1)<<32)-PAGE_SIZE;NativeAdrenoMemory edge;
 CHECK(edge.allocate(PAGE_SIZE+4096,32,false,2*PAGE_SIZE)==kIOReturnUnsupported && !edge.backed() && fixture.released==1);cases++;
 reset();NativeAdrenoMemory m;CHECK(NativeAdrenoMemory::reservePool(36,16384)==kIOReturnUnsupported && NativeAdrenoMemory::writeCombinePool()==kIOReturnUnsupported && !NativeAdrenoMemory::poolBytes());cases++;
 if(PAGE_SIZE==16384){CHECK(m.allocate(4096,36,false,4096)==kIOReturnNoResources && !fixture.created);cases++;}
 return cases;
}
static unsigned neighbours(){unsigned cases=0;reset();NativeAdrenoMemory a,b;
 CHECK(!a.allocate(4096,36,false,PAGE_SIZE) && !b.allocate(4096,36,false,PAGE_SIZE));auto pa=pageNumbers(a),pb=pageNumbers(b);for(auto pn:pa)CHECK(!pb.count(pn));
 memset(b.mapping(),0x5c,b.ownedBytes());CHECK(!a.makeWriteCombined());for(auto pn:pb)CHECK(attributes[pn]==VM_WIMG_DEFAULT);
 for(size_t i=0;i<b.ownedBytes();i++)CHECK(((unsigned char*)b.mapping())[i]==0x5c);
 CHECK(!a.release() && !b.release());cases++;
 // 4K maintenance stays inside the owned BO even with a 16K CPU backing.
 reset();CHECK(!a.allocate(12288,36,false,NativeAdrenoMemory::backingBudget(12288)));cache_lines.clear();CHECK(!a.publishForDevice(4096,4096,true));
 CHECK(cache_lines.size()==4096/64);for(auto line:cache_lines)CHECK(line.address>=(uintptr_t)a.mapping()+4096 && line.address<(uintptr_t)a.mapping()+8192 && line.operation==1);CHECK(!a.release());cases++;
 // A clipped logical span is never sufficient to change a whole 16K page.
 if(PAGE_SIZE==16384){reset();NativeAdrenoPhysicalSpan s{0,0x30000000,4096};CHECK(NativeAdrenoSetPagesCacheMode(&s,1,true)==kIOReturnBadArgument && pmap_writes.empty());cases++;}
 return cases;
}
static unsigned pmapFailures(){unsigned cases=0;
 // Reassert is mandatory, including Unsupported after an earlier CPU page
 // was corrected, and IOError when a void pmap setter fails readback.
 for(unsigned fault=0;fault<2;fault++){
  reset();NativeAdrenoMemory m;CHECK(!m.allocate(PAGE_SIZE+4096,36,false,2*PAGE_SIZE) && !m.makeWriteCombined());
  auto pages=pageNumbers(m);CHECK(pages.size()==2);auto first=*pages.begin(),last=*pages.rbegin();
  pmap_writes.clear();attributes[first]=VM_WIMG_DEFAULT;
  if(!fault)attributes[last]=7;else attribute_write_fail=1;
  uint32_t corrected=0;CHECK(m.reassertWriteCombined(&corrected)==(fault?kIOReturnIOError:kIOReturnUnsupported));
  CHECK(corrected==(fault?0u:1u) && pmap_writes.size()==1 && pmap_writes[0].first==first);
  // Actual VM propagation is exercised by check_submit_cache_failure.py.
  m.quarantine();discardAfterQuarantine();cases++;
 }
 for(unsigned fail=0;fail<4;fail++){
  reset();NativeAdrenoMemory m;CHECK(!m.allocate(PAGE_SIZE+4096,36,false,2*PAGE_SIZE));auto pages=pageNumbers(m);auto last=*pages.rbegin();
  if(!fail)attributes[last]=7;else if(fail<3)attribute_write_fail=fail==1?1:2;
  if(fail<3){CHECK(m.makeWriteCombined()!=kIOReturnSuccess && m.quarantined() && m.descriptor() && m.ownedBytes()==2*PAGE_SIZE);}
  else {CHECK(!m.makeWriteCombined());pmap_writes.clear();attribute_write_fail=1;CHECK(m.release()==kIOReturnIOError && m.quarantined());}
  unsigned completed=fixture.completed,released=fixture.released;CHECK(m.release()==kIOReturnBusy && fixture.completed==completed && fixture.released==released && m.descriptor());
  NativeAdrenoCpuView v{};CHECK(!m.cpuView(&v) && !v.spans && !v.count && !v.bytes);discardAfterQuarantine();cases++;
 }
 reset();NativeAdrenoPhysicalSpan spans[]={{0,0x30000000,PAGE_SIZE},{PAGE_SIZE,0x30000000+2*PAGE_SIZE,PAGE_SIZE}};
 attributes[(ppnum_t)(spans[1].physical>>shift())]=7;CHECK(NativeAdrenoSetPagesCacheMode(spans,2,true)==kIOReturnUnsupported && pmap_writes.empty());cases++;
 reset();spans[1].physical=UINT64_MAX-PAGE_SIZE+1;CHECK(NativeAdrenoSetPagesCacheMode(spans,2,true)==kIOReturnBadArgument && pmap_writes.empty());cases++;
 // ppnum_t may be narrower than physical addresses; no truncating pmap ID.
 reset();gPhysBase=UINT64_C(1)<<47;gPhysSize=UINT64_C(1)<<20;
 NativeAdrenoPhysicalSpan high{0,gPhysBase,PAGE_SIZE};CHECK(NativeAdrenoSetPagesCacheMode(&high,1,true)==kIOReturnBadArgument && pmap_writes.empty());gPhysBase=0x10000000;gPhysSize=0x100000000;cases++;
 reset();NativeAdrenoMemory m;CHECK(!m.allocate(4096,36,false,PAGE_SIZE));fixture.complete_fail=true;CHECK(m.release()==kIOReturnIOError && m.quarantined() && !fixture.released && m.ownedBytes()==PAGE_SIZE);discardAfterQuarantine();cases++;
 return cases;
}
static unsigned imports(){unsigned cases=0;
 // The writable prepare refusal must retry a complete CPU-page range as
 // read-only, still qualifying raw physical segments before publishing it.
 for(unsigned fault=0;fault<2;fault++){
  reset();fixture.write_protected_imports=true;if(fault)fixture.mode=ShortSegment;NativeAdrenoMemory readonly;
  auto status=readonly.importTask((void*)4,0x10000000,2*PAGE_SIZE,36,2*PAGE_SIZE);
  CHECK(fixture.prepared==2 && fixture.imported==2 && fixture.imports_released>=1 && pmap_writes.empty());
  if(!fault){CHECK(!status && readonly.readOnly() && readonly.bytes()==2*PAGE_SIZE && readonly.ownedBytes()==2*PAGE_SIZE);NativeAdrenoCpuView v{};CHECK(!readonly.cpuView(&v));CHECK(!readonly.release() && !fixture.imports_live);}
  else CHECK(status==kIOReturnUnsupported && !readonly.backed() && !fixture.imports_live && fixture.completed==1);
  cases++;
 }

 for(unsigned fault=0;fault<4;fault++){
  reset();fixture.mode=(SegmentMode)(ZeroPhysical+fault);NativeAdrenoMemory m;
  CHECK(m.importTask((void*)4,0x10000000,2*PAGE_SIZE,36,2*PAGE_SIZE)==kIOReturnUnsupported && fixture.imports_live==0 && !m.backed() && pmap_writes.empty());cases++;
 }
 if(PAGE_SIZE==16384)for(unsigned fault=0;fault<2;fault++){
  reset();NativeAdrenoMemory m;CHECK(m.importTask((void*)4,0x10000000+(fault?4096:0),fault?16384:4096,36,16384)==kIOReturnUnsupported && !fixture.imported && pmap_writes.empty());cases++;
 }
 reset();NativeAdrenoMemory m;CHECK(!m.importTask((void*)4,0x10000000,2*PAGE_SIZE,36,2*PAGE_SIZE) && m.imported() && !m.mapping());NativeAdrenoCpuView v{(const NativeAdrenoPhysicalSpan*)1,2,3};CHECK(!m.cpuView(&v) && !v.spans && !v.count && !v.bytes);
 CHECK(m.makeWriteCombined()==kIOReturnNotReady && pmap_writes.empty());CHECK(!m.publishForDevice(0,4096,true) && !m.acquireDeviceWrites(0,4096));CHECK(!m.holdForDevice() && m.release()==kIOReturnBusy && !m.retireAfterQuiescence());CHECK(!m.release() && !fixture.imports_live && pmap_writes.empty());cases++;
 reset();fixture.complete_fail=true;CHECK(!m.importTask((void*)4,0x10000000,PAGE_SIZE,36,PAGE_SIZE));CHECK(m.release()==kIOReturnIOError && m.quarantined() && fixture.imports_live==1);discardAfterQuarantine();cases++;
 return cases;
}
static unsigned cpuMapReplies(){unsigned cases=0;
 reset();NativeAdrenoUserClient uc;auto&m=uc.entry.memory;
 CHECK(!m.allocate(4096,36,false,PAGE_SIZE));NativeAdrenoAbiBoCpuMap request{91};NativeAdrenoAbiBoCpuMapReply reply{99,0,999};
 CHECK(!uc.cpuMap(&request,&reply) && reply.token==7 && reply.bytes==PAGE_SIZE && m.bytes()==4096 && uc.entry.mapping_leases==1);cases++;
 NativeAdrenoAbiBoCpuUnmap unmap{91,7,0};CHECK(!uc.cpuUnmap(&unmap) && !uc.entry.mapping_leases && !m.release());cases++;
 for(unsigned bad=0;bad<7;bad++){
  reset();NativeAdrenoUserClient baduc;auto&bo=baduc.entry.memory;
  CHECK(!bo.allocate(4096,36,false,PAGE_SIZE));NativeAdrenoAbiBoCpuMap r{91};NativeAdrenoAbiBoCpuMapReply output{99,0,999};
  if(!bad)baduc.open_=false;if(bad==1)r.handle=92;if(bad==2)baduc.entry.unreleasable=true;
  if(bad==3)bo.quarantine();if(bad==4)baduc.entry.mapping_leases=UINT32_MAX;
  if(bad==5)CHECK(!bo.release());
  unsigned before=baduc.entry.mapping_leases;
  auto status=bad==6?baduc.cpuMap(nullptr,&output):baduc.cpuMap(&r,&output);
  CHECK(status!=kIOReturnSuccess && baduc.entry.mapping_leases==before);
  if(bad!=6)CHECK(!output.token && !output.bytes);
  if(bad==3)discardAfterQuarantine();else if(bad!=5)CHECK(!bo.release());cases++;
 }
 reset();NativeAdrenoUserClient imported;CHECK(!imported.entry.memory.importTask((void*)4,0x10000000,PAGE_SIZE,36,PAGE_SIZE));
 reply={99,0,999};CHECK(imported.cpuMap(&request,&reply)==kIOReturnUnsupported && !reply.token && !reply.bytes && !imported.entry.mapping_leases && !imported.entry.memory.release());cases++;
 return cases;
}
static unsigned views(){unsigned cases=0;
 for(size_t logical:{4096u,12288u,20480u}){
  reset();fixture.mode=Scattered;NativeAdrenoMemory m;CHECK(!m.allocate(logical,36,false,NativeAdrenoMemory::backingBudget(logical)));CoreFixture core{&m};AGXDeviceUserClient uc;uc.core_=&core;
  IOOptionBits options=0;IOMemoryDescriptor *view=nullptr;CHECK(!uc.clientMemoryForType(7,&options,&view) && view && options==(kIOMapAnywhere|kIOMapInhibitCache));
  CHECK(view->bytes==m.ownedBytes() && view->ranges.size()==m.ownedSpanCount());size_t bytes=0;for(auto range:view->ranges){CHECK(!(range.address&(PAGE_SIZE-1)) && !(range.length&(PAGE_SIZE-1)));bytes+=range.length;}CHECK(bytes==m.ownedBytes());
  view->release();IOMemoryDescriptor *cached=nullptr;CHECK(!uc.clientMemoryForType(7,&options,&cached) && cached==view && fixture.views_created==1);cached->release();uc.discardViews();CHECK(fixture.views_released==1 && !m.release());cases++;
 }
 for(unsigned fault=0;fault<5;fault++){
  reset();NativeAdrenoMemory m;CHECK(!m.allocate(4096,36,false,PAGE_SIZE));CoreFixture core{&m};AGXDeviceUserClient uc;uc.core_=&core;IOOptionBits options=0;IOMemoryDescriptor *view=(IOMemoryDescriptor*)1;
  if(!fault)uc.live_=false;if(fault==1)m.quarantine();if(fault==2)fixture.metadata_fail=true;if(fault==3)fixture.view_fail=true;if(fault==4)core.token=8;
  CHECK(uc.clientMemoryForType(7,&options,&view)!=kIOReturnSuccess && !view && !fixture.views_created && !locks);
  fixture.metadata_fail=false;uc.discardViews();if(fault==1)discardAfterQuarantine();else CHECK(!m.release());cases++;
 }
 reset();NativeAdrenoMemory m;CHECK(!m.importTask((void*)4,0x10000000,PAGE_SIZE,36,PAGE_SIZE));CoreFixture core{&m};AGXDeviceUserClient uc;uc.core_=&core;IOOptionBits options=0;IOMemoryDescriptor *view=(IOMemoryDescriptor*)1;CHECK(uc.clientMemoryForType(7,&options,&view)!=kIOReturnSuccess && !view && !fixture.views_created);uc.discardViews();CHECK(!m.release());cases++;
 // Revalidate a cached descriptor before every grant. Quarantine, closed
 // client and withdrawn ownership retain the old cache but grant no new lease.
 for(unsigned fault=0;fault<3;fault++){
  reset();NativeAdrenoMemory owned;CHECK(!owned.allocate(4096,36,false,PAGE_SIZE));CoreFixture cachedcore{&owned};AGXDeviceUserClient cachedclient;cachedclient.core_=&cachedcore;view=nullptr;
  CHECK(!cachedclient.clientMemoryForType(7,&options,&view) && view);view->release();unsigned retains=fixture.view_retain_calls;
  if(!fault)owned.quarantine();if(fault==1)cachedclient.live_=false;if(fault==2)cachedcore.memory=nullptr;
  view=(IOMemoryDescriptor*)1;CHECK(cachedclient.clientMemoryForType(7,&options,&view)==kIOReturnNotReady && !view && fixture.view_retain_calls==retains && fixture.view_live.size()==1 && fixture.views_created==1 && !locks);
  cachedclient.discardViews();CHECK(fixture.views_released==1);if(!fault)discardAfterQuarantine();else CHECK(!owned.release());cases++;
 }
 // Never expose a descriptor which cannot be held in the per-BO view cache.
 reset();NativeAdrenoMemory objects[5];CoreFixture cachecore{};AGXDeviceUserClient cacheuc;cacheuc.core_=&cachecore;
 for(unsigned i=0;i<5;i++){
  CHECK(!objects[i].allocate(4096,36,false,PAGE_SIZE));cachecore.memory=&objects[i];cachecore.token=7+i;view=nullptr;
  auto status=cacheuc.clientMemoryForType(7+i,&options,&view);
  if(i<4){CHECK(!status && view);view->release();}else CHECK(status==kIOReturnNoResources && !view && fixture.views_released==1);
 }
 CHECK(fixture.view_live.size()==4);cacheuc.discardViews();for(auto&object:objects)CHECK(!object.release());CHECK(fixture.views_created==5 && fixture.views_released==5);cases++;
 return cases;
}
int main(){unsigned cases=queries()+allocations()+neighbours()+pmapFailures()+imports()+views()+cpuMapReplies();reset();printf("PASS: CPU%uK/GPU4K actual Memory/Cpu/Publish-view/cpuMap %u boundary profiles (ASAN/UBSAN); no kernel/device qualification\n",PAGE_SIZE/1024,cases);}
'''
with tempfile.TemporaryDirectory(prefix='native-adreno-page-geometry-') as td:
    td=Path(td)
    for name in ['IOKit/IOTypes.h','IOKit/IOBufferMemoryDescriptor.h','IOKit/IOLib.h','kern/task.h','kern/cpu_data.h','vm/vm_map.h','mach/vm_param.h','kern/clock.h','vm/memory_types.h']:
        h=td/name;h.parent.mkdir(parents=True,exist_ok=True);h.write_text('#include "XnuMemoryFixture.h"\n')
    c=td/'test.cpp';c.write_text(prefix+cpu+memory+view_prefix+cpu_map+cpu_unmap+publish+main)
    for page in (4096,16384):
        exe=td/f'test-{page}'
        subprocess.run(['clang++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer',f'-DPAGE_SIZE={page}','-I',str(td),'-I',str(HERE),'-I',str(ROOT),str(c),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)
    legacy=td/'legacy-memory'
    subprocess.run(['clang++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer','-I',str(td),'-I',str(HERE),'-I',str(ROOT),str(ROOT/'NativeAdrenoMemory.cpp'),str(HERE/'test_memory.cpp'),'-o',str(legacy)],check=True)
    subprocess.run([str(legacy)],check=True)
