#!/usr/bin/env python3
"""Run the real fixed NC native adapter with architectural AT/barrier shims.

No real EFI service, GPU access, SMC or firmware is executed. The submit shim
models device writes only after checking the actual adapter's exact IB words.
"""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''
#define HGKI_NATIVE_HOST_TEST 1
#define STATIC static
#define CONST const
#define VOID void
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
typedef uint8_t UINT8;
typedef uint32_t UINT32;
typedef uint64_t UINT64;
typedef uintptr_t UINTN;
#define MAX_UINTN UINTPTR_MAX
#define TPL_APPLICATION 4
#include "uefi/GpuFirmwareMemory.h"
#include "uefi/GpuHostRing.h"
static unsigned checks;
#define CHECK(X) do {++checks;if(!(X)){fprintf(stderr,"native:%d %s\n",__LINE__,#X);assert(X);}}while(0)
static struct hfm_allocation mGpuOnlyMemory;
static UINT32 mGpuOnlyNext[HSC_CLASSES];
static ArmSmmu4KRange mScratchRanges[HSC_GPU_RANGES];
static ArmSmmu4KConfig mScratchConfig;
static ArmSmmu4KResult mScratchBuilt;
static UINT64 mScratchTablePhysical,*mScratchTables;
static struct hhr_result mHostRing;
static struct {unsigned started,authenticated,submitted,idle,complete,phase,code;} mHostMode;
static struct {unsigned stage,stopped,cm3_reset;uint32_t ack[3];} mHostBusStop;
static struct {unsigned quarantined;struct {uint64_t x[8];} last_output;} mHostAperture;
static unsigned mHostRingUnsafe,mHostRingPrepared,mHostWriteCalls,mHostWriteFaults,mHostRingCpFailed;
static unsigned mGpuSaveAllowed,mHostApertureKind,mHostApertureValid,mHostApertureCode;
static UINT64 mHostApertureAvailable;
static unsigned prep_calls,prep_fail,firmware_calls,firmware_fail,audit_calls,audit_fail;
static unsigned tpl,tpl_calls,at_calls,at_fail,at_bad,barriers,corrupt_barrier,prints;
static unsigned owner_calls,owner_fail,submit_calls,idle_calls,submit_fail,idle_fail;
static unsigned gpu_mode,late_unsafe,trace_calls,corrupt_initial,owner_mutation;
static unsigned lease_calls,lease_fail,post_reads,isolation_fail;
static UINT8 *allocation,*arena;
static UINT64 tables[4096];
static int in_runtime;
static int HostRingBusLease(void) {CHECK(!in_runtime);return ++lease_calls==lease_fail;}
static int StockRead32(void *unused,uint32_t a,uint32_t *v) {
 (void)unused;CHECK(!in_runtime && a==0x3d7e000 && v);++post_reads;*v=isolation_fail==1?0:1;return isolation_fail==4;
}
static int GpuTryRead32(uint32_t a,uint32_t *v) {
 CHECK(!in_runtime && (a==0x3d0005c || a==0x3d0f118) && v);++post_reads;
 *v=a==0x3d0005c?(isolation_fail==2?0:1):(isolation_fail==3?1:3);return isolation_fail==5;
}
static int HostPreparationGuard(void *unused) {
 (void)unused;CHECK(!in_runtime);return ++prep_calls==prep_fail;
}
static unsigned LiveLogTpl(void *unused) {(void)unused;CHECK(!in_runtime);++tpl_calls;return tpl;}
static int FirmwareVerifyPages(uint64_t physical,void *cpu,unsigned pages,unsigned nc) {
 CHECK(!in_runtime);++firmware_calls;CHECK(physical==mGpuOnlyMemory.physical && cpu==arena);
 CHECK(pages==HSC_POOL_PAGES && nc==1);return firmware_fail;
}
static int ScratchAudit(void) {CHECK(!in_runtime);++audit_calls;return audit_fail;}
static void Print(const wchar_t *fmt,...) {CHECK(!in_runtime && fmt);++prints;}
static void trace(unsigned s,uint64_t a,uint64_t v) {
 CHECK(in_runtime && s==0x7300 && a==0x62084000 && v==(HGKI_PROGRESS?287:247));++trace_calls;
}
#define HOUJI_CALL_TRACE(S,A,V) trace(S,A,V)
#include "uefi/GpuKnownImage2dNative.h"
static int KnownImage2dAtPage(UINT64 physical,UINT64 *r,UINT64 *w) {
 ++at_calls;CHECK(r && w && !(physical&4095));
 CHECK(physical>=0x20080000 && physical<0x20087000);
 *r=*w=physical|(UINT64_C(0x44)<<56);
 if(at_bad==1)*r|=1;
 if(at_bad==2)*w|=1;
 if(at_bad==3)*r^=4096;
 if(at_bad==4)*w^=4096;
 if(at_bad==5)*r=physical|(UINT64_C(0xff)<<56);
 if(at_bad==6)*w=physical;
 return at_calls==at_fail;
}
static void KnownImage2dBarrier(void) {
 ++barriers;
 if(corrupt_barrier==barriers)arena[HGKI_CLASS_CURSOR]^=1;
}
static int owner(void *c,unsigned phase) {
 CHECK(c==(void *)(uintptr_t)0x55 && in_runtime && mKnownImage2dNative.running);
 CHECK(phase>=1 && phase<=5);++owner_calls;
 if(owner_mutation && owner_calls==owner_mutation)mGpuOnlyNext[2]+=4096;
 return owner_calls==owner_fail;
}
static int submit(void *c,const uint32_t *w,unsigned n) {
 CHECK(c==(void *)(uintptr_t)0x55 && in_runtime && mKnownImage2dNative.running);
 CHECK(n==4 && w==hgki_ib && w[0]==hhr_pkt7(0x3f,3));
 CHECK(w[1]==HGKI_COMMAND && !w[2] && w[3]==HGKI_SELECTED_COMMAND_WORDS);++submit_calls;
 CHECK(mKnownImage2dNative.initial_valid && mKnownImage2d.submit_attempted);
 CHECK(mHostRing.rptr==12 && mHostRing.wptr==12);
 CHECK(arena[HGKI_CLASS_CURSOR+5*HGKI_PAGE]==0x6d);
 CHECK(mGpuOnlyNext[2]==0x87000 && !prints);
 if(submit_fail)return 10;
 mHostRing.wptr=16;
 if(late_unsafe)mHostRingUnsafe=0;
 return 0;
}
static int idle(void *c) {
 CHECK(c==(void *)(uintptr_t)0x55 && in_runtime && mKnownImage2dNative.running);
 CHECK(submit_calls==1 && mKnownImage2d.submit_returned);++idle_calls;
 if(idle_fail)return 11;
 for(unsigned m=0;m<HGKI_PROGRESS_MARKERS;m++) {
  if(gpu_mode==7 && m+1==HGKI_PROGRESS_MARKERS)continue;
  uint32_t v=hgki_marker_value(m);
  for(unsigned b=0;b<4;b++)arena[HGKI_CLASS_CURSOR+4*m+b]=(uint8_t)(v>>(8*b));
 }
 if(gpu_mode!=1)for(unsigned i=0;i<HGKI_OUTPUT_BYTES;i++)
  arena[HGKI_CLASS_CURSOR+5*HGKI_PAGE+i]=(i%4==0 || i%4==3)?255:0;
 if(gpu_mode==2)arena[HGKI_CLASS_CURSOR+5*HGKI_PAGE+2047]^=1;
 if(gpu_mode==3)arena[HGKI_CLASS_CURSOR+6*HGKI_PAGE+4095]^=1;
 if(gpu_mode==4)arena[HGKI_CLASS_CURSOR+4*HGKI_PAGE+17]^=1;
 if(gpu_mode!=5)mHostRing.rptr=16;
 if(gpu_mode==6)mHostRing.busy=1u<<23;
 return 0;
}
static const struct hgki_native_owner ops={(void *)(uintptr_t)0x55,owner,submit,idle};
static void reset(void) {
 memset(&mKnownImage2dNative,0,sizeof mKnownImage2dNative);
 memset(&mKnownImage2d,0,sizeof mKnownImage2d);memset(mKnownImage2dReadback,0x97,sizeof mKnownImage2dReadback);
 memset(&mHostRing,0,sizeof mHostRing);memset(&mHostMode,0,sizeof mHostMode);
 memset(&mHostAperture,0,sizeof mHostAperture);memset(&mHostBusStop,0,sizeof mHostBusStop);
 memset(mScratchRanges,0,sizeof mScratchRanges);memset(arena,0,HSC_POOL_BYTES);
 memset(allocation,0x7f,4096);memset(arena+HSC_POOL_BYTES,0x7f,4096);
 mGpuOnlyMemory=(struct hfm_allocation){0x20000000,arena,HSC_POOL_PAGES,1,HSC_GPU_ONLY_IOVA};
 for(unsigned i=0;i<4;i++)mGpuOnlyNext[i]=i*HSC_CLASS_BYTES;
 mScratchRanges[HSC_CLASSES+3]=(ArmSmmu4KRange){HGKI_BASE,0x20080000,HSC_CLASS_BYTES,3,0,3};
 mScratchTables=tables;mScratchTablePhysical=0x21000000;
 mScratchConfig=(ArmSmmu4KConfig){32,36,0x21000000,HSC_GPU_LEAF_PAGES};
 mScratchBuilt=(ArmSmmu4KResult){.root_physical=0x21000000};
 mHostRingUnsafe=mHostRingPrepared=mHostWriteCalls=mHostWriteFaults=mHostRingCpFailed=0;
 mGpuSaveAllowed=1;mHostApertureKind=mHostApertureValid=mHostApertureCode=0;mHostApertureAvailable=0;
 prep_calls=prep_fail=firmware_calls=firmware_fail=audit_calls=audit_fail=0;
 tpl=4;tpl_calls=at_calls=at_fail=at_bad=barriers=corrupt_barrier=prints=0;
 owner_calls=owner_fail=submit_calls=idle_calls=submit_fail=idle_fail=0;
 gpu_mode=late_unsafe=trace_calls=corrupt_initial=owner_mutation=0;in_runtime=0;
 lease_calls=lease_fail=post_reads=isolation_fail=0;
}
static void bounds(void) {
 for(unsigned i=0;i<4096;i++)CHECK(allocation[i]==0x7f && arena[HSC_POOL_BYTES+i]==0x7f);
 for(unsigned i=0;i<HGKI_CLASS_CURSOR;i++)CHECK(arena[i]==0);
 for(unsigned i=HGKI_CLASS_CURSOR+HGKI_BYTES;i<HSC_POOL_BYTES;i++)CHECK(arena[i]==0);
 CHECK(mGpuOnlyNext[0]==0 && mGpuOnlyNext[1]==HSC_CLASS_BYTES && mGpuOnlyNext[3]==3*HSC_CLASS_BYTES);
}
static void prepared(void) {
 CHECK(KnownImage2dNativePrepare()==HGKIN_OK);
 CHECK(mKnownImage2dNative.ready && mKnownImage2dNative.retained);
 CHECK(mKnownImage2dNative.published_pages==7 && mKnownImage2dNative.verified_pages==7);
 CHECK(mKnownImage2dNative.table_valid && !mKnownImage2dNative.aperture_valid);
 CHECK(mGpuOnlyNext[2]==0x87000 && at_calls==14 && firmware_calls==1 && audit_calls==1);
 for(unsigned i=0;i<HGKI_BYTES;i++)CHECK(arena[HGKI_CLASS_CURSOR+i]==hgki_initial_byte(i));
}
static void running(void) {
 mHostRingUnsafe=mHostRingPrepared=mHostWriteCalls=1;mGpuSaveAllowed=0;
 mHostRing=(struct hhr_result){.started=1,.phase=4,.enabled=1,.init_idle=1,.rptr=12,.wptr=12,.busy_valid=1};
 mHostMode=(typeof(mHostMode)){1,1,1,1,1,5,0};
 mHostApertureKind=2;mHostApertureValid=1;mHostApertureAvailable=1;in_runtime=1;
}
static unsigned run(void) {return RunKnownImage2d(&ops,1);}
static void success(void) {
 reset();prepared();unsigned prepare_guards=prep_calls;bounds();
 CHECK(KnownImage2dNativePrepare()==HGKIN_REUSED && prep_calls==prepare_guards);
 running();CHECK(run()==HGKIN_OK);CHECK(mKnownImage2d.verified && mKnownImage2d.phase==8);
 CHECK(mKnownImage2d.completed && mKnownImage2d.readback_valid && mKnownImage2d.output_crc==0xe843b26a);
 CHECK(submit_calls==1 && idle_calls==1 && trace_calls==1 && mKnownImage2dNative.read_pages==14);
 CHECK(at_calls==28 && mKnownImage2dNative.aperture_valid);
 CHECK(!mKnownImage2dNative.running && mKnownImage2dNative.retained && mGpuOnlyNext[2]==0x87000);
 CHECK(run()==HGKIN_REUSED && submit_calls==1);bounds();
 KnownImage2dReport();CHECK(!prints);in_runtime=0;mHostRingUnsafe=0;mGpuSaveAllowed=1;
 KnownImage2dReport();CHECK(prints==4+HGKI_PROGRESS_MARKERS);
}
static void prepare_failures(void) {
 reset();prepared();unsigned n=prep_calls;
 for(unsigned i=1;i<=n;i++) {
  reset();prep_fail=i;CHECK(KnownImage2dNativePrepare()!=HGKIN_OK);
  CHECK(!mKnownImage2dNative.ready && !submit_calls && !idle_calls);
  CHECK(mGpuOnlyNext[2]==(mKnownImage2dNative.retained?0x87000:0x80000));
  CHECK(KnownImage2dNativePrepare()==HGKIN_REUSED);
 }
 for(unsigned i=1;i<=14;i++) {
  reset();at_fail=i;CHECK(KnownImage2dNativePrepare()==HGKIN_TRANSLATION);
  CHECK(mKnownImage2dNative.at_failed && !mKnownImage2dNative.ready);
  CHECK(mGpuOnlyNext[2]==(i<=7?0x80000:0x87000));
 }
 for(unsigned i=1;i<=6;i++) {
  reset();at_bad=i;CHECK(KnownImage2dNativePrepare()==HGKIN_TRANSLATION && at_calls==1);
 }
 if(HGKI_PROGRESS) {
  reset();prepared();running();gpu_mode=7;CHECK(run()==HGKIN_VERIFY && mKnownImage2d.code==HGKI_CHANGED);
 }
 reset();tpl=8;CHECK(KnownImage2dNativePrepare()==HGKIN_TPL && !at_calls);
 reset();firmware_fail=1;CHECK(KnownImage2dNativePrepare()==HGKIN_MEMORY && !audit_calls);
 reset();audit_fail=1;CHECK(KnownImage2dNativePrepare()==HGKIN_MEMORY && !at_calls);
 reset();arena[HGKI_CLASS_CURSOR+HGKI_BYTES-1]=1;
 CHECK(KnownImage2dNativePrepare()==HGKIN_VIRGIN && !mKnownImage2dNative.retained);
 reset();corrupt_barrier=8;CHECK(KnownImage2dNativePrepare()==HGKIN_PUBLISH);
 CHECK(mKnownImage2dNative.retained && mKnownImage2dNative.published_pages==1);
 for(unsigned i=0;i<18;i++) {
  reset();switch(i) {
   case 0:mHostRingUnsafe=1;break;case 1:mHostRing.enabled=1;break;case 2:mHostWriteCalls=1;break;
   case 3:mHostRingPrepared=1;break;case 4:mHostRing.started=1;break;case 5:mGpuSaveAllowed=0;break;
   case 6:mGpuOnlyNext[2]+=4096;break;case 7:mGpuOnlyMemory.nc=0;break;
   case 8:mGpuOnlyMemory.pages--;break;case 9:mGpuOnlyMemory.iova++;break;
   case 10:mGpuOnlyMemory.physical=UINT64_MAX;break;case 11:mGpuOnlyMemory.cpu=NULL;break;
   case 12:mScratchRanges[7].permissions|=ArmSmmu4KPrivileged;break;
   case 13:mScratchRanges[7].permissions|=ArmSmmu4KExecute;break;
   case 14:mScratchRanges[7].writeback=1;break;case 15:mScratchRanges[7].shareability=2;break;
   case 16:mScratchBuilt.root_physical++;break;case 17:mScratchConfig.table_physical++;break;
  }
  CHECK(KnownImage2dNativePrepare()!=HGKIN_OK);CHECK(!at_calls && !mKnownImage2dNative.retained);
 }
}
static void runtime_failures(void) {
 reset();prepared();running();CHECK(run()==HGKIN_OK);unsigned n=owner_calls;
 for(unsigned i=1;i<=n;i++) {
  reset();prepared();running();owner_fail=i;CHECK(run()!=HGKIN_OK);
  CHECK(!mKnownImage2d.verified && mKnownImage2dNative.retained && mGpuOnlyNext[2]==0x87000);
  CHECK(run()==HGKIN_REUSED);
 }
 for(unsigned i=15;i<=28;i++) {
  reset();prepared();running();at_fail=i;CHECK(run()==HGKIN_READBACK);
  CHECK(mKnownImage2dNative.at_failed && !mKnownImage2d.verified);
 }
 reset();CHECK(run()==HGKIN_NOT_PREPARED && !submit_calls);
 reset();prepared();running();CHECK(RunKnownImage2d(NULL,1)==HGKIN_QUALIFICATION && !submit_calls);
 reset();prepared();running();CHECK(RunKnownImage2d(&ops,0)==HGKIN_QUALIFICATION && !submit_calls);
 reset();prepared();running();submit_fail=1;CHECK(run()==HGKIN_SUBMIT && !idle_calls);
 reset();prepared();running();idle_fail=1;CHECK(run()==HGKIN_IDLE && !mKnownImage2d.completed);
 reset();prepared();running();late_unsafe=1;CHECK(run()==HGKIN_OWNER && !idle_calls);
 reset();prepared();running();owner_mutation=1;CHECK(run()!=HGKIN_OK && !submit_calls);
 for(unsigned page=0;page<7;page++) {
  reset();prepared();arena[HGKI_CLASS_CURSOR+page*HGKI_PAGE+17]^=1;running();
  CHECK(run()==HGKIN_READBACK && !submit_calls && !mKnownImage2dNative.initial_valid);
 }
 for(unsigned i=1;i<=6;i++) {
  reset();prepared();running();gpu_mode=i;CHECK(run()!=(unsigned)HGKIN_OK);
  if(i<5)CHECK(mKnownImage2d.readback_valid && !mKnownImage2d.verified);
  else CHECK(!mKnownImage2d.completed && !mKnownImage2d.readback_valid);
  if(i==1)CHECK(mKnownImage2d.code==HGKI_COLOR && mKnownImage2d.first_bad==5*HGKI_PAGE);
  if(i==3)CHECK(mKnownImage2d.code==HGKI_CHANGED && mKnownImage2d.first_bad==HGKI_BYTES-1);
 }
 for(unsigned i=0;i<29;i++) {
  reset();prepared();running();switch(i) {
   case 0:mHostRingUnsafe=0;break;case 1:mGpuSaveAllowed=1;break;case 2:mHostRingPrepared=0;break;
   case 3:mHostRing.enabled=0;break;case 4:mHostRing.init_idle=0;break;case 5:mHostRing.phase=5;break;
   case 6:mHostRing.code=1;break;case 7:mHostRing.stopped=1;break;case 8:mHostRingCpFailed=1;break;
   case 9:mHostBusStop.stage=1;break;case 10:mHostWriteFaults=1;break;case 11:mHostMode.authenticated=0;break;
   case 12:mHostMode.submitted=0;break;case 13:mHostMode.idle=0;break;case 14:mHostMode.code=1;break;
   case 15:mHostMode.phase=3;break;case 16:mHostApertureKind=1;break;case 17:mHostApertureValid=0;break;
   case 18:mHostApertureAvailable=0;break;case 19:mHostApertureCode=1;break;case 20:mHostAperture.quarantined=1;break;
   case 21:mHostAperture.last_output.x[0]=1;break;case 22:mGpuOnlyNext[2]++;break;
   case 23:mKnownImage2dNative.source_valid=0;break;case 24:mKnownImage2dNative.table_valid=0;break;
   case 25:mHostRing.rptr=11;break;case 26:mHostRing.busy_valid=0;break;case 27:mHostRing.busy=1u<<23;break;
   case 28:mGpuOnlyMemory.cpu=(void *)(uintptr_t)1;break;
  }
  CHECK(run()!=HGKIN_OK && !submit_calls && !mKnownImage2d.verified);
 }
}
static void isolated(void) {
 in_runtime=0;mHostRingUnsafe=0;mGpuSaveAllowed=1;mHostRing.stopped=1;
 mHostBusStop=(typeof(mHostBusStop)){.stage=5,.stopped=1,.cm3_reset=1,.ack={1,3,3}};
}
static void diagnostic(void) {
 reset();prepared();running();idle_fail=1;CHECK(run()==HGKIN_IDLE);isolated();
 struct hgki_result original=mKnownImage2d;
 if(!HGKI_PROGRESS) {CHECK(KnownImage2dIsolatedCapture()==HGKIN_ISOLATION && !post_reads);return;}
 for(unsigned m=0;m<4;m++)for(unsigned b=0;b<4;b++)
  arena[HGKI_CLASS_CURSOR+4*m+b]=(uint8_t)(hgki_marker_value(m)>>(8*b));
 for(unsigned i=0;i<32*4;i++)arena[HGKI_CLASS_CURSOR+5*HGKI_PAGE+i]=(i%4==0 || i%4==3)?255:0;
 CHECK(KnownImage2dIsolatedCapture()==HGKIN_OK);
 CHECK(mKnownImage2dNative.diagnostic_valid && mKnownImage2dNative.diagnostic_pages==7);
 CHECK(mKnownImage2dNative.diagnostic_marker_mask==15 && mKnownImage2dNative.diagnostic_red_pixels==32);
 CHECK(mKnownImage2dNative.diagnostic_guards_intact && !memcmp(&original,&mKnownImage2d,sizeof original));
 CHECK(!mKnownImage2d.completed && !mKnownImage2d.readback_valid && !mKnownImage2d.verified);
 CHECK(mKnownImage2dNative.diagnostic_marker[4]==0xa5a5a5a5);
 unsigned total=lease_calls,reads=post_reads;
 CHECK(KnownImage2dIsolatedCapture()==HGKIN_REUSED && post_reads==reads);
 for(unsigned i=1;i<=total;i++) {
  reset();prepared();running();idle_fail=1;CHECK(run()==HGKIN_IDLE);isolated();lease_fail=i;
  CHECK(KnownImage2dIsolatedCapture()==HGKIN_ISOLATION && !mKnownImage2dNative.diagnostic_valid);
  CHECK(!mKnownImage2d.completed && !mKnownImage2d.verified);
 }
 for(unsigned i=1;i<=5;i++) {
  reset();prepared();running();idle_fail=1;CHECK(run()==HGKIN_IDLE);isolated();isolation_fail=i;
  CHECK(KnownImage2dIsolatedCapture()==HGKIN_ISOLATION && !mKnownImage2dNative.diagnostic_pages);
 }
 for(unsigned i=0;i<13;i++) {
  reset();prepared();running();idle_fail=1;CHECK(run()==HGKIN_IDLE);isolated();switch(i) {
   case 0:mHostRingUnsafe=1;break;case 1:mGpuSaveAllowed=0;break;case 2:mHostRing.stopped=0;break;
   case 3:mHostBusStop.stage=4;break;case 4:mHostBusStop.stopped=0;break;case 5:mHostBusStop.cm3_reset=0;break;
   case 6:mHostBusStop.ack[0]=0;break;case 7:mHostBusStop.ack[1]=2;break;case 8:mHostBusStop.ack[2]=1;break;
   case 9:mKnownImage2dNative.retained=0;break;case 10:mKnownImage2dNative.table_valid=0;break;
   case 11:mGpuOnlyNext[2]++;break;case 12:mGpuOnlyMemory.cpu=(void *)(uintptr_t)1;break;
  }
  CHECK(KnownImage2dIsolatedCapture()==HGKIN_ISOLATION && !post_reads && !mKnownImage2dNative.diagnostic_pages);
 }
 reset();prepared();running();idle_fail=1;CHECK(run()==HGKIN_IDLE);isolated();firmware_fail=1;
 CHECK(KnownImage2dIsolatedCapture()==HGKIN_MEMORY && !mKnownImage2dNative.diagnostic_valid);
 reset();prepared();running();idle_fail=1;CHECK(run()==HGKIN_IDLE);isolated();at_fail=at_calls+1;
 CHECK(KnownImage2dIsolatedCapture()==HGKIN_TRANSLATION && !mKnownImage2dNative.diagnostic_valid);
}
int main(void) {
 allocation=malloc(HSC_POOL_BYTES+8192);CHECK(allocation);arena=allocation+4096;
 success();prepare_failures();runtime_failures();diagnostic();free(allocation);
 printf("%u actual native fixed-2D checks PASS progress=%u\n",checks,HGKI_PROGRESS);return 0;
}
'''

with tempfile.TemporaryDirectory(prefix="houji-known-image-native-") as tmp:
    source = Path(tmp) / "native.c"
    binary = Path(tmp) / "native"
    source.write_text(SOURCE)
    for progress in (0, 1):
      subprocess.run([
        "clang", "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-O1", "-g",
        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
        f"-DHGKI_PROGRESS={progress}",
        "-I", str(ROOT / "native/gpu"), str(source), "-o", str(binary)
      ], check=True)
      env = os.environ.copy()
      env["ASAN_OPTIONS"] = "detect_leaks=0:abort_on_error=1"
      env["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
      subprocess.run([str(binary)], check=True, env=env)
