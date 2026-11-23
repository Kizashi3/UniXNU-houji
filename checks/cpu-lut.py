#!/usr/bin/env python3
"""Exercise the actual board LUT reader against Recovery's frequency inventory."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / 'kernel/overlay/iokit/Kernel/arm/HoujiCpuDvfs.inc').read_text()
reader = source[source.index('namespace HoujiCpuDvfs {'):source.index('static bool vote(')] + '\n}\n'
# CPU domains are EPSS order, not Linux policy-number order. The X4 boost
# frequencies were read separately with boost=1 on houji in OrangeFox.
frequencies = [
    [364800, 460800, 556800, 672000, 787200, 902400, 1017600, 1132800,
     1248000, 1344000, 1459200, 1574400, 1689600, 1804800, 1920000,
     2035200, 2150400, 2265600],
    [499200, 614400, 729600, 844800, 960000, 1075200, 1190400, 1286400,
     1401600, 1497600, 1612800, 1708800, 1824000, 1920000, 2035200,
     2131200, 2188800, 2246400, 2323200, 2380800, 2438400, 2515200,
     2572800, 2630400, 2707200, 2764800, 2841600, 2899200, 2956800],
    [480000, 576000, 672000, 787200, 902400, 1017600, 1132800, 1248000,
     1363200, 1478400, 1593600, 1708800, 1824000, 1939200, 2035200,
     2112000, 2169600, 2246400, 2304000, 2380800, 2438400, 2496000,
     2553600, 2630400, 2688000, 2745600, 2803200, 2880000, 2937600,
     2995200, 3052800, 3110400, 3187200, 3244800, 3302400],
    [499200, 614400, 729600, 844800, 960000, 1075200, 1190400, 1286400,
     1401600, 1497600, 1612800, 1708800, 1824000, 1920000, 2035200,
     2131200, 2188800, 2246400, 2323200, 2380800, 2438400, 2515200,
     2572800, 2630400, 2707200, 2764800, 2841600, 2899200, 2956800,
     3014400, 3072000, 3148800],
]
fixture = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <vector>
alignas(4096) static uint32_t registers[4][1024];
struct IOMemoryMap {
    unsigned domain;
    uintptr_t getVirtualAddress(){return (uintptr_t)registers[domain];}
};
struct IODeviceMemory {
    IOMemoryMap mapping;
    static IODeviceMemory *withRange(uint64_t address,unsigned size) {
        static IODeviceMemory devices[]={ {{0}}, {{1}}, {{2}}, {{3}} };
        assert(address>=0x17d91000 && address<0x17d95000 && size==4096);
        return &devices[(address-0x17d91000)/4096];
    }
    IOMemoryMap *map(unsigned){return &mapping;}
    void release(){}
};
enum {kIOMapAnywhere=1,kIOMapInhibitCache=2};
static void IOLog(const char *,...){}
'''
inventory = 'static const std::vector<uint32_t> inventory[]={' + ','.join(
    '{' + ','.join(map(str, values)) + '}' for values in frequencies) + '};\n'
test = r'''
static void reset(unsigned id) {
    using namespace HoujiCpuDvfs;
    d[id]={};for(auto &r:registers[id])r=0;
    registers[id][0]=1;
    for(unsigned row=0;row<rows;++row){
        unsigned at=row<inventory[id].size()?row:inventory[id].size()-1;
        // The register source/L encoding is documented by qcom-cpufreq-hw.
        registers[id][0x100/4+row]=(1u<<30)|(inventory[id][at]/19200);
    }
    registers[id][0x320/4]=inventory[id].size()-1;
}
int main() {
    using namespace HoujiCpuDvfs;
    for(unsigned id=0;id<4;++id){
        reset(id);assert(init(id));assert(d[id].n==inventory[id].size());
        for(unsigned i=0;i<d[id].n;++i){
            assert(d[id].khz[i]==inventory[id][i] && d[id].index[i]==i);
        }
    }
    assert(d[2].khz[d[2].n-1]==3302400 && d[2].cur==d[2].n-1);
    reset(2);registers[2][0x100/4+31]=registers[2][0x100/4+30];
    assert(!init(2)); // a source missing the advertised boost cap is rejected
    reset(2);registers[2][0x100/4+12]=registers[2][0x100/4+10];
    assert(!init(2)); // descending/corrupt LUT
    reset(2);registers[2][0x320/4]=40;assert(!init(2));
    reset(2);registers[2][0]=0;assert(!init(2));
    puts("PASS: actual CPU EPSS LUT reader preserves four X4 boost rows through 3302400 kHz; rejects missing/corrupt/disabled tables; no hardware execution");
}
'''
with tempfile.TemporaryDirectory(prefix='houji-cpu-lut-') as folder:
    path = Path(folder)
    (path / 'test.cpp').write_text(fixture + reader + inventory + test)
    subprocess.run(['clang++', '-std=c++17', '-Wall', '-Wextra',
                    '-Wno-unused-variable', '-Werror', '-fsanitize=address,undefined',
                    str(path / 'test.cpp'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
