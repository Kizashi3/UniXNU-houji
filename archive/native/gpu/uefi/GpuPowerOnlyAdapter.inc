/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * CANDIDATE ONLY. Include once at the end of GpuPower.c, after its existing
 * static helpers. Main must require returned EFI_SUCCESS AND a decoded,
 * complete hph_record before publishing only its scalar bytes to XNU.
 *
 * This path never calls HoujiGpuPowerPrepare, firmware/scratch allocators,
 * hgd/disabled-context/DMA/stock-GMU/CP paths, or installs a configuration
 * table. Native clock references and the three bus fields remain retained
 * until whole-platform reset. It provides boot power, not a runtime lease,
 * clock measurement, frequency qualification or GPU-resource ownership.
 */
#include "GpuPowerOnlyHandoff.h"
STATIC BOOLEAN mPowerOnlyAttempted,mPowerOnlyActive,mPowerOnlyQueryUncertain;
STATIC struct hph_record mPowerOnlyRecord;

STATIC BOOLEAN PowerOnlyLegacyUsed(VOID) {
 return mGmuCalled || mDmaCalled || mStockCalled || mContextCalled ||
  mFirmwareHeld || mScratchReady || mCodeReady || mScratchAssigned ||
  mSecureAssigned || mSecureMemory.owned || mSecureTableOwned ||
  mHostRing.started || mHostRing.enabled || mHostWriteCalls || mHostRingUnsafe;
}
STATIC int PowerOnlyExclusive(VOID *Cookie) {
 (VOID)Cookie;
 return !mPowerOnlyAttempted || !mPowerOnlyActive || !mAttempted ||
  mGpuMustStop || PowerOnlyLegacyUsed() || mPowerOnlyQueryUncertain ||
  mQmpUncertain || mQmp.phase!=QPT_CLOSED || mQmp.pending || mQmp.leased || mQmp.owned ||
  !mClock || mClock->Version!=0x1000a || !mClock->GetClockFreqHz ||
  mIds[GPP_GMU_RATE]!=mIds[GPP_GMU_CLK] || mIds[GPP_HUB_RATE]!=mIds[GPP_HUB_CLK] ||
  mIds[GPP_GMU_RATE]>MAX_UINT32 || mIds[GPP_HUB_RATE]>MAX_UINT32 ||
  (mIds[GPP_GMU_RATE]&0xffff0000u)!=0x10000u ||
  (mIds[GPP_HUB_RATE]&0xffff0000u)!=0x10000u;
}
STATIC GPP_U64 PowerOnlyRead(VOID *Cookie,GPP_U32 Address,GPP_U32 *Value) {
 if(!Value || !hph_read_allowed(Address) || PowerOnlyExclusive(Cookie))return EFI_ACCESS_DENIED;
 for(unsigned I=0;I<HGB_REGS;I++)if(Address==hgb_address(I))return BusRead(NULL,Address,Value);
 if(hgb_survey_address(Address))return BusRead(NULL,Address,Value);
 // Only actual hcw_address words and the held-reset HFI status remain.
 return GpuTryRead32(Address,Value)?EFI_DEVICE_ERROR:EFI_SUCCESS;
}
STATIC GPP_U64 PowerOnlyWrite(VOID *Cookie,GPP_U32 Address,GPP_U32 Value) {
 if(hph_field(Address)<0 || PowerOnlyExclusive(Cookie))return EFI_ACCESS_DENIED;
 return BusWrite(NULL,Address,Value);
}
STATIC GPP_U64 PowerOnlyDelay(VOID *Cookie,unsigned Us) {
 if(Us!=1 || PowerOnlyExclusive(Cookie))return EFI_ACCESS_DENIED;
 return Delay(NULL,Us);
}
STATIC GPP_U64 PowerOnlyConfigured(VOID *Cookie,unsigned Which,UINT32 *Hz) {
 if(Which>1 || !Hz || PowerOnlyExclusive(Cookie))return EFI_ACCESS_DENIED;
 *Hz=0;
 EFI_STATUS Status=mClock->GetClockFreqHz(mClock,mIds[Which?GPP_HUB_RATE:GPP_GMU_RATE],Hz);
 // NotStarted is the known software-cache absence, never a zero-Hz claim.
 // Any other failed native query freezes this session before further I/O.
 if(Status!=EFI_SUCCESS && Status!=EFI_NOT_STARTED)mPowerOnlyQueryUncertain=TRUE;
 return Status;
}
STATIC GPP_U64 PowerOnlyHub(VOID *Cookie,CONST struct gpp_report *Power,CONST struct hgb_result *Bus) {
 if(PowerOnlyExclusive(Cookie))return EFI_ACCESS_DENIED;
 EFI_TPL Tpl=gBS->RaiseTPL(TPL_HIGH_LEVEL);gBS->RestoreTPL(Tpl);
 if(Tpl!=TPL_NOTIFY)return EFI_UNSUPPORTED;
 // Existing helper checks exact cold inputs and lowers/restores its own TPL.
 // Its checkpoint stages 4/5 are RAM-only and call no firmware allocator.
 EFI_STATUS Status=PrepareGmuHub(Power,Bus);
 Tpl=gBS->RaiseTPL(TPL_HIGH_LEVEL);gBS->RestoreTPL(Tpl);
 if(Tpl!=TPL_NOTIFY || PowerOnlyExclusive(Cookie))return EFI_ACCESS_DENIED;
 return Status;
}
STATIC VOID PowerOnlyFailure(unsigned Code,UINT64 Status,CONST struct gpp_report *Power,UINT64 PrepareStatus) {
 if(!mPowerOnlyRecord.started) {
  hph_zero(&mPowerOnlyRecord,sizeof(mPowerOnlyRecord));
  mPowerOnlyRecord.magic=HPH_MAGIC;mPowerOnlyRecord.version=HPH_VERSION;
  mPowerOnlyRecord.bytes=HPH_RECORD_BYTES;mPowerOnlyRecord.started=1;
  mPowerOnlyRecord.phase=HPH_PHASE_POWER;
  mPowerOnlyRecord.mask[0]=mPowerOnlyRecord.mask[1]=2;mPowerOnlyRecord.mask[2]=1;
 }
 if(!mPowerOnlyRecord.code) {
  mPowerOnlyRecord.code=Code;mPowerOnlyRecord.first_operation=0x100;
  mPowerOnlyRecord.first_status_lo=(UINT32)Status;
  mPowerOnlyRecord.first_status_hi=(UINT32)(Status>>32);
 }
 if(Power) {
  hph_copy(mPowerOnlyRecord.power_words,Power,sizeof(*Power));
  mPowerOnlyRecord.prepare_status_lo=(UINT32)PrepareStatus;
  mPowerOnlyRecord.prepare_status_hi=(UINT32)(PrepareStatus>>32);
  mPowerOnlyRecord.retained|=!!Power->attempted;
 }
 mPowerOnlyRecord.complete=0;hph_seal(&mPowerOnlyRecord);mGpuMustStop=TRUE;
}
EFI_STATUS HoujiGpuPowerOnlyPrepare(EFI_HANDLE ImageHandle,struct hph_record *Record) {
 struct gpp_report Power;EFI_STATUS Status,PowerStatus;EFI_TPL OldTpl;
 (VOID)ImageHandle;
 if(!Record)return EFI_INVALID_PARAMETER;
 if(mPowerOnlyAttempted) {
  CopyMem(Record,&mPowerOnlyRecord,sizeof(*Record));return EFI_ALREADY_STARTED;
 }
 hph_zero(Record,sizeof(*Record));
 OldTpl=gBS->RaiseTPL(TPL_HIGH_LEVEL);gBS->RestoreTPL(OldTpl);
 if(OldTpl!=TPL_APPLICATION)return EFI_UNSUPPORTED;
 if(mAttempted || mGpuMustStop || !mGpuSaveAllowed || PowerOnlyLegacyUsed()) {
  // A foreign/old GPU path is never made safe by this new entry point.
  mGpuMustStop=TRUE;mGpuSaveAllowed=FALSE;return EFI_ACCESS_DENIED;
 }
 mPowerOnlyAttempted=TRUE;gpp_report_init(&Power);
 mGpuBatchStart=BatchCounter();
 Status=ProbeCheckpoint("before-native-GPU-power-only");
 if(Status!=EFI_SUCCESS) {
  PowerOnlyFailure(HPH_RECORD,Status,NULL,0);
  if(!EFI_ERROR(Status))Status=EFI_DEVICE_ERROR;goto Finished;
 }
 Status=Prepare(&Power,sizeof(Power));PowerStatus=Status;
 if(!hph_power_qualified(&Power,Status)) {
  mGpuSaveAllowed=FALSE;PowerOnlyFailure(HPH_POWER,Status,&Power,PowerStatus);
  if(!EFI_ERROR(Status))Status=EFI_ACCESS_DENIED;goto Finished;
 }
 // Resolve maps only; no context, table, firmware allocation or MMIO write.
 Status=MapMmio(0x3da0000,0x40000);
 if(Status!=EFI_SUCCESS) {
  mGpuSaveAllowed=FALSE;PowerOnlyFailure(HPH_BUS,Status,&Power,PowerStatus);
  if(!EFI_ERROR(Status))Status=EFI_DEVICE_ERROR;goto Finished;
 }
 mGpuSaveAllowed=FALSE;mPowerOnlyActive=TRUE;
 OldTpl=gBS->RaiseTPL(TPL_NOTIFY);
 CONST struct hph_io Io={NULL,PowerOnlyRead,PowerOnlyWrite,PowerOnlyDelay,
  PowerOnlyHub,PowerOnlyConfigured,PowerOnlyExclusive};
 unsigned Code=hph_run(&Io,&Power,PowerStatus,&mPowerOnlyRecord);
 gBS->RestoreTPL(OldTpl);mPowerOnlyActive=FALSE;
 if(Code || !hph_record_valid(&mPowerOnlyRecord) || !mPowerOnlyRecord.complete) {
  PowerOnlyFailure(Code?Code:HPH_RECORD,EFI_DEVICE_ERROR,NULL,0);
  Status=EFI_DEVICE_ERROR;goto Finished;
 }
 // Fresh complete cold proof: CM3=1, every stream FAULT, every CB.M=0.
 // Only this success reopens storage checkpoint permission. Unknown/error
 // retains gates, blocks XNU and keeps MaySave false; no optimistic rollback.
 mGpuSaveAllowed=TRUE;
 Status=ProbeCheckpoint("after-native-GPU-power-only-COLD-no-DMA");
 if(Status!=EFI_SUCCESS) {
  PowerOnlyFailure(HPH_RECORD,Status,NULL,0);
  if(!EFI_ERROR(Status))Status=EFI_DEVICE_ERROR;goto Finished;
 }
 Status=EFI_SUCCESS;
Finished:
 mPowerOnlyActive=FALSE;
 CopyMem(Record,&mPowerOnlyRecord,sizeof(*Record));
 return Status;
}
