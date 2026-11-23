/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef HOUJI_GPU_LIVE_LOG_NATIVE_H
#define HOUJI_GPU_LIVE_LOG_NATIVE_H
#include "GpuLiveLog.h"
STATIC struct hll_result mLiveLog;
STATIC struct hll_result mLiveLogBefore;
STATIC unsigned mLiveLogMode;
STATIC struct hhb_result *mLiveBootstrap;
STATIC unsigned LiveLogTpl(VOID *Cookie) {
 (VOID)Cookie;HOUJI_CALL_TRACE(0x1200,0,TPL_HIGH_LEVEL);
 EFI_TPL Tpl=gBS->RaiseTPL(TPL_HIGH_LEVEL);HOUJI_CALL_TRACE(0x1201,0,Tpl);
 HOUJI_CALL_TRACE(0x1202,0,Tpl);gBS->RestoreTPL(Tpl);HOUJI_CALL_TRACE(0x1203,0,Tpl);return Tpl;
}
STATIC VOID LiveLogLower(VOID *Cookie) {
 (VOID)Cookie;HOUJI_CALL_TRACE(0x1204,0,TPL_APPLICATION);gBS->RestoreTPL(TPL_APPLICATION);
 HOUJI_CALL_TRACE(0x1205,0,TPL_APPLICATION);
}
STATIC int LiveLogRestore(VOID *Cookie) {
 (VOID)Cookie;HOUJI_CALL_TRACE(0x1206,0,TPL_NOTIFY);
 EFI_TPL Before=gBS->RaiseTPL(TPL_NOTIFY);HOUJI_CALL_TRACE(0x1207,0,Before);return Before!=TPL_APPLICATION;
}
STATIC int LiveLogGuard(VOID *Cookie) {
 (VOID)Cookie;BOOLEAN ApertureOkay=(mLiveLogMode==1 && !mCpApertureCalled) ||
  (mLiveLogMode==2 && mCpApertureCalled && !mCpApertureResult && mCpApertureValid && !mCpAperture.quarantined &&
   !mCpAperture.last_output.x[0] && mCpInit.phase==2 && mCpInit.aperture_attempted &&
   !mLiveLogBefore.code && mLiveLogBefore.phase==5 && mLiveLogBefore.restored);
 if(!mLiveBootstrap || mLiveBootstrap->code || mLiveBootstrap->completed!=HHB_STEPS ||
  mCpInit.raw_attempted || !ApertureOkay || Gen7Guard(NULL) || mGen7.code || mGen7.phase!=6 || !mGen7.record_ready ||
  MmioRead32(h7c_ops[0].address)!=mCpIrqMask || ScratchAudit() || SecureDomainGuard(NULL))return 1;
 struct ggh_io Hfi={mFirmwareMemory.memory[5].cpu,GGH_BYTES,GGH_IOVA,NULL,StockHfiBarrier};
 for(unsigned I=0;I<GGH_QUEUES;I++) {
  volatile uint32_t *Header,*Ring;unsigned Read,Write;
  if(ggh_queue(&Hfi,I,&Header,&Ring,&Read,&Write) || Read!=Write)return 1;
 }
 // All device-reachable ordinary memory stays allocated and pinned; the exact
 // GPU/GMU/secure graph audits above exclude general UEFI/UFS buffers. Validate
 // actual CPU mappings again before and after the file operation.
 for(unsigned I=0;I<=mFirmwareMemory.count;I++) {
  CONST struct hfm_allocation *M=&mFirmwareMemory.memory[I];
  if(FirmwareVerifyPages(M->physical,M->cpu,M->pages,M->nc))return 1;
 }
 return FirmwareVerifyPages(mCodeMemory.physical,mCodeMemory.cpu,HCC_PAGES,1) ||
  FirmwareVerifyPages(mGpuOnlyMemory.physical,mGpuOnlyMemory.cpu,HSC_POOL_PAGES,1) ||
  FirmwareVerifyPages(mScratchTablePhysical,mScratchTables,HSC_GPU_TABLE_PAGES,0);
}
STATIC uint64_t LiveLogSave(VOID *Cookie) {(VOID)Cookie;return ProbeCheckpoint(mLiveLogMode==1?"live-GMU-before-aperture":"live-GMU-after-aperture-before-RAW");}
STATIC unsigned RunLiveLogCanary(struct hhb_result *Bootstrap) {
 mLiveBootstrap=Bootstrap;mLiveLogMode=1;
 Print(L"HOUJI GPU LIVE LOG CANARY: completed-HFI=%u resources=%u all queues must be empty; OOB held, code/config/record ready; no aperture or RAW attempted\n",Bootstrap->completed,Bootstrap->resource_acks);
 GxStartReport();CodeBindReport();Gen7Report();
 CONST struct hll_io Io={NULL,LiveLogTpl,LiveLogLower,LiveLogRestore,LiveLogGuard,LiveLogSave};
 return hll_run(&Io,&mLiveLog);
}
STATIC unsigned CpPreRawCheckpoint(VOID) {
 if(mLiveLogMode!=1 || mLiveLog.code || mLiveLog.phase!=5 || !mLiveLog.restored)return 1;
 mLiveLogBefore=mLiveLog;mLiveLogMode=2;
 if(ArmCpPolling())return 1;
 Print(L"HOUJI GPU PRE RAW: aperture-code=%u actual-calls=%u raw-valid=%u a0=%lx a1=%lx; no RAW has been sent, durable snapshot next\n",mCpApertureResult,mCpApertureCalled,mCpApertureValid,mCpAperture.last_output.x[0],mCpAperture.last_output.x[1]);
 CONST struct hll_io Io={NULL,LiveLogTpl,LiveLogLower,LiveLogRestore,LiveLogGuard,LiveLogSave};
 return hll_run(&Io,&mLiveLog);
}
STATIC VOID LiveLogReport(VOID) {
 Print(L"HOUJI GPU LIVE LOG RESULT: code=%u phase=%u lowered=%u restored=%u guards=%u TPL=%u/%u status=%lx; pre-CP points only, CM3 reset before subsequent normal snapshots\n",
 mLiveLog.code,mLiveLog.phase,mLiveLog.lowered,mLiveLog.restored,mLiveLog.guards,mLiveLog.before_tpl,mLiveLog.after_tpl,mLiveLog.status);
 Print(L"HOUJI GPU LIVE LOG STAGES: mode=%u prior-code=%u prior-phase=%u prior-restored=%u; no filesystem snapshot after RAW dispatch while firmware runs\n",mLiveLogMode,mLiveLogBefore.code,mLiveLogBefore.phase,mLiveLogBefore.restored);
}
STATIC struct hll_result mCpIdleLog,mCpStoppedLog;
STATIC int CpIdleLogGuard(VOID *Cookie) {
 (VOID)Cookie;
 if(mCpInit.code || mCpInit.phase!=6 || !mCpInit.idle || !mCpInit.raw.record[0].ack ||
  mCpInit.raw.code || !mCpInit.raw.completed || !mCpPollArmed || mCpPoll.failed ||
  (mCpIrqMask?!CpPolledHealthy(NULL):!CpHealth(NULL)) || ScratchAudit() || SecureDomainGuard(NULL) ||
  MmioRead32(0x3d8ec30)&(1u<<23) || MmioRead32(0x3d00840) || MmioRead32(0x3d00804) ||
  MmioRead32(h7c_ops[0].address)!=mCpIrqMask)return 1;
 struct ggh_io Hfi={mFirmwareMemory.memory[5].cpu,GGH_BYTES,GGH_IOVA,NULL,StockHfiBarrier};
 for(unsigned I=0;I<GGH_QUEUES;I++) {
  volatile uint32_t *Header,*Ring;unsigned Read,Write;
  if(ggh_queue(&Hfi,I,&Header,&Ring,&Read,&Write) || Read!=Write)return 1;
 }
 return 0;
}
STATIC uint64_t CpIdleLogSave(VOID *Cookie) {(VOID)Cookie;return ProbeCheckpoint("CP-ACK-idle-before-GMU-reset");}
STATIC unsigned CpIdleCheckpoint(VOID) {
 if(CpIdleLogGuard(NULL))return 1;
 CpInitReport();
 CONST struct hll_io Io={NULL,LiveLogTpl,LiveLogLower,LiveLogRestore,CpIdleLogGuard,CpIdleLogSave};
 return hll_run(&Io,&mCpIdleLog);
}
STATIC int CpStoppedLogGuard(VOID *Cookie) {
 (VOID)Cookie;return !mStockCalled || !mFirmwareHeld || mFirmwareMemory.retained!=HFM_ALL ||
  !mStockResult.release_attempted || !mStockResult.reset_held || !mGpuSaveAllowed || mHostRingUnsafe;
}
STATIC uint64_t CpStoppedLogSave(VOID *Cookie) {(VOID)Cookie;return ProbeCheckpoint("CP-result-confirmed-GMU-reset-before-fault-MMIO");}
STATIC int CpStoppedCheckpoint(VOID *Cookie) {
 (VOID)Cookie;mGpuSaveAllowed=mStockResult.reset_held && !mHostRingUnsafe;
 if(CpStoppedLogGuard(NULL))return 1;
 // RAM results only here. This callback precedes all post-reset fault MMIO.
 Print(L"HOUJI GPU CP EARLY STOP: code=%u phase=%u reset-held=%u failed-phase=%u; no post-reset fault MMIO yet\n",mStockResult.code,mStockResult.phase,mStockResult.reset_held,mStockResult.failed_phase);
 CpInitReport();
 HostRingReport();
 CONST struct hll_io Io={NULL,LiveLogTpl,LiveLogLower,LiveLogRestore,CpStoppedLogGuard,CpStoppedLogSave};
 return hll_run(&Io,&mCpStoppedLog);
}
#endif
