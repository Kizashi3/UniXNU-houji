/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Exact A750 host command ring binding. Ordinary GPU-only privileged RW/NX
 * pages, no GMU alias, allocation or table changes while SQE is running.
 */
#ifndef HOUJI_GPU_HOST_RING_NATIVE_H
#define HOUJI_GPU_HOST_RING_NATIVE_H
#include "GpuHostRing.h"
#include "GpuKnownImage2d.h"
#include "GpuFirstContext.h"
#include "GpuHostWriteFaultNative.h"
STATIC VOID HostRingReport(VOID);
STATIC int HostRingLoadAuthenticatedZap(VOID);
STATIC int HostRingRunKnownImage(VOID);
STATIC int HostRingBuildFirstContext(VOID);
STATIC CONST uint32_t *HostRingFirstContextWords(VOID);
STATIC int HostRingFirstContextMatch(CONST uint32_t *Words,unsigned Count);
STATIC unsigned CaptureGraphicsStall(unsigned Stage);
STATIC struct hhr_result mHostRing;
STATIC struct ggs_state mHostAperture;
STATIC unsigned mHostApertureKind,mHostApertureCalls,mHostApertureValid,mHostRingPrepared;
STATIC unsigned mHostApertureQueryCode,mHostApertureCode;
STATIC UINT64 mHostApertureAvailable,mHostApertureElapsed,mHostRingRoots[4];
STATIC struct hll_result mHostRingLog;
STATIC struct hll_result mHostEngineLog;
STATIC unsigned mHostEngineStopped,mHostEngineComplete,mHostRingEntryReady,mHostRingCpFailed,mHostDirectReady;
STATIC struct {unsigned started,authenticated,published,submitted,idle,complete,phase,code;} mHostMode;
STATIC struct {unsigned started,published,submitted,idle,complete,phase,code,kick_code,idle_code,stall_code;} mHostImage;
STATIC struct {unsigned started,built,published,submitted,idle,complete,phase,code,kick_code,idle_code,stall_code;} mHostContext;
STATIC struct {unsigned valid,operation,code;uint32_t address,value;} mHostFirstIo;
enum {HHG_BUS_POWER=1,HHG_POWER,HHG_ROUTES,HHG_GUARD,HHG_LEASE,HHG_LOG,HHG_ENGINE,HHG_READ};
enum {HHG_STATE=1,HHG_POWER_OWNER,HHG_REGISTER,HHG_BOOTSTRAP,HHG_PREPARATION,HHG_CONTEXT,
 HHG_AUDIT,HHG_QUEUE,HHG_MEMORY,HHG_ARGUMENT,HHG_ALLOW};
enum {HHR_NATIVE_ARGUMENT=1,HHR_NATIVE_ALLOW,HHR_NATIVE_GUARD,HHR_NATIVE_READ};
STATIC struct {unsigned seen,phase,stage,kind,valid;uint32_t address;
 uint64_t mask,expected,actual;int read_code;} mHostFirstGuard;
STATIC struct {unsigned reads,busy,idle_required,valid;uint32_t last;} mHostRingBusy;
struct hhs_sample {unsigned valid,failed;uint32_t sqe,rptr,status,irq,fault,busy;};
STATIC struct {unsigned polls,timeout;int read_code;uint32_t wptr;
 struct hhs_sample first,last;} mHostStopPoll;
// REGISTER valid identifies an actual successful raw register read. Other
// kinds describe CPU state or an opaque wrapper result, never a new MMIO read;
// QUEUE/MEMORY address is a logical selector rather than a register address.
STATIC int HostRingGuardFailure(unsigned Stage,unsigned Kind,uint32_t Address,uint64_t Mask,
 uint64_t Expected,uint64_t Actual,unsigned Valid,int ReadCode) {
 if(!mHostFirstGuard.seen)mHostFirstGuard=(__typeof__(mHostFirstGuard)){
  1,mHostRing.phase,Stage,Kind,Valid,Address,Mask,Expected,Actual,ReadCode};
 return 1;
}
STATIC int HostRingCheck32(unsigned Stage,uint32_t Address,uint32_t Mask,uint32_t Expected) {
 uint32_t V=0;int Code=GpuTryRead32(Address,&V);
 if(Code)return HostRingGuardFailure(Stage,HHG_REGISTER,Address,Mask,Expected,0,0,Code);
 return (V&Mask)!=Expected?HostRingGuardFailure(Stage,HHG_REGISTER,Address,Mask,Expected,V,1,0):0;
}
STATIC int HostRingCheckRoot(unsigned Stage,uint32_t Address,uint64_t Expected) {
 uint64_t V=0;int Code=GpuTryRead64(Address,&V);
 if(Code)return HostRingGuardFailure(Stage,HHG_REGISTER,Address,UINT64_MAX,Expected,0,0,Code);
 return V!=Expected?HostRingGuardFailure(Stage,HHG_REGISTER,Address,UINT64_MAX,Expected,V,1,0):0;
}
STATIC int HostRingIoFailed(unsigned Operation,uint32_t Address,uint32_t Value,unsigned Code) {
 if(!mHostFirstIo.valid) {
  mHostFirstIo=(__typeof__(mHostFirstIo)){1,Operation,Code,Address,Value};
#ifdef HOUJI_CALL_TRACE_NATIVE
  HoujiGpuCallTraceFreezeFirstFailure();
#endif
 }
 if(mHostRing.enabled)mHostRingCpFailed=1;return 1;
}
STATIC int HostRingStop(VOID *Cookie,uint32_t Wptr);
// Mainline host-ring hw_init differs from vendor HWSCHED configuration:
// deassert both GBIF halts and disable the unused trusted VA range. This does
// NOT write RBBM_SECVID_TRUST_CNTL or leave secure mode; PAS remains separate.
STATIC CONST uint32_t mHostHwAddresses[]={0x3d0f114,0x3d00058,0x3d02800,
 0x3d3e00c,0x3d3e000,0x3d3e004,0x3d3e008};
STATIC uint32_t mHostHwBefore[7],mHostHwAfter[7];
STATIC unsigned mHostHwDone;
STATIC struct {unsigned stage,stopped,valid,cm3_reset;uint32_t sqe,ack[3],fsr,fsynr,gfsr,gmu_fsr;uint64_t far;} mHostBusStop;
STATIC CONST uint32_t mHostRingRootAddresses[]={0x3dc0020,0x3dc0028,0x3dc2020,0x3dc2028};
STATIC CONST uint32_t mHostRingSnapshotAddresses[]={
 0x3d7e340,0x3d8ec40,0x3d8ec30,0x3d8ec4c,0x3da0048,0x3dc0058,0x3dc0068,0x3dc2058,
 0x3d02000,0x3d02004,0x3d02008,0x3d02010,0x3d02014,0x3d02018,0x3d0201c,0x3d02020,
 0x3d02048,0x3d02084,0x3d0208c,0x3d02090,0x3d02094,0x3d020c0,0x3d020c4,
 0x3d02a60,0x3d02a64,0x3d00840,0x3d0084c,0x3d00804,0x3d000e0,0x3d02110};
STATIC struct {unsigned taken;uint32_t valid,word[30],scratch[4];} mHostRingSnapshots[6];
STATIC volatile uint32_t *HostRingCpu(VOID) {
 return (volatile uint32_t *)((UINTN)mGpuOnlyMemory.cpu+3*HSC_CLASS_BYTES);
}
STATIC int HostRingBusPower(VOID) {
 // CPU-only failure bitmap, in the original short-circuit condition order.
 // Bits 0..35 identify each original state gate; no new hardware observation.
 uint64_t State=(uint64_t)!mHostProfileReady | ((uint64_t)!!mHostPrep.code<<1) |
  ((uint64_t)(mHostPrep.phase!=6)<<2) | ((uint64_t)!mFirmwareHeld<<3) |
  ((uint64_t)!mGxMapped<<4) | ((uint64_t)!mGen7Mapped<<5) | ((uint64_t)!mCodeReady<<6) |
  ((uint64_t)!mGxStart.acked<<7) | ((uint64_t)!mGxStart.clear_confirmed<<8) |
  ((uint64_t)!mScratchAssigned<<9) | ((uint64_t)!mScratchReady<<10) |
  ((uint64_t)!!mScratchResult.code<<11) | ((uint64_t)(mScratchResult.phase!=5)<<12) |
  ((uint64_t)(mScratchResult.enabled!=1)<<13) | ((uint64_t)(mScratchResult.attached!=1)<<14) |
  ((uint64_t)(mScratchResult.retained!=1)<<15) | ((uint64_t)(mScratchResult.lpac!=1)<<16) |
  ((uint64_t)(mScratchResult.sid0_attached!=1)<<17) | ((uint64_t)(mScratchResult.lpac_attached!=1)<<18) |
  ((uint64_t)(mScratchResult.sid0_smr!=0x80000000u)<<19) | ((uint64_t)!!mScratchResult.sid0_s2cr<<20) |
  ((uint64_t)(mScratchResult.lpac_smr!=0x80000001u)<<21) | ((uint64_t)!!mScratchResult.lpac_s2cr<<22) |
  ((uint64_t)!!mGen7.code<<23) | ((uint64_t)(mGen7.phase!=6)<<24) | ((uint64_t)!mGen7.record_ready<<25) |
  ((uint64_t)!!mCodeBind.code<<26) | ((uint64_t)(mCodeBind.phase!=6)<<27) |
  ((uint64_t)(mCodeBind.verified!=15)<<28) | ((uint64_t)(mFirmwareMemory.retained!=HFM_ALL)<<29) |
  ((uint64_t)!mDmaZeroRetained<<30) | ((uint64_t)!!mSharedCount<<31) |
  ((uint64_t)!!mSecureAssigned<<32) | ((uint64_t)!!mSecureContext.attached<<33) |
  ((uint64_t)!!mSecureMemory.owned<<34) | ((uint64_t)!!mSecureTableOwned<<35);
 if(State)return HostRingGuardFailure(HHG_BUS_POWER,HHG_STATE,0,UINT64_MAX,0,State,1,0);
 CONST struct hgf_io Io={.read=StockRead32};
 int Power=hgf_power(&Io,&mStockResult);
 if(!Power)return HostRingGuardFailure(HHG_BUS_POWER,HHG_POWER_OWNER,0,1,1,Power,1,0);
 return HostRingCheck32(HHG_BUS_POWER,0x3d7e340,3,0) ||
  HostRingCheck32(HHG_BUS_POWER,0x3d8ec40,0xffffffffu,0);
}
STATIC int HostRingPower(VOID) {
 if(HostRingBusPower())return 1;
 // GMU GPU_BUSY is expected after a real SQE start attempt. Continue to
 // observe it on every guard, but do not reject ordinary running I/O for it.
 // enabled alone is insufficient: generic code sets it before the first
 // store, whose fresh pre-start guard must still require an idle GPU.
 unsigned RequireIdle=!(mHostRing.enabled && mHostWriteCalls && mHostRingUnsafe);
 uint32_t Busy=0;int Code=GpuTryRead32(0x3d8ec30,&Busy);
 mHostRingBusy.reads++;mHostRingBusy.valid=!Code;mHostRingBusy.idle_required+=RequireIdle;
 if(Code)return HostRingGuardFailure(HHG_POWER,HHG_REGISTER,0x3d8ec30,1u<<23,0,0,0,Code);
 mHostRingBusy.last=Busy;mHostRingBusy.busy+=!!(Busy&(1u<<23));
 return RequireIdle && (Busy&(1u<<23))?HostRingGuardFailure(HHG_POWER,HHG_REGISTER,0x3d8ec30,1u<<23,0,Busy,1,0):0;
}
STATIC int HostRingRoutes(VOID) {
 // The completed attachment surveyed all 24 slots and 22 banks. Keep the
 // three owned routes fresh in hot guards; no route is changed during a ring.
 return HostRingCheck32(HHG_ROUTES,0x3da0800,0xffffffffu,0x80000005u) ||
  HostRingCheck32(HHG_ROUTES,0x3da0c00,0xffffffffu,2) ||
  HostRingCheck32(HHG_ROUTES,0x3da0804,0xffffffffu,0x80000000u) ||
  HostRingCheck32(HHG_ROUTES,0x3da0c04,0xffffffffu,0) ||
  HostRingCheck32(HHG_ROUTES,0x3da0808,0xffffffffu,0x80000001u) ||
  HostRingCheck32(HHG_ROUTES,0x3da0c08,0xffffffffu,0);
}
STATIC int HostRingGuard(VOID *Cookie) {
 (VOID)Cookie;
 HOUJI_CALL_TRACE(0x6000,0,mHostRingPrepared);
 if(!mHostRingPrepared) {
  int Code=HostPreparationGuard(NULL);HOUJI_CALL_TRACE(0x6001,0,Code);
  return Code?HostRingGuardFailure(HHG_GUARD,HHG_PREPARATION,0,UINT64_MAX,0,Code,1,0):0;
 }
 HOUJI_CALL_TRACE(0x6002,0,0);int Power=HostRingPower();HOUJI_CALL_TRACE(0x6003,0,Power);
 if(Power)return 1;
 HOUJI_CALL_TRACE(0x6004,0,0);int Healthy=StockBootstrapHealthy(NULL);HOUJI_CALL_TRACE(0x6005,0,Healthy);
 if(!Healthy)return HostRingGuardFailure(HHG_GUARD,HHG_BOOTSTRAP,0,1,1,Healthy,1,0);
 if(HostRingCheck32(HHG_GUARD,0x3dc0058,0xc00001feu,0) || HostRingRoutes() ||
  HostRingCheck32(HHG_GUARD,0x3dc0000,~0x1000u,0x27) ||
  HostRingCheck32(HHG_GUARD,0x3dc2000,~0x1000u,0x27))return 1;
 for(unsigned I=0;I<4;I++)if(HostRingCheckRoot(HHG_GUARD,mHostRingRootAddresses[I],mHostRingRoots[I]))return 1;
 HOUJI_CALL_TRACE(0x6007,0,0);
 return 0;
}
#include "GpuGraphicsReadinessNative.h"
STATIC int HostRingGraphicsCapture(unsigned Stage) {
 if(Stage>=HGR_STAGES){mHostRingCpFailed=1;return HostRingIoFailed(1,0,0,HHR_NATIVE_ARGUMENT);}
 int Code=GraphicsReadinessCapture(Stage);if(!Code)return 0;
 CONST struct hgr_result *R=&mGraphicsReadiness[Stage];mHostRingCpFailed=1;
 uint32_t Address=R->code==HGR_READ && R->reads?hgr_address(R->reads-1):0;
 if(R->code==HGR_READ)HostRingGuardFailure(HHG_READ,HHG_REGISTER,Address,0,0,0,0,R->read_code);
 return HostRingIoFailed(1,Address,0,R->code==HGR_READ?HHR_NATIVE_READ:HHR_NATIVE_GUARD);
}
STATIC int HostRingPrepare(VOID *Cookie) {
 (VOID)Cookie;if(mHostRingPrepared || HostPreparationGuard(NULL) || mGpuOnlyNext[3]!=3*HSC_CLASS_BYTES ||
  mGpuOnlyMemory.iova+3*HSC_CLASS_BYTES!=HHR_RING ||
  FirmwareVerifyPages(mGpuOnlyMemory.physical,mGpuOnlyMemory.cpu,HSC_POOL_PAGES,1))return 1;
 volatile uint32_t *Cpu=HostRingCpu();
 for(unsigned I=0;I<HSC_CLASS_BYTES/4;I++)if(Cpu[I])return 1;
 for(unsigned I=0;I<ARRAY_SIZE(mHostHwAddresses);I++) {
  if(HostPreparationGuard(NULL) || GpuTryRead32(mHostHwAddresses[I],&mHostHwBefore[I]))return 1;
  MmioWrite32(mHostHwAddresses[I],0);__asm__ volatile("dsb sy":::"memory");
  if(GpuTryRead32(mHostHwAddresses[I],&mHostHwAfter[I]) || mHostHwAfter[I])return 1;
  mHostHwDone++;
 }
 // Virgin ring and writeback words remain zero. CPU never stores the expected
 // GPU canary values into the scratch page, even on a failed test.
 for(unsigned I=0;I<4;I++)if(GpuTryRead64(mHostRingRootAddresses[I],&mHostRingRoots[I]))return 1;
 mGpuOnlyNext[3]+=HHR_BYTES+4096;mHostRingPrepared=1;
 Print(L"HOUJI GPU HOST RING MEMORY: ring=%x bytes=%x scratch=%x PA=%lx privilegedRW/NX GPU-only; CPU writes canaries=0; pins retained until reset\n",HHR_RING,HHR_BYTES,HHR_SCRATCH,mGpuOnlyMemory.physical+3*HSC_CLASS_BYTES);
 if(HostRingGuard(NULL))return 1;
 return HostRingGraphicsCapture(HGR_PRE_APERTURE);
}
STATIC int HostApertureCall(VOID *Cookie,struct ggs_regs *R) {
 (VOID)Cookie;mHostApertureValid=0;
 if(!R || HostPreparationGuard(NULL) || !mSecureCx.convention_verified || !mSecureCx.init_succeeded ||
  mSecureCx.quarantined || R->x[7])return 1;
 uint64_t Function=mHostApertureKind==1?0x42000601:0x42000c1b;
 if(!((R->x[0]==Function && !R->x[6]) || (R->x[0]==1 && mHostAperture.last_output.x[0]==1 &&
  R->x[6]==mHostAperture.last_output.x[6])))return 1;
 if(mHostApertureKind==1) {
  if(R->x[1]!=1 || R->x[2]!=0x02000c1b || R->x[3] || R->x[4] || R->x[5])return 1;
 } else if(mHostApertureKind!=2 || !mHostApertureAvailable || R->x[1]!=4 || R->x[2]!=0xffff0000u ||
  R->x[3]!=0xffffffffu || R->x[4]!=0xffffffffu || R->x[5]!=0xffffffffu)return 1;
 mHostApertureCalls++;UINT64 Begin=BatchCounter();int Code=ggs_aarch64_call(NULL,R);
 mHostApertureElapsed+=BatchMicroseconds(Begin);mHostApertureValid=!Code;return Code;
}
STATIC int HostRingAperture(VOID *Cookie) {
 (VOID)Cookie;if(mHostApertureKind || HostPreparationGuard(NULL))return 1;
 mHostAperture=mSecureCx;mHostAperture.calls=mHostAperture.busy_retries=mHostAperture.interrupt_resumes=0;
 CONST struct ggs_ops Io={NULL,HostApertureCall,SecureCxDelay,NULL};mHostApertureKind=1;
 mHostApertureQueryCode=ggs_exchange(&Io,&mHostAperture,0x42000601,0x02000c1b);
 if(mHostApertureQueryCode || !mHostApertureValid || !mHostAperture.last_output.x[1])return 1;
 mHostApertureAvailable=mHostAperture.last_output.x[1];mHostApertureKind=2;
 CONST struct ggs_regs Request={{0x42000c1b,4,0xffff0000u,0xffffffffu,0xffffffffu,0xffffffffu,0,0}};
 mHostApertureCode=ggs_exchange_frame(&Io,&mHostAperture,&Request);
 Print(L"HOUJI GPU HOST APERTURE: query=%u available=%lx code=%u actual-calls=%u valid=%u a0=%lx a1=%lx busy=%u resumes=%u elapsed-us=%lu; real fixed bank0 SCM, no MP_ASSIGN/PAS\n",mHostApertureQueryCode,mHostApertureAvailable,mHostApertureCode,mHostApertureCalls,mHostApertureValid,mHostAperture.last_output.x[0],mHostAperture.last_output.x[1],mHostAperture.busy_retries,mHostAperture.interrupt_resumes,mHostApertureElapsed);
 int Code=mHostApertureCode || !mHostApertureValid || mHostAperture.last_output.x[0] || HostPreparationGuard(NULL);
 return Code?Code:HostRingGraphicsCapture(HGR_POST_APERTURE);
}
STATIC int HostRingRead(VOID *Cookie,uint32_t Address,uint32_t *Value) {
 (VOID)Cookie;BOOLEAN Allowed=FALSE;
 for(unsigned I=0;I<ARRAY_SIZE(mHostRingSnapshotAddresses);I++)if(Address==mHostRingSnapshotAddresses[I])Allowed=TRUE;
 if(!Value) {
  HostRingGuardFailure(HHG_READ,HHG_ARGUMENT,Address,1,1,0,1,0);
  return HostRingIoFailed(1,Address,0,HHR_NATIVE_ARGUMENT);
 }
 if(!Allowed) {
  HostRingGuardFailure(HHG_READ,HHG_ALLOW,Address,1,1,0,1,0);
  return HostRingIoFailed(1,Address,0,HHR_NATIVE_ALLOW);
 }
 if(HostRingGuard(NULL))return HostRingIoFailed(1,Address,0,HHR_NATIVE_GUARD);
 int Code=GpuTryRead32(Address,Value);
 if(Code) {
  HostRingGuardFailure(HHG_READ,HHG_REGISTER,Address,0,0,0,0,Code);
  return HostRingIoFailed(1,Address,0,HHR_NATIVE_READ);
 }
 return 0;
}
STATIC int HostRingWrite(VOID *Cookie,uint32_t Address,uint32_t Value) {
 (VOID)Cookie;HOUJI_CALL_TRACE(0x3004,Address,Value);
 if(!mHostRingPrepared || HostRingGuard(NULL))return HostRingIoFailed(2,Address,Value,1);
 HOUJI_CALL_TRACE(0x3005,Address,Value);
 BOOLEAN Allowed=FALSE;
 CONST uint32_t A[]={0x3d02000,0x3d02004,0x3d02008,0x3d02010,0x3d02014,0x3d02a60,0x3d02a64};
 CONST uint32_t V[]={HHR_RING,0,0x20c,HHR_SCRATCH+0x100,0,HHR_SCRATCH+0x108,0};
 for(unsigned I=0;I<7;I++)if(mHostRing.phase==2 && !mHostRing.enabled && Address==A[I] && Value==V[I])Allowed=TRUE;
 if(Address==0x3d02020 && Value==1 && mHostRing.phase==3 && mHostRing.enabled &&
  mHostRingEntryReady &&
  (!mHostEngineStopped || (mHostEngineComplete && mHostEngineLog.phase==5 && !mHostEngineLog.code && mHostEngineLog.restored))) {
  Allowed=TRUE;mHostRingUnsafe=TRUE;mGpuSaveAllowed=FALSE;
 }
 if(Address==0x3d0201c && mHostRing.enabled && Value==mHostRing.wptr) {
  if(mHostRing.phase==4 && !mHostMode.started && Value==10)Allowed=TRUE;
  if(mHostRing.phase==4 && mHostMode.authenticated && mHostMode.published &&
   mHostMode.phase==3 && !mHostMode.submitted && Value==12)Allowed=TRUE;
  if(mHostRing.phase==4 && mHostMode.complete && mHostContext.built && mHostContext.published &&
   mHostContext.phase==3 && !mHostContext.submitted && Value==12+HFC_WORDS)Allowed=TRUE;
  if(mHostRing.phase==4 && mHostMode.complete && mHostContext.complete && mHostImage.started &&
   mHostImage.published && mHostImage.phase==3 && !mHostImage.submitted && Value==16+HFC_WORDS)Allowed=TRUE;
  if(mHostRing.phase>=5 && mHostRing.phase<=6 && (!mHostMode.started || mHostMode.complete) &&
   (!mHostImage.started || mHostImage.complete) &&
   (!mHostContext.started || mHostContext.complete) &&
   Value==10+5*(mHostRing.phase-4)+(mHostMode.complete?2:0)+(mHostImage.complete?4:0)+(mHostContext.complete?HFC_WORDS:0))Allowed=TRUE;
 }
 if(!Allowed)return HostRingIoFailed(2,Address,Value,2);
 if(Address==0x3d02020) {
  HOUJI_CALL_TRACE(0x3006,Address,Value);int Code=HostRingStore32(Value);
  HOUJI_CALL_TRACE(0x3007,Address,Code);return Code?HostRingIoFailed(2,Address,Value,Code):0;
 }
 MmioWrite32(Address,Value);__asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC int HostRingPublish(VOID *Cookie,unsigned Offset,CONST uint32_t *Words,unsigned Count) {
 (VOID)Cookie;if(!Words || HostRingGuard(NULL) || !mHostRingPrepared ||
  Offset>HHR_WORDS || Count>HHR_WORDS-Offset || FirmwareVerifyPages(mGpuOnlyMemory.physical,mGpuOnlyMemory.cpu,HSC_POOL_PAGES,1))return 1;
 unsigned Mode=(mHostRing.phase==4 && mHostMode.authenticated && !mHostMode.submitted &&
  mHostRing.init_idle && Offset==10 && Count==2);
 unsigned Context=(mHostRing.phase==4 && mHostMode.complete && mHostContext.started && mHostContext.built &&
  !mHostContext.published && !mHostContext.submitted && mHostContext.phase==2 &&
  mHostRing.init_idle && Offset==12 && Count==HFC_WORDS);
 unsigned Image=(mHostRing.phase==4 && mHostMode.complete && mHostContext.complete && mHostImage.started &&
  !mHostImage.published && !mHostImage.submitted && mHostRing.init_idle && Offset==12+HFC_WORDS && Count==4);
 unsigned Shift=(mHostMode.complete?2:0)+(mHostImage.complete?4:0)+(mHostContext.complete?HFC_WORDS:0);
 if(!((mHostRing.phase==2 && Offset==0 && Count==10) || Mode || Context || Image ||
  (mHostRing.phase==5 && Offset==10+Shift && Count==5) ||
  (mHostRing.phase==6 && Offset==15+Shift && Count==5)))return 1;
 CONST uint32_t Init[]={0x70970001,0x08000000,0x70c80007,0x94b,3,0x20000000,2,HHR_RECORD,0,0x80000000};
 unsigned Pass=mHostRing.phase==6;
 CONST uint32_t Write[]={0x703d8003,HHR_SCRATCH+4*Pass,0,0xc0ffee00u+Pass,0x70928000};
 CONST uint32_t Nonsecure[]={hhr_pkt7(0x66,1),0};
 CONST uint32_t *Expected=Context?HostRingFirstContextWords():Image?hgki_ib:Mode?Nonsecure:Offset?Write:Init;
 if(!Expected)return 1;
 if(Context && HostRingFirstContextMatch(Words,Count))return 1;
 volatile uint32_t *Cpu=HostRingCpu();
 for(unsigned I=0;I<Count;I++)if(Words[I]!=Expected[I] || Cpu[Offset+I])return 1;
 for(unsigned I=0;I<Count;I++)Cpu[Offset+I]=Words[I];
 __asm__ volatile("dsb sy":::"memory");
 for(unsigned I=0;I<Count;I++)if(Cpu[Offset+I]!=Words[I])return 1;
 return HostRingGuard(NULL);
}
STATIC int HostRingPeek(VOID *Cookie,unsigned Index,uint32_t *Value) {
 (VOID)Cookie;if(!Value || Index>1 || HostRingGuard(NULL))return 1;
 __asm__ volatile("dsb sy":::"memory");*Value=HostRingCpu()[HHR_BYTES/4+Index];return 0;
}
STATIC VOID HostRingSnapshot(VOID *Cookie,unsigned Stage) {
 (VOID)Cookie;if(Stage>=6)return;
 if(mHostRing.code || mHostRingCpFailed || mHostWriteFaults) {
  mHostRingSnapshots[Stage].taken=1;
  if(mHostRingPrepared) {
   volatile uint32_t *Scratch=HostRingCpu()+HHR_BYTES/4;
   mHostRingSnapshots[Stage].scratch[0]=Scratch[0];mHostRingSnapshots[Stage].scratch[1]=Scratch[1];
  }
  Print(L"HOUJI GPU HOST FIRST IO: valid=%u op=%u native-code=%u address=%x value=%x ring-code=%u phase=%u SQE-store-calls=%u; failure snapshot CPU RAM only, no GX/CP reads\n",mHostFirstIo.valid,mHostFirstIo.operation,mHostFirstIo.code,mHostFirstIo.address,mHostFirstIo.value,mHostRing.code,mHostRing.phase,mHostWriteCalls);
  return;
 }
 if(HostRingPower())return;
 if(Stage==1 && HostRingGraphicsCapture(HGR_POST_CP_IDLE)){mHostRing.code=HHR_IO;return;}
 mHostRingSnapshots[Stage].taken=1;
 for(unsigned I=0;I<ARRAY_SIZE(mHostRingSnapshotAddresses);I++) {
  uint32_t Value;if(!GpuTryRead32(mHostRingSnapshotAddresses[I],&Value)) {
   mHostRingSnapshots[Stage].word[I]=Value;mHostRingSnapshots[Stage].valid|=1u<<I;
  } else if(mHostRing.enabled){mHostRingCpFailed=1;break;}
 }
 if(mHostRingPrepared) {
  volatile uint32_t *Scratch=HostRingCpu()+HHR_BYTES/4;
  mHostRingSnapshots[Stage].scratch[0]=Scratch[0];mHostRingSnapshots[Stage].scratch[1]=Scratch[1];
  mHostRingSnapshots[Stage].scratch[2]=Scratch[0x100/4];mHostRingSnapshots[Stage].scratch[3]=Scratch[0x108/4];
 }
 Print(L"HOUJI GPU HOST RING STEP: stage=%u phase=%u code=%u RPTR=%u WPTR=%u status=%x IRQ=%x fault=%x writes=%u words=%x/%x; RAM snapshot only\n",Stage,mHostRing.phase,mHostRing.code,mHostRing.rptr,mHostRing.wptr,mHostRing.status,mHostRing.irq,mHostRing.hwfault,mHostRing.writebacks,mHostRingSnapshots[Stage].scratch[0],mHostRingSnapshots[Stage].scratch[1]);
}
STATIC int HostRingLogGuard(VOID *Cookie) {
 (VOID)Cookie;unsigned State=!!mHostRingUnsafe | (!!mHostRing.enabled<<1) | ((mHostRing.configured!=7)<<2);
 if(State)return HostRingGuardFailure(HHG_LOG,HHG_STATE,0,7,0,State,1,0);
 int Code=HostPreparationGuard(NULL);
 if(Code)return HostRingGuardFailure(HHG_LOG,HHG_PREPARATION,0,UINT64_MAX,0,Code,1,0);
 return HostRingGuard(NULL);
}
STATIC uint64_t HostRingLogSave(VOID *Cookie) {
 (VOID)Cookie;return ProbeCheckpoint("HOST-ring-configured-aperture-ready-before-SQE-and-actual-CP");
}
STATIC int HostRingCheckpoint(VOID *Cookie) {
 (VOID)Cookie;
#ifdef HOUJI_CALL_TRACE_NATIVE
 HoujiGpuCallTraceStart();
#endif
 // r121 isolates SQE from live FAT/TPL/console callbacks. The earlier host
 // preparation snapshot remains durable. Keep all fresh owner/power checks;
 // no log-save success or restored-TPL result is fabricated for this run.
 (VOID)HostRingLogSave;(VOID)mHostRingLog;
 HOUJI_CALL_TRACE(0x3000,0,0);
 int Code=HostRingLogGuard(NULL);mHostRingEntryReady=!Code;HOUJI_CALL_TRACE(0x3001,mHostRingEntryReady,Code);
 return Code;
}
STATIC int HostEngineGuard(VOID *Cookie) {
 (VOID)Cookie;unsigned State=!!mHostBusStop.stage | (!mHostEngineStopped<<1) |
  (!!mHostRingUnsafe<<2) | (!!mHostRing.kicks<<3) | (!!mHostRing.wptr<<4);
 if(State)return HostRingGuardFailure(HHG_ENGINE,HHG_STATE,0,31,0,State,1,0);
 if(HostRingGuard(NULL))return 1;
 int Code=HostContextQualified();
 if(Code)return HostRingGuardFailure(HHG_ENGINE,HHG_CONTEXT,0,UINT64_MAX,0,Code,1,0);
 Code=ScratchAudit();if(Code)return HostRingGuardFailure(HHG_ENGINE,HHG_AUDIT,0,UINT64_MAX,0,Code,1,0);
 if(HostRingCheck32(HHG_ENGINE,0x3d02020,0xffffffffu,3) ||
  HostRingCheck32(HHG_ENGINE,0x3d02018,0xffffffffu,0) ||
  HostRingCheck32(HHG_ENGINE,0x3d0201c,0xffffffffu,0) ||
  HostRingCheck32(HHG_ENGINE,0x3d00840,~1u,0) ||
  HostRingCheck32(HHG_ENGINE,0x3d00804,0xffffffffu,0) ||
  HostRingCheck32(HHG_ENGINE,0x3d02084,0xffffffffu,0))return 1;
 struct ggh_io Hfi={mFirmwareMemory.memory[5].cpu,GGH_BYTES,GGH_IOVA,NULL,StockHfiBarrier};
 for(unsigned I=0;I<GGH_QUEUES;I++) {
  volatile uint32_t *Header,*Ring;unsigned Read=0,Write=0;
  Code=ggh_queue(&Hfi,I,&Header,&Ring,&Read,&Write);
  if(Code || Read!=Write)return HostRingGuardFailure(HHG_ENGINE,HHG_QUEUE,I,0xffffffffu,Read,Write,!Code,Code);
 }
 for(unsigned I=0;I<=mFirmwareMemory.count;I++) {
  CONST struct hfm_allocation *M=&mFirmwareMemory.memory[I];
  Code=FirmwareVerifyPages(M->physical,M->cpu,M->pages,M->nc);
  if(Code)return HostRingGuardFailure(HHG_ENGINE,HHG_MEMORY,I,UINT64_MAX,0,Code,1,0);
 }
 Code=FirmwareVerifyPages(mCodeMemory.physical,mCodeMemory.cpu,HCC_PAGES,1);
 if(Code)return HostRingGuardFailure(HHG_ENGINE,HHG_MEMORY,0x100,UINT64_MAX,0,Code,1,0);
 Code=FirmwareVerifyPages(mGpuOnlyMemory.physical,mGpuOnlyMemory.cpu,HSC_POOL_PAGES,1);
 if(Code)return HostRingGuardFailure(HHG_ENGINE,HHG_MEMORY,0x101,UINT64_MAX,0,Code,1,0);
 Code=FirmwareVerifyPages(mScratchTablePhysical,mScratchTables,HSC_GPU_TABLE_PAGES,0);
 return Code?HostRingGuardFailure(HHG_ENGINE,HHG_MEMORY,0x102,UINT64_MAX,0,Code,1,0):0;
}
STATIC uint64_t HostEngineSave(VOID *Cookie) {
 (VOID)Cookie;return ProbeCheckpoint("HOST-SQE-started-then-halted-empty-ring-before-first-WPTR");
}
STATIC int HostRingEngineProbe(VOID *Cookie) {
 (VOID)Cookie;if(mHostEngineStopped || mHostEngineComplete || mHostRing.kicks || mHostRing.wptr ||
  mHostRing.phase!=3 || !mHostRing.enabled || !mHostRingUnsafe || !mHostWriteCalls ||
  mHostRing.sqe!=1 || !mHostRing.last_valid || mHostRing.last_operation!=1 ||
  mHostRing.last_address!=0x3d02020 || mHostRing.last_value!=1 || HostRingGuard(NULL))return 1;
 // Linux/OnePlus start SQE, submit CP_INIT, then poll completion. The former
 // empty-ring halt/save/restart was an extra diagnostic, not a prerequisite.
 // Keep its helpers dormant for offline tests; do not fabricate their results.
 (VOID)HostEngineGuard;(VOID)HostEngineSave;
 mHostDirectReady=1;return 0;
}
STATIC int HostRingBusLease(VOID) {
 if(HostRingBusPower())return 1;
 if(!mHostRingPrepared)return HostRingGuardFailure(HHG_LEASE,HHG_STATE,0,1,1,0,1,0);
 for(unsigned I=0;I<4;I++)if(HostRingCheckRoot(HHG_LEASE,mHostRingRootAddresses[I],mHostRingRoots[I]))return 1;
 return HostRingRoutes();
}
STATIC int HostRingBusHalt(VOID) {
 if(mHostBusStop.stage || !mHostRing.enabled || HostRingBusLease())return 1;
 mHostBusStop.stage=1;
 // Preserve sticky faults; they are not a DMA-drain acknowledgement. Only
 // Linux's actual GPU/GBIF halt acknowledgements below can qualify this path.
 if(!GpuTryRead32(0x3dc0058,&mHostBusStop.fsr))mHostBusStop.valid|=1;
 if(!GpuTryRead32(0x3dc0068,&mHostBusStop.fsynr))mHostBusStop.valid|=2;
 if(!GpuTryRead64(0x3dc0060,&mHostBusStop.far))mHostBusStop.valid|=4;
 if(!GpuTryRead32(0x3da0048,&mHostBusStop.gfsr))mHostBusStop.valid|=8;
 if(!GpuTryRead32(0x3dc2058,&mHostBusStop.gmu_fsr))mHostBusStop.valid|=16;
 // Linux a6xx_gmu_force_off and OnePlus gen7_gmu_suspend hold CM3 reset
 // before bus isolation. Never revisit SQE/CP registers on this fault path.
 HOUJI_CALL_TRACE(0x7200,0x3d7e000,1);
 mStockResult.reset_held=0;
 if(StockWrite32(NULL,0x3d7e000,1))return 1;
 unsigned ResetPoll;
 for(ResetPoll=0;ResetPoll<1000;ResetPoll++) {
  uint32_t Reset;
  if(HostRingBusLease() || StockRead32(NULL,0x3d7e000,&Reset))return 1;
  if(Reset==1){mStockResult.reset_held=1;mHostBusStop.cm3_reset=1;break;}
  if(ContextDelay(NULL,10))return 1;
 }
 if(ResetPoll==1000)return 1;
 HOUJI_CALL_TRACE(0x7201,0x3d7e000,1);
 // Linux21a7f44 a6xx_bus_clear_pending_transactions(hung): A750 GBIF
 // GX halt, client halt, AXI arb halt. Keep ALL halts asserted until RESET.
 CONST uint32_t Address[]={0x3d00058,0x3d0f114,0x3d0f114};
 CONST uint32_t Ack[]={0x3d0005c,0x3d0f118,0x3d0f118};
 CONST uint32_t Value[]={1,1,2};
 for(unsigned I=0;I<3;I++) {
  mHostBusStop.stage=2+I;
  if(HostRingBusLease())return 1;
  MmioWrite32(Address[I],Value[I]);__asm__ volatile("dsb sy":::"memory");
  unsigned Poll;
  for(Poll=0;Poll<1000;Poll++) {
   if(HostRingBusLease() || GpuTryRead32(Ack[I],&mHostBusStop.ack[I]))return 1;
   if((mHostBusStop.ack[I]&Value[I])==Value[I])break;
   if(ContextDelay(NULL,10))return 1;
  }
  if(Poll==1000)return 1;
 }
 if(HostRingBusLease() || ScratchAudit())return 1;
 // Keep the failed CP aperture untouched even after bus isolation. Preserve
 // the CPU call trace, first I/O failure and five SMMU fault scalars instead.
 if(HostRingBusLease())return 1;
 mHostBusStop.stage=5;mHostBusStop.stopped=1;mHostRingUnsafe=FALSE;return 0;
}
STATIC int HostRingStop(VOID *Cookie,uint32_t Wptr) {
 (VOID)Cookie;if(!mHostRing.enabled)return 1;
 if(mHostBusStop.stopped) {
  uint32_t GxAck,ArbAck,Reset;mHostRingUnsafe=TRUE;
  if(mHostBusStop.stage!=5 || !mHostBusStop.cm3_reset || !(mHostBusStop.ack[1]&1) ||
   HostRingBusLease() || StockRead32(NULL,0x3d7e000,&Reset) || Reset!=1 ||
   GpuTryRead32(0x3d0005c,&GxAck) || !(GxAck&1) ||
   GpuTryRead32(0x3d0f118,&ArbAck) || !(ArbAck&2))return 1;
  mHostRingUnsafe=FALSE;return 0;
 }
 // A rejected adapter write is not an executed SQE operation. The virgin
 // ring's earlier readback was zero; with no SQE store, kicks or WPTR there
 // is no CP engine to stop. Do not issue HALT3 to a never-started engine.
 if(!mHostWriteCalls && !mHostRingUnsafe && !mHostRing.kicks && !mHostRing.wptr)return 0;
 if(mHostRing.code || mHostRingCpFailed || mHostWriteFaults)return HostRingBusHalt();
 if(HostRingGuard(NULL))return HostRingBusHalt();
 // Linux recover uses SQE_CNTL=3. Readback alone is insufficient: also require
 // consumed ring, GPU idle, no fault, unchanged roots, then full graph audit.
 if(HostRingStore32(3))return HostRingBusHalt();
 for(unsigned I=0;I<1000;I++) {
  struct hhs_sample Sample={0};int Code=HostRingGuard(NULL);
  if(!Code) {
   Sample.busy=mHostRingBusy.last;if(mHostRingBusy.valid)Sample.valid|=32;
   Code=GpuTryRead32(0x3d02020,&Sample.sqe);if(!Code)Sample.valid|=1;
  }
  if(!Code){Code=GpuTryRead32(0x3d02018,&Sample.rptr);if(!Code)Sample.valid|=2;}
  if(!Code){Code=GpuTryRead32(0x3d00840,&Sample.status);if(!Code)Sample.valid|=4;}
  if(!Code){Code=GpuTryRead32(0x3d00804,&Sample.irq);if(!Code)Sample.valid|=8;}
  if(!Code){Code=GpuTryRead32(0x3d02084,&Sample.fault);if(!Code)Sample.valid|=16;}
  Sample.failed=(~Sample.valid&63) | (Sample.sqe!=3) | ((Sample.rptr!=Wptr)<<1) |
   (!!(Sample.status&~1u)<<2) | (!!Sample.irq<<3) | (!!Sample.fault<<4) | (!!(Sample.busy&(1u<<23))<<5);
  if(!mHostStopPoll.polls){mHostStopPoll.first=Sample;mHostStopPoll.wptr=Wptr;}
  mHostStopPoll.last=Sample;mHostStopPoll.polls++;mHostStopPoll.read_code=Code;
  if(Code)return HostRingBusHalt();
  if(!Sample.failed) {
   if(HostContextQualified() || ScratchAudit())return HostRingBusHalt();
   mHostRingUnsafe=FALSE;return 0;
  }
  if(ContextDelay(NULL,100))return 1;
 }
 mHostStopPoll.timeout=1;
#ifdef HOUJI_CALL_TRACE_NATIVE
 HoujiGpuCallTraceFreezeFirstFailure();
#endif
 return HostRingBusHalt();
}
STATIC VOID HostRingReport(VOID) {
 #ifdef HOUJI_CALL_TRACE_NATIVE
 if(!mHostRingUnsafe){HoujiGpuCallTraceStop();HoujiGpuCallTraceReport();HoujiGpuCallTraceResume();}
 #endif
 HostWriteReport();
 GraphicsReadinessReport();
 Print(L"HOUJI GPU HOST MODE TRANSITION: started=%u authenticated=%u submitted=%u idle=%u complete=%u phase=%u code=%u hook-attempted=%u hook-complete=%u; signed PAS13 then exact CP_SET_SECURE_MODE(0), no TRUST_CNTL write\n",mHostMode.started,mHostMode.authenticated,mHostMode.submitted,mHostMode.idle,mHostMode.complete,mHostMode.phase,mHostMode.code,mHostRing.post_init_attempted,mHostRing.post_init_complete);
 Print(L"HOUJI GPU HOST IMAGE SUBMIT: started=%u published=%u submitted=%u idle=%u complete=%u phase=%u code=%u kick-code=%u idle-code=%u stall-code=%u; fixed class2 IB only, pixel proof in separate known-image report\n",mHostImage.started,mHostImage.published,mHostImage.submitted,mHostImage.idle,mHostImage.complete,mHostImage.phase,mHostImage.code,mHostImage.kick_code,mHostImage.idle_code,mHostImage.stall_code);
 Print(L"HOUJI GPU HOST FIRST CONTEXT: started=%u built=%u published=%u submitted=%u idle=%u complete=%u phase=%u code=%u kick-code=%u idle-code=%u stall-code=%u words=%u end-WPTR=%u; source-derived outer privileged ring, same audited root/ASID only, not inside class2 IB\n",mHostContext.started,mHostContext.built,mHostContext.published,mHostContext.submitted,mHostContext.idle,mHostContext.complete,mHostContext.phase,mHostContext.code,mHostContext.kick_code,mHostContext.idle_code,mHostContext.stall_code,HFC_WORDS,12+HFC_WORDS);
 Print(L"HOUJI GPU HOST BUSY: reads=%u busy=%u idle-required=%u last=%x valid=%u; running SQE may be busy, normal quiescence requires idle\n",mHostRingBusy.reads,mHostRingBusy.busy,mHostRingBusy.idle_required,mHostRingBusy.last,mHostRingBusy.valid);
 Print(L"HOUJI GPU HOST COMPLETION BUSY: value=%x valid=%u; actual last completion read, bit23 must clear with RPTR and RBBM idle\n",mHostRing.busy,mHostRing.busy_valid);
 Print(L"HOUJI GPU HOST FIRST GUARD: seen=%u phase=%u stage=%u kind=%u address=%x mask=%lx expected=%lx actual=%lx valid=%u raw-read-code=%d; first failure only, existing observations, no diagnostic MMIO\n",mHostFirstGuard.seen,mHostFirstGuard.phase,mHostFirstGuard.stage,mHostFirstGuard.kind,mHostFirstGuard.address,mHostFirstGuard.mask,mHostFirstGuard.expected,mHostFirstGuard.actual,mHostFirstGuard.valid,mHostFirstGuard.read_code);
 Print(L"HOUJI GPU HOST FIRST IO: valid=%u op=%u native-code=%u address=%x value=%x entry-ready=%u CP-failed=%u CM3-reset=%u; first failure retained before cleanup\n",mHostFirstIo.valid,mHostFirstIo.operation,mHostFirstIo.code,mHostFirstIo.address,mHostFirstIo.value,mHostRingEntryReady,mHostRingCpFailed,mHostBusStop.cm3_reset);
 Print(L"HOUJI GPU HOST BUS STOP: stage=%u isolated=%u SQE-valid=0 ACK=%x/%x/%x fault-valid=%x FSR=%x FAR=%lx FSYNR=%x GFSR=%x GMU-FSR=%x; no SQE read on isolation path, actual halt ACK required, retained until platform reset\n",mHostBusStop.stage,mHostBusStop.stopped,mHostBusStop.ack[0],mHostBusStop.ack[1],mHostBusStop.ack[2],mHostBusStop.valid,mHostBusStop.fsr,mHostBusStop.far,mHostBusStop.fsynr,mHostBusStop.gfsr,mHostBusStop.gmu_fsr);
 Print(L"HOUJI GPU HOST STOP POLL: polls=%u timeout=%u guard-or-read-code=%d WPTR=%x; valid/failed bits SQE/RPTR/RBBM/IRQ/fault/busy, existing observations only\n",mHostStopPoll.polls,mHostStopPoll.timeout,mHostStopPoll.read_code,mHostStopPoll.wptr);
 CONST struct hhs_sample *StopSamples[]={&mHostStopPoll.first,&mHostStopPoll.last};
 for(unsigned I=0;I<ARRAY_SIZE(StopSamples);I++)Print(L"HOUJI GPU HOST STOP SAMPLE: i=%u valid=%x failed=%x SQE=%x RPTR=%x RBBM=%x IRQ=%x fault=%x busy=%x\n",I,StopSamples[I]->valid,StopSamples[I]->failed,StopSamples[I]->sqe,StopSamples[I]->rptr,StopSamples[I]->status,StopSamples[I]->irq,StopSamples[I]->fault,StopSamples[I]->busy);
 for(unsigned I=0;I<mHostHwDone;I++)Print(L"HOUJI GPU HOST HW INIT: i=%u address=%x before=%x after=%x; Linux host-ring baseline, TRUST_CNTL unchanged\n",I,mHostHwAddresses[I],mHostHwBefore[I],mHostHwAfter[I]);
 Print(L"HOUJI GPU HOST RING RESULT: started=%u code=%u phase=%u configured=%u enabled=%u kicks=%u init-idle=%u writebacks=%u observed=%08x/%08x RPTR=%u WPTR=%u status=%x IRQ=%x fault=%x SQE=%x stopped=%u unsafe=%u polls=%u reads=%u writes=%u fence-retries=%u last=%x/%x op=%u valid=%u; actual CP test, no PAS/shaders/Metal/desktop acceleration claim\n",mHostRing.started,mHostRing.code,mHostRing.phase,mHostRing.configured,mHostRing.enabled,mHostRing.kicks,mHostRing.init_idle,mHostRing.writebacks,mHostRing.observed[0],mHostRing.observed[1],mHostRing.rptr,mHostRing.wptr,mHostRing.status,mHostRing.irq,mHostRing.hwfault,mHostRing.sqe,mHostRing.stopped,mHostRingUnsafe,mHostRing.polls,mHostRing.reads,mHostRing.writes,mHostRing.fence_retries,mHostRing.last_address,mHostRing.last_value,mHostRing.last_operation,mHostRing.last_valid);
 Print(L"HOUJI GPU HOST ENGINE PROBE: complete=%u halted=%u checkpoint=%u/%u restored=%u; legacy extra diagnostic unused by direct profile, no fabricated success\n",mHostEngineComplete,mHostEngineStopped,mHostEngineLog.code,mHostEngineLog.phase,mHostEngineLog.restored);
 Print(L"HOUJI GPU HOST DIRECT PROFILE: ready=%u extra-empty-probe=skipped; actual SQE readback then fresh running guard, CP_INIT next, no interim halt/save/restart or filesystem access\n",mHostDirectReady);
 for(unsigned S=0;S<6;S++)if(mHostRingSnapshots[S].taken) {
  for(unsigned I=0;I<30;I++)Print(L"HOUJI GPU HOST RING SNAPSHOT: stage=%u i=%u address=%x value=%08x valid=%u\n",S,I,mHostRingSnapshotAddresses[I],mHostRingSnapshots[S].word[I],(mHostRingSnapshots[S].valid>>I)&1);
  Print(L"HOUJI GPU HOST RING SHADOW: stage=%u canary=%08x/%08x BR=%u BV=%u; CPU scratch stores=0\n",S,mHostRingSnapshots[S].scratch[0],mHostRingSnapshots[S].scratch[1],mHostRingSnapshots[S].scratch[2],mHostRingSnapshots[S].scratch[3]);
 }
}
STATIC int HostRingFirstContext(VOID) {
 if(mHostContext.started || !mHostMode.complete || mHostRing.phase!=4 ||
  mHostRing.wptr!=12 || mHostRing.rptr!=12 || HostRingGuard(NULL))return 1;
 mHostContext.started=1;mHostContext.phase=1;
 mHostContext.code=(unsigned)HostRingBuildFirstContext();
 if(mHostContext.code)return 1;
 mHostContext.built=1;mHostContext.phase=2;
 if(HostRingPublish(NULL,12,HostRingFirstContextWords(),HFC_WORDS)) {
  mHostContext.code=HHR_MEMORY;return 1;
 }
 mHostContext.published=1;mHostContext.phase=3;mHostRing.wptr=12+HFC_WORDS;
 CONST struct hhr_io Io={.guard=HostRingGuard,.read=HostRingRead,
  .write=HostRingWrite,.delay=ContextDelay};
 unsigned Code=hhr_kick(&Io,&mHostRing);mHostContext.code=mHostContext.kick_code=Code;
 if(Code)return 1;mHostContext.submitted=1;mHostContext.phase=4;
 Code=hhr_idle(&Io,&mHostRing);mHostContext.code=mHostContext.idle_code=Code;
 if(Code==HHR_TIMEOUT)mHostContext.stall_code=CaptureGraphicsStall(1);
 if(Code)return 1;
 mHostContext.idle=1;mHostContext.complete=1;mHostContext.phase=5;return 0;
}
STATIC int HostRingPostInit(VOID *Cookie,struct hhr_result *R) {
 (VOID)Cookie;
 if(R!=&mHostRing || mHostMode.started || R->phase!=4 || !R->init_idle ||
  R->rptr!=10 || R->wptr!=10 || !R->enabled || !mHostRingUnsafe ||
  !mHostDirectReady || HostRingGuard(NULL) || !mHostRingBusy.valid ||
  (mHostRingBusy.last&(1u<<23)))return 1;
 mHostMode.started=1;mHostMode.phase=1;
 int Code=HostRingLoadAuthenticatedZap();mHostMode.code=(unsigned)Code;
 if(Code)goto failed;
 mHostMode.authenticated=1;mHostMode.phase=2;
 if(HostRingGraphicsCapture(HGR_POST_AUTH))goto failed;
 CONST uint32_t Packet[]={hhr_pkt7(0x66,1),0};
 if(HostRingPublish(NULL,10,Packet,2))goto failed;
 mHostMode.published=1;
 R->wptr=12;
 CONST struct hhr_io Io={.guard=HostRingGuard,.read=HostRingRead,
  .write=HostRingWrite,.delay=ContextDelay};
 mHostMode.phase=3;Code=hhr_kick(&Io,R);mHostMode.code=(unsigned)Code;
 if(Code)goto failed;
 mHostMode.submitted=1;mHostMode.phase=4;
 Code=hhr_idle(&Io,R);mHostMode.code=(unsigned)Code;if(Code)goto failed;
 mHostMode.idle=1;
 if(HostRingGraphicsCapture(HGR_POST_MODE_IDLE))goto failed;
 mHostMode.complete=1;mHostMode.phase=5;
 if(HostRingFirstContext())goto context_failed;
 if(!HostRingRunKnownImage())return 0;
context_failed:
 mHostRingCpFailed=1;
#ifdef HOUJI_CALL_TRACE_NATIVE
 HoujiGpuCallTraceFreezeFirstFailure();
#endif
 return 1;
failed:
 if(!mHostMode.code)mHostMode.code=HHR_IO;
 mHostRingCpFailed=1;
#ifdef HOUJI_CALL_TRACE_NATIVE
 HoujiGpuCallTraceFreezeFirstFailure();
#endif
 return 1;
}
STATIC int HostKnownImageSubmit(VOID *Cookie,CONST uint32_t *Words,unsigned Count) {
 (VOID)Cookie;
 if(!Words || Count!=4 || mHostRing.phase!=4 || mHostRing.wptr!=12+HFC_WORDS ||
  mHostRing.rptr!=12+HFC_WORDS || !mHostMode.complete || !mHostContext.complete || !mHostImage.started ||
  mHostImage.published || mHostImage.submitted || HostRingGuard(NULL) ||
  !mHostRingBusy.valid || (mHostRingBusy.last&(1u<<23)))return 1;
 for(unsigned I=0;I<4;I++)if(Words[I]!=hgki_ib[I])return 1;
 mHostImage.phase=2;
 if(HostRingPublish(NULL,12+HFC_WORDS,Words,4))return 1;
 mHostImage.published=1;mHostRing.wptr=16+HFC_WORDS;mHostImage.phase=3;
 CONST struct hhr_io Io={.guard=HostRingGuard,.read=HostRingRead,
  .write=HostRingWrite,.delay=ContextDelay};
 unsigned Code=hhr_kick(&Io,&mHostRing);mHostImage.code=mHostImage.kick_code=Code;
 if(Code)return 1;mHostImage.submitted=1;return 0;
}
STATIC int HostKnownImageIdle(VOID *Cookie) {
 (VOID)Cookie;
 if(!mHostImage.submitted || mHostImage.idle || mHostImage.phase!=3 ||
  mHostRing.wptr!=16+HFC_WORDS || !mHostMode.complete || !mHostContext.complete)return 1;
 CONST struct hhr_io Io={.guard=HostRingGuard,.read=HostRingRead,.delay=ContextDelay};
 unsigned Code=hhr_idle(&Io,&mHostRing);mHostImage.code=mHostImage.idle_code=Code;
 if(Code==HHR_TIMEOUT)mHostImage.stall_code=CaptureGraphicsStall(1);
 if(Code)return 1;mHostImage.idle=1;mHostImage.phase=4;return 0;
}
STATIC unsigned RunHostRing(VOID) {
 CONST struct hhr_io Io={NULL,HostRingGuard,HostRingPrepare,HostRingAperture,HostRingRead,HostRingWrite,
  HostRingPublish,HostRingPeek,ContextDelay,HostRingCheckpoint,HostRingSnapshot,HostRingStop,HostRingEngineProbe,HostRingPostInit};
 return hhr_run(&Io,&mHostRing);
}
#endif
