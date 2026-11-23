#include <stdint.h>
#include <assert.h>
#include <stdio.h>
#include <stdarg.h>
struct Lock {bool held=false;};
static bool IOLockTryLock(Lock*l){if(l->held)return false;l->held=true;return true;}
static void IOLockUnlock(Lock*l){assert(l->held);l->held=false;}
enum NativeAdrenoRingFence {NativeAdrenoRingFenceComplete,NativeAdrenoRingFenceTimeout,NativeAdrenoRingFencePoisoned};
struct Ring {uint32_t seq=10,seen=10;bool poisoned=false;uint32_t lastSubmitted(){return seq;}NativeAdrenoRingFence observeFence(uint32_t f,const void*c,uint32_t us,uint32_t*out){assert(!c && !us && f==seq);*out=seen;return poisoned?NativeAdrenoRingFencePoisoned:seen>=f?NativeAdrenoRingFenceComplete:NativeAdrenoRingFenceTimeout;}};
static uint64_t tick;static uint64_t now(void*){tick+=10;return tick;}
static struct {bool published=false,dying=false;Lock*lock=nullptr;Ring*ring=nullptr;struct{void*cookie=nullptr;uint64_t(*now_us)(void*)=now;}clock;}g;
static bool running=true;static bool native_adreno_board_running(){return running;}
static void IOLog(const char*,...){}
static uint64_t gHoujiPresentSync[7];
extern "C" int native_adreno_present_begin(void){
 __atomic_fetch_add(&gHoujiPresentSync[0],1ull,__ATOMIC_RELAXED);
 if(!g.published || !g.lock || !g.ring)return 0;
 if(!IOLockTryLock(g.lock)){__atomic_fetch_add(&gHoujiPresentSync[2],1ull,__ATOMIC_RELAXED);return -1;}
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
 uint64_t v[7];for(unsigned i=0;i<7;i++)v[i]=__atomic_load_n(&gHoujiPresentSync[i],__ATOMIC_RELAXED);
 IOLog("HOUJI PRESENT SYNC: attempts=%llu granted=%llu gate-busy=%llu GPU-pending=%llu observed-fence=%llu max-hold-us=%llu; no sleep, reference retirement or display MMIO\n",v[0],v[1],v[2],v[3],v[4],v[6]);
}
int main(){Lock lock;Ring ring;assert(native_adreno_present_begin()==0);g.published=true;g.lock=&lock;g.ring=&ring;running=false;assert(native_adreno_present_begin()<0 && !lock.held);running=true;lock.held=true;assert(native_adreno_present_begin()<0 && lock.held);lock.held=false;ring.seen=9;assert(native_adreno_present_begin()<0 && !lock.held);ring.poisoned=true;assert(native_adreno_present_begin()<0 && !lock.held);ring.poisoned=false;ring.seen=10;assert(native_adreno_present_begin()==1 && lock.held);assert(native_adreno_present_begin()<0 && lock.held);native_adreno_present_end();assert(!lock.held && gHoujiPresentSync[6]==10);g.dying=true;assert(native_adreno_present_begin()<0 && !lock.held);g.dying=false;ring.seq=0;assert(native_adreno_present_begin()==1 && lock.held);native_adreno_present_end();assert(!lock.held);puts("PASS actual extracted gate: unpublished/busy/pending/poison/dying refuse as expected; real completion holds issuer through copy; balanced release; no wait/ref retirement (synthetic peer, not GPU emulation)");}