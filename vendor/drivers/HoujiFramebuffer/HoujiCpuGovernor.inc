/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Houji EPSS thermal governor.  Four CPU domains, fps25 interaction
 * targets, and a temperature-first limit shared by all domains.  The
 * governor only votes factory LUT indices; voltage and PLL control stay
 * with the EPSS hardware.  It never runs unless houji_gov=1.
 */
#include <IOKit/IOLib.h>
#include <IOKit/IOMemoryDescriptor.h>

extern "C" uint64_t houji_cpu_idle_mach(int cpu);
extern "C" int houji_thermal_group_temp(unsigned group);
extern "C" unsigned houji_thermal_group_valid(unsigned group);

namespace HoujiCpuGovernor {
constexpr unsigned kDomains = 4;
constexpr unsigned kRows = 40;
constexpr unsigned kCounts[4] = {2, 2, 1, 3};
constexpr unsigned kCpuMap[8] = {0, 0, 3, 3, 3, 1, 1, 2};
constexpr uint32_t kTargetKhz[4] = {2112000, 2880000, 2880000, 2880000};
constexpr uint32_t kCapKhz[4] = {2265600, 2956800, 3302400, 3148800};

struct Domain {
    IOMemoryMap *map;
    uintptr_t va;
    uint32_t khz[kRows];
    uint8_t index[kRows];
    unsigned n, cur, low, bad, changes;
};

static Domain d[kDomains];
static uint64_t idle[8];
static uint32_t enabled, dry, started;
static unsigned tick;

static uint32_t read32(Domain &w, unsigned off) {
    return *(volatile uint32_t *)(w.va + off);
}

static bool init(unsigned id) {
    auto &w = d[id];
    IODeviceMemory *m = IODeviceMemory::withRange(0x17d91000ULL + id * 0x1000, 0x1000);
    w.map = m ? m->map(kIOMapAnywhere | kIOMapInhibitCache) : nullptr;
    if (m) m->release();
    w.va = w.map ? w.map->getVirtualAddress() : 0;
    if (!w.va || !(read32(w, 0) & 1)) {
        IOLog("HOUJI GOV: domain %u EPSS window unavailable\n", id);
        return false;
    }

    uint32_t prev = 0;
    for (unsigned i = 0; i < kRows; ++i) {
        uint32_t raw = read32(w, 0x100 + i * 4);
        uint32_t src = raw >> 30;
        uint32_t khz = (raw & 0xff) * 19200;
        if (!src) break;
        if (khz < 300000 || khz > 4000000) return false;
        if (i && khz == prev) break;
        if (i && khz < prev) return false;
        prev = khz;
        if (khz > kCapKhz[id]) continue;
        w.khz[w.n] = khz;
        w.index[w.n] = (uint8_t)i;
        ++w.n;
    }
    if (w.n < 2) return false;

    w.cur = w.n - 1;
    uint32_t request = read32(w, 0x320);
    for (unsigned i = 0; i < w.n; ++i) {
        if (w.index[i] == request) w.cur = i;
    }
    IOLog("HOUJI GOV INIT: d=%u rows=%u min=%u max=%u cur=%u request=%u control=%x\n",
        id, w.n, w.khz[0], w.khz[w.n - 1], w.khz[w.cur], request, read32(w, 0xb0));
    return true;
}

static bool vote(unsigned id, unsigned at) {
    auto &w = d[id];
    if (w.bad || at >= w.n || !(read32(w, 0) & 1)) return false;
    unsigned cores = (read32(w, 0xb0) & 1) ? kCounts[id] : 1;
    for (unsigned c = 0; c < cores; ++c) {
        *(volatile uint32_t *)(w.va + 0x320 + c * 4) = w.index[at];
    }
    __asm__ volatile("dsb sy" ::: "memory");
    for (unsigned c = 0; c < cores; ++c) {
        uint32_t got = read32(w, 0x320 + c * 4);
        if (got != w.index[at]) {
            w.bad = 1;
            IOLog("HOUJI GOV FAIL: d=%u vote=%u readback=%u core=%u; writes disabled\n",
                id, w.index[at], got, c);
            return false;
        }
    }
    if (w.cur != at) ++w.changes;
    w.cur = at;
    return true;
}

static unsigned choose(unsigned id, unsigned limit, unsigned busy, unsigned globalBusy) {
    auto &w = d[id];
    uint32_t maxKhz = w.khz[w.n - 1];
    uint32_t capKhz = (uint32_t)((uint64_t)maxKhz * limit / 1000);
    uint32_t target = kTargetKhz[id];
    if (target > capKhz) target = capKhz;

    if (busy < 120 && globalBusy < 350) {
        target = w.khz[0];
    } else if (busy < 900) {
        uint32_t demand = (uint32_t)((uint64_t)kTargetKhz[id] * busy / 800);
        if (demand < target) target = demand;
        uint32_t floor = (uint32_t)((uint64_t)kTargetKhz[id] * 55 / 100);
        if (busy > 250 && target < floor) target = floor;
    }
    if (globalBusy > 550) {
        uint32_t floor = (uint32_t)((uint64_t)kTargetKhz[id] * 65 / 100);
        if (target < floor) target = floor;
    }

    unsigned at = 0;
    while (at + 1 < w.n && w.khz[at + 1] <= target) ++at;
    if (at > w.cur) return at;
    if (at == w.cur) {
        w.low = 0;
        return at;
    }
    if (limit < 800) return at; /* thermal fall is immediate */
    if (++w.low < 4) return w.cur;
    w.low = 0;
    return at;
}

static unsigned busyPermille(unsigned id, uint64_t dt) {
    unsigned best = 0;
    for (unsigned c = 0; c < 8; ++c) {
        if (kCpuMap[c] != id) continue;
        uint64_t v = houji_cpu_idle_mach((int)c);
        uint64_t old = idle[c];
        idle[c] = v;
        if (v == UINT64_MAX || old == UINT64_MAX || v < old) continue;
        uint64_t di = v - old;
        if (di > dt) di = dt;
        unsigned b = (unsigned)(((dt - di) * 1000) / dt);
        if (b > best) best = b;
    }
    return best;
}

static unsigned thermalLimit(unsigned temp, int *integral) {
    int error = 820 - (int)temp;
    int acc = *integral + error;
    if (acc < -4000) acc = -4000;
    if (acc > 2000) acc = 2000;
    *integral = acc;
    int limit = 1000 + error * 20 + acc / 4;
    if (limit < 250) limit = 250;
    if (limit > 1000) limit = 1000;
    if (temp >= 950 && limit > 450) limit = 450;
    if (temp >= 1000 && limit > 300) limit = 300;
    if (temp >= 1050 && limit > 200) limit = 200;
    return (unsigned)limit;
}

static void worker(void *, wait_result_t) {
    thread_set_thread_name(current_thread(), "houji-cpu-gov");
    IOSleep(3000);
    for (unsigned id = 0; id < kDomains; ++id) {
        if (!init(id)) return;
    }

    for (unsigned c = 0; c < 8; ++c) idle[c] = houji_cpu_idle_mach((int)c);
    uint64_t last = mach_absolute_time();
    int integral = 0;
    unsigned filtered = 420;

    for (;;) {
        IOSleep(100);
        uint64_t now = mach_absolute_time();
        uint64_t dt = now - last;
        last = now;
        if (!dt) continue;

        int temp = -400;
        for (unsigned g = 0; g < 5; ++g) {
            if (!houji_thermal_group_valid(g)) continue;
            int t = houji_thermal_group_temp(g);
            if (t > temp) temp = t;
        }
        if (temp < 0) temp = 420;
        filtered = (filtered * 3 + (unsigned)temp) / 4;
        unsigned limit = thermalLimit(filtered, &integral);

        unsigned busy[kDomains], globalBusy = 0;
        for (unsigned id = 0; id < kDomains; ++id) {
            busy[id] = busyPermille(id, dt);
            if (busy[id] > globalBusy) globalBusy = busy[id];
        }
        for (unsigned id = 0; id < kDomains; ++id) {
            unsigned at = choose(id, limit, busy[id], globalBusy);
            if (!dry && at != d[id].cur) vote(id, at);
        }

        if ((++tick % 50) == 0) {
            IOLog("HOUJI GOV: temp=%d filt=%u limit=%u busy=%u,%u,%u,%u freq=%u,%u,%u,%u dry=%u\n",
                temp, filtered, limit, busy[0], busy[1], busy[2], busy[3],
                d[0].khz[d[0].cur] / 1000, d[1].khz[d[1].cur] / 1000,
                d[2].khz[d[2].cur] / 1000, d[3].khz[d[3].cur] / 1000, dry);
        }
    }
}

static void start() {
    if (__atomic_exchange_n(&started, 1u, __ATOMIC_ACQ_REL)) return;
    PE_parse_boot_argn("houji_gov", &enabled, sizeof(enabled));
    PE_parse_boot_argn("houji_gov_dry", &dry, sizeof(dry));
    if (!enabled) return;
    thread_t t;
    if (kernel_thread_start(worker, nullptr, &t) == KERN_SUCCESS) {
        thread_deallocate(t);
        IOLog("HOUJI GOV: started thermal-aware EPSS governor (dry=%u)\n", dry);
    } else {
        IOLog("HOUJI GOV: worker unavailable\n");
    }
}
}

extern "C" void houji_cpu_governor_start(void) { HoujiCpuGovernor::start(); }