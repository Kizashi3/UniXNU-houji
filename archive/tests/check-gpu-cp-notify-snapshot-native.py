#!/usr/bin/env python3
"""Actual batched pre-notification snapshot: valid reads only, stop at first fault."""
from pathlib import Path
import subprocess,tempfile
p=Path(__file__).resolve().parents[1];s=(p/'native/gpu/uefi/GpuCpNotifySnapshotNative.h').read_text();a=s.index('STATIC int CpNotifySnapshot(');body=s[a:s.rindex('#endif')]
program=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "GpuCpPoll.h"
#define STATIC static
#define VOID void
#define CONST const
#define UINT64 uint64_t
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
enum {GGH_BYTES=0x12000,GGH_IOVA=0x60010000};
static struct {struct {void*cpu;}memory[6];}mFirmwareMemory;
static struct hcf_result mCpPoll;
static uint64_t mCpPollRoots[HCF_ROOTS];
static unsigned maps,health,reads,ready,prints,reports,queues,fail_map,fail_health,fail_read,fail_ready;
static int bad_queue=-1,nonempty=-1;
static unsigned readycode(void){ready++;return ready==fail_ready;}
static int CpPolledReady(void*c){(void)c;return readycode();}
static int CpNotifyMap(uint64_t a){assert(a>=0x3d00000 && a<0x3e00000 && !(a&3));maps++;return maps==fail_map;}
static int CpPolledHealthy(void*c){(void)c;return ++health!=fail_health;}
static int GpuTryRead32(uint64_t a,uint32_t*v){reads++;if(reads==fail_read)return 2;*v=(uint32_t)a^0x12345678;return 0;}
static void Print(const void*fmt,...){(void)fmt;prints++;}
static uint64_t BatchCounter(void){return 100;}
static uint64_t BatchMicroseconds(uint64_t before){assert(before==100);return 50;}
static void GpuDoorbellFaultReport(void){reports++;}
static void StockHfiBarrier(void*c){(void)c;}
struct ggh_io {void*cpu;unsigned bytes,iova;void*cookie;void(*barrier)(void*);};
static int ggh_queue(const struct ggh_io*i,unsigned q,volatile uint32_t**header,volatile uint32_t**ring,unsigned*r,unsigned*w){static volatile uint32_t h[3]={1,0,0};(void)i;(void)ring;assert(q<3);queues++;*header=h;*r=4*q;*w=*r+(nonempty==(int)q?4:0);return bad_queue==(int)q;}
'''+body+r'''
static void reset(void){maps=health=reads=ready=prints=reports=queues=fail_map=fail_health=fail_read=fail_ready=0;bad_queue=nonempty=-1;}
int main(void){unsigned cases=0;reset();assert(!CpNotifySnapshot() && maps==19 && health==19 && reads==19 && ready==2 && reports==1 && queues==3);cases++;
 for(unsigned type=0;type<3;type++)for(unsigned i=1;i<=19;i++){reset();if(type==0)fail_map=i;if(type==1)fail_health=i;if(type==2)fail_read=i;assert(CpNotifySnapshot() && !reports && !queues && prints==i-1 && maps==i);cases++;}
 for(unsigned i=1;i<=2;i++){reset();fail_ready=i;assert(CpNotifySnapshot() && ready==i && (i==2 || !reads));cases++;}
 for(unsigned q=0;q<3;q++){reset();bad_queue=q;assert(CpNotifySnapshot() && queues==q+1 && !reports);reset();nonempty=q;assert(CpNotifySnapshot() && queues==q+1 && !reports);cases+=2;}
 printf("PASS: %u actual batched snapshot cases; nineteen mapped/current-lease/read checks, no invalid observations or hardware writes, empty queues, failure stops before persistence\n",cases);
}
'''
with tempfile.TemporaryDirectory() as folder:
 f=Path(folder);(f/'test.c').write_text(program)
 subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(p/'native/gpu/uefi'),str(f/'test.c'),'-o',str(f/'test')],check=True)
 subprocess.run([str(f/'test')],check=True)
