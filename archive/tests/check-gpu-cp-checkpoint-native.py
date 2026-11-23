#!/usr/bin/env python3
"""Exercise the actual idle/reset snapshot gates; never allow an in-flight RAW."""
from pathlib import Path
import subprocess, tempfile
p=Path(__file__).resolve().parents[1]
s=(p/'native/gpu/uefi/GpuLiveLogNative.h').read_text()
def fn(name):
    a=s.index('STATIC int '+name+'(');b=s.index('{',a)+1;depth=1
    while depth:depth+=(s[b]=='{')-(s[b]=='}');b+=1
    return s[a:b]
program=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#define STATIC static
#define VOID void
enum {HFM_ALL=255,GGH_QUEUES=17,GGH_BYTES=0x12000,GGH_IOVA=0x60010000};
static struct {unsigned code,phase,idle;struct {unsigned code,completed;struct {unsigned ack;}record[1];}raw;}mCpInit={0,6,1,{0,1,{{1}}}};
static unsigned mCpPollArmed=1,mStockCalled=1,mFirmwareHeld=1,mGpuSaveAllowed=1,mHostRingUnsafe;
static struct {unsigned failed;}mCpPoll;
static struct {unsigned release_attempted,reset_held;}mStockResult={1,1};
static struct {unsigned retained;struct {void*cpu;}memory[6];}mFirmwareMemory={HFM_ALL,{{0}}};
static struct {uint32_t address;}h7c_ops[1]={{0x3d000e0}};
static unsigned mCpIrqMask;
static unsigned health=1,bad_scratch,bad_secure,busy,rbbm,irq,mask,reads,cases;
static int bad_queue=-1,nonempty_queue=-1;
static int CpHealth(void*c){(void)c;return health;}
static int CpPolledHealthy(void*c){(void)c;return health;}
static int ScratchAudit(void){return bad_scratch;}
static int SecureDomainGuard(void*c){(void)c;return bad_secure;}
static uint32_t MmioRead32(uint32_t a){reads++;switch(a){case 0x3d8ec30:return busy;case 0x3d00840:return rbbm;case 0x3d00804:return irq;case 0x3d000e0:return mask;default:assert(0);return 0;}}
struct ggh_io{void*cpu;unsigned bytes,iova;void*cookie;void(*barrier)(void*);};
static void StockHfiBarrier(void*c){(void)c;}
static int ggh_queue(const struct ggh_io*i,unsigned q,volatile uint32_t**h,volatile uint32_t**r,unsigned*read,unsigned*write){(void)i;(void)h;(void)r;assert(q<17);*read=0;*write=(int)q==nonempty_queue;return (int)q==bad_queue;}
'''+fn('CpIdleLogGuard')+'\n'+fn('CpStoppedLogGuard')+r'''
int main(void){assert(!CpIdleLogGuard(0));cases++;
 unsigned *zero[]={&mCpInit.code,&mCpInit.raw.code,&mCpPoll.failed,&bad_scratch,&bad_secure,&rbbm,&irq,&mask};
 for(unsigned i=0;i<sizeof zero/sizeof zero[0];i++){*zero[i]=1;assert(CpIdleLogGuard(0));*zero[i]=0;cases++;}
 unsigned *one[]={&mCpInit.phase,&mCpInit.idle,&mCpInit.raw.record[0].ack,&mCpInit.raw.completed,&mCpPollArmed,&health};
 for(unsigned i=0;i<sizeof one/sizeof one[0];i++){unsigned saved=*one[i];*one[i]=0;assert(CpIdleLogGuard(0));*one[i]=saved;cases++;}
 busy=1u<<23;assert(CpIdleLogGuard(0));busy=0;cases++;
 for(int i=0;i<17;i++){bad_queue=i;assert(CpIdleLogGuard(0));bad_queue=-1;nonempty_queue=i;assert(CpIdleLogGuard(0));nonempty_queue=-1;cases+=2;}
 unsigned before=reads;assert(!CpStoppedLogGuard(0) && reads==before);cases++;
 unsigned *owned[]={&mStockCalled,&mFirmwareHeld,&mGpuSaveAllowed,&mStockResult.release_attempted,&mStockResult.reset_held,&mFirmwareMemory.retained};
 for(unsigned i=0;i<sizeof owned/sizeof owned[0];i++){unsigned saved=*owned[i];*owned[i]=0;assert(CpStoppedLogGuard(0) && reads==before);*owned[i]=saved;cases++;}
 mHostRingUnsafe=1;assert(CpStoppedLogGuard(0) && reads==before);mHostRingUnsafe=0;cases++;
 printf("PASS: %u actual CP checkpoint gates; ACK+idle+zero fault+empty queues, or confirmed GMU reset with pinned resources; reset gate performs no diagnostic MMIO\n",cases);
}
'''
with tempfile.TemporaryDirectory() as folder:
    f=Path(folder);(f/'test.c').write_text(program)
    subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(f/'test.c'),'-o',str(f/'test')],check=True)
    subprocess.run([str(f/'test')],check=True)
