#!/usr/bin/env python3
"""Exercise actual slot selection and diagnostics with all occupancy states."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / 'kernel/overlay/iokit/Kernel/houji-ufs-root'
client = (BOARD / 'Adreno740/NativeAdrenoUserClient.cpp').read_text()
start = client.index('static volatile uint32_t *clientStats(')
stats = client[start:client.index('\n}', start) + 2]
source = r'''
#include "HoujiGpuClientLayout.h"
#include "Adreno740/NativeAdrenoABI.h"
#include <cassert>
#include <cstdio>
volatile uint32_t native_adreno_client_stats[NativeAdrenoMaxClients+1][6];
'''
source += stats
source += r'''
int main() {
    static_assert(NativeAdrenoGeneralClients==4 && NativeAdrenoPreferencesSlot==4 && NativeAdrenoMaxClients==5);
    assert(kClientWindows[4].start==0x20000000 && kClientWindows[4].bytes==0x10000000);
    for(unsigned mask=0;mask<32;mask++) {
        bool used[5];for(unsigned i=0;i<5;i++)used[i]=(mask>>i)&1;
        const unsigned preferences=houjiGpuClientSlot(false,true,used);
        assert(preferences==(used[4]?5u:4u));
        unsigned generic=5;
        for(unsigned i=1;i<4;i++)if(!used[i]){generic=i;break;}
        assert(houjiGpuClientSlot(false,false,used)==generic);
        assert(houjiGpuClientSlot(true,false,used)==(used[0]?generic:0u));
        assert(mask==unsigned(used[0]|used[1]<<1|used[2]<<2|used[3]<<3|used[4]<<4));
    }
    bool full[5]={true,true,true,true,false};
    assert(houjiGpuClientSlot(false,true,full)==4);
    full[4]=true;assert(houjiGpuClientSlot(false,true,full)==5);
    full[4]=false;assert(houjiGpuClientSlot(false,true,full)==4);
    assert(houjiGpuClientSlot(false,false,full)==5); // cannot take the reserved slot
    for(unsigned i=0;i<5;i++) {
        auto *row=clientStats(i*NativeAdrenoAbiMaxQueues,kClientWindows[i].bytes);
        assert(row==native_adreno_client_stats[i]);row[0]=10+i;
    }
    assert(clientStats(0,0)==native_adreno_client_stats[5]);
    assert(clientStats(5*NativeAdrenoAbiMaxQueues,4096)==native_adreno_client_stats[5]);
    assert(clientStats(UINT32_MAX,4096)==native_adreno_client_stats[5]);
    assert(native_adreno_client_stats[4][0]==14 && native_adreno_client_stats[5][0]==0);
    puts("PASS: 32 occupancy states preserve generic slots and reserve Preferences; fifth-client and kernel counters cannot alias; no GPU");
}
'''
with tempfile.TemporaryDirectory(prefix='houji-client-slots-') as directory:
    tmp = Path(directory)
    unit, binary = tmp / 'check.cpp', tmp / 'check'
    unit.write_text(source)
    subprocess.run(['clang++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-I' + str(BOARD), str(unit), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=10)
