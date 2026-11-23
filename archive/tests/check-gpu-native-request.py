#!/usr/bin/env python3
"""Exercise the actual firmware entry against its strict pristine-request ABI."""
from pathlib import Path
import subprocess
import tempfile
p=Path(__file__).resolve().parents[1]
s=(p/'native/gpu/uefi/GpuPower.c').read_text()
s=s[s.index('VOID HoujiGpuPowerPrepare(VOID)'):]
program=r'''
#include <stdint.h>
#include <assert.h>
#include <stdio.h>
#include <stddef.h>
#define VOID void
#define EFI_ERROR(x) ((x)!=0)
typedef uint64_t EFI_STATUS;
typedef uint32_t UINT32;
typedef size_t UINTN;
#include "GpuPowerPolicy.h"
static unsigned calls,mode,reads,cm3_reads;
struct FakeClock {EFI_STATUS(*GetClockFreqHz)(FakeClock*,UINTN,UINT32*);};
static EFI_STATUS freq(FakeClock*,UINTN,UINT32* out){*out=625000000;return 0;}
static FakeClock clock_mock={freq},*mClock;
static UINTN mIds[GPP_RESOURCE_COUNT];
static EFI_STATUS ProbeCheckpoint(const char*){return 0;}
static UINT32 MmioRead32(UINTN address){
 reads++;
 switch(address){
 case 0x3d99108:return mode==1?1:0;
 case 0x3d99168:return 0x80000000;
 case 0x3d9911c:return 0;
 case 0x3d7e000:cm3_reads++;return 1;
 case 0x3d99318:case 0x3d9931c:case 0x3d993ec:case 0x3d993f0:return 0;
 default:assert(false);return 0;
 }
}
static EFI_STATUS Prepare(struct gpp_report *r,UINTN bytes){
 assert(bytes==sizeof(*r));
 assert(gpp_report_requested(r) && "native entry must not pre-seal a request");
 calls++;r->phase=mode?GPP_PHASE_CLOCKS:GPP_PHASE_RESOLVE;
 r->code=mode?GPP_ERR_INITIAL:GPP_ERR_RESOLVE;
 if(mode){r->resource=GPP_GMU_CLK;r->confirmed=0x1002;}
 gpp_report_seal(r);
 return 1;
}
template<class... T> static void Print(const wchar_t*,T...){ }
static void HoujiGpuBusProbe(const struct gpp_report*){}
'''+s+r'''
int main(){HoujiGpuPowerPrepare();assert(calls==1 && !reads);
 mClock=&clock_mock;mode=1;HoujiGpuPowerPrepare();assert(calls==2 && reads==3 && !cm3_reads);
 mode=2;reads=0;HoujiGpuPowerPrepare();assert(calls==3 && reads==8 && cm3_reads==1);
 puts("PASS: real native entry submits pristine requests; inherited-state diagnostics gate CM3 access and only read whitelisted registers");}
'''
with tempfile.TemporaryDirectory() as directory:
 d=Path(directory);(d/'test.cpp').write_text(program)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
  '-I',str(p/'native/gpu/uefi'),str(d/'test.cpp'),'-o',str(d/'test')],check=True)
 subprocess.run([str(d/'test')],check=True)
