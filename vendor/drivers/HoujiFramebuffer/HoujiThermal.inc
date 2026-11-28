/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Read-only TSENS v2 monitoring for SM8650/houji. The three TM windows,
 * sensor assignments and GPU 95 C / 5 C trip come from houji's FDT.
 * CPU 95 C is a conservative software cap below the 108/110 C CPU trips.
 * This does not implement PMIC skin/battery sensing or emergency shutdown.
 */
#include <IOKit/IOMemoryDescriptor.h>
#include "HoujiThermalPolicy.h"
namespace HoujiThermal {
static IOMemoryMap *maps[3];
static uintptr_t bases[3];
struct Group {
    unsigned bank, mask, levels, cap; int temperature; bool valid; HoujiThermalPolicy policy;
    unsigned samples, invalid, hot, retries, invalidMask, invalidRaw, peak, maxReads;
};
// EPSS domains: A520(0,1), A720(5,6), X4(7), A720(2,3,4), then GPU.
static Group groups[5] = {
    {1,0x0030,0,1,0,false,{}}, {0,0x7800,0,1,0,false,{}},
    {1,0x000e,0,1,0,false,{}}, {0,0x07e0,0,1,0,false,{}},
    {2,0x01fe,12,1,0,false,{}}
};
static uint32_t started;
static uint64_t nowUs() {
    uint64_t ns=0;absolutetime_to_nanoseconds(mach_absolute_time(),&ns);return ns/1000;
}
static bool temperature(Group &g, int *out) {
    if (!bases[g.bank]) return false;
    int hottest=-400;const uint64_t deadline=nowUs()+20000;
    for(unsigned s=0;s<16;++s) if(g.mask&(1u<<s)) {
        int t=0;unsigned waits=0;HoujiTsensSample sample={};
        auto read=[&](){uint32_t raw=*(volatile uint32_t *)(bases[g.bank]+0xa0+4*s);
            __asm__ volatile("dmb oshld" ::: "memory");return raw;};
        auto pause=[&](){if(++waits<=32)IODelay(1);else IOSleep(1);};
        bool valid=houjiTsensRead(read,nowUs,pause,deadline,&t,&sample);
        if(sample.reads>1)__atomic_fetch_add(&g.retries,1u,__ATOMIC_RELAXED);
        if(sample.reads>__atomic_load_n(&g.maxReads,__ATOMIC_RELAXED))
            __atomic_store_n(&g.maxReads,sample.reads,__ATOMIC_RELAXED);
        // An incomplete group cannot certify the hottest junction.
        if(!valid) {
            __atomic_fetch_or(&g.invalidMask,1u<<s,__ATOMIC_RELAXED);
            __atomic_store_n(&g.invalidRaw,sample.raw,__ATOMIC_RELAXED);return false;
        }
        if(t>hottest) hottest=t;
    }
    *out=hottest;return true;
}
static void worker(void *,wait_result_t) {
    thread_set_thread_name(current_thread(),"houji-thermal");
    for(unsigned bank=0;bank<3;++bank) {
        IODeviceMemory *m=IODeviceMemory::withRange(0xc228000ULL+bank*0x1000,0x1000);
        maps[bank]=m?m->map(kIOMapAnywhere|kIOMapInhibitCache):nullptr;
        if(m)m->release();
        bases[bank]=maps[bank]?maps[bank]->getVirtualAddress():0;
    }
    for(unsigned sample=0;;++sample) {
        for(unsigned i=0;i<5;++i) {
            auto &g=groups[i];int t=0;bool ok=temperature(g,&t);
            unsigned levels=__atomic_load_n(&g.levels,__ATOMIC_ACQUIRE);
            if(!levels)continue;
            __atomic_fetch_add(&g.samples,1u,__ATOMIC_RELAXED);
            if(!ok)__atomic_fetch_add(&g.invalid,1u,__ATOMIC_RELAXED);
            if(ok && t>=950)__atomic_fetch_add(&g.hot,1u,__ATOMIC_RELAXED);
            if(ok && t>0 && (unsigned)t>__atomic_load_n(&g.peak,__ATOMIC_RELAXED))
                __atomic_store_n(&g.peak,(unsigned)t,__ATOMIC_RELAXED);
            unsigned cap=houjiThermalChoose(&g.policy,levels,ok,t,950);
            if(!sample || ok!=g.valid || cap!=g.cap || sample%100==0)
                IOLog("HOUJI THERMAL: group=%u valid=%u deciC=%d cap=%u/%u; TSENS read-only, junction policy\n",i,ok,t,cap,levels);
            __atomic_store_n(&g.valid,ok,__ATOMIC_RELEASE);
            __atomic_store_n(&g.temperature,t,__ATOMIC_RELAXED);
            __atomic_store_n(&g.cap,cap,__ATOMIC_RELEASE);
        }
        IOSleep(100);
    }
}
static void start() {
    if(__atomic_exchange_n(&started,1u,__ATOMIC_ACQ_REL))return;
    thread_t t;
    if(kernel_thread_start(worker,nullptr,&t)==KERN_SUCCESS)thread_deallocate(t);
    else IOLog("HOUJI THERMAL: worker unavailable; CPU/GPU caps remain at lowest OPP\n");
}
}
extern "C" void houji_thermal_start(void) { HoujiThermal::start(); }
extern "C" void houji_thermal_cpu_levels(unsigned domain,unsigned levels) {
    if(domain<4 && levels)__atomic_store_n(&HoujiThermal::groups[domain].levels,levels,__ATOMIC_RELEASE);
}
extern "C" unsigned houji_thermal_cpu_cap(unsigned domain) {
    return domain<4?__atomic_load_n(&HoujiThermal::groups[domain].cap,__ATOMIC_ACQUIRE):1;
}
extern "C" unsigned houji_thermal_gpu_cap(void) {
    return __atomic_load_n(&HoujiThermal::groups[4].cap,__ATOMIC_ACQUIRE);
}
/* The kernel message ring can wrap before recovery. Preserve these cached
 * facts in the fixed snapshot prefix; no MMIO, locks or filesystem access.
 */
extern "C" unsigned houji_thermal_snapshot(char *out,unsigned capacity) {
    if(!out || !capacity)return 0;unsigned used=0;out[0]=0;
    for(unsigned i=0;i<5 && used<capacity-1;++i) {
        auto &g=HoujiThermal::groups[i];
        auto load=[](const unsigned *v){return __atomic_load_n(v,__ATOMIC_RELAXED);};
        int n=snprintf(out+used,capacity-used,
            "HOUJI THERMAL SNAPSHOT: group=%u valid=%u deciC=%d peak=%u cap=%u/%u samples=%u invalid=%u hot=%u retries=%u max-reads=%u invalid-mask=%x last-invalid=%x\n",
            i,__atomic_load_n(&g.valid,__ATOMIC_ACQUIRE),__atomic_load_n(&g.temperature,__ATOMIC_RELAXED),
            load(&g.peak),load(&g.cap),load(&g.levels),load(&g.samples),load(&g.invalid),load(&g.hot),
            load(&g.retries),load(&g.maxReads),load(&g.invalidMask),load(&g.invalidRaw));
        if(n>0)used+=(unsigned)n<capacity-used?(unsigned)n:capacity-used-1;
    }
    return used;
}
