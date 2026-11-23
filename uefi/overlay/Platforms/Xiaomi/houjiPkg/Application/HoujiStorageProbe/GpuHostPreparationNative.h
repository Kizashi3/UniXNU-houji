/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Same-boot host-ring preparation after the actual qualified r112 protocol.
 * Attach normalGPU SID0+LPAC SID1 to owned bank0, then the minimum
 * OOB/code/config path. Secure SID2 and all unrelated streams remain FAULT.
 * No secure context, HWSCHED allocation, aperture, SQE enable, ring kick or CP.
 */
#ifndef HOUJI_GPU_HOST_PREPARATION_NATIVE_H
#define HOUJI_GPU_HOST_PREPARATION_NATIVE_H
STATIC struct {unsigned started,phase,code;struct hll_result log;} mHostPrep;
STATIC int HostContextQualified(VOID) {
 if(!mHostProfileReady || !mGxMapped || !mScratchAssigned || mScratchResult.code ||
  mScratchResult.phase!=5 || mScratchResult.enabled!=1 || mScratchResult.attached!=1 ||
  mScratchResult.retained!=1 || mScratchResult.lpac!=1 || mScratchResult.sid0_attached!=1 ||
  mScratchResult.lpac_attached!=1 || mScratchResult.sid0_smr!=0x80000000u ||
  mScratchResult.sid0_s2cr || mScratchResult.lpac_smr!=0x80000001u || mScratchResult.lpac_s2cr ||
  !mScratchReady || mSharedCount || mSecureAssigned || mSecureContext.attached ||
  mSecureMemory.owned || mSecureTableOwned || !StockBootstrapHealthy(NULL) || ScratchGuard(NULL))return 1;
 uint32_t Value;
 CONST uint32_t Faults[]={0x3da0048,0x3dc0058,0x3dc2058};
 for(unsigned I=0;I<3;I++)if(GpuTryRead32(Faults[I],&Value) ||
  (Value&(I?0xc00001feu:0xffffffffu)))return 1;
 return 0;
}
STATIC int HostPreparationGuard(VOID *Cookie) {
 (VOID)Cookie;if(HostContextQualified() || Gen7Guard(NULL) || mGen7.code || mGen7.phase!=6 ||
  !mGen7.record_ready || !mGxStart.gx_ready || !mGxStart.acked || !mGxStart.clear_confirmed ||
  MmioRead32(0x3d02020)!=0 || ScratchAudit())return 1;
 struct ggh_io Hfi={mFirmwareMemory.memory[5].cpu,GGH_BYTES,GGH_IOVA,NULL,StockHfiBarrier};
 for(unsigned I=0;I<GGH_QUEUES;I++) {
  volatile uint32_t *Header,*Ring;unsigned Read,Write;
  if(ggh_queue(&Hfi,I,&Header,&Ring,&Read,&Write) || Read!=Write)return 1;
 }
 for(unsigned I=0;I<=mFirmwareMemory.count;I++) {
  CONST struct hfm_allocation *M=&mFirmwareMemory.memory[I];
  if(FirmwareVerifyPagesQuiet(M->physical,M->cpu,M->pages,M->nc))return 1;
 }
 return FirmwareVerifyPagesQuiet(mCodeMemory.physical,mCodeMemory.cpu,HCC_PAGES,1) ||
  FirmwareVerifyPagesQuiet(mGpuOnlyMemory.physical,mGpuOnlyMemory.cpu,HSC_POOL_PAGES,1) ||
  FirmwareVerifyPagesQuiet(mScratchTablePhysical,mScratchTables,HSC_GPU_TABLE_PAGES,0);
}
#include "GpuCpDeviceNative.h"
STATIC uint64_t HostPreparationSave(VOID *Cookie) {
 (VOID)Cookie;
 // hll_run already lowered to application TPL after its second full guard.
 // Persist either the actual mapping proof or its failure before any SQE start.
 int MapCode=CpDeviceNgNrePrepare();
 int ClockCode=MapCode?0:GpuClockWitnessR1();
#ifdef HOUJI_CALL_TRACE_NATIVE
 // Select before the durable save; Start/Resume retain this mode, so no
 // normal trace framebuffer store can occur in the later SQE critical path.
 HoujiGpuCallTraceRamOnly();
#endif
 // Query-only PAS capability observations are captured at application TPL
 // and committed by this existing checkpoint before any SQE store.
 int GraphicsCode=(MapCode || ClockCode)?0:PrepareGraphicsPrerequisites();
 uint64_t SaveCode=ProbeCheckpoint("HOST-ring-normalGPU-OOB-code-config-ready-NO-CP");
 // HLL consumes EFI_STATUS: a small nonzero integer is not an EFI error.
 return (MapCode || ClockCode || GraphicsCode)?0x8000000000000003ULL:SaveCode;
}
STATIC unsigned RunHostPreparation(struct hhb_result *Bootstrap) {
 if(!Bootstrap || Bootstrap->code || Bootstrap->completed!=HHP_STEPS || !mHostProfileReady ||
  mHostPrep.started || mScratchAssigned || mSecureAssigned || mSharedCount || !mScratchReady ||
  !mCodeReady || !StockBootstrapHealthy(NULL) || ScratchAudit())return HCI_GUARD;
 mHostPrep.started=1;mHostPrep.phase=1;mScratchAssigned=TRUE;
 CONST struct hgp_io Attach={NULL,ScratchRead32,ScratchRead64,ScratchWrite32,ScratchWrite64,
  ContextDelay,ScratchGuard,NULL};
 unsigned Code=hsc_run_lpac(&Attach,&mScratchConfig,&mScratchBuilt,&mScratchResult);
 Print(L"HOUJI GPU HOST PREP: normalGPU attach=%u phase=%u attached=%u LPAC-profile=%u SID0-proof=%u LPAC-proof=%u; bank0 SID0+SID1 only, secure SID2 remains FAULT\n",
  Code,mScratchResult.phase,mScratchResult.attached,mScratchResult.lpac,mScratchResult.sid0_attached,mScratchResult.lpac_attached);
 Print(L"HOUJI GPU HOST PREP ROUTES: SID0 SMR=%08x S2CR=%08x LPAC SMR=%08x S2CR=%08x; actual attachment readback, no SQE stream observation\n",
  mScratchResult.sid0_smr,mScratchResult.sid0_s2cr,mScratchResult.lpac_smr,mScratchResult.lpac_s2cr);
 if(!Code) {mHostPrep.phase=2;Code=RunGxStart(Bootstrap);GxStartReport();}
 if(!Code) {mHostPrep.phase=3;Code=RunCodeBind();CodeBindReport();}
 if(!Code) {mHostPrep.phase=4;Code=RunGen7Config();Gen7Report();}
 if(!Code) {
  mHostPrep.phase=5;
  CONST struct hll_io Log={NULL,LiveLogTpl,LiveLogLower,LiveLogRestore,HostPreparationGuard,HostPreparationSave};
  Code=hll_run(&Log,&mHostPrep.log);
 }
 mHostPrep.code=Code;if(!Code)mHostPrep.phase=6;
 Print(L"HOUJI GPU HOST PREP: result=%u phase=%u checkpoint=%u/%u restored=%u; normal context, OOB and code/config only; NO SQE start/ring/CP/PAS/Metal\n",
  Code,mHostPrep.phase,mHostPrep.log.code,mHostPrep.log.phase,mHostPrep.log.restored);
 return Code;
}
#endif
