#!/usr/bin/env python3
"""Compile actual canary owner and TPL bindings with hostile native callbacks."""
from pathlib import Path
import subprocess,tempfile
p=Path(__file__).resolve().parents[1];s=(p/'native/gpu/uefi/GpuLiveLogNative.h').read_text()
def fn(name):
 at=s.index(name+'(');a=s.rfind('STATIC ',0,at);b=s.index('{',a)+1;depth=1
 while depth:depth+=(s[b]=='{')-(s[b]=='}');b+=1
 return s[a:b]
program=r'''
#include <assert.h>
#include <stdio.h>
#include <stdint.h>
#include "GpuGen7Table.h"
#define STATIC static
#define VOID void
#define CONST const
#define BOOLEAN int
typedef unsigned EFI_TPL;typedef uint64_t UINT64;
enum {TPL_HIGH_LEVEL=31,TPL_NOTIFY=16,TPL_APPLICATION=4,HHB_STEPS=9,GGH_QUEUES=17,GGH_BYTES=0x12000,GGH_IOVA=0x60010000,HCC_PAGES=64,HSC_POOL_PAGES=256,HSC_GPU_TABLE_PAGES=7};
static unsigned tpl=16,mCpIrqMask;
static unsigned raise_tpl(unsigned to){unsigned old=tpl;tpl=to;return old;}
static void restore_tpl(unsigned to){tpl=to;}
static struct {unsigned(*RaiseTPL)(unsigned);void(*RestoreTPL)(unsigned);} bs={raise_tpl,restore_tpl},*gBS=&bs;
static struct {unsigned code,completed,resource_acks;} bootstrap={0,9,10},*mLiveBootstrap=&bootstrap;
static struct {unsigned raw_attempted,phase,aperture_attempted;} mCpInit;
static unsigned mCpApertureCalled,mCpApertureResult,mCpApertureValid,mLiveLogMode=1,bad_gen7,bad_scratch,bad_secure,irq_mask,verify_calls,fail_verify,cases;
static struct {unsigned quarantined;struct {uint64_t x[8];}last_output;}mCpAperture;
static struct {unsigned code,phase,restored;}mLiveLogBefore;
static int fail_queue=-1,nonempty_queue=-1;
static struct {unsigned code,phase,record_ready;} mGen7={0,6,1};
struct hfm_allocation{uint64_t physical;void *cpu;unsigned pages,nc;};
static struct {unsigned count;struct hfm_allocation memory[6];}mFirmwareMemory={2,{{0}}};
static struct hfm_allocation mCodeMemory={0x400000,(void*)0x400000,64,1},mGpuOnlyMemory={0x500000,(void*)0x500000,256,1};
static uint64_t mScratchTablePhysical=0x300000;static void*mScratchTables=(void*)0x300000;
static int Gen7Guard(void*c){(void)c;return (int)bad_gen7;}
static int ScratchAudit(void){return (int)bad_scratch;}
static int SecureDomainGuard(void*c){(void)c;return (int)bad_secure;}
static uint32_t MmioRead32(uint32_t a){assert(a==0x3d000e0);return irq_mask;}
struct ggh_io{void *words;unsigned bytes,iova;void*cookie;void(*barrier)(void*);};
static void StockHfiBarrier(void*c){(void)c;}
static int ggh_queue(const struct ggh_io*io,unsigned q,volatile uint32_t**h,volatile uint32_t**ring,unsigned*r,unsigned*w){(void)io;(void)h;(void)ring;assert(q<17);*r=0;*w=(int)q==nonempty_queue?4:0;return (int)q==fail_queue;}
static int FirmwareVerifyPages(uint64_t pa,void*cpu,unsigned pages,unsigned nc){(void)nc;assert(pa==(uintptr_t)cpu && pages);return ++verify_calls==fail_verify;}
'''+ '\n'.join(fn(name) for name in ('LiveLogTpl','LiveLogLower','LiveLogRestore','LiveLogGuard')) +r'''
int main(void){for(unsigned i=0;i<3;i++)mFirmwareMemory.memory[i]=(struct hfm_allocation){0x100000+i*4096,(void*)(uintptr_t)(0x100000+i*4096),1,0};
 assert(!LiveLogGuard(0) && verify_calls==6);cases++;
 for(unsigned i=1;i<=6;i++){verify_calls=0;fail_verify=i;assert(LiveLogGuard(0) && verify_calls==i);cases++;}fail_verify=0;
 for(int i=0;i<17;i++){fail_queue=i;assert(LiveLogGuard(0));fail_queue=-1;nonempty_queue=i;assert(LiveLogGuard(0));nonempty_queue=-1;cases+=2;}
 for(unsigned bit=0;bit<32;bit++){irq_mask=1u<<bit;assert(LiveLogGuard(0));cases++;}irq_mask=0;
 bad_gen7=1;assert(LiveLogGuard(0));bad_gen7=0;cases++;
 bad_scratch=1;assert(LiveLogGuard(0));bad_scratch=0;cases++;
 bad_secure=1;assert(LiveLogGuard(0));bad_secure=0;cases++;
 mCpInit.raw_attempted=1;assert(LiveLogGuard(0));mCpInit.raw_attempted=0;cases++;
 mCpApertureCalled=1;assert(LiveLogGuard(0));mCpApertureCalled=0;cases++;
 bootstrap.completed=8;assert(LiveLogGuard(0));bootstrap.completed=9;cases++;
 mGen7.record_ready=0;assert(LiveLogGuard(0));mGen7.record_ready=1;cases++;
 mLiveLogMode=2;mCpApertureCalled=1;mCpApertureValid=1;mCpInit.phase=2;mCpInit.aperture_attempted=1;mLiveLogBefore.phase=5;mLiveLogBefore.restored=1;
 assert(!LiveLogGuard(0));cases++;
 mCpApertureResult=1;assert(LiveLogGuard(0));mCpApertureResult=0;cases++;
 mCpApertureValid=0;assert(LiveLogGuard(0));mCpApertureValid=1;cases++;
 mCpAperture.quarantined=1;assert(LiveLogGuard(0));mCpAperture.quarantined=0;cases++;
 mCpAperture.last_output.x[0]=1;assert(LiveLogGuard(0));mCpAperture.last_output.x[0]=0;cases++;
 mCpInit.phase=3;assert(LiveLogGuard(0));mCpInit.phase=2;cases++;
 mLiveLogBefore.restored=0;assert(LiveLogGuard(0));mLiveLogBefore.restored=1;cases++;
 mLiveLogBefore.code=1;assert(LiveLogGuard(0));mLiveLogBefore.code=0;cases++;
 mCpInit.raw_attempted=1;assert(LiveLogGuard(0));mCpInit.raw_attempted=0;cases++;
 mLiveLogMode=3;assert(LiveLogGuard(0));mLiveLogMode=2;cases++;
 assert(LiveLogTpl(0)==16 && tpl==16);LiveLogLower(0);assert(tpl==4 && !LiveLogRestore(0) && tpl==16);cases++;
 printf("PASS: %u actual live-log native ownership/TPL cases; all17queues empty, noCP/aperture, full audits and CPU mappings, masked IRQ required\n",cases);
}
'''
with tempfile.TemporaryDirectory() as folder:
 f=Path(folder);(f/'test.c').write_text(program)
 subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(p/'native/gpu/uefi'),str(f/'test.c'),'-o',str(f/'test')],check=True)
 subprocess.run([str(f/'test')],check=True)
