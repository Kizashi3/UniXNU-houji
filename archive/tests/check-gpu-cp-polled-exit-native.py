#!/usr/bin/env python3
"""Execute actual post-preflight no-RAW native query/exit, including failures."""
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
static struct hci_result mCpInit;
static struct hll_result mCpPreflightLog;
static struct {unsigned started,published;}mCpTransport;
static unsigned mCpPreflightValid=1,mode,checks,send_calls,doorbells,receives,header;
static int CpPreflightGuard(void*c){(void)c;return mode==1;}
static int CpPolledHealthy(void*c){(void)c;checks++;return mode!=2;}
static int StockBootstrapSend(void*c,const uint32_t*w,unsigned n){(void)c;assert(n==3 && (w[0]&0xfffff)==0x30c && w[1]==125 && !w[2]);send_calls++;header=w[0];return mode==3;}
static int StockBootstrapDoorbell(void*c){(void)c;doorbells++;return mode==4;}
static int StockBootstrapReceive(void*c,unsigned q,uint32_t*w,unsigned*n){(void)c;assert(q==1);receives++;if(mode==5)return 3;*n=4;w[0]=0x1040c;w[1]=header;w[2]=mode==6?0:1;w[3]=mode==7?1:0;return 0;}
static int ContextDelay(void*c,unsigned u){(void)c;(void)u;assert(0);return 1;}
#include "GpuCpPolledExitNative.h"
static void reset(void){mCpInit=(struct hci_result){.phase=2};mCpPreflightLog=(struct hll_result){.phase=5,.restored=1};mCpTransport.started=mCpTransport.published=0;mCpPreflightValid=1;memset(&mCpExitQuery,0,sizeof mCpExitQuery);mode=checks=send_calls=doorbells=receives=header=0;}
int main(void){unsigned cases=0;struct hhb_result b;reset();b=(struct hhb_result){.next_sequence=23};assert(!RunCpPolledExit(&b) && mCpInit.phase==8 && !mCpInit.raw_attempted && !mCpTransport.published && b.next_sequence==24 && send_calls==1 && doorbells==1 && receives==1);cases++;
 for(unsigned i=1;i<=7;i++){reset();b=(struct hhb_result){.next_sequence=23};mode=i;assert(RunCpPolledExit(&b) && !mCpInit.raw_attempted && !mCpTransport.published);cases++;}
 for(unsigned i=0;i<11;i++){reset();b=(struct hhb_result){.next_sequence=23};if(i==0)mCpPreflightValid=0;if(i==1)mCpPreflightLog.code=1;if(i==2)mCpPreflightLog.phase=4;if(i==3)mCpPreflightLog.restored=0;if(i==4)mCpInit.phase=3;if(i==5)mCpInit.raw_attempted=1;if(i==6)mCpTransport.started=1;if(i==7)mCpTransport.published=1;if(i==8)b.next_sequence=1;if(i==9)b.next_sequence=4094;assert(RunCpPolledExit(i==10?0:&b) && !send_calls && !checks);cases++;}
 printf("PASS: %u actual no-RAW exit cases; full preflight restored before ordinary query, exact GET_VALUE125, status/ACK and all partial failures stop; no CP payload\n",cases);
}
'''
with tempfile.TemporaryDirectory() as folder:
 f=Path(folder);(f/'test.c').write_text(program)
 subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(p/'native/gpu/uefi'),'-I',str(p/'native/gpu'),str(f/'test.c'),'-o',str(f/'test')],check=True)
 subprocess.run([str(f/'test')],check=True)
