#include <stdint.h>
#include <assert.h>
#include <stdio.h>
#include <stdarg.h>
#include <mutex>
#include <atomic>
#include <thread>
#include <chrono>
struct Lock {std::mutex mutex;std::atomic<bool>held{false};};
static bool IOLockTryLock(Lock*l){if(!l->mutex.try_lock())return false;l->held=true;return true;}
static void IOLockLock(Lock*l){l->mutex.lock();l->held=true;}
static void IOLockUnlock(Lock*l){assert(l->held);l->held=false;l->mutex.unlock();}
enum NativeAdrenoRingFence {NativeAdrenoRingFenceComplete,NativeAdrenoRingFenceTimeout,NativeAdrenoRingFencePoisoned};
struct Ring {uint32_t seq=10,seen=10;bool poisoned=false;uint32_t lastSubmitted(){return seq;}NativeAdrenoRingFence observeFence(uint32_t f,const void*c,uint32_t us,uint32_t*out){assert(!c && !us && f==seq);*out=seen;return poisoned?NativeAdrenoRingFencePoisoned:seen>=f?NativeAdrenoRingFenceComplete:NativeAdrenoRingFenceTimeout;}};
static uint64_t tick;static uint64_t now(void*){tick+=10;return tick;}
static struct {bool published=false,dying=false;Lock*lock=nullptr;Ring*ring=nullptr;struct{void*cookie=nullptr;uint64_t(*now_us)(void*)=now;}clock;}g;
static bool running=true;static bool native_adreno_board_running(){return running;}
static void IOLog(const char*,...){}
static uint64_t gHoujiPresentSync[9];
extern "C" int native_adreno_present_begin(void){
 __atomic_fetch_add(&gHoujiPresentSync[0],1ull,__ATOMIC_RELAXED);
 if(!g.published || !g.lock || !g.ring)return 0;
 if(!IOLockTryLock(g.lock)){
  __atomic_fetch_add(&gHoujiPresentSync[2],1ull,__ATOMIC_RELAXED);
  uint64_t began=g.clock.now_us(g.clock.cookie);
  IOLockLock(g.lock); /* normal priority-inheriting CPU mutex, no GPU wait */
  uint64_t elapsed=g.clock.now_us(g.clock.cookie)-began;
  __atomic_fetch_add(&gHoujiPresentSync[7],elapsed,__ATOMIC_RELAXED);
  uint64_t old=__atomic_load_n(&gHoujiPresentSync[8],__ATOMIC_RELAXED);
  while(elapsed>old && !__atomic_compare_exchange_n(&gHoujiPresentSync[8],&old,elapsed,false,__ATOMIC_RELAXED,__ATOMIC_RELAXED)){}
 }
 if(g.dying || !native_adreno_board_running()){IOLockUnlock(g.lock);return -1;}
 uint32_t fence=g.ring->lastSubmitted(),seen=0;
 if(fence && g.ring->observeFence(fence,nullptr,0,&seen)!=NativeAdrenoRingFenceComplete){
  __atomic_fetch_add(&gHoujiPresentSync[3],1ull,__ATOMIC_RELAXED);IOLockUnlock(g.lock);return -1;
 }
 __atomic_store_n(&gHoujiPresentSync[4],seen,__ATOMIC_RELAXED);
 __atomic_store_n(&gHoujiPresentSync[5],g.clock.now_us(g.clock.cookie),__ATOMIC_RELAXED);
 __atomic_fetch_add(&gHoujiPresentSync[1],1ull,__ATOMIC_RELAXED);return 1;
}
extern "C" void native_adreno_present_end(void){
 uint64_t elapsed=g.clock.now_us(g.clock.cookie)-__atomic_load_n(&gHoujiPresentSync[5],__ATOMIC_RELAXED);
 uint64_t old=__atomic_load_n(&gHoujiPresentSync[6],__ATOMIC_RELAXED);
 while(elapsed>old && !__atomic_compare_exchange_n(&gHoujiPresentSync[6],&old,elapsed,false,__ATOMIC_RELAXED,__ATOMIC_RELAXED)){}
 IOLockUnlock(g.lock);
}
extern "C" void native_adreno_present_sync_report(void){
 uint64_t v[9];for(unsigned i=0;i<9;i++)v[i]=__atomic_load_n(&gHoujiPresentSync[i],__ATOMIC_RELAXED);
 IOLog("HOUJI PRESENT SYNC: attempts=%llu granted=%llu gate-busy=%llu GPU-pending=%llu observed-fence=%llu max-hold-us=%llu lock-wait-us=%llu max-lock-wait-us=%llu; queued CPU mutex, zero-timeout GPU observation\n",v[0],v[1],v[2],v[3],v[4],v[6],v[7],v[8]);
}

int main(){Lock lock;Ring ring;assert(native_adreno_present_begin()==0);g.published=true;g.lock=&lock;g.ring=&ring;running=false;assert(native_adreno_present_begin()<0&&!lock.held);running=true;ring.seen=9;assert(native_adreno_present_begin()<0&&!lock.held);ring.poisoned=true;assert(native_adreno_present_begin()<0&&!lock.held);ring.poisoned=false;ring.seen=10;
std::atomic<bool>ready{false};std::thread producer([&]{IOLockLock(&lock);ready=true;std::this_thread::sleep_for(std::chrono::milliseconds(20));IOLockUnlock(&lock);});while(!ready)std::this_thread::yield();assert(native_adreno_present_begin()==1&&lock.held);producer.join();native_adreno_present_end();assert(!lock.held&&gHoujiPresentSync[2]==1&&gHoujiPresentSync[7]>0&&gHoujiPresentSync[8]>0);g.dying=true;assert(native_adreno_present_begin()<0&&!lock.held);g.dying=false;ring.seq=0;assert(native_adreno_present_begin()==1&&lock.held);native_adreno_present_end();assert(!lock.held);puts("PASS actual queued gate: a contended CPU issuer releases to the presenter; pending/poison/dying refuse; zero-timeout fence check and balanced copy lock retained. Synthetic mutex/ring peers, not GPU emulation.");}
