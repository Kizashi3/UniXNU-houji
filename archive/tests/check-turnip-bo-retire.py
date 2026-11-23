#!/usr/bin/env python3
"""Run the actual BO finish function with a deterministic slot-reuse schedule."""
from pathlib import Path
import subprocess

P = Path(__file__).resolve().parents[1]
SOURCE = P / 'native/gpu/turnip-bo-lifetime-runtime'
OUT = P / 'out/upstream-comparison-20261030/bo-retire-regression'
OUT.mkdir(exist_ok=True)

STUBS = r'''
#include <atomic>
#include <cassert>
#include <cstring>
#include <thread>
#include <pthread.h>
using VkResult=int;
constexpr int VK_SUCCESS=0, DARWIN_RETIRED_BOS=8;
struct tu_bo {unsigned gem_handle;int refcnt;void *map;unsigned darwin_token,darwin_handle;unsigned long long iova,size;};
struct Entry {unsigned handle;unsigned long long iova,size;void *map;unsigned token,fence;};
struct darwin_retire_state {pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;unsigned count=0,head=0,pressure_waits=0,enqueued=0;int failure=0;Entry entries[8]{};};
struct tu_device {int dma_bo_lock,vk;void *darwin_retire;};
struct {pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;unsigned last_fence=1;} dw;
static std::atomic<bool> returned{false},reused{false};
static pthread_mutex_t *retire_mutex;
static std::thread::id finisher;
static void u_rwlock_rdlock(int*){}
static void u_rwlock_rdunlock(int*){}
static bool p_atomic_dec_zero(int *p){return --*p==0;}
static void tu_debug_bos_del(tu_device*,tu_bo*){}
static void tu_dump_bo_del(tu_device*,tu_bo*){}
static VkResult darwin_wait_idle(tu_device*){return 0;}
static int vk_device_set_lost(int*,const char*){return -1;}
#define TU_RMV(...) do {} while(0)
static void darwin_reap_locked(tu_device*,darwin_retire_state *r){
 if(r->count){--r->count;returned.store(true,std::memory_order_release);}
}
// Force the allocator to win the exact race after the retire unlock. The
// original and repaired function bodies below are taken verbatim from source.
static void scheduled_unlock(pthread_mutex_t *m){
 pthread_mutex_unlock(m);
 if(m==retire_mutex && std::this_thread::get_id()==finisher && returned.load())
  while(!reused.load(std::memory_order_acquire))std::this_thread::yield();
}
#define pthread_mutex_unlock scheduled_unlock
'''

MAIN = r'''
#undef pthread_mutex_unlock
int main(){
 darwin_retire_state retire;retire_mutex=&retire.lock;
 tu_device dev{};dev.darwin_retire=&retire;
 tu_bo bo{};bo.gem_handle=7;bo.darwin_handle=7;bo.refcnt=1;bo.iova=0x12340000;bo.size=4096;
 finisher=std::this_thread::get_id();
 std::thread allocator([&]{
  while(!returned.load(std::memory_order_acquire))std::this_thread::yield();
  pthread_mutex_lock(retire_mutex);
  bo.gem_handle=0xbeef;bo.darwin_handle=0xbeef;bo.refcnt=1;bo.iova=0x40000000;bo.size=16384;
  reused.store(true,std::memory_order_release);
  pthread_mutex_unlock(retire_mutex);
 });
 darwin_bo_finish(&dev,&bo);allocator.join();
 return bo.gem_handle==0xbeef && bo.iova==0x40000000 && bo.size==16384 ? 0:1;
}
'''


def function(text):
    start = text.index('darwin_bo_finish(struct tu_device *dev, struct tu_bo *bo)')
    end = text.index('/* ---- submissions ---- */', start)
    return 'static void\n' + text[start:end]


for name, expected in [('before-tu_knl_darwin.cc', 1), ('tu_knl_darwin.cc', 0)]:
    unit = OUT / (name + '.cpp')
    binary = OUT / name
    unit.write_text(STUBS + function((SOURCE / name).read_text()) + MAIN)
    subprocess.run(['clang++', '-std=c++17', '-O2', '-pthread', str(unit), '-o', str(binary)], check=True)
    result = subprocess.run([str(binary)], timeout=10)
    assert result.returncode == expected, (name, result.returncode, expected)
print('PASS: old function destroys the reused slot; repaired actual function preserves it under the same schedule')
