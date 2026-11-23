/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Controlled CPU memory-type comparison for the fixed CP register page.
 * Called at application TPL, with SQE still zero, before the existing durable
 * host-preparation checkpoint. Does not touch a GPU register or SMMU table.
 */
#ifndef HOUJI_GPU_CP_DEVICE_NATIVE_H
#define HOUJI_GPU_CP_DEVICE_NATIVE_H
#include <Library/ArmMmuLib.h>
STATIC ARM_HOUJI_CP_DEVICE_REPORT mCpDeviceReport;
STATIC unsigned mCpDeviceAttempted;
STATIC int CpDeviceNgNrePrepare(VOID) {
 if(mCpDeviceAttempted || HostPreparationGuard(NULL))return 1;
 mCpDeviceAttempted=1;
 EFI_STATUS Status=ArmSetHoujiCpDeviceNgNre(&mCpDeviceReport);
 Print(L"HOUJI GPU CPU CP TYPE: status=%lx version=%u stage=%u failed=%u audit=%u tables=%u leaves=%u splits=%u used=%u; fixed CP 03d02000/1000 only\n",
  (UINT64)Status,mCpDeviceReport.Version,mCpDeviceReport.Stage,mCpDeviceReport.Failed,mCpDeviceReport.AuditCode,
  mCpDeviceReport.Tables,mCpDeviceReport.Leaves,mCpDeviceReport.SplitsNeeded,mCpDeviceReport.SpareUsed);
 Print(L"HOUJI GPU CPU CP REGIME: TTBR0=%lx TCR=%lx MAIR=%lx/%lx; CPU page tables, not GPU SMMU\n",
  mCpDeviceReport.Root,mCpDeviceReport.Tcr,mCpDeviceReport.MairBefore,mCpDeviceReport.MairAfter);
 Print(L"HOUJI GPU CPU CP PTE: level=%u/%u descriptor=%lx/%lx; only AttrIndx changes\n",
  mCpDeviceReport.BeforeLevel,mCpDeviceReport.AfterLevel,mCpDeviceReport.BeforeDescriptor,mCpDeviceReport.AfterDescriptor);
 Print(L"HOUJI GPU CPU CP PAR: R/W before=%lx/%lx after=%lx/%lx neighbor before=%lx/%lx after=%lx/%lx; require identity Device04 and neighbors unchanged\n",
  mCpDeviceReport.ParBeforeRead,mCpDeviceReport.ParBeforeWrite,mCpDeviceReport.ParAfterRead,mCpDeviceReport.ParAfterWrite,
  mCpDeviceReport.NeighborBefore[0],mCpDeviceReport.NeighborBefore[1],mCpDeviceReport.NeighborAfter[0],mCpDeviceReport.NeighborAfter[1]);
 return EFI_ERROR(Status) || mCpDeviceReport.Version!=1 || mCpDeviceReport.Status!=Status ||
  mCpDeviceReport.Stage!=8 || mCpDeviceReport.Failed || HostPreparationGuard(NULL);
}
#endif
