#!/usr/bin/env python3
"""Exercise the active client-window and TLB bounds against boot-range peers."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / 'kernel/overlay/iokit/Kernel/houji-ufs-root'
provider = (BOARD / 'HoujiGpuNativeProvider.inc').read_text()
start = provider.index('extern "C" bool native_adreno_board_va_window(')
window = provider[start:provider.index('/* Cached CPU timing', start)]
start = provider.index('static bool houjiProviderTlbValue(')
tlb = provider[start:provider.index('static int houjiProviderPublish(', start)]
windows = '#include "HoujiGpuClientLayout.h"\n'
unit = r'''
#include "HoujiGpuAddressLayout.h"
#include <cassert>
#include <cstdio>
struct Range {uint64_t iova,bytes;};
static Range boot[12];
static int state,arena;
static struct {struct {int *state,*arena;Range *boot_ranges;unsigned boot_count;} binding;} gHoujiVm={{&state,&arena,boot,12}};
static bool running=true,operation=true;
static bool native_adreno_board_running(){return running;}
static bool houjiApiInOperation(){return operation;}
static bool hzr_overlap(uint64_t a,uint64_t n,uint64_t b,uint64_t m){return a<b+m && b<a+n;}
'''
unit += window + tlb + windows
unit += r'''
int main(){
    for(unsigned i=0;i<12;i++)boot[i]={0x60000000+i*0x10000u,4096};
    assert(NativeAdrenoMaxClients==5);
    assert(kClientWindows[0].bytes==UINT64_C(2)*1024*1024*1024);
    for(unsigned i=0;i<NativeAdrenoMaxClients;i++){
        const auto &a=kClientWindows[i];assert(native_adreno_board_va_window(a.start,a.bytes));
        for(unsigned j=0;j<i;j++){const auto &b=kClientWindows[j];assert(!hzr_overlap(a.start,a.bytes,b.start,b.bytes));}
    }
    const Range saved=boot[0];boot[0]={0x28000000,4096};
    assert(!native_adreno_board_va_window(kClientWindows[4].start,kClientWindows[4].bytes));
    boot[0]=saved;
    assert(native_adreno_board_va_window(HOUJI_GPU_APERTURE-4096,4096));
    assert(!native_adreno_board_va_window(HOUJI_GPU_APERTURE-4096,8192));
    assert(!native_adreno_board_va_window(HOUJI_GPU_APERTURE,4096));
    assert(!native_adreno_board_va_window(UINT64_MAX-4095,8192));
    assert(!native_adreno_board_va_window(0x1000000,4096));
    assert(!native_adreno_board_va_window(boot[0].iova,4096));
    assert(!native_adreno_board_va_window(HOUJI_GPU_RENDER_START,0));
    const uint64_t asid=UINT64_C(0x751)<<48;
    assert(houjiProviderTlbValue(asid|((HOUJI_GPU_APERTURE-4096)>>12)));
    assert(!houjiProviderTlbValue(asid|(HOUJI_GPU_APERTURE>>12)));
    assert(!houjiProviderTlbValue((asid+(UINT64_C(1)<<48))|0x80000));
    operation=false;assert(!houjiProviderTlbValue(asid|0x80000));operation=true;
    running=false;assert(!houjiProviderTlbValue(asid|0x80000));
    gHoujiVm.binding.state=nullptr;
    assert(!native_adreno_board_va_window(HOUJI_GPU_RENDER_START,4096));
    puts("PASS: actual 2 GiB client window, 4 GiB board/TLB boundaries, reserved-range and overlap checks; host peers");
}
'''
with tempfile.TemporaryDirectory(prefix='houji-address-') as directory:
    tmp = Path(directory)
    (tmp / 'address.cpp').write_text(unit)
    subprocess.run(['clang++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-I' + str(BOARD),
                    str(tmp / 'address.cpp'), '-o', str(tmp / 'address')], check=True)
    subprocess.run([str(tmp / 'address')], check=True, timeout=10)
