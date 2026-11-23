#!/usr/bin/env python3
"""Exercise the actual ClockDxe HUB adapter; no native API is called on host."""
from pathlib import Path
import subprocess
import tempfile
p=Path(__file__).resolve().parents[1]
source=(p/'native/gpu/uefi/GpuPower.c').read_text()
body=source.split('STATIC EFI_STATUS PrepareGmuHub',1)[1].split('STATIC unsigned RunGmuProbe',1)[0]
program=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
using UINT32=uint32_t;using UINTN=size_t;using EFI_STATUS=uint64_t;using VOID=void;using BOOLEAN=bool;
using EFI_TPL=unsigned;
#define CONST const
#define STATIC static
#define FALSE false
#define EFI_ERROR(x) ((x)!=0)
enum {EFI_ACCESS_DENIED=1,EFI_DEVICE_ERROR=2,EFI_NOT_STARTED=19,EFI_CLOCK_FREQUENCY_HZ_EXACT=3,EFI_UNSUPPORTED=4};
enum {TPL_APPLICATION=4,TPL_NOTIFY=16,TPL_HIGH_LEVEL=31};
static unsigned tpl=TPL_NOTIFY;
struct BS {static EFI_TPL RaiseTPL(unsigned t){assert(t>=tpl);unsigned old=tpl;tpl=t;return old;}static void RestoreTPL(unsigned t){tpl=t;}};
static BS bs,*gBS=&bs;
#include "GpuGmuProbe.h"
struct Clock {
 EFI_STATUS(*GetClockFreqHz)(Clock*,UINTN,UINT32*);
 EFI_STATUS(*SetClockFreqHz)(Clock*,UINTN,UINT32,unsigned,UINT32*);
 EFI_STATUS(*EnableClock)(Clock*,UINTN);
 EFI_STATUS(*IsClockEnabled)(Clock*,UINTN,BOOLEAN*);
 EFI_STATUS(*IsClockOn)(Clock*,UINTN,BOOLEAN*);
};
static unsigned mode,get_calls,set_calls,enable_calls,checkpoints;
static UINTN mIds[GPP_RESOURCE_COUNT];
static EFI_STATUS get(Clock*,UINTN id,UINT32*out){assert(id==7 && tpl==TPL_APPLICATION);get_calls++;
 if(get_calls==1){*out=mode==1?200000000:0;return mode==1?0:EFI_NOT_STARTED;}
 *out=mode==7?0:200000000;return 0;}
static EFI_STATUS set(Clock*,UINTN id,UINT32 hz,unsigned how,UINT32*out){
 assert(tpl==TPL_APPLICATION && id==7 && hz==200000000 && how==EFI_CLOCK_FREQUENCY_HZ_EXACT && get_calls==1);
 set_calls++;*out=mode==6?0:hz;return mode==5?EFI_DEVICE_ERROR:0;}
static EFI_STATUS enable(Clock*,UINTN id){assert(tpl==TPL_APPLICATION && id==7 && get_calls==2 && set_calls==1);enable_calls++;return mode==8?EFI_DEVICE_ERROR:0;}
static EFI_STATUS enabled(Clock*,UINTN id,BOOLEAN*out){assert(id==7);*out=false;return 0;}
static EFI_STATUS on(Clock*,UINTN id,BOOLEAN*out){assert(id==7);*out=mode!=9;return 0;}
static Clock clock_mock={get,set,enable,enabled,on},*mClock=&clock_mock;
static EFI_STATUS GmuCheckpoint(void*,unsigned stage){assert(tpl==TPL_NOTIFY && (stage==4 || stage==5));checkpoints++;return mode==11 && stage==4?EFI_DEVICE_ERROR:0;}
template<class... T>static void Print(const wchar_t*,T...){ }
template<class... T>static void CallBegin(T...){ }
template<class... T>static void CallEnd(T...){ }
static UINT32 MmioRead32(UINTN a){switch(a){
 case 0x171004:case 0x171010:case 0x171018:case 0x3d97000:return 1;
 case 0x3d99108:return mode==3?1:0;
 case 0x3d99168:return 0x80000000;
 case 0x3d9911c:case 0x3d7e070:return 0;
 case 0x3d7e000:return mode==4?0:1;
 case 0x3d7e340:return 3;
 case 0x3d993e8:return mode==2?1:0;
 case 0x3d993ec:return 0;
 case 0x3d993f0:return set_calls?(mode==10?0:0x505):0;
 default:assert(false);return 0;}}
STATIC EFI_STATUS PrepareGmuHub'''+body+r'''
int main(){
 struct gpp_report p;gpp_report_init(&p);p.code=GPP_ERR_INITIAL;p.phase=GPP_PHASE_CLOCKS;
 p.resource=GPP_GMU_CLK;p.attempted=p.confirmed=0x1002;p.flags=GPP_ACD_CONSUMED;gpp_report_seal(&p);
 struct hgb_result b{};b.valid=0x7fff;b.attempted=7;b.streams_seen=24;b.banks_seen=22;
 b.values[HGB_ID0]=0x4c017e18;b.values[HGB_ID1]=0x40000016;b.values[HGB_ID2]=0x5511;
 b.values[HGB_RESET]=1;b.values[HGB_GXPOWER]=3;for(unsigned i=0;i<24;i++)b.s2cr[i]=0x20000;
 mIds[GPP_HUB_RATE]=mIds[GPP_HUB_CLK]=7;
 for(mode=0;mode<12;mode++) {
  get_calls=set_calls=enable_calls=checkpoints=0;
  EFI_STATUS status=PrepareGmuHub(&p,&b);
  assert(tpl==TPL_NOTIFY);
  if(!mode)assert(!status && set_calls==1 && enable_calls==1 && checkpoints==2);
  else {assert(status);if(mode<=4 || mode==11)assert(!set_calls && !enable_calls);}
 }
 for(unsigned bank=0;bank<22;bank++){
  mode=0;b.sctlr[bank]=1;get_calls=set_calls=enable_calls=checkpoints=0;
  assert(PrepareGmuHub(&p,&b)==EFI_ACCESS_DENIED && !checkpoints && !set_calls);b.sctlr[bank]=0;
 }
 puts("PASS: actual HUB adapter; exact cold-source proof, native 200 MHz set/get/enable, source readback, all 22 busy banks, checkpoint/native failure refusal; inherited clocks never retuned");
}
'''
with tempfile.TemporaryDirectory() as directory:
 d=Path(directory);(d/'test.cpp').write_text(program)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
  '-I',str(p/'native/gpu/uefi'),str(d/'test.cpp'),'-o',str(d/'test')],check=True)
 subprocess.run([str(d/'test')],check=True)
