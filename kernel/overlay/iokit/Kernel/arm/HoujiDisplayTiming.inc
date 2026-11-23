/* SPDX-License-Identifier: MIT */
// Optional one-shot diagnostic, after the first completed GUI copy. The
// device driver keeps ownership of display modes, interrupts and scanout.
#include "HoujiDisplayTiming.h"
namespace HoujiDisplayTiming {
static Snapshot cached;
static unsigned state;
static uint32_t readRegister(void *context,uint32_t offset) {
    uint32_t value=static_cast<volatile uint32_t *>(context)[offset/4];
    __asm__ volatile("dmb oshld":::"memory");return value;
}
static void sampleThread(void *,wait_result_t) {
    thread_set_thread_name(current_thread(),"houji-panel-timing");
    IODeviceMemory *memory=IODeviceMemory::withRange(Base,Bytes);
    IOMemoryMap *map=memory?memory->map(kIOMapAnywhere|kIOMapInhibitCache):nullptr;
    OSSafeReleaseNULL(memory);
    if(!map){__atomic_store_n(&state,2u,__ATOMIC_RELEASE);return;}
    void *base=reinterpret_cast<void *>(map->getVirtualAddress());
    Snapshot result{};readConfiguration(result,base,readRegister);
    for(unsigned i=0;i<5;++i) {
        uint64_t ns=0;absolutetime_to_nanoseconds(mach_absolute_time(),&ns);
        readCounts(result,i,base,readRegister,ns/1000);
        if(i!=4)IOSleep(1000);
    }
    map->release();cached=result;
    __atomic_store_n(&state,3u,__ATOMIC_RELEASE);
}
static void start() {
    int enabled=0;
    if(!PE_parse_boot_argn("-ht",&enabled,sizeof(enabled)) || enabled!=1)return;
    unsigned expected=0;
    if(!__atomic_compare_exchange_n(&state,&expected,1u,false,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return;
    thread_t thread=THREAD_NULL;
    if(kernel_thread_start(sampleThread,nullptr,&thread)==KERN_SUCCESS)thread_deallocate(thread);
    else __atomic_store_n(&state,4u,__ATOMIC_RELEASE);
}
}
extern "C" unsigned houji_display_timing_snapshot(char *out,unsigned capacity) {
    const unsigned state=__atomic_load_n(&HoujiDisplayTiming::state,__ATOMIC_ACQUIRE);
    return HoujiDisplayTiming::format(HoujiDisplayTiming::cached,state,out,capacity);
}
