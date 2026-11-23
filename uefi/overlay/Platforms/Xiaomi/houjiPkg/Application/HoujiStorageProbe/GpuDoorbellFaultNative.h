/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * One known HFI notification address/value only. On a precise STR abort,
 * preserve failure and unknown write side effects; quarantine ALL later HFI
 * notifications, never retry. No SError/arbitrary instruction/write recovery.
 * Handler uses CPU RAM only; the existing outer reset retains every resource.
 */
#ifndef HOUJI_GPU_DOORBELL_FAULT_NATIVE_H
#define HOUJI_GPU_DOORBELL_FAULT_NATIVE_H
#include "GpuDoorbellFaultPolicy.h"
STATIC volatile struct hdf_request mGpuDoorbellRequest;
STATIC struct hdf_fault mGpuDoorbellFirstFault;
STATIC unsigned mGpuDoorbellCalls,mGpuDoorbellFaults,mGpuDoorbellStage,mGpuDoorbellQuarantined;
STATIC VOID __attribute__((naked)) GpuDoorbellWriteStub(UINT64 Address,UINT32 Value) {
 __asm__ volatile("str w1, [x0]\n\tret");
}
BOOLEAN EFIAPI HoujiGpuHandleDoorbellFault(EFI_EXCEPTION_TYPE Type,EFI_SYSTEM_CONTEXT_AARCH64 *C) {
 if(Type!=EXCEPT_AARCH64_SYNCHRONOUS_EXCEPTIONS || !C)return FALSE;
 struct hdf_request R=mGpuDoorbellRequest;
 if(R.pc!=(UINTN)GpuDoorbellWriteStub || *((CONST UINT32 *)(UINTN)R.pc+1)!=0xd65f03c0u ||
  !hdf_expected(&R,C->ELR,C->X0,C->X1,C->ESR,C->FAR,*(CONST UINT32 *)(UINTN)R.pc))return FALSE;
 mGpuDoorbellRequest.failed=1;mGpuDoorbellFaults++;mGpuDoorbellQuarantined=1;
 if(!mGpuDoorbellFirstFault.valid)mGpuDoorbellFirstFault=(struct hdf_fault){C->ELR,R.address,C->ESR,C->FAR,C->LR,1};
 C->ELR+=4;return TRUE; // Exact RET, no success value; wrapper reports uncertainty.
}
STATIC int GpuDoorbellBegin(UINT64 Address,UINT32 Value,UINTN Pc) {
 if(Address!=0x3d7e650 || Value!=1 || mGpuDoorbellQuarantined || mGpuDoorbellRequest.armed ||
  Pc!=(UINTN)GpuDoorbellWriteStub || *(CONST UINT32 *)Pc!=0xb9000001u ||
  *((CONST UINT32 *)Pc+1)!=0xd65f03c0u)return 1;
 mGpuDoorbellRequest=(struct hdf_request){Pc,Address,Value,1,0};
 mGpuDoorbellCalls++;mGpuDoorbellStage=1;__asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC int GpuDoorbellWrite(UINT64 Address,UINT32 Value) {
 if(GpuDoorbellBegin(Address,Value,(UINTN)GpuDoorbellWriteStub))return 1;
 GpuDoorbellWriteStub(Address,Value);mGpuDoorbellRequest.armed=0;
 if(mGpuDoorbellRequest.failed){mGpuDoorbellStage=4;return 2;}
 mGpuDoorbellStage=2;__asm__ volatile("dsb sy":::"memory");mGpuDoorbellStage=3;return 0;
}
STATIC VOID GpuDoorbellFaultReport(VOID) {
 Print(L"HOUJI GPU DOORBELL IO: calls=%u stage=%u faults=%u quarantined=%u first-valid=%u PC=%lx address=%lx ESR=%lx FAR=%lx LR=%lx; stages1=STR/2=DSB/3=returned/4=precise-fault; failed write effects uncertain, never retried\n",
  mGpuDoorbellCalls,mGpuDoorbellStage,mGpuDoorbellFaults,mGpuDoorbellQuarantined,
  mGpuDoorbellFirstFault.valid,mGpuDoorbellFirstFault.pc,mGpuDoorbellFirstFault.address,
  mGpuDoorbellFirstFault.esr,mGpuDoorbellFirstFault.far,mGpuDoorbellFirstFault.lr);
}
#endif
