#!/usr/bin/env python3
"""Execute the production pending-fence loop with clock, lock and CP peers.

Checks control flow and the mapping qualification, not GPU cache coherence.
"""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BOARD = ROOT / 'kernel/overlay/iokit/Kernel/houji-ufs-root'
source = (BOARD / 'Adreno740/NativeAdrenoPublish.cpp').read_text()
board = (BOARD / 'HoujiGpuNativeSubmit.inc').read_text()


def function(text, signature):
    start = text.index(signature)
    return text[start:text.index('\n}', start) + 2]


unit = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include "NativeAdrenoABI.h"
using IOReturn=int;
constexpr int kIOReturnSuccess=0,kIOReturnTimeout=1,kIOReturnNotReady=2;
constexpr int THREAD_UNINT=0,NSEC_PER_USEC=1000;
#define THREAD_CONTINUE_NULL nullptr
#define IOLog(...) ((void)0)
using event_t=void*;
static bool held=false,armed=false,running=true;
static unsigned locks=0,dispatches=0,sleeps=0,signals=0,pauseUs=0,barriers=0;
static int dispatchError=-1;
static uint64_t clockUs=0,completeAt=300;
static volatile uint64_t native_adreno_wait_outer[5];
static void (*duringSleep)();
static uint64_t now(void*){return clockUs;}
struct {bool dying=false;struct {uint64_t(*now_us)(void*);void *cookie;} clock={now,nullptr};} g;
static bool native_adreno_board_running(){return running;}
static void nativeAdrenoIssuerLock(unsigned){assert(!held);held=true;++locks;}
static void nativeAdrenoIssuerUnlock(){assert(held);held=false;}
static void nativeAdrenoIssuerContext(unsigned,unsigned,const void*,size_t){assert(held);}
static void nativeAdrenoSignalProgressLocked(){assert(held);++signals;}
static void houjiStockReadBarrier(){assert(!held);++barriers;}
enum {HHR_RING=0x620c0000,HHR_SCRATCH=0x620c8000};
alignas(16384) static unsigned char storage[1024*1024];
struct Entry {
 struct {void *cpu;uint64_t physical;} backing={storage,0x92000000};
 struct {uint64_t owned_bytes;} request={sizeof storage};
} entry;
struct {Entry &entry(unsigned i){assert(i==12);return ::entry;}} gHoujiFullMemory;
static bool atOk=true;
static uint64_t par=0;
static bool houjiFullHostAt(uintptr_t va,bool write,uint64_t *out){
 assert(va==(uintptr_t)storage+0xc8104 && !write);*out=par;return atOk;
}
'''
unit += board[board.index('static const volatile uint32_t *houjiSubmitFenceHint='):
              board.index('static int houjiSubmitAcquire(')]
qualify = board[board.index(' {const auto&e=gHoujiFullMemory.entry(12);', board.index('s.adopted=1;')):
                board.index('\n for(s.iteration=', board.index('s.adopted=1;'))]
unit += '\nstatic void qualifyHint(){\n' + qualify + '\n}\n'
unit += source[source.index('static uint32_t nativeAdrenoHintIssued='):
               source.index('/* Query/status/info', source.index('static uint32_t nativeAdrenoHintIssued='))]
unit += r'''
static volatile uint32_t *completion=(volatile uint32_t*)(storage+0xc8104);
struct Core {
 int dispatch(uint32_t method,const void *input,size_t size,void*,size_t,void*){
  assert(held && method==NativeAdrenoMethodWaitFence && size==sizeof(NativeAdrenoAbiWaitFence));
  auto &poll=*static_cast<const NativeAdrenoAbiWaitFence*>(input);assert(!poll.timeout_ns);++dispatches;
  if(dispatchError>=0)return dispatchError;
  if(!poll.fence || poll.fence>UINT32_MAX || poll.fence>nativeAdrenoHintIssued)return 9;
  return *completion>=poll.fence?kIOReturnSuccess:kIOReturnTimeout;
 }
} core;
struct AGXDeviceUserClient {unsigned slot_=0;bool live_=true;Core *core_=&core;} client;
struct NativeAdrenoDispatchClock {void lap(unsigned){}};
static void assert_wait_timeout(event_t event,int kind,uint32_t us,int unit){
 assert(!held && !armed && event==&native_adreno_wait_outer && kind==THREAD_UNINT && unit==NSEC_PER_USEC);
 assert(us && us<=100);armed=true;pauseUs=us;
}
static void thread_block(void*){
 assert(!held && armed);++sleeps;clockUs+=pauseUs;armed=false;
 if(clockUs>=completeAt)*completion=8;
 if(duringSleep)duringSleep();
}
static void reset(){
 assert(!held && !armed);running=true;g.dying=false;client.live_=true;
 locks=dispatches=sleeps=signals=pauseUs=barriers=0;clockUs=0;completeAt=300;
 dispatchError=-1;duringSleep=nullptr;*completion=7;
 for(auto &n:native_adreno_wait_outer)n=0;
 nativeAdrenoHintIssued=8;nativeAdrenoHintEnabled=1;
 houjiSubmitFenceHint=completion;
}
'''
unit += function(source, 'static IOReturn nativeAdrenoWaitFence(AGXDeviceUserClient *connection')
unit += r'''
static IOReturn wait(uint64_t fence=8,uint64_t timeoutNs=1000000){
 NativeAdrenoAbiWaitFence input{fence,timeoutNs};NativeAdrenoDispatchClock timing;
 return nativeAdrenoWaitFence(&client,&input,nullptr,0,timing);
}
int main(){
 // Qualification rejects an AT fault, wrong physical page, cached mapping,
 // inaccessible translation and a word outside the retained allocation.
 par=(UINT64_C(0x44)<<56)|0x920c8000;
 qualifyHint();assert(houjiSubmitFenceHint==completion);
 for(uint64_t bad:{par|1,(UINT64_C(0xff)<<56)|0x920c8000,par+4096}){
  uint64_t good=par;par=bad;houjiSubmitFenceHint=nullptr;qualifyHint();
  assert(!houjiSubmitFenceHint);par=good;
 }
 atOk=false;qualifyHint();assert(!houjiSubmitFenceHint);atOk=true;
 entry.request.owned_bytes=0xc8107;qualifyHint();assert(!houjiSubmitFenceHint);
 entry.request.owned_bytes=sizeof storage;
 reset();assert(wait()==0 && locks==1 && dispatches==1 && sleeps==3 && clockUs==300);
 assert(native_adreno_wait_outer[4]==3 && signals==1 && !held);
 // Observing a completed value is NOT permission to report success. A
 // poisoned/error result from the original locked dispatcher wins.
 reset();*completion=8;dispatchError=12;
 assert(wait()==12 && locks==1 && dispatches==1 && !sleeps);
 reset();*completion=UINT32_MAX;dispatchError=12;
 assert(wait()==12 && locks==1 && dispatches==1);
 reset();*completion=8;dispatchError=kIOReturnTimeout;completeAt=UINT64_MAX;
 assert(wait(8,150000)==kIOReturnTimeout && clockUs==150 && dispatches==3);
 // A stale negative hint is bounded by the request's deadline. Even a
 // one-microsecond slice must eventually execute the locked validation.
 reset();completeAt=UINT64_MAX;
 assert(wait(8,250000)==kIOReturnTimeout && clockUs==250 && pauseUs==50);
 assert(locks==1 && dispatches==1 && sleeps==3 && native_adreno_wait_outer[4]==3);
 reset();completeAt=UINT64_MAX;
 assert(wait(8,1000)==kIOReturnTimeout && clockUs==1 && sleeps==1 && dispatches==1);
 reset();assert(wait(8,0)==kIOReturnTimeout && !sleeps && !barriers && dispatches==1);
 // Invalid, unissued and wider-than-CP fences retain core validation.
 for(uint64_t fence:{UINT64_C(0),UINT64_C(9),UINT64_C(0x100000008)}){
  reset();assert(wait(fence)==9 && !sleeps && !barriers && dispatches==1);
 }
 reset();nativeAdrenoHintEnabled=0;
 assert(wait()==0 && dispatches==4 && sleeps==3 && !native_adreno_wait_outer[4]);
 reset();houjiSubmitFenceHint=nullptr;
 assert(wait()==0 && dispatches==4 && sleeps==3);
 // Provider shutdown revokes the hint; validation under the issuer mutex
 // notices stop. A closed client is never dispatched when completion arrives.
 reset();duringSleep=+[]{g.dying=true;__atomic_store_n(&nativeAdrenoHintEnabled,0u,__ATOMIC_RELEASE);};
 assert(wait()==kIOReturnNotReady && locks==1 && !dispatches && sleeps==1);
 reset();duringSleep=+[]{client.live_=false;};
 assert(wait()==kIOReturnNotReady && locks==1 && !dispatches && sleeps==3);
 reset();duringSleep=+[]{running=false;};
 assert(wait()==kIOReturnNotReady && locks==1 && !dispatches && sleeps==3);
 // A later submission does not change which fence this waiter validates.
 reset();duringSleep=+[]{__atomic_store_n(&nativeAdrenoHintIssued,12u,__ATOMIC_RELEASE);};
 assert(wait()==0 && locks==1 && dispatches==1 && sleeps==3);
 puts("PASS: production fence loop, exact-PA NC qualification, pending lock elision, mandatory locked completion, deadlines, invalid fences, fallback, close and stop");
}
'''
unit = '#include <initializer_list>\n' + unit
with tempfile.TemporaryDirectory(prefix='houji-fence-poll-') as directory:
    path = Path(directory)
    (path / 'test.cpp').write_text(unit)
    subprocess.run(['clang++', '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    '-I', str(BOARD / 'Adreno740'), str(path / 'test.cpp'),
                    '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
