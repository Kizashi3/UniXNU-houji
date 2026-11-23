#!/usr/bin/env python3
"""Actual fixed local-mask writer/lease callbacks, including partial readback."""
from pathlib import Path
import subprocess,tempfile
p=Path(__file__).resolve().parents[1];s=(p/'native/gpu/uefi/GpuCpPolledIrqNative.h').read_text()
def fn(name):
 a=s.index('STATIC int '+name+'(');b=s.index('{',a)+1;depth=1
 while depth:depth+=(s[b]=='{')-(s[b]=='}');b+=1
 return s[a:b].replace('__asm__ volatile("dsb sy":::"memory");','')
macros='\n'.join(x for x in s.splitlines() if x.startswith('#define HCI_'))
program=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "GpuLiveLog.h"
#define STATIC static
#define VOID void
'''+macros+r'''
static unsigned mCpGicMapped=1,mCpIrqMask,mCpGicGroup,mCpGicEnable,mCpIrqBefore,mCpIrqAfter;
static uint32_t mCpFirmwareVersion[5]={0x40020014};
static struct {unsigned phase,raw_attempted;}mCpInit={7,0};
static struct hll_result mCpBoundaryLog={.phase=5,.restored=1},mCpIrqLog={.phase=5,.restored=1};
static unsigned mCpApertureCalled=1,mCpApertureResult,mCpApertureValid=1;
static struct {unsigned quarantined;struct {uint64_t x[8];}last_output;}mCpAperture;
static uint32_t group=HCI_GIC_GPU_BIT,enabled,local,corrupt_write;
static unsigned writes,reads,cases,health=1,full_bad;
static int CpHealth(void*c){(void)c;return health;}
static int CpReady(void*c){(void)c;return full_bad;}
static int Gen7Guard(void*c){(void)c;return full_bad;}
static uint32_t MmioRead32(uint32_t a){reads++;if(a==HCI_GIC_GROUP)return group;if(a==HCI_GIC_ENABLE)return enabled;assert(a==0x3d000e0);return local;}
static uint32_t fail_read;
static int GpuTryRead32(uint64_t a,uint32_t*v){if(a==fail_read)return 2;*v=MmioRead32((uint32_t)a);return 0;}
static void MmioWrite32(uint32_t a,uint32_t v){assert(a==0x3d000e0 && v==HCI_GPU_ERROR_MASK);writes++;local=v^corrupt_write;}
'''+ '\n'.join(fn(x) for x in ('CpPolledHealthy','CpPolledReady','CpReuseAperture','CpPolledWriteMask'))+r'''
static void reset(void){mCpGicMapped=health=1;mCpIrqMask=mCpGicGroup=mCpGicEnable=mCpIrqBefore=mCpIrqAfter=0;mCpFirmwareVersion[0]=0x40020014;mCpInit.phase=7;mCpInit.raw_attempted=0;mCpBoundaryLog=(struct hll_result){.phase=5,.restored=1};mCpIrqLog=mCpBoundaryLog;mCpApertureCalled=mCpApertureValid=1;mCpApertureResult=mCpAperture.quarantined=0;mCpAperture.last_output.x[0]=0;group=HCI_GIC_GPU_BIT;enabled=local=corrupt_write=writes=reads=full_bad=0;}
int main(void){reset();assert(!CpPolledWriteMask(0x3d000e0,HCI_GPU_ERROR_MASK) && writes==1 && local==HCI_GPU_ERROR_MASK && mCpIrqMask==local && CpPolledHealthy(0) && !CpReuseAperture(0));cases++;
 for(uint32_t a=0x3d00000;a<0x3d40000;a+=4){reset();unsigned good=a==0x3d000e0;assert((!CpPolledWriteMask(a,HCI_GPU_ERROR_MASK))==good && writes==good);cases++;}
 for(unsigned b=0;b<32;b++){reset();assert(CpPolledWriteMask(0x3d000e0,HCI_GPU_ERROR_MASK^(1u<<b)) && !writes);cases++;}
 for(unsigned b=0;b<32;b++){reset();corrupt_write=1u<<b;assert(CpPolledWriteMask(0x3d000e0,HCI_GPU_ERROR_MASK) && writes==1 && !mCpIrqMask);cases++;}
 unsigned *ones[]={&mCpGicMapped,&mCpInit.phase,&mCpFirmwareVersion[0],&mCpBoundaryLog.phase,&mCpBoundaryLog.restored};
 for(unsigned i=0;i<sizeof ones/sizeof ones[0];i++){reset();*ones[i]=0;assert(CpPolledWriteMask(0x3d000e0,HCI_GPU_ERROR_MASK) && !writes);cases++;}
 unsigned *zeros[]={&mCpIrqMask,&mCpInit.raw_attempted,&mCpBoundaryLog.code,&full_bad};
 for(unsigned i=0;i<sizeof zeros/sizeof zeros[0];i++){reset();*zeros[i]=1;assert(CpPolledWriteMask(0x3d000e0,HCI_GPU_ERROR_MASK) && !writes);cases++;}
 reset();group=0;assert(CpPolledWriteMask(0x3d000e0,HCI_GPU_ERROR_MASK) && !writes && reads==1);cases++;
 reset();enabled=HCI_GIC_GPU_BIT;assert(CpPolledWriteMask(0x3d000e0,HCI_GPU_ERROR_MASK) && !writes && reads==2);cases++;
 reset();local=1;assert(CpPolledWriteMask(0x3d000e0,HCI_GPU_ERROR_MASK) && !writes);cases++;
 reset();enabled=~HCI_GIC_GPU_BIT;assert(!CpPolledWriteMask(0x3d000e0,HCI_GPU_ERROR_MASK) && CpPolledHealthy(0));cases++;
 unsigned *lease[]={&mCpGicMapped,&health};
 for(unsigned i=0;i<2;i++){reset();assert(!CpPolledWriteMask(0x3d000e0,HCI_GPU_ERROR_MASK));reads=0;*lease[i]=0;assert(!CpPolledHealthy(0) && !reads);cases++;}
 for(unsigned i=0;i<3;i++){reset();assert(!CpPolledWriteMask(0x3d000e0,HCI_GPU_ERROR_MASK));if(i==0)group=0;if(i==1)enabled=HCI_GIC_GPU_BIT;if(i==2)local^=1;assert(!CpPolledHealthy(0));cases++;}
 unsigned *old[]={&mCpApertureResult,&mCpAperture.quarantined,&mCpBoundaryLog.code,&mCpIrqLog.code};
 for(unsigned i=0;i<4;i++){reset();assert(!CpPolledWriteMask(0x3d000e0,HCI_GPU_ERROR_MASK));*old[i]=1;assert(CpReuseAperture(0));cases++;}
 reset();assert(!CpPolledWriteMask(0x3d000e0,HCI_GPU_ERROR_MASK));mCpApertureCalled=2;assert(CpReuseAperture(0));cases++;
 for(unsigned i=0;i<3;i++){reset();assert(!CpPolledWriteMask(0x3d000e0,HCI_GPU_ERROR_MASK));fail_read=i==0?HCI_GIC_GROUP:i==1?HCI_GIC_ENABLE:0x3d000e0;assert(!CpPolledHealthy(0));fail_read=0;cases++;}
 printf("PASS: %u actual polled IRQ cases; only fixed HWSCHED local mask, no GIC writes, NS-group+CPU-disable proof, partial writes retained, current power/lease and single real aperture required\n",cases);
}
'''
with tempfile.TemporaryDirectory() as folder:
 f=Path(folder);(f/'test.c').write_text(program)
 subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(p/'native/gpu/uefi'),str(f/'test.c'),'-o',str(f/'test')],check=True)
 subprocess.run([str(f/'test')],check=True)
