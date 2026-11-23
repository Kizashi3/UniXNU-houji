from pathlib import Path
import subprocess,json
p=Path('${HOUJI_PORT_ROOT}');d=p/'native/display/swap-lifetime-runtime';s=(p/'native/display/SweetFramebuffer.cpp').read_text();a=s.index('IOReturn\nAppleCLCD::swap(');b=s.index('\nbool\nAppleCLCD::present(',a);methods=s[a:b]
pre=r'''#include <cstdint>
#include <cstdio>
#include <cassert>
#include <cstring>
#include <mutex>
#include <condition_variable>
#include <thread>
#include <future>
#include <chrono>
#include <atomic>
#include "HoujiFrameQueue.h"
#define SWEET_FB_SWAP_REC_SIZE 0x46c
#define SWEET_FB_LAYERS 4
#define THREAD_ABORTSAFE 0
#define THREAD_AWAKENED 0
using IOReturn=int;
static constexpr int kIOReturnSuccess=0,kIOReturnBadArgument=1,kIOReturnTimeout=2;
struct IOLock{std::mutex mutex;std::condition_variable condition;};
static thread_local bool held=false;
static void IOLockLock(IOLock*l){l->mutex.lock();held=true;}
static void IOLockUnlock(IOLock*l){held=false;l->mutex.unlock();}
static uint64_t mach_absolute_time(){return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
static void nanoseconds_to_absolutetime(uint64_t ns,uint64_t*out){*out=ns;}
static int IOLockSleepDeadline(IOLock*l,void*,uint64_t deadline,int){std::unique_lock<std::mutex> lock(l->mutex,std::adopt_lock);held=false;auto status=l->condition.wait_until(lock,std::chrono::steady_clock::time_point(std::chrono::nanoseconds(deadline)));held=true;lock.release();return status==std::cv_status::timeout?1:0;}
static void IOLockWakeup(IOLock*l,void*,bool){l->condition.notify_all();}
struct SweetSurface{std::atomic<unsigned> refs{1};void retain(){refs++;}void release(){assert(refs.fetch_sub(1)>1);}};
static SweetSurface surface;
static SweetSurface*sweet_surface_copy(uint32_t id){if(id!=1)return nullptr;surface.retain();return &surface;}
static uint32_t native_adreno_present_capture_fence(){assert(!held);return 77;}
static uint32_t get32(const uint8_t*p,unsigned at){uint32_t v;memcpy(&v,p+at,4);return v;}
static void put32(uint8_t*p,unsigned at,uint32_t v){memcpy(p+at,&v,4);}
static uint64_t houji_fb_queue_full,houji_fb_queue_peak,sweet_fb_swap_count,houji_fb_waits,houji_fb_wait_blocked,houji_fb_wait_timeout,houji_fb_retired;
struct HoujiDisplayFrame{uint8_t rec[SWEET_FB_SWAP_REC_SIZE]{};SweetSurface*surfaces[4]{};uint32_t id=0,fence=0;};
struct AppleCLCD{IOLock lock;IOLock*fLock=&lock;HoujiFrameQueue<HoujiDisplayFrame,8>fFrames;IOReturn swap(const uint8_t*);IOReturn waitSwap(uint32_t,uint64_t);};
'''
a=s.index('  IOLockLock(fb->fLock);\n  bool retired=');b=s.index('\n }',a);retirement=s[a:b]
test=r'''
static void finish(AppleCLCD*fb){IOLockLock(fb->fLock);assert(fb->fFrames.count());auto frame=*fb->fFrames.front();IOLockUnlock(fb->fLock);
RETIREMENT
}
static int submit(AppleCLCD&fb,uint32_t id,uint32_t sid=1){uint8_t rec[SWEET_FB_SWAP_REC_SIZE]{};put32(rec,0x50,id);put32(rec,0x54,sid);put32(rec,0x104,1);return fb.swap(rec);}
int main(){AppleCLCD fb;assert(submit(fb,1)==0);assert(surface.refs==2&&fb.fFrames.front()->fence==77);auto waiter=std::async(std::launch::async,[&]{return fb.waitSwap(1,0);});assert(waiter.wait_for(std::chrono::milliseconds(20))==std::future_status::timeout);/* An unfinished GPU/copy callback does not retire the frame. */assert(!fb.fFrames.complete(1)&&surface.refs==2);finish(&fb);assert(waiter.get()==0&&surface.refs==1&&fb.fFrames.complete(1));
for(unsigned id=2;id<10;id++)assert(submit(fb,id)==0);assert(fb.fFrames.full()&&surface.refs==9);assert(submit(fb,10)==kIOReturnTimeout&&surface.refs==9);assert(!fb.fFrames.complete(9));assert(fb.waitSwap(9,1)==kIOReturnTimeout);for(unsigned id=2;id<10;id++){assert(fb.fFrames.front()->id==id);finish(&fb);}assert(surface.refs==1&&fb.fFrames.count()==0);assert(submit(fb,10,999)==kIOReturnBadArgument&&surface.refs==1);assert(fb.waitSwap(9,0)==0);
HoujiFrameQueue<HoujiDisplayFrame,8> q;HoujiDisplayFrame frame{};frame.id=5;assert(q.push(frame));frame.id=4;assert(q.push(frame));assert(q.finish(5)&&q.complete(5)&&!q.complete(4));assert(q.finish(4)&&q.complete(4));assert(!q.complete(6));HoujiFrameQueue<HoujiDisplayFrame,8> wrap;frame.id=0xfffffffeu;assert(wrap.push(frame)&&wrap.finish(frame.id));frame.id=1;assert(wrap.push(frame)&&!wrap.complete(1));assert(wrap.finish(1)&&wrap.complete(1));
for(unsigned id=10;id<10010;id++){assert(submit(fb,id)==0);assert(!fb.fFrames.complete(id));finish(&fb);assert(surface.refs==1&&fb.fFrames.complete(id));}
printf("PASS actual producer/waiter/retirement: retained references, per-frame fence capture outside display lock, no premature completion, full-queue timeout, FIFO, ID wrap and10000 cycles; synthetic locks/surfaces, no GPU emulation\n");}
'''.replace('RETIREMENT',retirement)
cpp=d/'check-frame-lifetime.cpp';cpp.write_text(pre+methods+test);exe=d/'check-frame-lifetime';subprocess.run(['clang++','-std=c++17','-pthread','-fsanitize=address,undefined','-fno-omit-frame-pointer','-I',str(p/'native/display'),str(cpp),'-o',str(exe)],check=True);r=subprocess.run([str(exe)],capture_output=True,text=True,timeout=15);assert r.returncode==0,(r.returncode,r.stderr);(d/'checks.json').write_text(json.dumps({'status':'PASS','actual_production_methods_extracted':True,'ASAN_UBSAN':True,'stdout':r.stdout,'stderr':r.stderr,'hardware_tested':False},indent=2)+'\n');print(r.stdout)
