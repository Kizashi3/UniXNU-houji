#!/usr/bin/env python3
"""Actual candidate .inc; existing firmware helpers/TPL/MMIO are boundary peers."""
from pathlib import Path
import subprocess
import tempfile

p = Path(__file__).resolve().parents[1]
program = r'''
#define main portable_test_main
#include "PORTABLE_TEST"
#undef main
#define STATIC static
#define CONST const
#define VOID void
#define TRUE 1
#define FALSE 0
typedef unsigned BOOLEAN;
typedef void *EFI_HANDLE;
typedef uint64_t EFI_STATUS;
typedef uint64_t UINT64;
typedef uint32_t UINT32;
typedef unsigned EFI_TPL;
#define MAX_UINT32 UINT32_MAX
#define CopyMem memcpy
#define EFI_SUCCESS UINT64_C(0)
#define EFI_INVALID_PARAMETER UINT64_C(0x8000000000000002)
#define EFI_UNSUPPORTED UINT64_C(0x8000000000000003)
#define EFI_DEVICE_ERROR UINT64_C(0x8000000000000007)
#define EFI_ACCESS_DENIED UINT64_C(0x800000000000000f)
#define EFI_NOT_STARTED UINT64_C(0x8000000000000013)
#define EFI_ALREADY_STARTED UINT64_C(0x8000000000000014)
#define EFI_ERROR(s) (((uint64_t)(s)>>63)!=0)
enum {TPL_APPLICATION=4,TPL_NOTIFY=16,TPL_HIGH_LEVEL=31,QPT_CLOSED=0};
static BOOLEAN mGmuCalled,mDmaCalled,mStockCalled,mContextCalled,mFirmwareHeld;
static BOOLEAN mScratchReady,mCodeReady,mScratchAssigned,mSecureAssigned,mSecureTableOwned;
static struct {unsigned owned;} mSecureMemory;
static struct {unsigned started,enabled;} mHostRing;
static unsigned mHostWriteCalls,mHostRingUnsafe,mAttempted,mGpuMustStop,mGpuSaveAllowed;
static unsigned mQmpUncertain;
static struct {unsigned phase,pending,leased,owned;} mQmp;
static uint64_t mGpuBatchStart,mIds[GPP_RESOURCE_COUNT];
struct clock_protocol {
 uint64_t Version;
 EFI_STATUS (*GetClockFreqHz)(struct clock_protocol *,uint64_t,uint32_t *);
};
static struct clock_protocol protocol,*mClock;
static struct mock device;
static unsigned current_tpl=TPL_APPLICATION,checkpoint_calls,prepare_calls,map_calls;
static unsigned fail_checkpoint,warn_checkpoint,fail_map,bad_prepare,hub_bad_tpl,query_error,legacy_after_read;
static unsigned sequence[32],seq_count,callback_bad_map;
static unsigned RaiseTpl(unsigned tpl) {unsigned old=current_tpl;assert(tpl>=old);current_tpl=tpl;return old;}
static void RestoreTpl(unsigned tpl) {assert(tpl<=current_tpl);current_tpl=tpl;}
static const struct {unsigned (*RaiseTPL)(unsigned);void (*RestoreTPL)(unsigned);} bs={RaiseTpl,RestoreTpl};
static const __typeof__(bs) *gBS=&bs;
static EFI_STATUS ProbeCheckpoint(const char *name);
static EFI_STATUS Prepare(struct gpp_report *out,uint64_t bytes) {
 assert(current_tpl==TPL_APPLICATION && !mAttempted && !prepare_calls++ && checkpoint_calls==1);
 assert(bytes==sizeof(*out) && gpp_report_requested(out));sequence[seq_count++]=2;
 mAttempted=1;*out=power();
 if(bad_prepare==1)return EFI_SUCCESS;
 if(bad_prepare==2) {out->code=GPP_ERR_RATE;gpp_report_seal(out);}
 if(bad_prepare==3)out->crc32^=1;
 if(bad_prepare==4)mQmp.leased=1;
 return HPH_PREPARE_STATUS;
}
static EFI_STATUS MapMmio(uint64_t base,uint64_t bytes) {
 assert(current_tpl==TPL_APPLICATION && prepare_calls==1 && !map_calls++);
 assert(base==0x3da0000 && bytes==0x40000);sequence[seq_count++]=3;
 return fail_map?(fail_map==2?1:EFI_DEVICE_ERROR):EFI_SUCCESS;
}
static GPP_U64 BusRead(void *c,uint32_t a,uint32_t *v) {
 (void)c;assert(current_tpl==TPL_NOTIFY && map_calls==1);
 assert(reg_index(a)>=0 || hgb_survey_address(a));
 GPP_U64 s=read32(&device,a,v);
 if(legacy_after_read && device.reads==legacy_after_read)mGmuCalled=1;
 return s;
}
static int GpuTryRead32(uint32_t a,uint32_t *v) {
 assert(current_tpl==TPL_NOTIFY && map_calls==1 && hph_read_allowed(a));
 if(!callback_bad_map)assert(clock_index(a)>=0 || a==0x3d7e600);
 return read32(&device,a,v)?1:0;
}
static GPP_U64 BusWrite(void *c,uint32_t a,uint32_t v) {
 (void)c;assert(current_tpl==TPL_NOTIFY && map_calls==1);return write32(&device,a,v);
}
static GPP_U64 Delay(void *c,unsigned us) {(void)c;assert(current_tpl==TPL_NOTIFY);return delay_us(&device,us);}
static EFI_STATUS PrepareGmuHub(const struct gpp_report *pwr,const struct hgb_result *bus) {
 assert(current_tpl==TPL_NOTIFY);sequence[seq_count++]=4;
 RestoreTpl(TPL_APPLICATION); // Same helper-owned TPL lowering as actual source.
 EFI_STATUS s=hub(&device,pwr,bus);
 if(!hub_bad_tpl)(void)RaiseTpl(TPL_NOTIFY);
 return s;
}
static EFI_STATUS GetConfigured(struct clock_protocol *clock,uint64_t id,uint32_t *hz) {
 assert(current_tpl==TPL_NOTIFY && clock==&protocol && device.queries<2);
 unsigned which=id==mIds[GPP_HUB_RATE];assert(id==mIds[which?GPP_HUB_RATE:GPP_GMU_RATE]);
 sequence[seq_count++]=5;
 if(query_error) {device.queries++;*hz=123;return query_error==2?1:EFI_DEVICE_ERROR;}
 return configured(&device,which,hz);
}
static uint64_t BatchCounter(void) {assert(current_tpl==TPL_APPLICATION);return 1234;}
#include "GpuPowerOnlyAdapter.inc"
static EFI_STATUS ProbeCheckpoint(const char *name) {
 assert(current_tpl==TPL_APPLICATION && mGpuSaveAllowed && !mPowerOnlyActive);
 checkpoint_calls++;
 if(checkpoint_calls==1) {
  assert(!strcmp(name,"before-native-GPU-power-only") && !mAttempted && !device.reads);
  sequence[seq_count++]=1;
 } else {
  assert(checkpoint_calls==2 && !strcmp(name,"after-native-GPU-power-only-COLD-no-DMA"));
  assert(mPowerOnlyRecord.complete && hph_record_valid(&mPowerOnlyRecord) && !mGpuMustStop);
  sequence[seq_count++]=6;
 }
 return checkpoint_calls==fail_checkpoint?EFI_DEVICE_ERROR:(checkpoint_calls==warn_checkpoint?1:EFI_SUCCESS);
}
static void reset(void) {
 mGmuCalled=mDmaCalled=mStockCalled=mContextCalled=mFirmwareHeld=0;
 mScratchReady=mCodeReady=mScratchAssigned=mSecureAssigned=mSecureTableOwned=0;
 mSecureMemory.owned=0;mHostRing.started=mHostRing.enabled=0;
 mHostWriteCalls=mHostRingUnsafe=mAttempted=mGpuMustStop=mQmpUncertain=0;mGpuSaveAllowed=1;
 memset(&mQmp,0,sizeof(mQmp));mGpuBatchStart=0;
 memset(mIds,0,sizeof(mIds));mIds[GPP_GMU_RATE]=mIds[GPP_GMU_CLK]=0x10011;
 mIds[GPP_HUB_RATE]=mIds[GPP_HUB_CLK]=0x10022;
 protocol.Version=0x1000a;protocol.GetClockFreqHz=GetConfigured;mClock=&protocol;
 device=initial();current_tpl=TPL_APPLICATION;checkpoint_calls=prepare_calls=map_calls=0;
 fail_checkpoint=warn_checkpoint=fail_map=bad_prepare=hub_bad_tpl=query_error=legacy_after_read=0;
 seq_count=callback_bad_map=0;memset(sequence,0,sizeof(sequence));
 mPowerOnlyAttempted=mPowerOnlyActive=mPowerOnlyQueryUncertain=0;
 memset(&mPowerOnlyRecord,0,sizeof(mPowerOnlyRecord));
}
static EFI_STATUS go(struct hph_record *r) {
 EFI_STATUS s=HoujiGpuPowerOnlyPrepare(NULL,r);
 assert(current_tpl==TPL_APPLICATION && !mPowerOnlyActive);
 return s;
}
static void stopped(struct hph_record *r,unsigned can_save) {
 assert(EFI_ERROR(go(r)) && !r->complete && mGpuMustStop && mGpuSaveAllowed==can_save);
 assert(hph_record_valid(r) && device.writes<=3);
 unsigned calls=prepare_calls,reads=device.reads,writes=device.writes,maps=map_calls;
 assert(HoujiGpuPowerOnlyPrepare(NULL,r)==EFI_ALREADY_STARTED && current_tpl==TPL_APPLICATION);
 assert(prepare_calls==calls && device.reads==reads && device.writes==writes && map_calls==maps);
 cases++;
}
int main(void) {
 struct hph_record r;reset();assert(!go(&r) && r.complete && hph_record_valid(&r));cases++;
 assert(!mGpuMustStop && mGpuSaveAllowed && prepare_calls==1 && map_calls==1 && checkpoint_calls==2);
 assert(device.writes==3 && device.hubs==1 && device.queries==2 && !mFirmwareHeld && !mContextCalled && !mDmaCalled && !mStockCalled);
 assert(seq_count==7 && sequence[0]==1 && sequence[1]==2 && sequence[2]==3 &&
  sequence[3]==4 && sequence[4]==5 && sequence[5]==5 && sequence[6]==6);
 assert(r.prepare_status_lo==7 && r.prepare_status_hi==0x80000000u);
 unsigned success_reads=device.reads;
 assert(HoujiGpuPowerOnlyPrepare(NULL,&r)==EFI_ALREADY_STARTED && r.complete && prepare_calls==1);cases++;
 reset();assert(HoujiGpuPowerOnlyPrepare(NULL,NULL)==EFI_INVALID_PARAMETER && !mPowerOnlyAttempted && !checkpoint_calls);cases++;
 reset();current_tpl=TPL_NOTIFY;memset(&r,0xa5,sizeof(r));
 assert(HoujiGpuPowerOnlyPrepare(NULL,&r)==EFI_UNSUPPORTED && current_tpl==TPL_NOTIFY && !r.started && !mPowerOnlyAttempted);cases++;
 reset();fail_checkpoint=1;stopped(&r,1);assert(!prepare_calls && !map_calls && !device.reads && !r.retained);
 reset();fail_checkpoint=2;stopped(&r,1);assert(prepare_calls==1 && device.writes==3 && r.retained && r.code==HPH_RECORD);
 reset();fail_map=1;stopped(&r,0);assert(prepare_calls==1 && !device.reads && r.retained && r.prepare_status_lo==7);
 reset();fail_map=2;stopped(&r,0);assert(!device.reads && r.first_status_lo==1);
 reset();warn_checkpoint=1;stopped(&r,1);assert(!prepare_calls && r.first_status_lo==1);
 reset();warn_checkpoint=2;stopped(&r,1);assert(r.retained && r.first_status_lo==1);
 for(unsigned i=1;i<=4;i++) {reset();bad_prepare=i;stopped(&r,0);assert(!device.writes && !device.hubs);}
 for(unsigned i=1;i<=success_reads;i++) {reset();device.fail_read=i;stopped(&r,0);}
 for(unsigned i=1;i<=3;i++) {reset();device.fail_write=i;stopped(&r,0);assert(device.writes==i);}
 reset();device.fail_hub=1;stopped(&r,0);
 reset();hub_bad_tpl=1;stopped(&r,0);assert(r.code==HPH_HUB);
 reset();query_error=1;stopped(&r,0);assert(mPowerOnlyQueryUncertain && device.queries==1);
 reset();query_error=2;stopped(&r,0);assert(mPowerOnlyQueryUncertain && device.queries==1);
 reset();legacy_after_read=10;stopped(&r,0);assert(mGmuCalled && !device.hubs);
 // Each old GPU/allocation path rejects before native power, maps or checkpoint.
 unsigned *old[]={&mGmuCalled,&mDmaCalled,&mStockCalled,&mContextCalled,&mFirmwareHeld,
  &mScratchReady,&mCodeReady,&mScratchAssigned,&mSecureAssigned,&mSecureTableOwned,
  &mSecureMemory.owned,&mHostRing.started,&mHostRing.enabled,&mHostWriteCalls,&mHostRingUnsafe};
 for(unsigned i=0;i<sizeof(old)/sizeof(old[0]);i++) {
  reset();*old[i]=1;assert(go(&r)==EFI_ACCESS_DENIED && !prepare_calls && !map_calls &&
   !checkpoint_calls && !device.reads && mGpuMustStop && !mGpuSaveAllowed && !r.started);cases++;
 }
 // Actual adapter callbacks deny any address or frequency operation outside ABI.
 reset();r=(struct hph_record){0};assert(!go(&r));
 mPowerOnlyActive=1;unsigned writes=device.writes,reads=device.reads;
 assert(PowerOnlyWrite(NULL,0x3d7e000,0)==EFI_ACCESS_DENIED && device.writes==writes);
 uint32_t value=0;assert(PowerOnlyRead(NULL,0x3d02020,&value)==EFI_ACCESS_DENIED && device.reads==reads);
 assert(PowerOnlyConfigured(NULL,2,&value)==EFI_ACCESS_DENIED && device.queries==2);cases++;
 mPowerOnlyActive=0;
 printf("power-only actual adapter: %u cases PASS; APP/NOTIFY restored; retained failures block XNU\n",cases);
 return 0;
}
'''.replace("PORTABLE_TEST", str(p / "tests/check-gpu-power-only-handoff.c"))

with tempfile.TemporaryDirectory(prefix="houji-power-only-adapter-") as tmp:
    source = Path(tmp) / "adapter.c"
    source.write_text(program)
    binary = Path(tmp) / "adapter"
    subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror", "-g",
                    "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                    "-I", str(p / "native/gpu/uefi"), str(source), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
