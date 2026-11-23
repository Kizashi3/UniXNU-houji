#!/usr/bin/env python3
"""Compile the actual native binding with only processor/MMIO/BS boundaries mocked."""
from pathlib import Path
import subprocess,tempfile
p=Path(__file__).resolve().parents[1]
prefix=r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define GG_HOST_TEST
#include "vendor/Ace5Gmu/giulia_gpu_scm.h"
#include "GpuHostRing.h"
#include "GpuFirstContext.h"
#include "GpuKnownImage2d.h"
#define HOUJI_GPU_HOST_WRITE_FAULT_NATIVE_H
#include "GpuLiveLog.h"
#define STATIC static
#define CONST const
#define VOID void
#define BOOLEAN unsigned
#define UINTN uintptr_t
#define UINT32 uint32_t
#define UINT64 uint64_t
#define TRUE 1
#define FALSE 0
#define Print(...) ((void)0)
#define HOUJI_CALL_TRACE_NATIVE 1
static unsigned freeze_calls;
static void HoujiGpuCallTraceFreezeFirstFailure(void){freeze_calls++;}
static void HoujiGpuCallTraceStart(void){}
static void HoujiGpuCallTraceStop(void){}
static void HoujiGpuCallTraceReport(void){}
static void HoujiGpuCallTraceResume(void){}
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define HSC_CLASS_BYTES 0x40000u
#define HSC_POOL_PAGES 256
#define HFM_ALL 0xffffu
#define HCC_PAGES 64
#define HSC_GPU_TABLE_PAGES 7
#define GGH_QUEUES 17
#define GGH_BYTES 0x12000
#define GGH_IOVA 0x60010000
static unsigned mHostProfileReady,mFirmwareHeld,mGxMapped,mGen7Mapped,mCodeReady,mScratchAssigned,mScratchReady,mSharedCount,mSecureAssigned,mSecureTableOwned,mDmaZeroRetained,mHostRingUnsafe,mGpuSaveAllowed;
static struct {unsigned code,phase;}mHostPrep;
static struct {unsigned acked,clear_confirmed;}mGxStart;
static struct {unsigned code,phase,enabled,attached,retained,lpac,sid0_attached,lpac_attached;uint32_t sid0_smr,sid0_s2cr,lpac_smr,lpac_s2cr;}mScratchResult;
static struct {unsigned attached;}mSecureContext;
static struct {unsigned code,phase,record_ready;}mGen7;
static struct {unsigned code,phase,verified;}mCodeBind;
struct hfm_allocation {uint64_t physical;void*cpu;unsigned pages,nc;};
static struct {unsigned retained,count;struct hfm_allocation memory[12];}mFirmwareMemory;
static struct hfm_allocation mCodeMemory;
static uint64_t mScratchTablePhysical;static void*mScratchTables;
static struct {unsigned owned;}mSecureMemory;
static struct {uint64_t iova,physical;void*cpu;}mGpuOnlyMemory;
static unsigned mGpuOnlyNext[4];
struct ggh_io{void*cpu;unsigned bytes,iova;void*cookie;void(*barrier)(void*);};
static unsigned queue_calls,queue_fail,queue_mismatch;
static void StockHfiBarrier(void*c){(void)c;}
static int ggh_queue(const struct ggh_io*i,unsigned q,volatile uint32_t**h,volatile uint32_t**r,unsigned*a,unsigned*b){(void)i;(void)q;(void)h;(void)r;queue_calls++;if(queue_calls==queue_fail)return 17;*a=0;*b=queue_calls==queue_mismatch;return 0;}
static unsigned char pool[0x100000];
static struct ggs_state mSecureCx;
static struct {unsigned dummy,reset_held;}mStockResult;
struct hgf_io {int(*read)(void*,uint32_t,uint32_t*);};
static unsigned failure,mmio_writes,mmio_reads,cp_reads,cp_writes,forbid_cp,power_checks,scm_calls,prep_checks,memchecks,tpl,fs,mHostWriteCalls,mHostWriteFaults;
static unsigned fail_read_at,bad_read_at,mem_fail_at;
static int fail_read_code;
static uint64_t bad_read_mask;
static uint32_t route_bad_address,route_bad_mask,route_fail_address;
static uint32_t fake_sqe,fake_wptr,fake_rptr,fake_gx_halt,fake_gbif_halt,fake_cm3;
static uint32_t fake_busy;
static unsigned mode_gpu,mode_consumed,image_gpu,image_consumed,image_fail;
static unsigned context_consumed,context_build_calls,context_build_fail,context_publish_fail,context_kick_fail,context_idle_fail,context_words_null,context_root_reads;
static unsigned stall_calls,stall_stage,stall_cp_failed,doorbells,doorbell_wptr[8];
static uint32_t context_words[HFC_WORDS];
static struct hfc_result context_build_result;
static const struct hfc_config context_config={0x81111000,0x81111000,1,1,1,1,1};
static unsigned busy_reads,busy_clear_after,delay_calls;
static unsigned cp_address(uint64_t a){return a>=0x3d02000 && a<0x3d02c00;}
static int HostPreparationGuard(void*c){(void)c;prep_checks++;return failure==1 || fake_sqe!=0;}
static int FirmwareVerifyPages(uint64_t p,void*c,unsigned n,unsigned nc){(void)p;(void)c;(void)n;(void)nc;memchecks++;return failure==2 || (mem_fail_at && memchecks==mem_fail_at);}
static int StockRead32(void*c,uint32_t a,uint32_t*v){(void)c;assert(a==0x3d7e000 && v);mmio_reads++;*v=failure==27?0:fake_cm3;return 0;}
static unsigned context_doorbell_blocked(void);
static int hgf_power(const struct hgf_io*i,void*r){(void)i;(void)r;power_checks++;return failure!=3 && !context_doorbell_blocked();}
static int StockBootstrapHealthy(void*c){(void)c;return failure!=4;}
static int HostContextQualified(void){return failure==5;}
static int ScratchAudit(void){return failure==6;}
static int GpuTryRead32(uint64_t a,uint32_t*v){mmio_reads++;if(cp_address(a)){cp_reads++;assert(!forbid_cp);}if(mmio_reads==fail_read_at)return fail_read_code;if(failure==7 || (failure==29 && a==0x3d02020) || a==route_fail_address)return 1;*v=0;
 if(a==0x3dc0058 || a==0x3dc2058)*v=failure==8?2:0x400;
 if(a==0x3da0800)*v=0x80000005;if(a==0x3da0c00)*v=2;
 if(a==0x3da0804)*v=0x80000000;
 if(a==0x3da0808)*v=0x80000001;
 if(a==0x3dc0000 || a==0x3dc2000)*v=0x1027;
 if(a==0x3d8ec30){busy_reads++;*v=busy_clear_after && busy_reads>=busy_clear_after?0:fake_busy;}
 if(a==0x3d3d000)*v=!mode_consumed;
 if(a==0x3d02020)*v=fake_sqe^(failure==26?2:0);if(a==0x3d02018)*v=fake_rptr;if(a==0x3d0201c)*v=fake_wptr;
 if(a==0x3d00840)*v=failure==10 || (context_idle_fail==1 && fake_wptr==37)?2:1;
 if(a==0x3d00804)*v=failure==11;
 if(a==0x3d8ec4c && context_kick_fail==1 && fake_wptr==37)return 31;
 if(a==0x3d02084)*v=failure==12 || (context_idle_fail==2 && fake_wptr==37);if(a==0x3d0005c)*v=failure==23?0:fake_gx_halt;if(a==0x3d0f118)*v=fake_gbif_halt&~(failure==24?1u:failure==25?2u:0u);if(a==route_bad_address)*v^=route_bad_mask;if(mmio_reads==bad_read_at)*v^=(uint32_t)bad_read_mask;return 0;}
static int GpuTryRead64(uint64_t a,uint64_t*v){mmio_reads++;if(cp_address(a)){cp_reads++;assert(!forbid_cp);}if(mmio_reads==fail_read_at)return fail_read_code;if(failure==9)return 1;if(a==0x3dc0060){*v=0x63001000;return 0;}assert(a==0x3dc0020 || a==0x3dc0028 || a==0x3dc2020 || a==0x3dc2028);*v=a;if(mmio_reads==bad_read_at)*v^=bad_read_mask;return 0;}
static void MmioWrite32(uint32_t a,uint32_t v){
 mmio_writes++;if(cp_address(a)){cp_writes++;assert(!forbid_cp);}
 if(a==0x3d02020)fake_sqe=v;
 if(a==0x3d0201c){
  fake_wptr=v;
  if(mode_gpu){
   assert(doorbells<ARRAY_SIZE(doorbell_wptr));doorbell_wptr[doorbells++]=v;
   uint32_t*words=(uint32_t*)(pool+3*HSC_CLASS_BYTES);
   if(v<=41)assert(!words[0x8000/4] && !words[0x8000/4+1]);
   if(v==12){assert(words[10]==0x70e60001 && !words[11]);mode_consumed++;}
   else if(v==37){assert(HFC_WORDS==25 && context_build_result.ready && context_build_result.valid==3);for(unsigned i=0;i<25;i++)assert(words[12+i]==hfc_word(context_config.root_physical,i));context_consumed++;}
   else if(v==41){assert(context_consumed==1);for(unsigned i=0;i<4;i++)assert(words[37+i]==hgki_ib[i]);assert(hgki_ib[3]==HGKI_SELECTED_COMMAND_WORDS);image_consumed++;}
   else {
    assert(v==46 || v==51);unsigned pass=v==51,at=41+5*pass;
    assert(words[at]==0x703d8003 && words[at+1]==HHR_SCRATCH+4*pass && !words[at+2] && words[at+3]==0xc0ffee00u+pass && words[at+4]==0x70928000 && !words[0x8000/4+pass]);
    /* Simulated GPU store happens only after the actual doorbell callback,
       never in the native CPU publication code under test. */
    words[0x8000/4+pass]=words[at+3];
   }
   fake_rptr=v;
  }
 }
 if((a==0x3d00058 || a==0x3d0f114) && v)assert(fake_cm3==1);
 if(a==0x3d00058)fake_gx_halt=v;if(a==0x3d0f114)fake_gbif_halt=v;if(a==0x3d7e000)fake_cm3=v;
}
static int StockWrite32(void*c,uint32_t a,uint32_t v){(void)c;assert(a==0x3d7e000 && v==1);if(failure==28)return 1;MmioWrite32(a,v);return 0;}
static int HostRingStore32(uint32_t v){mHostWriteCalls++;MmioWrite32(0x3d02020,v);return 0;}
static void HostWriteReport(void){}
static unsigned zap_calls,zap_fail;
static int HostRingLoadAuthenticatedZap(void){zap_calls++;return zap_fail;}
static int HostRingRunKnownImage(void);
static unsigned CaptureGraphicsStall(unsigned Stage);
static int HostRingBuildFirstContext(void);
static const uint32_t *HostRingFirstContextWords(void);
static int HostRingFirstContextMatch(const uint32_t*,unsigned);
static int ggs_aarch64_call(void*c,struct ggs_regs*r){(void)c;scm_calls++;if(failure==13)return 1;uint64_t f=r->x[0];r->x[0]=failure==14?2:0;r->x[1]=f==0x42000601?(failure==15?0:1):0;return 0;}
static uint64_t BatchCounter(void){return 0;}
static uint64_t BatchMicroseconds(uint64_t a){return a;}
static int SecureCxDelay(void*c,unsigned u){(void)c;(void)u;return 0;}
static int ContextDelay(void*c,unsigned u){(void)c;(void)u;delay_calls++;return failure==16;}
static uint64_t ProbeCheckpoint(const char*s){(void)s;assert(!mHostRingUnsafe && (fake_sqe==0 || fake_sqe==3 || ((fake_gx_halt&1) && (fake_gbif_halt&2))) && tpl==4);fs++;return 0;}
'''
suffix=r'''
static void reset(void){memset(pool,0,sizeof pool);memset(&mHostRing,0,sizeof mHostRing);memset(&mHostRingLog,0,sizeof mHostRingLog);memset(&mHostAperture,0,sizeof mHostAperture);memset(mHostRingSnapshots,0,sizeof mHostRingSnapshots);mHostRingPrepared=mHostApertureKind=mHostApertureCalls=mHostApertureValid=mHostApertureQueryCode=mHostApertureCode=0;fake_gx_halt=fake_gbif_halt=fake_cm3=0;memset(&mHostBusStop,0,sizeof mHostBusStop);mHostHwDone=0;mHostApertureAvailable=mHostApertureElapsed=0;mHostEngineStopped=mHostEngineComplete=0;memset(&mHostEngineLog,0,sizeof mHostEngineLog);memset(&mHostFirstIo,0,sizeof mHostFirstIo);memset(&mStockResult,0,sizeof mStockResult);mHostRingCpFailed=mHostRingEntryReady=0;
 memset(&mHostFirstGuard,0,sizeof mHostFirstGuard);freeze_calls=fail_read_at=bad_read_at=mem_fail_at=0;fail_read_code=17;bad_read_mask=0;queue_calls=queue_fail=queue_mismatch=0;mFirmwareMemory.count=0;
 memset(&mHostRingBusy,0,sizeof mHostRingBusy);fake_busy=busy_reads=busy_clear_after=delay_calls=0;
 memset(&mHostStopPoll,0,sizeof mHostStopPoll);mHostDirectReady=0;memset(&mHostMode,0,sizeof mHostMode);memset(&mHostImage,0,sizeof mHostImage);memset(&mHostContext,0,sizeof mHostContext);memset(&context_build_result,0,sizeof context_build_result);memset(context_words,0,sizeof context_words);context_consumed=context_build_calls=context_build_fail=context_publish_fail=context_kick_fail=context_idle_fail=context_words_null=context_root_reads=stall_calls=stall_stage=stall_cp_failed=doorbells=0;memset(doorbell_wptr,0,sizeof doorbell_wptr);zap_calls=zap_fail=mode_gpu=mode_consumed=image_gpu=image_consumed=image_fail=0;
 memset(mGraphicsReadiness,0,sizeof mGraphicsReadiness);
 failure=mmio_writes=mmio_reads=cp_reads=cp_writes=forbid_cp=power_checks=scm_calls=prep_checks=memchecks=fs=fake_sqe=fake_rptr=fake_wptr=mHostWriteCalls=mHostWriteFaults=0;tpl=16;
 route_bad_address=route_bad_mask=route_fail_address=0;
 mHostProfileReady=mFirmwareHeld=mGxMapped=mGen7Mapped=mCodeReady=mScratchAssigned=mScratchReady=mDmaZeroRetained=1;
 mHostPrep.code=mGen7.code=mCodeBind.code=0;mHostPrep.phase=mGen7.phase=mCodeBind.phase=6;mGen7.record_ready=1;mCodeBind.verified=15;
 mGxStart.acked=mGxStart.clear_confirmed=1;memset(&mScratchResult,0,sizeof mScratchResult);
 mScratchResult.phase=5;mScratchResult.enabled=mScratchResult.attached=mScratchResult.retained=mScratchResult.lpac=mScratchResult.sid0_attached=mScratchResult.lpac_attached=1;
 mScratchResult.sid0_smr=0x80000000;mScratchResult.lpac_smr=0x80000001;
 mSharedCount=mSecureAssigned=mSecureContext.attached=mSecureMemory.owned=mSecureTableOwned=mHostRingUnsafe=0;mGpuSaveAllowed=1;mFirmwareMemory.retained=HFM_ALL;
 mGpuOnlyMemory.iova=0x62000000;mGpuOnlyMemory.physical=0x80000000;mGpuOnlyMemory.cpu=pool;mGpuOnlyNext[3]=3*HSC_CLASS_BYTES;
 mSecureCx=(struct ggs_state){.convention_verified=1,.init_succeeded=1};}
static void prepared(void){reset();assert(!HostRingPrepare(NULL) && mHostHwDone==7);mmio_writes=mmio_reads=cp_reads=cp_writes=power_checks=0;memset(&mHostRingBusy,0,sizeof mHostRingBusy);busy_reads=0;}
static void first_guard(unsigned stage,unsigned kind,uint32_t address,uint64_t mask,uint64_t expected,uint64_t actual,unsigned valid,int code){
 assert(mHostFirstGuard.seen==1 && mHostFirstGuard.phase==3 && mHostFirstGuard.stage==stage && mHostFirstGuard.kind==kind && mHostFirstGuard.address==address && mHostFirstGuard.mask==mask && mHostFirstGuard.expected==expected && mHostFirstGuard.actual==actual && mHostFirstGuard.valid==valid && mHostFirstGuard.read_code==code);
}
static void engine_prepared(void){prepared();mHostRing.phase=3;mHostEngineStopped=1;fake_sqe=3;memchecks=0;}
static void direct_prepared(void){prepared();assert(!HostRingAperture(NULL));mHostRing.phase=3;mHostRing.configured=7;assert(!HostRingCheckpoint(NULL));mHostRing.enabled=1;assert(!HostRingWrite(NULL,0x3d02020,1));const struct hhr_io io={.read=HostRingRead};assert(!hhr_read(&io,&mHostRing,0x3d02020,&mHostRing.sqe));}
static void cp_idle_prepared(void){direct_prepared();assert(!HostRingEngineProbe(NULL));mHostRing.phase=4;mHostRing.wptr=10;assert(!HostRingWrite(NULL,0x3d0201c,10));fake_rptr=10;const struct hhr_io io={.guard=HostRingGuard,.read=HostRingRead,.delay=ContextDelay};assert(!hhr_idle(&io,&mHostRing));}
static unsigned sticky_diagnostics(void){unsigned cases=0;
 // Each pre-existing CPU ownership predicate identifies its own bit without
 // evaluating power/MMIO, and the diagnostic latch preserves the first one.
 for(unsigned i=0;i<36;i++){
  prepared();mHostRing.phase=3;unsigned *state[]={&mHostProfileReady,&mHostPrep.code,&mHostPrep.phase,&mFirmwareHeld,&mGxMapped,&mGen7Mapped,&mCodeReady,&mGxStart.acked,&mGxStart.clear_confirmed,&mScratchAssigned,&mScratchReady,&mScratchResult.code,&mScratchResult.phase,&mScratchResult.enabled,&mScratchResult.attached,&mScratchResult.retained,&mScratchResult.lpac,&mScratchResult.sid0_attached,&mScratchResult.lpac_attached,&mScratchResult.sid0_smr,&mScratchResult.sid0_s2cr,&mScratchResult.lpac_smr,&mScratchResult.lpac_s2cr,&mGen7.code,&mGen7.phase,&mGen7.record_ready,&mCodeBind.code,&mCodeBind.phase,&mCodeBind.verified,&mFirmwareMemory.retained,&mDmaZeroRetained,&mSharedCount,&mSecureAssigned,&mSecureContext.attached,&mSecureMemory.owned,&mSecureTableOwned};
  *state[i]^=1;assert(HostRingBusPower() && !mmio_reads && !mmio_writes && !power_checks && !freeze_calls);
  first_guard(HHG_BUS_POWER,HHG_STATE,0,UINT64_MAX,0,1ULL<<i,1,0);cases++;
 }
 // The actual guard performs exactly these 16 observations in order. Both a
 // failed raw read and a bad successful value stop at the same observation.
 const struct {unsigned stage;uint32_t address;uint64_t mask,expected,normal;} guards[]={
  {HHG_BUS_POWER,0x3d7e340,3,0,0},{HHG_BUS_POWER,0x3d8ec40,0xffffffffu,0,0},
  {HHG_POWER,0x3d8ec30,0x800000,0,0},{HHG_GUARD,0x3dc0058,0xc00001feu,0,0x400},
  {HHG_ROUTES,0x3da0800,0xffffffffu,0x80000005,0x80000005},{HHG_ROUTES,0x3da0c00,0xffffffffu,2,2},
  {HHG_ROUTES,0x3da0804,0xffffffffu,0x80000000,0x80000000},{HHG_ROUTES,0x3da0c04,0xffffffffu,0,0},
  {HHG_ROUTES,0x3da0808,0xffffffffu,0x80000001,0x80000001},{HHG_ROUTES,0x3da0c08,0xffffffffu,0,0},
  {HHG_GUARD,0x3dc0000,0xffffefff,0x27,0x1027},{HHG_GUARD,0x3dc2000,0xffffefff,0x27,0x1027},
  {HHG_GUARD,0x3dc0020,UINT64_MAX,0x3dc0020,0x3dc0020},{HHG_GUARD,0x3dc0028,UINT64_MAX,0x3dc0028,0x3dc0028},
  {HHG_GUARD,0x3dc2020,UINT64_MAX,0x3dc2020,0x3dc2020},{HHG_GUARD,0x3dc2028,UINT64_MAX,0x3dc2028,0x3dc2028}};
 for(unsigned i=0;i<ARRAY_SIZE(guards);i++)for(unsigned bad=0;bad<2;bad++){
  prepared();mHostRing.phase=3;uint64_t bit=guards[i].mask&(~guards[i].mask+1);
  if(bad){bad_read_at=i+1;bad_read_mask=bit;}else fail_read_at=i+1;
  assert(HostRingGuard(NULL) && mmio_reads==i+1 && !mmio_writes && !freeze_calls);
  first_guard(guards[i].stage,HHG_REGISTER,guards[i].address,guards[i].mask,guards[i].expected,bad?(guards[i].normal^bit):0,bad,bad?0:17);
  __typeof__(mHostFirstGuard) saved=mHostFirstGuard;unsigned reads=mmio_reads;failure=3;fail_read_at=bad_read_at=0;uint32_t value=0xfeedface;
  assert(HostRingRead(NULL,0x3d02020,&value) && value==0xfeedface && mHostFirstIo.code==HHR_NATIVE_GUARD && freeze_calls==1);
  assert(HostRingRead(NULL,0x3d02020,&value) && freeze_calls==1 && mmio_reads==reads && !memcmp(&saved,&mHostFirstGuard,sizeof saved));cases++;
 }
 prepared();mHostRing.phase=3;assert(!HostRingGuard(NULL) && mmio_reads==16 && !mmio_writes && !mHostFirstGuard.seen);cases++;
 prepared();mHostRing.phase=3;failure=3;assert(HostRingGuard(NULL) && !mmio_reads && power_checks==1);first_guard(HHG_BUS_POWER,HHG_POWER_OWNER,0,1,1,0,1,0);cases++;
 prepared();mHostRing.phase=3;failure=4;assert(HostRingGuard(NULL) && mmio_reads==3);first_guard(HHG_GUARD,HHG_BOOTSTRAP,0,1,1,0,1,0);cases++;
 prepared();mHostRing.phase=3;mHostRingPrepared=0;failure=1;assert(HostRingGuard(NULL) && !mmio_reads);first_guard(HHG_GUARD,HHG_PREPARATION,0,UINT64_MAX,0,1,1,0);cases++;
 prepared();mHostRing.phase=3;mHostRingPrepared=0;assert(HostRingBusLease() && mmio_reads==2);first_guard(HHG_LEASE,HHG_STATE,0,1,1,0,1,0);cases++;
 for(unsigned i=0;i<4;i++){
  prepared();mHostRing.phase=3;fail_read_at=i+3;assert(HostRingBusLease() && mmio_reads==i+3);first_guard(HHG_LEASE,HHG_REGISTER,guards[12+i].address,UINT64_MAX,guards[12+i].expected,0,0,17);cases++;
 }
 // NULL output, address allowlist, guard refusal, and the actual final read
 // have distinct native codes. A successful callback adds only its one read.
 for(unsigned branch=0;branch<4;branch++){
  prepared();mHostRing.phase=3;uint32_t value=0xfeedface;uint32_t address=branch==1?0x1234:0x3d02020;
  if(branch==2){bad_read_at=3;bad_read_mask=0x800000;}if(branch==3)fail_read_at=17;
  assert(HostRingRead(NULL,address,branch?&value:NULL) && freeze_calls==1 && mHostFirstIo.operation==1 && mHostFirstIo.code==branch+1 && value==0xfeedface);
  assert(mmio_reads==(branch<2?0:branch==2?3:17) && !mmio_writes);
  if(branch<2)first_guard(HHG_READ,branch?HHG_ALLOW:HHG_ARGUMENT,address,1,1,0,1,0);
  else if(branch==2)first_guard(HHG_POWER,HHG_REGISTER,0x3d8ec30,0x800000,0,0x800000,1,0);
  else first_guard(HHG_READ,HHG_REGISTER,address,0,0,0,0,17);cases++;
 }
 prepared();mHostRing.phase=3;fake_sqe=1;uint32_t value=0;assert(!HostRingRead(NULL,0x3d02020,&value) && value==1 && mmio_reads==17 && !mHostFirstGuard.seen && !freeze_calls);cases++;
 for(unsigned i=0;i<3;i++){
  prepared();mHostRing.phase=3;mHostRing.configured=7;unsigned *state[]={&mHostRingUnsafe,&mHostRing.enabled,&mHostRing.configured};*state[i]^=1;
  assert(HostRingLogGuard(NULL) && !mmio_reads);first_guard(HHG_LOG,HHG_STATE,0,7,0,1u<<i,1,0);cases++;
 }
 prepared();mHostRing.phase=3;mHostRing.configured=7;failure=1;assert(HostRingLogGuard(NULL) && !mmio_reads);first_guard(HHG_LOG,HHG_PREPARATION,0,UINT64_MAX,0,1,1,0);cases++;
 for(unsigned i=0;i<5;i++){
  engine_prepared();unsigned *state[]={&mHostBusStop.stage,&mHostEngineStopped,&mHostRingUnsafe,&mHostRing.kicks,&mHostRing.wptr};*state[i]^=1;
  assert(HostEngineGuard(NULL) && !mmio_reads);first_guard(HHG_ENGINE,HHG_STATE,0,31,0,1u<<i,1,0);cases++;
 }
 for(unsigned i=5;i<=6;i++){
  engine_prepared();failure=i;assert(HostEngineGuard(NULL) && mmio_reads==16);first_guard(HHG_ENGINE,i==5?HHG_CONTEXT:HHG_AUDIT,0,UINT64_MAX,0,1,1,0);cases++;
 }
 const uint32_t engine_addresses[]={0x3d02020,0x3d02018,0x3d0201c,0x3d00840,0x3d00804,0x3d02084};
 for(unsigned i=0;i<6;i++)for(unsigned bad=0;bad<2;bad++){
  engine_prepared();uint64_t mask=i==3?0xfffffffeu:0xffffffffu,expected=i?0:3,normal=i==3?1:expected,bit=mask&(~mask+1);
  if(bad){bad_read_at=i+17;bad_read_mask=bit;}else fail_read_at=i+17;
  assert(HostEngineGuard(NULL) && mmio_reads==i+17 && !queue_calls);first_guard(HHG_ENGINE,HHG_REGISTER,engine_addresses[i],mask,expected,bad?(normal^bit):0,bad,bad?0:17);cases++;
 }
 for(unsigned i=1;i<=GGH_QUEUES;i++)for(unsigned bad=0;bad<2;bad++){
  engine_prepared();if(bad)queue_mismatch=i;else queue_fail=i;
  assert(HostEngineGuard(NULL) && mmio_reads==22 && queue_calls==i && !memchecks);first_guard(HHG_ENGINE,HHG_QUEUE,i-1,0xffffffffu,0,bad?1:0,bad,bad?0:17);cases++;
 }
 for(unsigned i=1;i<=4;i++){
  engine_prepared();mem_fail_at=i;assert(HostEngineGuard(NULL) && mmio_reads==22 && queue_calls==17 && memchecks==i);
  first_guard(HHG_ENGINE,HHG_MEMORY,i==1?0:0xfe + i,UINT64_MAX,0,1,1,0);cases++;
 }
 engine_prepared();assert(!HostEngineGuard(NULL) && mmio_reads==22 && queue_calls==17 && memchecks==4 && !mHostFirstGuard.seen && !freeze_calls);cases++;
 return cases;
}
static unsigned running_busy(void){unsigned cases=0;
 // enabled is set before the first SQE store. It cannot grant running access;
 // neither can an unsafe marker without an actual low-level store attempt.
 for(unsigned unsafe=0;unsafe<2;unsafe++){
  prepared();mHostRing.phase=3;mHostRing.enabled=1;mHostRingUnsafe=unsafe;fake_busy=0x71c00004;uint32_t value=0xfeedface;
  assert(HostRingRead(NULL,0x3d02020,&value) && value==0xfeedface && !cp_reads && mmio_reads==3 && mHostFirstIo.code==HHR_NATIVE_GUARD);
  first_guard(HHG_POWER,HHG_REGISTER,0x3d8ec30,0x800000,0,0x71c00004,1,0);assert(mHostRingBusy.idle_required==1 && mHostRingBusy.busy==1);cases++;
 }
 // Use the real Checkpoint -> Write(1) path before asserting running busy.
 prepared();mHostRing.phase=3;mHostRing.configured=7;assert(!HostRingCheckpoint(NULL));mHostRing.enabled=1;assert(!HostRingWrite(NULL,0x3d02020,1));
 fake_busy=0x71c00004;uint32_t value=0;unsigned reads=mmio_reads,required=mHostRingBusy.idle_required;
 assert(!HostRingRead(NULL,0x3d02020,&value) && value==1 && mmio_reads==reads+17 && !mHostFirstGuard.seen && !freeze_calls && mHostRingBusy.last==fake_busy && mHostRingBusy.valid && mHostRingBusy.idle_required==required);
 mHostRing.phase=4;mHostRing.wptr=10;assert(!HostRingWrite(NULL,0x3d0201c,10) && fake_wptr==10 && !mHostFirstIo.valid);cases++;
 // Running busy never bypasses the original power/HFI/fault/root/routes gates.
 const unsigned failures[]={3,4,7,8,9};
 for(unsigned i=0;i<ARRAY_SIZE(failures);i++){
  prepared();mHostRing.phase=4;mHostRing.enabled=mHostRingUnsafe=mHostWriteCalls=1;fake_sqe=1;fake_busy=0x71c00004;failure=failures[i];value=0xfeedface;
  assert(HostRingRead(NULL,0x3d02020,&value) && value==0xfeedface && !cp_reads && !mmio_writes && mHostRingCpFailed && mHostFirstIo.code==HHR_NATIVE_GUARD);cases++;
 }
 for(unsigned i=0;i<6;i++){
  const uint32_t routes[]={0x3da0800,0x3da0c00,0x3da0804,0x3da0c04,0x3da0808,0x3da0c08};
  prepared();mHostRing.phase=4;mHostRing.enabled=mHostRingUnsafe=mHostWriteCalls=1;fake_busy=0x71c00004;route_bad_address=routes[i];route_bad_mask=1;
  assert(HostRingGuard(NULL) && mHostFirstGuard.stage==HHG_ROUTES && !cp_reads && !mmio_writes);cases++;
 }
 prepared();mHostRing.phase=4;mHostRing.enabled=mHostRingUnsafe=mHostWriteCalls=1;fake_sqe=1;fake_busy=0x71c00004;fail_read_at=17;value=0xfeedface;
 assert(HostRingRead(NULL,0x3d02020,&value) && mHostFirstIo.code==HHR_NATIVE_READ && value==0xfeedface && mmio_reads==17 && freeze_calls==1);cases++;
 // Both filesystem guards continue to require idle outside the running lease.
 prepared();mHostRing.phase=3;mHostRing.configured=7;mHostWriteCalls=1;fake_busy=0x71c00004;assert(HostRingLogGuard(NULL) && !fs && mmio_reads==3);cases++;
 engine_prepared();mHostWriteCalls=2;fake_busy=0x71c00004;assert(HostEngineGuard(NULL) && !fs && mmio_reads==3);cases++;
 // Normal quiescence polls busy rather than publishing stopped or touching FS.
 // It succeeds only after a fresh guard sees bit23 clear, preserving the
 // original finite stop bound and emergency-reset/three-ACK fallback.
 prepared();mHostRing.enabled=mHostRingUnsafe=mHostWriteCalls=1;fake_sqe=1;fake_busy=0x71c00004;busy_clear_after=4;
 assert(!HostRingStop(NULL,0) && !mHostRingUnsafe && fake_sqe==3 && !mHostBusStop.stage && busy_reads==4 && delay_calls==2 && mHostRingBusy.valid && !(mHostRingBusy.last&0x800000) && !fs);
 assert(mHostStopPoll.polls==3 && mHostStopPoll.first.valid==63 && mHostStopPoll.first.failed==32 && mHostStopPoll.first.busy==0x71c00004 && mHostStopPoll.last.valid==63 && !mHostStopPoll.last.failed && !mHostStopPoll.last.busy && !mHostStopPoll.timeout && !freeze_calls);cases++;
 prepared();mHostRing.enabled=mHostRingUnsafe=mHostWriteCalls=1;fake_sqe=1;fake_busy=0x71c00004;failure=16;
 assert(HostRingStop(NULL,0) && mHostRingUnsafe && fake_sqe==3 && !mHostBusStop.stage && busy_reads==2 && delay_calls==1 && !fs);cases++;
 prepared();mHostRing.enabled=mHostRingUnsafe=mHostWriteCalls=1;fake_sqe=1;fake_busy=0x71c00004;failure=23;
 assert(HostRingStop(NULL,0) && mHostRingUnsafe && !mHostBusStop.stopped && busy_reads==1001 && delay_calls>=1000 && !fs);cases++;
 return cases;
}
static unsigned direct_and_stop(void){unsigned cases=0;
 // The actual start/readback callback chain reaches direct CP_INIT without
 // a second SQE store, interim halt, filesystem save, or fake legacy result.
 direct_prepared();unsigned reads=mmio_reads,writes=mmio_writes;fake_busy=0x71c00004;
 assert(!HostRingEngineProbe(NULL) && mHostDirectReady && mmio_reads==reads+16 && mmio_writes==writes && mHostWriteCalls==1 && fake_sqe==1 && mHostRingUnsafe && !mGpuSaveAllowed && !fs && !mHostEngineStopped && !mHostEngineComplete && !mHostEngineLog.phase && !mHostEngineLog.restored);cases++;
 // Simulate the eventual final Stop after the real command callback path;
 // only this final quiescence is permitted to clear the unsafe lease.
 mHostRing.phase=7;mHostRing.wptr=fake_rptr=20;fake_busy=0;
 assert(!HostRingStop(NULL,20) && !mHostRingUnsafe && mHostWriteCalls==2 && !mHostBusStop.stage && mHostStopPoll.polls==1 && mHostStopPoll.first.valid==63 && !mHostStopPoll.first.failed && mHostStopPoll.last.sqe==3 && mHostStopPoll.wptr==20 && !freeze_calls && !fs);cases++;
 for(unsigned field=0;field<12;field++){
  direct_prepared();unsigned *state[]={&mHostEngineStopped,&mHostEngineComplete,&mHostRing.kicks,&mHostRing.wptr,&mHostRing.phase,&mHostRing.enabled,&mHostRingUnsafe,&mHostWriteCalls,&mHostRing.sqe,&mHostRing.last_valid,&mHostRing.last_operation,&mHostRing.last_address};
  *state[field]^=1;reads=mmio_reads;writes=mmio_writes;assert(HostRingEngineProbe(NULL) && !mHostDirectReady && mmio_reads==reads && mmio_writes==writes && !fs);cases++;
 }
 direct_prepared();mHostRing.last_value=0;reads=mmio_reads;assert(HostRingEngineProbe(NULL) && !mHostDirectReady && mmio_reads==reads && !fs);cases++;
 const unsigned rejected[]={3,4,7,8,9};
 for(unsigned i=0;i<ARRAY_SIZE(rejected);i++){
  direct_prepared();failure=rejected[i];writes=mmio_writes;assert(HostRingEngineProbe(NULL) && !mHostDirectReady && mmio_writes==writes && !fs && mHostRingUnsafe && !mHostEngineComplete && !mHostEngineStopped);cases++;
 }
 // Every normal Stop predicate has an independent sticky raw observation.
 // Persistent mismatches time out before emergency reset/isolation, which
 // cannot overwrite these CPU records or require a subsequent CP access.
 for(unsigned bad=0;bad<6;bad++){
  direct_prepared();if(bad==0)failure=26;if(bad==1)fake_rptr=1;if(bad==2)failure=10;if(bad==3)failure=11;if(bad==4)failure=12;if(bad==5)fake_busy=0x71c00004;
  assert(!HostRingStop(NULL,0) && mHostBusStop.stopped && !mHostRingUnsafe && mHostStopPoll.timeout && mHostStopPoll.polls==1000 && !mHostStopPoll.read_code && freeze_calls==1 && !fs);
  assert(mHostStopPoll.first.valid==63 && mHostStopPoll.last.valid==63 && mHostStopPoll.first.failed==(1u<<bad) && mHostStopPoll.last.failed==(1u<<bad));
  __typeof__(mHostStopPoll) saved=mHostStopPoll;unsigned cp=cp_reads;assert(!HostRingStop(NULL,0) && !memcmp(&saved,&mHostStopPoll,sizeof saved) && cp_reads==cp && freeze_calls==1);cases++;
 }
 // A failed read never turns an initialized zero into a successful raw value;
 // preserve the completed prefix and stop before any subsequent CP read.
 for(unsigned i=0;i<5;i++){
  direct_prepared();reads=mmio_reads;unsigned before_cp=cp_reads;fail_read_at=reads+33+i;
  const unsigned cp_counts[]={1,2,2,2,3};
  assert(!HostRingStop(NULL,0) && mHostBusStop.stopped && mHostStopPoll.polls==1 && !mHostStopPoll.timeout && mHostStopPoll.read_code==17 && mHostStopPoll.last.valid==(32u|((1u<<i)-1)) && cp_reads==before_cp+cp_counts[i] && !freeze_calls && !fs);
  assert(mHostStopPoll.last.failed==((~mHostStopPoll.last.valid)&63));cases++;
 }
 return cases;
}
static unsigned graphics_hooks(void){unsigned cases=0;
 prepared();assert(mGraphicsReadiness[0].started && mGraphicsReadiness[0].phase==4 && mGraphicsReadiness[0].valid==7 && mGraphicsReadiness[0].reads==3 && mGraphicsReadiness[0].guards==4 && !mGraphicsReadiness[1].started && !mGraphicsReadiness[2].started && !fs && !delay_calls && !mHostWriteCalls);cases++;
 assert(!HostRingAperture(NULL) && mGraphicsReadiness[1].phase==4 && mGraphicsReadiness[1].valid==7 && mmio_reads==67 && !mHostWriteCalls && !fs && !delay_calls);cases++;
 for(unsigned f=13;f<=15;f++){
  prepared();failure=f;assert(HostRingAperture(NULL) && !mGraphicsReadiness[1].started && !mmio_reads && !mHostWriteCalls && !freeze_calls);cases++;
 }
 // Prepare keeps its existing read/write/guard prefix; a failing original
 // guard must not start the new security-state snapshot at all.
 reset();fail_read_at=34;assert(HostRingPrepare(NULL) && !mGraphicsReadiness[0].started && mmio_reads==34 && !freeze_calls);cases++;
 for(unsigned i=0;i<3;i++){
  reset();fail_read_at=51+17*i;
  assert(HostRingPrepare(NULL) && mHostRingCpFailed && mHostFirstIo.valid && mHostFirstIo.address==hgr_address(i) && mHostFirstIo.code==HHR_NATIVE_READ && freeze_calls==1 && mmio_reads==51+17*i && !mGraphicsReadiness[1].started && !mHostWriteCalls && !fs);
  assert(mGraphicsReadiness[0].code==HGR_READ && mGraphicsReadiness[0].read_code==17 && mGraphicsReadiness[0].valid==((1u<<i)-1) && !mGraphicsReadiness[0].raw[i] && mHostFirstGuard.address==hgr_address(i) && !mHostFirstGuard.valid && mHostFirstGuard.read_code==17);cases++;
 }
 reset();fail_read_at=35;assert(HostRingPrepare(NULL) && mGraphicsReadiness[0].code==HGR_OWNER && !mGraphicsReadiness[0].reads && mHostRingCpFailed && mHostFirstIo.code==HHR_NATIVE_GUARD && freeze_calls==1 && mmio_reads==35);cases++;
 for(unsigned i=0;i<3;i++){
  prepared();fail_read_at=17+17*i;assert(HostRingAperture(NULL) && !mHostApertureCode && mGraphicsReadiness[1].code==HGR_READ && mGraphicsReadiness[1].valid==((1u<<i)-1) && mHostRingCpFailed && mHostFirstIo.address==hgr_address(i) && mHostFirstIo.code==HHR_NATIVE_READ && freeze_calls==1 && mmio_reads==17+17*i && !mHostWriteCalls && !fs);cases++;
 }
 cp_idle_prepared();unsigned reads=mmio_reads;HostRingSnapshot(NULL,1);
 assert(mGraphicsReadiness[2].phase==4 && mGraphicsReadiness[2].valid==7 && mHostRingSnapshots[1].taken && mmio_reads==reads+100 && !mHostRing.code && !mHostRingCpFailed && mHostRingUnsafe && !mGpuSaveAllowed && !fs && !freeze_calls);cases++;
 for(unsigned i=0;i<3;i++){
  cp_idle_prepared();reads=mmio_reads;unsigned cp=cp_reads;fail_read_at=reads+20+17*i;HostRingSnapshot(NULL,1);
  assert(mHostRing.code==HHR_IO && mHostRingCpFailed && mHostFirstIo.address==hgr_address(i) && mHostFirstIo.code==HHR_NATIVE_READ && freeze_calls==1 && mGraphicsReadiness[2].code==HGR_READ && mGraphicsReadiness[2].valid==((1u<<i)-1) && !mHostRingSnapshots[1].taken && cp_reads==cp && mmio_reads==reads+20+17*i && !mHostRing.init_idle && !fs);
  // The existing generic if(code) immediately takes this fault-isolation
  // path rather than publishing either canary or making another CP read.
  forbid_cp=1;assert(!HostRingStop(NULL,10) && mHostBusStop.stopped && !mHostRingUnsafe && cp_reads==cp && freeze_calls==1 && !mHostRing.writebacks && !fs);cases++;
 }
 cp_idle_prepared();reads=mmio_reads;fail_read_at=reads+4;HostRingSnapshot(NULL,1);
 assert(mHostRing.code==HHR_IO && mHostRingCpFailed && mGraphicsReadiness[2].code==HGR_OWNER && !mGraphicsReadiness[2].reads && mHostFirstIo.code==HHR_NATIVE_GUARD && freeze_calls==1 && mmio_reads==reads+4 && !mHostRingSnapshots[1].taken && !fs);cases++;
 return cases;
}

static unsigned context_doorbell_blocked(void){return context_kick_fail==2 && mHostContext.phase==3 && mHostContext.published && !mHostContext.submitted;}
static unsigned CaptureGraphicsStall(unsigned Stage){stall_calls++;stall_stage=Stage;stall_cp_failed=mHostRingCpFailed;return 0;}
static int context_policy_owner(void*c){assert(!c);return HostRingGuard(NULL);}
static int context_policy_root(void*c,uint32_t a,uint64_t*v){assert(!c && v && (a==0x3dc0020 || a==0x3dc0028));context_root_reads++;if(context_build_fail==3 && a==0x3dc0028)return 29;*v=((uint64_t)HFC_ASID<<48)|(a==0x3dc0020?context_config.root_physical:0);if(context_build_fail==4 && a==0x3dc0020)*v^=4096;return 0;}
static int HostRingBuildFirstContext(void){context_build_calls++;assert(mHostContext.started && mHostContext.phase==1 && !mHostContext.built);if(context_build_fail==1)return 47;struct hfc_config config=context_config;if(context_build_fail==2)config.prior_full_idle=0;const struct hfc_io io={NULL,context_policy_owner,context_policy_root};unsigned code=hfc_build(&io,&config,context_words,HFC_WORDS,&context_build_result);if(!code && context_publish_fail)mem_fail_at=memchecks+1;return (int)code;}
static const uint32_t *HostRingFirstContextWords(void){return context_words_null?NULL:context_words;}
static int HostRingFirstContextMatch(const uint32_t*words,unsigned count){if(!words || count!=HFC_WORDS || !context_build_result.ready || context_build_result.valid!=3 || context_build_result.ttbr0!=((uint64_t)HFC_ASID<<48|context_config.root_physical) || context_build_result.ttbr1!=((uint64_t)HFC_ASID<<48))return 1;for(unsigned i=0;i<HFC_WORDS;i++)if(words[i]!=hfc_word(context_config.root_physical,i))return 1;return 0;}
static int HostRingRunKnownImage(void){if(!image_gpu){(void)HostKnownImageSubmit;(void)HostKnownImageIdle;return 0;}mHostImage.started=1;mHostImage.phase=1;if(image_fail)return 1;if(HostKnownImageSubmit(NULL,hgki_ib,4) || HostKnownImageIdle(NULL))return 1;mHostImage.complete=1;mHostImage.phase=5;return 0;}
static void mode_prepared(void){cp_idle_prepared();mHostRing.init_idle=1;mode_gpu=1;}
static void context_ready_prepared(void){
 // Targeted publication/allowlist fixture: the mode exit is already idle.
 // The end-to-end cases below execute the actual PAS -> mode -> wrapper chain.
 mode_prepared();mHostRing.wptr=mHostRing.rptr=fake_wptr=fake_rptr=12;
 mHostMode.started=mHostMode.authenticated=mHostMode.published=mHostMode.submitted=mHostMode.idle=mHostMode.complete=1;mHostMode.phase=5;mode_consumed=1;
}
static void context_packet_prepared(void){
 context_ready_prepared();mHostContext.started=1;mHostContext.phase=1;
 assert(!HostRingBuildFirstContext() && context_build_result.ready && context_build_result.valid==3);
 mHostContext.built=1;mHostContext.phase=2;
}
static unsigned authenticated_mode(void){unsigned cases=0;
 mode_prepared();assert(!HostRingPostInit(NULL,&mHostRing));
 assert(zap_calls==1 && mHostMode.authenticated && mHostMode.submitted && mHostMode.idle && mHostMode.complete && mHostMode.phase==5 && !mHostMode.code && mHostRing.wptr==37 && mHostRing.rptr==37 && mode_consumed==1 && !fs && !mHostRingCpFailed);
 assert(mHostContext.started && mHostContext.built && mHostContext.published && mHostContext.submitted && mHostContext.idle && mHostContext.complete && mHostContext.phase==5 && !mHostContext.code && context_build_calls==1 && context_root_reads==2 && context_consumed==1 && !image_consumed && doorbells==2 && doorbell_wptr[0]==12 && doorbell_wptr[1]==37);
 assert(mGraphicsReadiness[HGR_POST_AUTH].valid==7 && mGraphicsReadiness[HGR_POST_AUTH].raw[0]==1 && mGraphicsReadiness[HGR_POST_MODE_IDLE].valid==7 && mGraphicsReadiness[HGR_POST_MODE_IDLE].raw[0]==0);
 assert(!HostRingCpu()[HHR_BYTES/4] && !HostRingCpu()[HHR_BYTES/4+1]);
 unsigned reads=mmio_reads,writes=mmio_writes;assert(HostRingPostInit(NULL,&mHostRing) && zap_calls==1 && reads==mmio_reads && writes==mmio_writes);cases++;
 // Original canaries move behind the real mode and 25-DW context prefix;
 // old offsets are refused without any partial CPU publication.
 mode_prepared();assert(!HostRingPostInit(NULL,&mHostRing));mHostRing.phase=5;
 uint32_t canary[]={0x703d8003,HHR_SCRATCH,0,0xc0ffee00,0x70928000};
 assert(HostRingPublish(NULL,10,canary,5));assert(HostRingPublish(NULL,12,canary,5));assert(!HostRingPublish(NULL,37,canary,5));
 mHostRing.phase=6;canary[1]+=4;canary[3]++;assert(HostRingPublish(NULL,17,canary,5));assert(!HostRingPublish(NULL,42,canary,5));
 assert(!HostRingCpu()[HHR_BYTES/4] && !HostRingCpu()[HHR_BYTES/4+1]);cases++;
 for(unsigned fault=0;fault<3;fault++){
  mode_prepared();if(fault==0)zap_fail=23;if(fault==1)route_fail_address=0x3d3f000;if(fault==2)mem_fail_at=memchecks+1;
  assert(HostRingPostInit(NULL,&mHostRing) && zap_calls==1 && mHostRingCpFailed && !mHostMode.complete && !mHostMode.submitted && !mode_consumed && fake_wptr==10 && !fs && freeze_calls && !mHostContext.started && !context_build_calls && !image_consumed);
  assert(mHostMode.authenticated==(fault!=0));if(!fault)assert(mHostMode.code==23);
  cp_reads=cp_writes=0;forbid_cp=1;route_fail_address=0;mem_fail_at=0;
  assert(!HostRingStop(NULL,10) && mHostBusStop.stopped && !mHostRingUnsafe && !cp_reads && !cp_writes);cases++;
 }
 for(unsigned gate=0;gate<10;gate++){
  mode_prepared();if(gate==0)mHostRing.phase=3;if(gate==1)mHostRing.init_idle=0;if(gate==2)mHostRing.rptr=9;if(gate==3)mHostRing.wptr=11;if(gate==4)mHostRing.enabled=0;if(gate==5)mHostRingUnsafe=0;if(gate==6)mHostDirectReady=0;if(gate==7)mHostMode.started=1;if(gate==8)fake_busy=0x71c00004;
  struct hhr_result other=mHostRing;assert(HostRingPostInit(NULL,gate==9?&other:&mHostRing) && !zap_calls && !mode_consumed && !mHostMode.complete && !mHostContext.started && !fs);cases++;
 }

 // Actual callbacks consume mode10..11 -> privileged context12..36 -> IB37..40.
 // Two canaries then prove distinct GPU-only writes at WPTR46 and51.
 mode_prepared();image_gpu=1;assert(!HostRingPostInit(NULL,&mHostRing));
 assert(mode_consumed==1 && context_consumed==1 && image_consumed==1 && mHostMode.complete && mHostContext.complete && mHostImage.started && mHostImage.published && mHostImage.submitted && mHostImage.idle && mHostImage.complete && mHostImage.phase==5 && mHostRing.rptr==41 && mHostRing.wptr==41 && !mHostRingCpFailed && !fs);
 const struct hhr_io io={.guard=HostRingGuard,.read=HostRingRead,.write=HostRingWrite,.peek=HostRingPeek,.delay=ContextDelay};
 for(unsigned pass=0;pass<2;pass++){
  mHostRing.phase=5+pass;uint32_t a[]={0x703d8003,HHR_SCRATCH+4*pass,0,0xc0ffee00u+pass,0x70928000};
  assert(HostRingPublish(NULL,pass?21:16,a,5));assert(HostRingPublish(NULL,pass?42:37,a,5));
  assert(!HostRingPublish(NULL,41+5*pass,a,5));
  assert(!HostRingCpu()[HHR_BYTES/4+pass]);mHostRing.wptr+=5;
  assert(!hhr_kick(&io,&mHostRing) && !hhr_idle(&io,&mHostRing));uint32_t observed=0;
  assert(!HostRingPeek(NULL,pass,&observed) && observed==0xc0ffee00u+pass);
 }
 const uint32_t expected_doorbells[]={12,37,41,46,51};
 assert(doorbells==5 && !memcmp(doorbell_wptr,expected_doorbells,sizeof expected_doorbells) && mHostRing.wptr==51 && mHostRing.rptr==51 && !fs);cases++;
 mode_prepared();image_gpu=image_fail=1;assert(HostRingPostInit(NULL,&mHostRing) && mHostMode.complete && !mHostMode.code && mHostContext.complete && mHostImage.started && !mHostImage.published && !mHostImage.submitted && !mHostImage.complete && mHostRingCpFailed && !image_consumed && !fs);cases++;
 for(unsigned word=0;word<4;word++)for(unsigned bit=0;bit<32;bit++){
  mode_prepared();assert(!HostRingPostInit(NULL,&mHostRing));mHostImage.started=1;mHostImage.phase=1;uint32_t packet[4];memcpy(packet,hgki_ib,sizeof packet);packet[word]^=1u<<bit;
  unsigned writes=mmio_writes;assert(HostKnownImageSubmit(NULL,packet,4) && !mHostImage.published && !mHostImage.submitted && mmio_writes==writes && fake_wptr==37 && !image_consumed && !fs);cases++;
 }
 assert(hhr_pkt7(0x66,1)==0x70e60001);cases++;
 return cases;
}
static unsigned first_context(void){unsigned cases=0;
 // The real portable builder checks qualification and both actual root values.
 // No failed build, publication, kick or idle may enter the IB callback.
 for(unsigned fault=1;fault<=4;fault++){
  mode_prepared();image_gpu=1;context_build_fail=fault;
  assert(HostRingPostInit(NULL,&mHostRing) && mHostMode.complete && mHostContext.started && !mHostContext.built && mHostContext.phase==1 && mHostContext.code && context_build_calls==1 && !mHostContext.published && !mHostContext.submitted && !mHostContext.complete);
  assert(mHostRingCpFailed && freeze_calls && fake_wptr==12 && doorbells==1 && !context_consumed && !mHostImage.started && !image_consumed && !fs);
  const unsigned codes[]={0,47,HFC_QUALIFICATION,HFC_READ,HFC_ROOT};assert(mHostContext.code==codes[fault]);cases++;
 }
 for(unsigned fault=0;fault<2;fault++){
  mode_prepared();image_gpu=1;if(fault)context_words_null=1;else context_publish_fail=1;
  assert(HostRingPostInit(NULL,&mHostRing) && mHostMode.complete && mHostContext.built && mHostContext.phase==2 && mHostContext.code==HHR_MEMORY && !mHostContext.published && !mHostContext.submitted && !mHostContext.complete && mHostRingCpFailed && freeze_calls);
  for(unsigned i=12;i<37;i++)assert(!HostRingCpu()[i]);
  assert(fake_wptr==12 && doorbells==1 && !context_consumed && !mHostImage.started && !image_consumed && !fs);cases++;
 }
 mode_prepared();image_gpu=context_kick_fail=1;
 assert(HostRingPostInit(NULL,&mHostRing) && mHostMode.complete && mHostContext.built && mHostContext.published && !mHostContext.submitted && !mHostContext.complete && mHostContext.phase==3 && mHostContext.code==HHR_IO && mHostContext.kick_code==HHR_IO && mHostRingCpFailed && freeze_calls);
 assert(fake_wptr==37 && doorbells==2 && context_consumed==1 && !mHostImage.started && !image_consumed && !stall_calls && !fs);cases++;
 // The fresh kick guard can refuse before the real WPTR store, while a
 // failed fence read above represents failure after that store took effect.
 mode_prepared();image_gpu=1;context_kick_fail=2;
 assert(HostRingPostInit(NULL,&mHostRing) && mHostContext.published && !mHostContext.submitted && mHostContext.phase==3 && mHostContext.code==HHR_GUARD && mHostContext.kick_code==HHR_GUARD && mHostRingCpFailed && freeze_calls);
 assert(fake_wptr==12 && mHostRing.wptr==37 && doorbells==1 && !context_consumed && !mHostImage.started && !image_consumed && !stall_calls && !fs);cases++;
 for(unsigned fault=1;fault<3;fault++){
  mode_prepared();image_gpu=1;context_idle_fail=fault;
  assert(HostRingPostInit(NULL,&mHostRing) && mHostMode.complete && mHostContext.published && mHostContext.submitted && !mHostContext.idle && !mHostContext.complete && mHostContext.phase==4 && mHostRingCpFailed && freeze_calls);
  assert(mHostContext.idle_code==(fault==1?HHR_TIMEOUT:HHR_FAULT) && mHostContext.code==mHostContext.idle_code && context_consumed==1 && !mHostImage.started && !image_consumed && fake_wptr==37 && doorbells==2 && !fs);
  assert(stall_calls==(fault==1) && (!stall_calls || (stall_stage==1 && !stall_cp_failed && delay_calls==HHR_POLLS)));cases++;
 }
 // Every unknown bit is rejected using the independent canonical encoder,
 // including mutation of the exact pointer returned as the expected packet.
 for(unsigned same_pointer=0;same_pointer<2;same_pointer++)for(unsigned word=0;word<HFC_WORDS;word++)for(unsigned bit=0;bit<32;bit++){
  context_packet_prepared();uint32_t packet[HFC_WORDS];memcpy(packet,context_words,sizeof packet);
  uint32_t *words=same_pointer?context_words:packet;words[word]^=1u<<bit;
  unsigned writes=mmio_writes;assert(HostRingPublish(NULL,12,words,HFC_WORDS) && !mHostContext.published && mmio_writes==writes && fake_wptr==12 && !context_consumed && !image_consumed && !fs);
  for(unsigned i=12;i<37;i++)assert(!HostRingCpu()[i]);cases++;
 }
 // Unknown counts, stale offsets, already-written destinations and absent
 // root proof never partially publish even when the source bytes are valid.
 for(unsigned fault=0;fault<8;fault++){
  context_packet_prepared();unsigned offset=12,count=HFC_WORDS;
  if(fault==0)count--;if(fault==1)count++;if(fault==2)offset=10;if(fault==3)offset=37;
  if(fault==4)context_build_result.valid=1;if(fault==5)context_build_result.ttbr0^=4096;
  if(fault==6)context_build_result.ready=0;if(fault==7)HostRingCpu()[20]=0xfeedface;
  uint32_t before[HFC_WORDS];for(unsigned i=0;i<HFC_WORDS;i++)before[i]=HostRingCpu()[12+i];unsigned writes=mmio_writes;
  assert(HostRingPublish(NULL,offset,context_words,count) && mmio_writes==writes && !context_consumed && !image_consumed && !fs);
  for(unsigned i=0;i<HFC_WORDS;i++)assert(HostRingCpu()[12+i]==before[i]);cases++;
 }
 // First-context and known-image doorbells are fixed phase/state transitions;
 // previous offsets must not be accepted merely because software WPTR agrees.
 const uint32_t stale[]={10,12,16,20,37,41,46,51};
 for(unsigned stage=0;stage<4;stage++)for(unsigned i=0;i<ARRAY_SIZE(stale);i++){
  const unsigned correct[]={37,41,46,51};if(stale[i]==correct[stage])continue;
  context_packet_prepared();assert(!HostRingPublish(NULL,12,context_words,HFC_WORDS));mHostContext.published=1;mHostContext.phase=3;
  if(stage){mHostContext.submitted=mHostContext.idle=mHostContext.complete=1;mHostContext.phase=5;mHostImage.started=mHostImage.published=1;mHostImage.phase=3;}
  if(stage>=2){mHostImage.submitted=mHostImage.idle=mHostImage.complete=1;mHostImage.phase=5;mHostRing.phase=stage+3;}
  mHostRing.wptr=stale[i];unsigned writes=mmio_writes;
  assert(HostRingWrite(NULL,0x3d0201c,stale[i]) && mmio_writes==writes && !context_consumed && !image_consumed && !fs && mHostRingCpFailed);cases++;
 }
 // A context may not be re-entered, run before mode completion, or run from
 // a stale CPU-observed ring position. These fail before invoking its builder.
 for(unsigned gate=0;gate<5;gate++){
  context_ready_prepared();if(gate==0)mHostContext.started=1;if(gate==1)mHostMode.complete=0;if(gate==2)mHostRing.phase=3;if(gate==3)mHostRing.wptr=10;if(gate==4)mHostRing.rptr=10;
  unsigned reads=mmio_reads,writes=mmio_writes;assert(HostRingFirstContext() && !context_build_calls && mmio_reads==reads && mmio_writes==writes && !image_consumed && !fs);cases++;
 }
 return cases;
}

int main(void){unsigned cases=0;prepared();assert(mHostRingPrepared && mGpuOnlyNext[3]==0xc9000);assert(!HostRingGuard(NULL));assert(!HostRingAperture(NULL) && scm_calls==2 && mHostApertureAvailable==1);cases++;
 // A retained SID0-only profile is insufficient for host execution. Every
 // completed dual-stream proof is checked before any live power/CP access.
 for(unsigned field=0;field<8;field++)for(unsigned variant=0;variant<2;variant++){
  prepared();unsigned *proof[]={&mScratchResult.code,&mScratchResult.phase,&mScratchResult.enabled,&mScratchResult.attached,&mScratchResult.retained,&mScratchResult.lpac,&mScratchResult.sid0_attached,&mScratchResult.lpac_attached};
  *proof[field]^=variant?3u:1u;
  assert(HostRingBusPower() && HostRingGuard(NULL) && HostRingBusLease() && !power_checks && !mmio_reads && !mmio_writes);cases++;
 }
 for(unsigned field=0;field<4;field++)for(unsigned bit=0;bit<32;bit++){
  prepared();uint32_t *proof[]={&mScratchResult.sid0_smr,&mScratchResult.sid0_s2cr,&mScratchResult.lpac_smr,&mScratchResult.lpac_s2cr};
  *proof[field]^=1u<<bit;
  assert(HostRingBusPower() && HostRingGuard(NULL) && HostRingBusLease() && !power_checks && !mmio_reads && !mmio_writes);cases++;
 }
 const uint32_t route_addresses[]={0x3da0800,0x3da0c00,0x3da0804,0x3da0c04,0x3da0808,0x3da0c08};
 for(unsigned field=0;field<6;field++){
  for(unsigned bit=0;bit<32;bit++){
   prepared();route_bad_address=route_addresses[field];route_bad_mask=1u<<bit;forbid_cp=1;
   assert(HostRingRoutes() && HostRingGuard(NULL) && HostRingBusLease() && !mmio_writes && !cp_reads && !cp_writes);cases++;
  }
  prepared();route_fail_address=route_addresses[field];forbid_cp=1;
  assert(HostRingRoutes() && HostRingGuard(NULL) && HostRingBusLease() && !mmio_writes && !cp_reads && !cp_writes);cases++;
 }
 prepared();route_bad_address=0x3da0808;route_bad_mask=3;forbid_cp=1;
 assert(HostRingGuard(NULL) && HostRingBusLease() && !cp_reads && !cp_writes);cases++; // SID2 is not LPAC SID1.
 prepared();route_bad_address=0x3da0c08;route_bad_mask=3;forbid_cp=1;
 assert(HostRingGuard(NULL) && HostRingBusLease() && !cp_reads && !cp_writes);cases++; // No secure bank3 route.
 for(unsigned f=1;f<=15;f++){prepared();failure=f;int r=HostRingGuard(NULL);if(f==3 || f==4 || f==7 || f==8 || f==9)assert(r);failure=0;cases++;}
 for(unsigned f=13;f<=15;f++){prepared();failure=f;assert(HostRingAperture(NULL));assert(!mmio_writes);cases++;}
 for(unsigned k=0;k<7;k++){prepared();mHostRing.phase=2;const uint32_t a[]={0x3d02000,0x3d02004,0x3d02008,0x3d02010,0x3d02014,0x3d02a60,0x3d02a64};const uint32_t v[]={HHR_RING,0,0x20c,HHR_SCRATCH+0x100,0,HHR_SCRATCH+0x108,0};assert(!HostRingWrite(NULL,a[k],v[k]) && mmio_writes==1);for(unsigned b=0;b<32;b++){assert(HostRingWrite(NULL,a[k],v[k]^(1u<<b)));cases++;}mHostRing.phase=4;assert(HostRingWrite(NULL,a[k],v[k]));cases++;}
 prepared();mHostRing.phase=2;for(unsigned a=0x3d00000;a<0x3d04000;a+=4){unsigned before=mmio_writes;int r=HostRingWrite(NULL,a,0xabcdef00);assert(r && before==mmio_writes);cases++;}
 prepared();mHostRing.phase=3;mHostRing.enabled=1;assert(HostRingWrite(NULL,0x3d02020,1));assert(!mHostWriteCalls && !mHostRingUnsafe);
 prepared();mHostRing.phase=3;mHostRing.configured=7;assert(!HostRingCheckpoint(NULL) && mHostRingEntryReady && !fs && !mHostRingLog.phase && !mHostRingLog.restored);
 mHostRing.enabled=1;assert(!HostRingWrite(NULL,0x3d02020,1) && mHostWriteCalls==1 && mHostRingUnsafe && !mGpuSaveAllowed && fake_sqe==1);cases++;
 for(unsigned ph=4;ph<=6;ph++){mHostRing.phase=ph;mHostRing.wptr=10+5*(ph-4);assert(!HostRingWrite(NULL,0x3d0201c,mHostRing.wptr));assert(HostRingWrite(NULL,0x3d0201c,mHostRing.wptr+1));cases++;}
 for(unsigned f=0;f<=12;f++){prepared();mHostRing.enabled=mHostRingUnsafe=1;fake_sqe=1;fake_rptr=20;failure=f;int r=HostRingStop(NULL,20);if(!f)assert(!r && !mHostRingUnsafe && fake_sqe==3);if(f==3 || f==6 || f==7 || f==9)assert(r && mHostRingUnsafe);else if(f>=3)assert(!r && !mHostRingUnsafe && mHostBusStop.stopped);cases++;}
 prepared();mHostRing.phase=2;uint32_t init[]={0x70970001,0x08000000,0x70c80007,0x94b,3,0x20000000,2,HHR_RECORD,0,0x80000000};assert(!HostRingPublish(NULL,0,init,10));assert(HostRingPublish(NULL,0,init,10));assert(!HostRingCpu()[HHR_BYTES/4]);cases++;
 for(unsigned i=0;i<10;i++){prepared();mHostRing.phase=2;init[i]^=1;assert(HostRingPublish(NULL,0,init,10));init[i]^=1;cases++;}
 prepared();mHostRing.phase=5;uint32_t w[]={0x703d8003,HHR_SCRATCH,0,0xc0ffee00,0x70928000};assert(!HostRingPublish(NULL,10,w,5));assert(!HostRingCpu()[HHR_BYTES/4]);mHostRing.phase=6;w[1]+=4;w[3]++;assert(!HostRingPublish(NULL,15,w,5));assert(!HostRingCpu()[HHR_BYTES/4+1]);cases++;
 prepared();mHostRing.phase=3;mHostRing.configured=7;assert(!HostRingCheckpoint(NULL) && mHostRingEntryReady && fs==0 && tpl==16);mHostRing.enabled=1;assert(HostRingCheckpoint(NULL) && fs==0);cases++;
 direct_prepared();assert(!HostRingEngineProbe(NULL) && !fs && mHostDirectReady && !mHostEngineComplete && !mHostEngineStopped && mHostRingUnsafe && fake_sqe==1 && mHostWriteCalls==1);cases++;
 // Rejecting the very first SQE write is not a running-engine failure: with
 // no actual store attempt, no unsafe lease, and no WPTR, stop must not send
 // a new halt store to an engine that was never started.
 prepared();mHostRing.phase=3;mHostRing.enabled=1;mHostRing.code=HHR_IO;
 assert(HostRingWrite(NULL,0x3d02020,1) && !mHostWriteCalls && !mHostRingUnsafe);
 unsigned never_started_writes=mmio_writes;
 assert(!HostRingStop(NULL,0) && !mHostWriteCalls && mmio_writes==never_started_writes && !cp_writes && !mHostRingUnsafe);cases++;
 for(unsigned f=23;f<=25;f++){prepared();mHostRing.enabled=mHostRingUnsafe=1;fake_sqe=1;failure=f;forbid_cp=1;assert(HostRingBusHalt() && mHostRingUnsafe && !mHostBusStop.stopped && !cp_reads && !cp_writes && !fs);cases++;}
 prepared();mHostRing.enabled=mHostRingUnsafe=1;fake_sqe=1;failure=8;forbid_cp=1;assert(!HostRingBusHalt() && !mHostRingUnsafe && mHostBusStop.stopped && mHostBusStop.valid==31 && mHostBusStop.fsr==2 && mHostBusStop.far==0x63001000 && (mHostBusStop.ack[0]&1) && (mHostBusStop.ack[1]&1) && (mHostBusStop.ack[2]&2) && !cp_reads && !cp_writes && fake_sqe==1);assert(!HostRingStop(NULL,0));failure=23;assert(HostRingStop(NULL,0) && mHostRingUnsafe);cases++;
 // A prior failed command/read/write must isolate the bus without touching CP,
 // including the otherwise dangerous SQE halt store and its readback.
 for(unsigned fault=0;fault<3;fault++) {
  prepared();mHostRing.enabled=mHostRingUnsafe=1;fake_sqe=1;forbid_cp=1;
  if(fault==0)mHostRing.code=HHR_IO;else if(fault==1)mHostRingCpFailed=1;else mHostWriteFaults=1;
  assert(!HostRingStop(NULL,0) && mHostBusStop.stopped && !mHostRingUnsafe && !cp_reads && !cp_writes && fake_sqe==1 && !fs);
  unsigned writes=mmio_writes;
  assert(!HostRingStop(NULL,0) && !mHostRingUnsafe && mmio_writes==writes && !cp_reads && !cp_writes);cases++;
  for(unsigned ack=23;ack<=25;ack+=2) {
   failure=ack;assert(HostRingStop(NULL,0) && mHostRingUnsafe && mmio_writes==writes && !cp_reads && !cp_writes && !fs);cases++;
   failure=0;assert(!HostRingStop(NULL,0) && !mHostRingUnsafe && mmio_writes==writes);
  }
  mHostBusStop.ack[1]=0;
  assert(HostRingStop(NULL,0) && mHostRingUnsafe && mmio_writes==writes && !cp_reads && !cp_writes && !fs);cases++;
 }
 // No individual GX/client/arb halt ACK may reopen the filesystem safety gate.
 for(unsigned fault=0;fault<3;fault++)for(unsigned ack=23;ack<=25;ack++) {
  prepared();mHostRing.enabled=mHostRingUnsafe=1;fake_sqe=1;forbid_cp=1;failure=ack;
  if(fault==0)mHostRing.code=HHR_IO;else if(fault==1)mHostRingCpFailed=1;else mHostWriteFaults=1;
  assert(HostRingStop(NULL,0) && mHostRingUnsafe && !mHostBusStop.stopped && !cp_reads && !cp_writes && !fs);cases++;
 }
 // Reset write success is insufficient: a real readback of one must precede
 // all bus halt writes and publication of reset_held or cm3_reset.
 for(unsigned reset_failure=27;reset_failure<=28;reset_failure++) {
  prepared();mHostRing.enabled=mHostRingUnsafe=1;mHostRing.code=HHR_IO;fake_sqe=1;forbid_cp=1;failure=reset_failure;
  assert(HostRingStop(NULL,0) && mHostRingUnsafe && !mHostBusStop.stopped && !mStockResult.reset_held && !mHostBusStop.cm3_reset && !fake_gx_halt && !fake_gbif_halt && !cp_reads && !cp_writes && !fs);cases++;
 }
 prepared();mHostRing.enabled=mHostRingUnsafe=1;mHostRing.code=HHR_IO;fake_sqe=1;forbid_cp=1;
 assert(!HostRingStop(NULL,0) && mStockResult.reset_held && mHostBusStop.cm3_reset && fake_cm3==1);
 fake_cm3=0;assert(HostRingStop(NULL,0) && mHostRingUnsafe && !cp_reads && !cp_writes && !fs);cases++;
 // Exercise the actual native read callback's failure latch, rather than
 // relying only on a pre-filled failure flag in the scenarios above.
 prepared();mHostRing.enabled=mHostRingUnsafe=1;fake_sqe=1;failure=29;uint32_t failed_value=0xfeedface;
 assert(HostRingRead(NULL,0x3d02020,&failed_value) && mHostRingCpFailed && failed_value==0xfeedface);
 assert(mHostFirstIo.valid && mHostFirstIo.operation==1 && mHostFirstIo.address==0x3d02020 && mHostFirstIo.code==HHR_NATIVE_READ && freeze_calls==1);
 failure=0;cp_reads=cp_writes=0;forbid_cp=1;
 assert(!HostRingStop(NULL,0) && !mHostRingUnsafe && mHostBusStop.stopped && !cp_reads && !cp_writes);
 assert(mHostFirstIo.valid && mHostFirstIo.operation==1 && mHostFirstIo.address==0x3d02020 && mHostFirstIo.code==HHR_NATIVE_READ && freeze_calls==1);cases++;
 // Every snapshot is CPU RAM only once a failure exists. In particular,
 // CP_INIT's stage-1 snapshot occurs before the generic path jumps to stop;
 // restricting this rule to stage 4 would re-enter the failed CP aperture.
 for(unsigned fault=0;fault<3;fault++)for(unsigned stage=0;stage<6;stage++) {
  prepared();mHostRing.enabled=mHostRingUnsafe=1;fake_sqe=1;forbid_cp=1;
  if(fault==0)mHostRing.code=HHR_IO;else if(fault==1)mHostRingCpFailed=1;else mHostWriteFaults=1;
  HostRingCpu()[HHR_BYTES/4]=0x1234;HostRingCpu()[HHR_BYTES/4+1]=0x5678;
  unsigned reads=mmio_reads,writes=mmio_writes,power=power_checks;
  HostRingSnapshot(NULL,stage);
  assert(mmio_reads==reads && mmio_writes==writes && power_checks==power && !cp_reads && !cp_writes && !fs);
  assert(mHostRingSnapshots[stage].taken && !mHostRingSnapshots[stage].valid && mHostRingSnapshots[stage].scratch[0]==0x1234 && mHostRingSnapshots[stage].scratch[1]==0x5678);cases++;
 }
 // A bad SQE readback cannot affect emergency isolation because it is never
 // read on that path. This was an old false dependency on SQE_CNTL=3.
 prepared();mHostRing.enabled=mHostRingUnsafe=1;fake_sqe=1;failure=26;forbid_cp=1;
 assert(!HostRingBusHalt() && mHostBusStop.stopped && !mHostRingUnsafe && !cp_reads && !cp_writes && fake_sqe==1);cases++;
 cases+=sticky_diagnostics();
 cases+=running_busy();
 cases+=direct_and_stop();
 cases+=graphics_hooks();
 cases+=authenticated_mode();
 cases+=first_context();
 prepared();for(unsigned i=0;i<6;i++)HostRingSnapshot(NULL,i);HostRingReport();uint32_t value;assert(!HostRingPeek(NULL,0,&value));assert(HostRingPeek(NULL,2,&value));(void)RunHostRing;
 printf("PASS: %u actual native ring cases; exact MMIO/address/value/phase allowlists, fixed scalar SCM, no CPU canary stores, full guards, fault recovery never touches CP, all three halt ACKs gate filesystem safety, fault snapshot CPU-only, fixed 25-DW context and 12/37/41/46/51 submission sequence\n",cases);
}
'''
native=(p/'native/gpu/uefi/GpuHostRingNative.h').read_text()
native=native.replace('__asm__ volatile("dsb sy":::"memory");','')
assert '__asm__' not in native
with tempfile.TemporaryDirectory() as d:
 f=Path(d);(f/'test.c').write_text(prefix+native+suffix)
 subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(p/'native/gpu/uefi'),'-I',str(p/'native/gpu'),str(f/'test.c'),'-o',str(f/'test')],check=True)
 subprocess.run([str(f/'test')],check=True)
