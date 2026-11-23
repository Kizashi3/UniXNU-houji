#!/usr/bin/env python3
"""Run the actual no-RAW boundary using bounded HFI and TPL models."""
from pathlib import Path
import subprocess,tempfile
p=Path(__file__).resolve().parents[1]
s=(p/'native/gpu/uefi/GpuCpBoundaryNative.h').read_text()
program=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>
#include "GpuCpInit.h"
#include "GpuLiveLog.h"
#define STATIC static
#define VOID void
#define CONST const
#define UINT32 uint32_t
static struct hci_result mCpInit;
static struct hll_result mLiveLog;
static unsigned scenario,ready_calls,sends,doorbells,version_reads,saves,tpl=16,cases;
static uint32_t header;
static void Print(const wchar_t*f,...){(void)f;}
static int CpReady(void*c){(void)c;ready_calls++;return (scenario==1 && ready_calls==1) || (scenario==3 && ready_calls==2);}
static int CpAperture(void*c){(void)c;mLiveLog=(struct hll_result){.phase=5,.restored=1};return scenario==2;}
static int CpHealth(void*c){(void)c;return 1;}
static int StockBootstrapSend(void*c,const uint32_t*q,unsigned n){(void)c;assert(n==3 && (q[0]&255)==12 && ((q[0]>>8)&255)==3 && q[1]==125 && !q[2]);header=q[0];sends++;return 0;}
static int StockBootstrapReceive(void*c,unsigned q,uint32_t*r,unsigned*n){(void)c;if(q==2)return 1;assert(q==1);*n=4;r[0]=(1u<<16)|(4u<<8)|12;r[1]=header;r[2]=scenario==5?0:1;r[3]=scenario==6?1:0;if(scenario==4)r[1]^=1;return 0;}
static int StockBootstrapDoorbell(void*c){(void)c;doorbells++;return 0;}
static int ContextDelay(void*c,unsigned us){(void)c;(void)us;return 0;}
static unsigned LiveLogTpl(void*c){(void)c;return tpl;}
static void LiveLogLower(void*c){(void)c;tpl=4;}
static int LiveLogRestore(void*c){(void)c;assert(tpl==4);tpl=16;return 0;}
static int LiveLogGuard(void*c){(void)c;return scenario==7;}
static uint64_t ProbeCheckpoint(const char*name){assert(tpl==4 && !strcmp(name,"aperture-complete-HFI-alive-NO-RAW-boundary"));assert(mCpInit.phase==2 && !mCpInit.raw_attempted);saves++;return scenario==8?UINT64_C(1)<<63:0;}
static uint32_t MmioRead32(uint32_t a){assert(a==0x3d74fe0+4*version_reads && version_reads<5);version_reads++;return 0x40020014;}
'''+s+r'''
int main(void){for(scenario=0;scenario<=8;scenario++){
 mCpInit=(struct hci_result){0};mLiveLog=(struct hll_result){0};mCpBoundaryQuery=(struct hhb_result){0};mCpBoundaryLog=(struct hll_result){0};ready_calls=sends=doorbells=version_reads=saves=0;tpl=16;
 struct hhb_result boot={.next_sequence=22};unsigned code=RunCpBoundary(&boot);
 assert((code==0)==(scenario==0));assert(!mCpInit.raw_attempted && tpl==16);
 if(!code)assert(mCpInit.phase==7 && version_reads==5 && sends==1 && doorbells==1 && saves==1 && boot.next_sequence==23 && mCpBoundaryLog.restored);
 if(scenario>=4 && scenario<=6)assert(!version_reads && !saves);
 if(scenario==7)assert(!saves);cases++;
 }
 printf("PASS: %u actual no-RAW native flows; exact GET_VALUE125, fixed5 version reads, TPL restored, pre/post-aperture/ACK/status/guard/FS failures stop without CP\n",cases);
}
'''
with tempfile.TemporaryDirectory() as folder:
 f=Path(folder);(f/'test.c').write_text(program)
 subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(p/'native/gpu'),'-I',str(p/'native/gpu/uefi'),str(f/'test.c'),'-o',str(f/'test')],check=True)
 subprocess.run([str(f/'test')],check=True)
