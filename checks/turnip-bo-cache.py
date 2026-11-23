#!/usr/bin/env python3
"""Exercise actual Darwin whole-BO cache/allocator/retirement over a kernel peer.

Checks ownership and RPC avoidance; this does not execute shaders or measure FPS.
"""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT/'graphics/turnip/overlay/src/freedreno/vulkan/tu_knl_darwin.cc').read_text()
def between(a, b):
    return source[source.index(a):source.index(b, source.index(a))]
structs = between('enum { DARWIN_RETIRED_BOS', 'static kern_return_t\ndw_call')
cache = between('static VkResult\ndarwin_release_native', 'static void\ndarwin_watch_memory_pressure')
reap = between('static VkResult\ndarwin_reap_locked', 'static VkResult\ndarwin_map_failure')
allocate = between('static VkResult\ndarwin_bo_init(struct', '/* VK_EXT_external_memory_host:')
mapping = between('static VkResult\ndarwin_bo_map(struct', 'static void\ndarwin_bo_set_metadata')
finish = between('static void\ndarwin_bo_finish(struct', '/* ---- submissions ---- */')
stubs = r'''
#include <algorithm>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <map>
#include <mutex>
#include <pthread.h>
#include <thread>
using VkResult=int;using kern_return_t=int;using mach_vm_address_t=uint64_t;using mach_vm_size_t=uint64_t;using VkMemoryPropertyFlags=unsigned;
constexpr int VK_SUCCESS=0,VK_TIMEOUT=1,VK_NOT_READY=2,VK_ERROR_DEVICE_LOST=-1,VK_ERROR_OUT_OF_DEVICE_MEMORY=-2,VK_ERROR_FEATURE_NOT_PRESENT=-3;
constexpr int KERN_SUCCESS=0,kIOReturnBusy=2;
constexpr unsigned NativeAdrenoMethodBoAlloc=2,NativeAdrenoMethodBoMap=3,NativeAdrenoMethodBoFree=4,NativeAdrenoMethodBoCpuUnmap=13,NativeAdrenoMethodBoCpuMap=12;
constexpr unsigned kIOMapAnywhere=1,kIOMapWriteCombineCache=2;constexpr int VK_ERROR_MEMORY_MAP_FAILED=-4;
enum tu_bo_alloc_flags {TU_BO_ALLOC_NO_FLAGS=0,TU_BO_ALLOC_ALLOW_DUMP=1,TU_BO_ALLOC_GPU_READ_ONLY=2,TU_BO_ALLOC_REPLAYABLE=4,TU_BO_ALLOC_INTERNAL_RESOURCE=8,TU_BO_ALLOC_DMABUF=16,TU_BO_ALLOC_SHAREABLE=32,TU_BO_ALLOC_IMPLICIT_SYNC=64};
struct NativeAdrenoAbiBoAlloc {uint64_t bytes;unsigned align_log2,contiguous;};
struct NativeAdrenoAbiBoAllocReply {uint64_t handle;};
struct NativeAdrenoAbiBoMap {uint64_t handle,iova;unsigned permissions,writeback,shareability;};
struct NativeAdrenoAbiBoMapReply {uint64_t unused;};
struct NativeAdrenoAbiBoFree {uint64_t handle;};
struct NativeAdrenoAbiBoCpuMap {uint64_t handle;};struct NativeAdrenoAbiBoCpuMapReply {unsigned token;};
struct NativeAdrenoAbiBoCpuUnmap {uint64_t handle;unsigned token;};
struct vk_object_base {};struct tu_sparse_vma {};
struct tu_bo {unsigned gem_handle;uint64_t size,iova;const char *name;int refcnt;bool implicit_sync;vk_object_base *base;uint64_t unique_id,darwin_handle,darwin_alloc_size;unsigned darwin_token;bool darwin_cacheable,darwin_read_only;void *map;bool never_unmap;};
struct tu_device {int vk,dma_bo_lock;void *darwin_retire;};
struct {int conn;pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;uint32_t last_fence=17;} dw;
static std::map<uint64_t,uint64_t> native, ranges;
static tu_bo slots[8192];static unsigned next_handle=1,alloc_calls,map_calls,unmap_calls,lease_calls,free_calls,range_frees;
static bool pending,enabled=true;static int fail_method=-1;static int failure_status=7;static unsigned fail_left;
static uint64_t next_iova=0x100000;static bool fail_iova;
static std::mutex fixture_lock;
static uint8_t cpu_view[16384],mapped_view[327680];static uint64_t returned_mapping_length;
static int IOConnectMapMemory64(int,unsigned,int,mach_vm_address_t *address,mach_vm_size_t *length,unsigned){*address=(uintptr_t)mapped_view;*length=returned_mapping_length;return KERN_SUCCESS;}
static int mach_task_self(){return 0;}
static int vk_device_set_lost(int *,const char *,...){return VK_ERROR_DEVICE_LOST;}
static int vk_error(tu_device *,int r){return r;}
static int vk_errorf(tu_device *,int r,const char *,...){return r;}
static bool debug_get_bool_option(const char *,bool){return enabled;}
static VkResult dw_wait_fence_raw(tu_device *,uint32_t,uint64_t){return pending?VK_TIMEOUT:VK_SUCCESS;}
static void darwin_free_iova(tu_device *,uint64_t iova,uint64_t size){assert(ranges.at(iova)==size);ranges.erase(iova);++range_frees;}
static VkResult darwin_allocate_iova(tu_device *,uint64_t size,uint64_t client,tu_bo_alloc_flags,uint64_t *out){if(fail_iova){fail_iova=false;return VK_ERROR_OUT_OF_DEVICE_MEMORY;}*out=client?client:next_iova;assert(ranges.emplace(*out,size).second);next_iova+=size;return 0;}
static kern_return_t IOConnectUnmapMemory64(int,unsigned,int,mach_vm_address_t){++unmap_calls;if(fail_method==100 && fail_left){--fail_left;return failure_status;}return 0;}
static kern_return_t dw_call(unsigned method,const void *in,size_t,void *out,size_t){
 std::lock_guard<std::mutex> guard(fixture_lock);
 if(method==NativeAdrenoMethodBoAlloc)++alloc_calls;
 if(method==NativeAdrenoMethodBoMap)++map_calls;
 if(method==NativeAdrenoMethodBoCpuUnmap)++lease_calls;
 if(method==NativeAdrenoMethodBoFree)++free_calls;
 if(int(method)==fail_method && fail_left){--fail_left;return failure_status;}
 if(method==NativeAdrenoMethodBoAlloc){auto req=(const NativeAdrenoAbiBoAlloc *)in;auto reply=(NativeAdrenoAbiBoAllocReply *)out;reply->handle=next_handle++;native[reply->handle]=req->bytes;}
 if(method==NativeAdrenoMethodBoCpuMap){((NativeAdrenoAbiBoCpuMapReply *)out)->token=789;}
 if(method==NativeAdrenoMethodBoFree){assert(native.erase(((const NativeAdrenoAbiBoFree *)in)->handle)==1);}
 return 0;
}
static VkResult darwin_map_failure(tu_device *dev,uint64_t handle,uint64_t iova,uint64_t size,int){NativeAdrenoAbiBoFree f{handle};dw_call(4,&f,sizeof f,nullptr,0);darwin_free_iova(dev,iova,size);return -2;}
static tu_bo *tu_device_lookup_bo(tu_device *,unsigned handle){assert(handle<8192);return &slots[handle];}
static const char *tu_debug_bos_add(tu_device *,uint64_t,const char *name){return name;}
static void tu_debug_bos_del(tu_device *,tu_bo *){}static void tu_dump_bo_init(tu_device *,tu_bo *){}static void tu_dump_bo_del(tu_device *,tu_bo *){}
static void u_rwlock_rdlock(int*){}static void u_rwlock_rdunlock(int*){}static bool p_atomic_dec_zero(int *value){return --*value==0;}
static VkResult darwin_wait_idle(tu_device *){pending=false;return 0;}
#define MESA_TRACE_FUNC() ((void)0)
#define TU_RMV(...) ((void)0)
'''
main = r'''
static tu_bo *make(tu_device &dev,uint64_t bytes,unsigned flags=TU_BO_ALLOC_ALLOW_DUMP,uint64_t address=0){tu_bo *bo=nullptr;assert(darwin_bo_init(&dev,nullptr,&bo,bytes,address,0,(tu_bo_alloc_flags)flags,nullptr,"test")==0);return bo;}
static void drain(tu_device &dev,darwin_retire_state &r){pending=false;assert(darwin_collect_retired(&dev)==0);pthread_mutex_lock(&r.lock);darwin_cache_flush(&dev,&r);pthread_mutex_unlock(&r.lock);assert(r.failure==0 && r.cache_count==0 && r.count==0);}
int main(){
 darwin_retire_state r{};pthread_mutex_init(&r.lock,nullptr);tu_device d{};d.darwin_retire=&r;
 auto bo=make(d,16384);bo->map=cpu_view;bo->darwin_token=123;bo->never_unmap=true;
 const auto handle=bo->darwin_handle,iova=bo->iova;
 pending=true;darwin_bo_finish(&d,bo);assert(r.count==1 && r.cache_count==0 && native.size()==1 && !free_calls && !range_frees);
 assert(darwin_collect_retired(&d)==0 && r.count==1);
 pending=false;assert(darwin_collect_retired(&d)==0 && r.count==0 && r.cache_count==1);
 const unsigned before_alloc=alloc_calls,before_map=map_calls;
 bo=make(d,16384);assert(bo->darwin_handle==handle && bo->iova==iova && bo->map==cpu_view && bo->darwin_token==123);
 assert(alloc_calls==before_alloc && map_calls==before_map && !unmap_calls && !lease_calls && !free_calls);
 darwin_bo_finish(&d,bo);
 // Wrong rights and entries more than 25 percent larger cannot be reused.
 bo=make(d,16384,TU_BO_ALLOC_GPU_READ_ONLY);assert(bo->darwin_handle!=handle);darwin_bo_finish(&d,bo);
 bo=make(d,8192);assert(bo->darwin_handle!=handle);darwin_bo_finish(&d,bo);
 memset(cpu_view,0xa5,sizeof cpu_view);bo=make(d,16384,TU_BO_ALLOC_INTERNAL_RESOURCE);
 assert(bo->darwin_handle==handle && std::all_of(std::begin(cpu_view),std::end(cpu_view),[](auto b){return b==0;}));darwin_bo_finish(&d,bo);
 // Exported, replayable, fixed-address and oversized allocations are not cached.
 for(unsigned flags:{unsigned(TU_BO_ALLOC_REPLAYABLE),unsigned(TU_BO_ALLOC_SHAREABLE),unsigned(TU_BO_ALLOC_DMABUF),unsigned(TU_BO_ALLOC_IMPLICIT_SYNC)}){bo=make(d,4096,flags);assert(!bo->darwin_cacheable);darwin_bo_finish(&d,bo);}
 bo=make(d,4096,0,0x8000000);assert(!bo->darwin_cacheable);darwin_bo_finish(&d,bo);
 bo=make(d,DARWIN_CACHE_MAX_BO+4096);assert(!bo->darwin_cacheable);darwin_bo_finish(&d,bo);
 drain(d,r);assert(native.empty() && ranges.empty());
 // Size classes are bounded, page-aligned, monotonic and unchanged outside the
 // eligible domain; zero/overflow values never reach clz or overflowing math.
 assert(darwin_size_class(0)==0 && darwin_size_class(UINT64_MAX)==UINT64_MAX);
 assert(darwin_size_class(DARWIN_CACHE_MAX_BO+1)==DARWIN_CACHE_MAX_BO+1);
 for(uint64_t size=4096,previous=0;size<=DARWIN_CACHE_MAX_BO;size+=4096){
  auto rounded=darwin_size_class(size);assert(rounded>=size && rounded%4096==0 && rounded<=DARWIN_CACHE_MAX_BO);
  assert(rounded>=previous && rounded-size<=size/4);previous=rounded;
 }
 // Logical size remains the request, but mapping, retirement and IOVA release
 // always use the actual retained allocation extent, even after repeated reuse.
 auto small=make(d,327680),large=make(d,393216);
 const auto small_handle=small->darwin_handle,large_handle=large->darwin_handle;
 std::vector<uint8_t> bigger_view(393216,0xa5);
 large->map=bigger_view.data();large->darwin_token=456;
 darwin_bo_finish(&d,small);darwin_bo_finish(&d,large); // larger is newer
 auto allocations=alloc_calls,maps=map_calls;
 bo=make(d,262144);assert(bo->darwin_handle==small_handle && bo->size==262144 && bo->darwin_alloc_size==327680);
 assert(alloc_calls==allocations && map_calls==maps);
 darwin_bo_finish(&d,bo);
 bo=make(d,266240,TU_BO_ALLOC_INTERNAL_RESOURCE);
 assert(bo->darwin_handle==large_handle && bo->size==266240 && bo->darwin_alloc_size==393216);
 assert(std::all_of(bigger_view.begin(),bigger_view.end(),[](auto v){return v==0;}));
 assert(native.at(large_handle)==393216 && ranges.at(bo->iova)==393216);
 darwin_bo_finish(&d,bo);drain(d,r);assert(ranges.empty());
 // The CPU view must span the retained extent, not only the smaller request.
 bo=make(d,266240);returned_mapping_length=266240;
 assert(darwin_bo_map(&d,bo,nullptr)==VK_ERROR_MEMORY_MAP_FAILED && !bo->map && !bo->darwin_token);
 returned_mapping_length=327680;assert(darwin_bo_map(&d,bo,nullptr)==VK_SUCCESS && bo->map==mapped_view);
 darwin_bo_finish(&d,bo);drain(d,r);
 // Equal-size entries prefer the most recent; too-small entries never match.
 small=make(d,327680);large=make(d,327680);const auto newest=large->darwin_handle;
 darwin_bo_finish(&d,small);darwin_bo_finish(&d,large);
 bo=make(d,327680);assert(bo->darwin_handle==newest);darwin_bo_finish(&d,bo);
 bo=make(d,393216);assert(bo->darwin_handle!=newest);darwin_bo_finish(&d,bo);drain(d,r);
 // Rounding on a cache miss uses the rounded extent for every cleanup path.
 bo=make(d,266240);assert(bo->size==266240 && bo->darwin_alloc_size==327680 && native.at(bo->darwin_handle)==327680);
 darwin_bo_finish(&d,bo);drain(d,r);
 fail_method=3;fail_left=1;tu_bo *failed=nullptr;
 assert(darwin_bo_init(&d,nullptr,&failed,266240,0,0,TU_BO_ALLOC_ALLOW_DUMP,nullptr,"map-failure")==VK_ERROR_OUT_OF_DEVICE_MEMORY);
 assert(!failed && native.empty() && ranges.empty());
 // Byte and entry bounds actually evict old complete mappings.
 std::vector<tu_bo *> held;
 for(unsigned i=0;i<12;i++)held.push_back(make(d,DARWIN_CACHE_MAX_BO));
 for(auto b:held){darwin_bo_finish(&d,b);assert(r.cache_bytes<=DARWIN_CACHE_BYTES && r.cache_count<=DARWIN_CACHED_BOS);}held.clear();
 drain(d,r);
 for(unsigned i=0;i<DARWIN_CACHED_BOS+8;i++)held.push_back(make(d,4096));
 for(auto b:held)darwin_bo_finish(&d,b);held.clear();assert(r.cache_count==DARWIN_CACHED_BOS);drain(d,r);
 // Memory-pressure event and allocation failures release retained native ranges.
 bo=make(d,8192);darwin_bo_finish(&d,bo);darwin_memory_pressure.fetch_add(1);assert(darwin_collect_retired(&d)==0 && !r.cache_count);
 bo=make(d,8192);darwin_bo_finish(&d,bo);fail_iova=true;bo=make(d,4096);assert(!r.cache_count);darwin_bo_finish(&d,bo);drain(d,r);
 bo=make(d,8192);darwin_bo_finish(&d,bo);fail_method=2;fail_left=1;bo=make(d,4096);assert(!r.cache_count);darwin_bo_finish(&d,bo);drain(d,r);
 // A partial release returning busy keeps the range and is never reused.
 bo=make(d,16384);bo->map=cpu_view;bo->darwin_token=123;darwin_bo_finish(&d,bo);
 auto old_frees=range_frees;fail_method=4;failure_status=kIOReturnBusy;fail_left=1;
 assert(!darwin_cache_flush(&d,&r));assert(r.cache_count==1 && r.cache[0].releasing && !r.cache[0].bo.mapping && !r.cache[0].bo.token && range_frees==old_frees);
 darwin_retired_bo hit{};assert(!darwin_cache_get(&r,16384,false,false,&hit));drain(d,r);
 // Fatal release failures do not authorize reuse or returning an IOVA.
 for(int method:{100,13,4}){
  bo=make(d,16384);bo->map=cpu_view;bo->darwin_token=123;darwin_bo_finish(&d,bo);old_frees=range_frees;
  fail_method=method;failure_status=7;fail_left=1;darwin_cache_flush(&d,&r);
  assert(r.failure==VK_ERROR_DEVICE_LOST && r.cache_count==1 && r.cache[0].releasing && range_frees==old_frees);
  assert(!darwin_cache_get(&r,16384,false,false,&hit));assert(darwin_collect_retired(&d)==VK_ERROR_DEVICE_LOST);
  // Fixture recovery only: production never clears device loss.
  r.failure=0;fail_left=0;drain(d,r);
 }
 // Real allocation/finish paths race under the same retirement gate; no duplicate
 // live ownership and statistics can be read while the allocator is active.
 std::thread stats([]{for(unsigned i=0;i<10000;i++){uint64_t v[8];tu_darwin_bo_cache_stats(v);tu_darwin_bo_cache_fit_stats(v);}});
 // IOVA and sparse-slot allocation in this small peer are single-threaded; cache
 // get/put concurrency is checked directly without pretending to emulate Mesa.
 std::thread workers[4];
 bo=make(d,8192);darwin_bo_finish(&d,bo);
 for(auto &worker:workers)worker=std::thread([&]{for(unsigned i=0;i<1000;i++){darwin_retired_bo h{};pthread_mutex_lock(&r.lock);if(darwin_cache_get(&r,8192,false,false,&h))assert(darwin_cache_put(&d,&r,&h));pthread_mutex_unlock(&r.lock);}});
 for(auto &worker:workers)worker.join();stats.join();drain(d,r);assert(native.empty() && ranges.empty());
 assert(darwin_cache_fit_stats[0]>0 && darwin_cache_fit_stats[1]>0 && darwin_cache_fit_stats[2]>0 && darwin_cache_fit_stats[3]>0);
 assert(darwin_cache_stats[1]>4000 && darwin_cache_stats[3]>0 && darwin_cache_stats[4]>0 && darwin_cache_stats[5]==0 && darwin_cache_stats[7]==0);
 pthread_mutex_destroy(&r.lock);
}
'''
with tempfile.TemporaryDirectory(prefix='houji-bo-cache-') as temporary:
    path=Path(temporary);cpp=path/'check.cpp'
    cpp.write_text(stubs+'\n#include <vector>\n'+structs+cache+reap+allocate+mapping+finish+main)
    for sanitizer in ('address,undefined','thread'):
        binary=path/sanitizer.replace(',','-')
        subprocess.run(['clang++','-std=c++17','-O1','-g','-pthread','-fsanitize='+sanitizer,str(cpp),'-o',str(binary)],check=True)
        subprocess.run([str(binary)],check=True,timeout=30)
print('PASS: actual BO reuse removes allocation/map RPCs after completed fences; bounded size classes/best fit, retained extent, rights, capacity, pressure, partial release, errors and concurrent cache ownership pass sanitizers; no GPU/FPS claim')
