#!/usr/bin/env python3
"""Run the actual native preflight and hci/hll paths, with every guard failing."""
from pathlib import Path
import subprocess,tempfile
p=Path(__file__).resolve().parents[1]
program=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "GpuCpInit.h"
#include "GpuLiveLog.h"
#define STATIC static
#define VOID void
#define CONST const
#define Print(...) ((void)0)
static unsigned tpl=16,checks,fail_at,saves,lowered,restored;
static struct hci_result mCpInit;
static struct hll_result mCpIrqLog={.phase=5,.restored=1};
static int check(void){return ++checks==fail_at;}
static int CpPolledHealthy(void*c){(void)c;return !check();}
static int CpPolledReady(void*c){(void)c;return check();}
static int CpReuseAperture(void*c){(void)c;return check();}
static int CpRead(void*c,uint32_t a,uint32_t*v){(void)c;(void)a;(void)v;assert(0);return 1;}
static int CpIrqLogGuard(void*c){(void)c;return check();}
static int StockBootstrapReceive(void*c,unsigned q,uint32_t*w,unsigned*n){(void)c;(void)q;(void)w;(void)n;assert(0);return 1;}
static int StockBootstrapDoorbell(void*c){(void)c;assert(0);return 1;}
static int ContextDelay(void*c,unsigned t){(void)c;(void)t;assert(0);return 1;}
static unsigned LiveLogTpl(void*c){(void)c;return tpl;}
static void LiveLogLower(void*c){(void)c;tpl=4;lowered++;}
static int LiveLogRestore(void*c){(void)c;assert(tpl==4);tpl=16;restored++;return 0;}
static uint64_t ProbeCheckpoint(const char*stage){assert(!strcmp(stage,"CP-pre-send-guards-and-packet-PASS-before-real-RAW") && tpl==4);saves++;return 0;}
static int CpNotifySnapshot(void){return check();}
#include "GpuCpPreflightNative.h"
static void reset(void){tpl=16;checks=fail_at=saves=lowered=restored=0;mCpInit=(struct hci_result){.phase=2,.aperture_ok=1};mCpIrqLog=(struct hll_result){.phase=5,.restored=1};mCpPreflight=(struct hci_result){0};mCpPreflightLog=(struct hll_result){0};mCpPreflightCalls=mCpPreflightValid=0;memset(mCpPreflightWords,0,sizeof mCpPreflightWords);}
int main(void){unsigned cases=0;struct hhb_result b={.next_sequence=23};reset();assert(!RunCpPreflight(&b));unsigned total=checks;assert(total>=8 && b.next_sequence==23 && saves==1 && lowered==1 && restored==1 && tpl==16 && mCpPreflightValid && mCpInit.phase==2 && !mCpInit.raw_attempted && !mCpPreflight.raw.record[0].sent && mCpPreflight.raw.next_sequence==24 && mCpPreflightWords[0]==0x1700b83);cases++;
 for(unsigned i=1;i<=total;i++){reset();b.next_sequence=23;fail_at=i;assert(RunCpPreflight(&b));assert(b.next_sequence==23 && tpl==16 && lowered==restored && saves<=1 && !mCpInit.raw_attempted && !mCpPreflight.raw.record[0].sent);cases++;}
 for(unsigned i=0;i<6;i++){reset();b.next_sequence=23;if(i==0)mCpIrqLog.code=1;if(i==1)mCpIrqLog.phase=4;if(i==2)mCpIrqLog.restored=0;if(i==3)mCpPreflightCalls=1;if(i==4)b.next_sequence=1;if(i==5)tpl=4;assert(RunCpPreflight(&b) && !saves);cases++;}
 reset();assert(RunCpPreflight(0) && !checks && !saves);cases++;
 for(unsigned count=0;count<256;count++){reset();uint32_t w[256]={0};assert(CpPreflightSend(0,w,count)==1 && mCpPreflightCalls==1 && !saves);assert(checks==(count==11));cases++;}
 reset();assert(CpPreflightSend(0,0,11)==1 && !checks);cases++;
 printf("PASS: %u actual preflight cases; guards, packet, unchanged real sequence, deliberate send rejection, no queue/doorbell/read/delay, TPL restoration\n",cases);
}
'''
with tempfile.TemporaryDirectory() as folder:
 f=Path(folder);(f/'test.c').write_text(program)
 subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(p/'native/gpu/uefi'),'-I',str(p/'native/gpu'),str(f/'test.c'),'-o',str(f/'test')],check=True)
 subprocess.run([str(f/'test')],check=True)
