#!/usr/bin/env python3
"""Exercise the active board submit gate; register/ring operations are peers."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / 'kernel/overlay/iokit/Kernel/houji-ufs-root/HoujiGpuNativeProvider.inc').read_text()
start = source.index('extern "C" IOReturn native_adreno_board_prepare_submit(void){')
function = source[start:source.index('\nstatic bool houjiProviderTlbValue', start)]
publish = (ROOT / 'kernel/overlay/iokit/Kernel/houji-ufs-root/Adreno740/NativeAdrenoPublish.cpp').read_text()
present_start = publish.index('extern "C" int native_adreno_present_begin_frame(uint32_t desired){')
present = publish[present_start:publish.index('extern "C" void native_adreno_present_end', present_start)]
signal_start = publish.index('static void nativeAdrenoSignalProgressLocked(void) {')
signal = publish[signal_start:publish.index('\n}\n', signal_start)+3]
unit = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
using IOReturn = int;
constexpr int kIOReturnSuccess=0, kIOReturnNotReady=1, kIOReturnTimeout=2;
static bool running=true;
static unsigned drains=0;
static int drainResult=0;
static bool native_adreno_board_running(){return running;}
static IOReturn native_adreno_board_quiesce(){++drains;return drainResult;}
struct State {uint64_t generation=7;} state;
struct {struct {State *state;} binding;} gHoujiVm={{&state}};
struct PollSubmit {
    unsigned calls=0;int result=kIOReturnTimeout;
    int waitAll(int*,unsigned timeout){assert(timeout==0);++calls;return result;}
};
struct {PollSubmit submit;int clock;} gHoujiApi;
'''
unit += function
unit += r'''
constexpr int NativeAdrenoRingFenceComplete=0, NativeAdrenoRingFenceTimeout=1,
              NativeAdrenoRingFencePoisoned=2;
using event_t=void*;
using wait_result_t=int;
constexpr int THREAD_UNINT=0, NSEC_PER_USEC=1000, THREAD_AWAKENED=1, THREAD_TIMED_OUT=2;
#define THREAD_CONTINUE_NULL nullptr
static uint64_t gHoujiPresentSync[14],timeUs;
static uint32_t gHoujiPresentProgress;
static bool held=false,armed=false,signalled=false,onUnlock=false;
static unsigned sleepCalls=0,signalCalls=0,waitUs=0;
struct Step {uint32_t seen,tail;bool stop=false;unsigned delay=50;};
static Step steps[4];
static unsigned stepCount=0,stepIndex=0;
static void applyStep();
static bool IOLockTryLock(void*){assert(!held);held=true;return true;}
static void IOLockLock(void*){assert(!held);held=true;}
static void IOLockUnlock(void*){
 assert(held);held=false;
 if(armed && onUnlock){onUnlock=false;applyStep();}
}
static uint64_t now(void*){return ++timeUs;}
struct PresentRing {
 uint32_t last=8,seen=7;bool poisoned=false;
 uint32_t lastSubmitted(){assert(held);return last;}
 uint32_t completedFence(){assert(held);return seen;}
 int observeFence(uint32_t f,void*,unsigned timeout,uint32_t *out){
  assert(held && !timeout);*out=seen;
  return poisoned?NativeAdrenoRingFencePoisoned:seen>=f?NativeAdrenoRingFenceComplete:NativeAdrenoRingFenceTimeout;
 }
} presentRing;
struct {
 bool published=true;void *lock=(void*)1;PresentRing *ring=&presentRing;
 bool dying=false;struct {uint64_t(*now_us)(void*);void *cookie;} clock={now,nullptr};
} g;
static void assert_wait_timeout(event_t e,int type,uint32_t us,int unit){
 assert(held && !armed && e==&gHoujiPresentProgress && type==THREAD_UNINT && unit==NSEC_PER_USEC);
 assert(us && us<=8333);armed=true;signalled=false;waitUs=us;
}
static void thread_wakeup(event_t e){
 assert(held && e==&gHoujiPresentProgress);++signalCalls;
 if(armed)signalled=true;
}
static wait_result_t thread_block(void*){
 assert(!held && armed);++sleepCalls;
 if(!signalled && stepIndex<stepCount)applyStep();
 bool woke=signalled;
 if(!woke)timeUs+=waitUs;
 armed=false;signalled=false;return woke?THREAD_AWAKENED:THREAD_TIMED_OUT;
}
'''
unit += r'''
static void nativeAdrenoIssuerLock(unsigned){IOLockLock(g.lock);}
static void nativeAdrenoIssuerUnlock(){IOLockUnlock(g.lock);}
struct {void subject(uint64_t){} void context(unsigned,unsigned,uint64_t){}} nativeAdrenoIssuerTrace;
static bool nativeAdrenoIssuerTryLock(unsigned){return IOLockTryLock(g.lock);}
'''
unit += signal
unit += r'''
static void applyStep(){
 assert(!held && stepIndex<stepCount);
 auto s=steps[stepIndex++];timeUs+=s.delay;
 IOLockLock(g.lock);presentRing.seen=s.seen;presentRing.last=s.tail;g.dying=s.stop;
 nativeAdrenoSignalProgressLocked();IOLockUnlock(g.lock);
}
static void resetPresent(){
 assert(!held && !armed);presentRing={};g.dying=false;g.published=true;running=true;
 timeUs=0;stepCount=stepIndex=sleepCalls=signalCalls=waitUs=0;onUnlock=false;
 gHoujiPresentProgress=0;for(auto &v:gHoujiPresentSync)v=0;
}
'''
unit += present
unit += r'''
int main(){
    // Pending non-coherent GPU writes must never reach cache publication or
    // a blocking board drain. The outer caller can sleep with its lock free.
    assert(native_adreno_board_prepare_submit()==kIOReturnTimeout && !drains);
    assert(gHoujiApi.submit.calls==1);
    gHoujiApi.submit.result=9;
    assert(native_adreno_board_prepare_submit()==9 && !drains);
    gHoujiApi.submit.result=0;drainResult=8;
    assert(native_adreno_board_prepare_submit()==8 && drains==1);
    drainResult=0;
    assert(native_adreno_board_prepare_submit()==kIOReturnSuccess && drains==2);
    state.generation=8;
    assert(native_adreno_board_prepare_submit()==kIOReturnSuccess && drains==3);
    gHoujiVm.binding.state=nullptr;
    assert(native_adreno_board_prepare_submit()==kIOReturnNotReady && drains==3);
    gHoujiVm.binding.state=&state;running=false;
    assert(native_adreno_board_prepare_submit()==kIOReturnNotReady && drains==3);
    running=true;
    // No observer: a bounded sleep expires; pending writes cannot be copied.
    resetPresent();
    assert(native_adreno_present_begin_frame(7)==-1 && !held);
    assert(sleepCalls==1 && gHoujiPresentSync[11]==1 && timeUs>=8333);
    // Observed completion wakes the same accepted frame without a vsync tick.
    resetPresent();steps[0]={8,8};stepCount=1;
    assert(native_adreno_present_begin_frame(7)==1 && held);
    assert(sleepCalls==1 && gHoujiPresentSync[10]==1 && timeUs<100);
    IOLockUnlock(g.lock);
    // Complete between dropping the issuer mutex and actually blocking:
    // wait registration must already exist, otherwise this wake is lost.
    resetPresent();steps[0]={8,8};stepCount=1;onUnlock=true;
    assert(native_adreno_present_begin_frame(7)==1 && held);
    assert(sleepCalls==1 && signalCalls==1 && timeUs<100);
    IOLockUnlock(g.lock);
    // Newer work can arrive while sleeping. The old producer completion is
    // insufficient: the new tail must also complete before granting a copy.
    resetPresent();steps[0]={8,10};steps[1]={10,10};stepCount=2;
    assert(native_adreno_present_begin_frame(7)==1 && held);
    assert(sleepCalls==2 && gHoujiPresentSync[4]==10 && stepIndex==2);
    // Repeated polling of an unchanged fence must not manufacture wakeups.
    unsigned before=signalCalls;nativeAdrenoSignalProgressLocked();
    assert(signalCalls==before);IOLockUnlock(g.lock);
    // A poisoned observation is a failure, never a timeout or completion.
    resetPresent();presentRing.poisoned=true;
    assert(native_adreno_present_begin_frame(7)==-1 && !held && !sleepCalls);
    // Stop while asleep still releases the issuer mutex and never grants.
    resetPresent();steps[0]={8,8,true};stepCount=1;
    assert(native_adreno_present_begin_frame(7)==-1 && !held && !gHoujiPresentSync[1]);
    // Already complete: no event wait and the copy retains the issuer gate.
    resetPresent();presentRing.seen=8;
    assert(native_adreno_present_begin_frame(7)==1 && held && !sleepCalls);
    IOLockUnlock(g.lock);
    // Partial observations do not renew the original wait budget forever.
    resetPresent();presentRing.last=12;steps[0]={8,12,false,3000};steps[1]={9,12,false,3000};steps[2]={10,12,false,3000};stepCount=3;
    assert(native_adreno_present_begin_frame(7)==-1 && !held && sleepCalls==3);
    assert(timeUs>=8333 && timeUs<9100 && !gHoujiPresentSync[1]);
    puts("PASS: active board gate polls without blocking; pending writes defer publication; idle work still takes the ownership/VM proof");
    puts("PASS: actual completion event wait, lost-wake window, new tail, timeout budget, poisoned ring, stop and unchanged-fence deduplication; issuer lock held only for observation/copy");
}
'''
with tempfile.TemporaryDirectory(prefix='houji-board-gate-') as directory:
    tmp = Path(directory)
    (tmp / 'gate.cpp').write_text(unit)
    subprocess.run(['clang++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(tmp / 'gate.cpp'),
                    '-o', str(tmp / 'gate')], check=True)
    subprocess.run([str(tmp / 'gate')], check=True, timeout=10)
