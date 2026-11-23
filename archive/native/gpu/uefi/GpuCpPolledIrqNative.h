/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Primary GEN7_HWSCHED_INT_MASK, not the ordinary A7XX mask.
 * Live FDT SPI300 +32 =332. CPU delivery must stay disabled at GICD.
 * No GIC write/IRQ handler, fault clear, PAS or new CP payload is used.
 */
#ifndef HOUJI_GPU_CP_POLLED_IRQ_NATIVE_H
#define HOUJI_GPU_CP_POLLED_IRQ_NATIVE_H
#define HCI_GPU_ERROR_MASK UINT32_C(0x03400042)
#define HCI_GIC_ENABLE UINT32_C(0x17100128)
#define HCI_GIC_GROUP UINT32_C(0x171000a8)
#define HCI_GIC_GPU_BIT (1u<<12)
STATIC struct hll_result mCpIrqLog;
STATIC int CpPolledHealthy(VOID *Cookie) {
 (VOID)Cookie;if(!mCpGicMapped || mCpIrqMask!=HCI_GPU_ERROR_MASK || !CpHealth(NULL))return 0;
 if(GpuTryRead32(HCI_GIC_GROUP,&mCpGicGroup) || !(mCpGicGroup&HCI_GIC_GPU_BIT))return 0;
 if(GpuTryRead32(HCI_GIC_ENABLE,&mCpGicEnable) || GpuTryRead32(0x3d000e0,&mCpIrqAfter))return 0;
 return !(mCpGicEnable&HCI_GIC_GPU_BIT) && mCpIrqAfter==mCpIrqMask;
}
STATIC int CpPolledReady(VOID *Cookie) {(VOID)Cookie;return !CpPolledHealthy(NULL) || Gen7Guard(NULL);}
STATIC int CpReuseAperture(VOID *Cookie) {
 (VOID)Cookie;return mCpApertureCalled!=1 || mCpApertureResult || !mCpApertureValid ||
  mCpAperture.quarantined || mCpAperture.last_output.x[0] || !mCpBoundaryLog.restored ||
  mCpBoundaryLog.code || mCpBoundaryLog.phase!=5 || !mCpIrqLog.restored ||
  mCpIrqLog.code || mCpIrqLog.phase!=5 || CpPolledReady(NULL);
}
STATIC int CpPolledWriteMask(uint32_t Address,uint32_t Value) {
 if(Address!=0x3d000e0 || Value!=HCI_GPU_ERROR_MASK || !mCpGicMapped || mCpIrqMask ||
  mCpInit.phase!=7 || mCpInit.raw_attempted || mCpFirmwareVersion[0]!=0x40020014 ||
  mCpBoundaryLog.code || mCpBoundaryLog.phase!=5 || !mCpBoundaryLog.restored || CpReady(NULL))return 1;
 mCpGicGroup=MmioRead32(HCI_GIC_GROUP);if(!(mCpGicGroup&HCI_GIC_GPU_BIT))return 1;
 mCpGicEnable=MmioRead32(HCI_GIC_ENABLE);if(mCpGicEnable&HCI_GIC_GPU_BIT)return 1;
 mCpIrqBefore=MmioRead32(Address);if(mCpIrqBefore)return 1;
 MmioWrite32(Address,Value);__asm__ volatile("dsb sy":::"memory");
 mCpIrqAfter=MmioRead32(Address);if(mCpIrqAfter!=Value)return 1;
 mCpIrqMask=Value;return 0;
}
STATIC int CpIrqLogGuard(VOID *Cookie) {
 (VOID)Cookie;return CpPolledReady(NULL) || mCpInit.raw_attempted || mCpInit.phase!=2 ||
  !mCpInit.aperture_ok || LiveLogGuard(NULL);
}
STATIC uint64_t CpIrqLogSave(VOID *Cookie) {(VOID)Cookie;return ProbeCheckpoint("polled-HWSCHED-local-IRQ-ready-before-RAW");}
#include "GpuCpNotifySnapshotNative.h"
#include "GpuCpPreflightNative.h"
#include "GpuCpSplitNative.h"
STATIC unsigned RunCpPolledIrq(struct hhb_result *Bootstrap) {
 if(mCpInit.phase!=7 || mCpInit.raw_attempted || CpReady(NULL))return HCI_GUARD;
 UINT64 SavedPar,Par=0,Address=HCI_GIC_ENABLE;
 EFI_TPL Tpl=gBS->RaiseTPL(TPL_HIGH_LEVEL);__asm__ volatile("mrs %0,par_el1":"=r"(SavedPar));
 __asm__ volatile("at s1e1r,%1; isb; mrs %0,par_el1":"=r"(Par):"r"(Address):"memory");
 mCpGicMapped=!(Par&1) && (Par&0x0000fffffffff000ULL)==(Address&~4095ULL) &&
  ((Par>>56)==0 || (Par>>56)==4);
 __asm__ volatile("msr par_el1,%0; isb"::"r"(SavedPar):"memory");gBS->RestoreTPL(Tpl);
 mCpIrqPrepCode=CpPolledWriteMask(0x3d000e0,HCI_GPU_ERROR_MASK);
 Print(L"HOUJI GPU CP IRQ PREP: code=%u GIC-map=%u PAR=%lx GIC-group=%x enable=%x SPI332-bit=%x before=%x after=%x expected=%x; local error mask only, no GIC write, no RAW yet\n",mCpIrqPrepCode,mCpGicMapped,Par,mCpGicGroup,mCpGicEnable,HCI_GIC_GPU_BIT,mCpIrqBefore,mCpIrqAfter,HCI_GPU_ERROR_MASK);
 if(mCpIrqPrepCode)return HCI_GUARD;
 mCpInit.phase=2;
 CONST struct hll_io Log={NULL,LiveLogTpl,LiveLogLower,LiveLogRestore,CpIrqLogGuard,CpIrqLogSave};
 if(hll_run(&Log,&mCpIrqLog))return HCI_IO;
 unsigned Preflight=RunCpPreflight(Bootstrap);if(Preflight)return Preflight;
 return RunCpSplit(Bootstrap);
}
#endif
