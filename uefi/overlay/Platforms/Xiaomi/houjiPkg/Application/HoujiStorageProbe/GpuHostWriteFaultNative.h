/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Exact SQE start/halt STR+RET only. A trapped write has UNKNOWN effects and
 * always returns failure. Only a separate real bus-halt proof may reopen logs.
 */
#ifndef HOUJI_GPU_HOST_WRITE_FAULT_NATIVE_H
#define HOUJI_GPU_HOST_WRITE_FAULT_NATIVE_H
#include "GpuHostWriteFaultPolicy.h"
#ifdef HOUJI_CALL_TRACE
#define HOUJI_HOST_WRITE_TRACE(Step,Address,Value) HOUJI_CALL_TRACE(Step,Address,Value)
#else
#define HOUJI_HOST_WRITE_TRACE(Step,Address,Value) ((void)0)
#endif
STATIC volatile struct hhw_request mHostWriteRequest;
STATIC unsigned mHostWriteCalls,mHostWriteFaults,mHostHaltAttempted,mHostHaltFailed;
STATIC struct {UINT64 pc,esr,far,lr,value;unsigned valid;} mHostWriteFirst;
STATIC VOID __attribute__((naked)) HostWriteStub(UINT64 Address,uint32_t Value) {
 __asm__ volatile("str w1, [x0]\n\tret");
}
BOOLEAN EFIAPI HoujiGpuHandleHostWriteFault(EFI_EXCEPTION_TYPE Type,EFI_SYSTEM_CONTEXT_AARCH64 *C) {
 if(Type!=EXCEPT_AARCH64_SYNCHRONOUS_EXCEPTIONS || !C)return FALSE;
 HOUJI_HOST_WRITE_TRACE(0x50f0,C->ELR,C->ESR);
 struct hhw_request Request=mHostWriteRequest;
 if(Request.pc!=(UINTN)HostWriteStub || *((CONST UINT32 *)(UINTN)Request.pc+1)!=0xd65f03c0u ||
  !hhw_match(&Request,C->ELR,C->X0,C->X1,C->ESR,C->FAR,*(CONST UINT32 *)(UINTN)Request.pc))return FALSE;
 mHostWriteRequest.failed=1;mHostWriteFaults++;
 if(!mHostWriteFirst.valid) {
  mHostWriteFirst.pc=C->ELR;mHostWriteFirst.esr=C->ESR;mHostWriteFirst.far=C->FAR;
  mHostWriteFirst.lr=C->LR;mHostWriteFirst.value=Request.value;mHostWriteFirst.valid=1;
 }
 HOUJI_HOST_WRITE_TRACE(0x50f1,C->FAR,Request.value);
 C->ELR+=4;return TRUE; // Exact RET, CPU-RAM recording only, wrapper returns failure.
}
STATIC int HostRingStore32(uint32_t Value) {
 HOUJI_HOST_WRITE_TRACE(0x5000,0x3d02020,Value);
 if((Value!=1 && Value!=3) || mHostWriteRequest.armed || (Value==1 && mHostWriteFaults) ||
  (Value==3 && mHostHaltFailed) ||
  *(CONST UINT32 *)(UINTN)HostWriteStub!=0xb9000001u ||
  *((CONST UINT32 *)(UINTN)HostWriteStub+1)!=0xd65f03c0u) {
  HOUJI_HOST_WRITE_TRACE(0x5001,0x3d02020,Value);return 1;
 }
 if(Value==3)mHostHaltAttempted=1;
 mHostWriteRequest=(struct hhw_request){(UINTN)HostWriteStub,1,0,Value};mHostWriteCalls++;
 HOUJI_HOST_WRITE_TRACE(0x5002,0x3d02020,Value);
 __asm__ volatile("dsb sy":::"memory");
 HOUJI_HOST_WRITE_TRACE(0x5003,0x3d02020,Value);
 HOUJI_HOST_WRITE_TRACE(0x5004,0x3d02020,Value);
 HostWriteStub(0x3d02020,Value);
 HOUJI_HOST_WRITE_TRACE(0x5005,0x3d02020,Value);
 HOUJI_HOST_WRITE_TRACE(0x5006,0x3d02020,Value);
 __asm__ volatile("dsb sy":::"memory");
 HOUJI_HOST_WRITE_TRACE(0x5007,0x3d02020,Value);
 mHostWriteRequest.armed=0;HOUJI_HOST_WRITE_TRACE(0x5008,0x3d02020,Value);
 if(mHostWriteRequest.failed) {
  if(Value==3)mHostHaltFailed=1;
  HOUJI_HOST_WRITE_TRACE(0x5009,0x3d02020,Value);return 1;
 }
 HOUJI_HOST_WRITE_TRACE(0x500a,0x3d02020,Value);return 0;
}
STATIC VOID HostWriteReport(VOID) {
 Print(L"HOUJI GPU HOST WRITE FAULT: calls=%u faults=%u valid=%u PC=%lx value=%lx ESR=%lx FAR=%lx LR=%lx; precise SQE STR+RET only, unknown effects on fault, no SError/OEM/arbitrary resume\n",mHostWriteCalls,mHostWriteFaults,mHostWriteFirst.valid,mHostWriteFirst.pc,mHostWriteFirst.value,mHostWriteFirst.esr,mHostWriteFirst.far,mHostWriteFirst.lr);
}
#undef HOUJI_HOST_WRITE_TRACE
#endif
