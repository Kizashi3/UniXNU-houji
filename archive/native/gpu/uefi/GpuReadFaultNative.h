/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Only a precise synchronous external READ abort at our one-load leaf may
 * return failure. No SError, OEM instruction, arbitrary PC or write is resumed.
 * The handler records CPU RAM only and never performs file/BS/MMIO operations.
 */
#ifndef HOUJI_GPU_READ_FAULT_NATIVE_H
#define HOUJI_GPU_READ_FAULT_NATIVE_H
#include "GpuReadFaultPolicy.h"
#ifdef HOUJI_CALL_TRACE
#define HOUJI_READ_TRACE(Step,Address,Value) HOUJI_CALL_TRACE(Step,Address,Value)
#else
#define HOUJI_READ_TRACE(Step,Address,Value) ((void)0)
#endif
STATIC volatile struct hrf_request mGpuReadRequest;
STATIC struct hrf_fault mGpuReadFirstFault;
STATIC unsigned mGpuReadCalls,mGpuReadFaults;
STATIC UINT32 __attribute__((naked)) GpuRead32Stub(UINT64 Address) {__asm__ volatile("ldr w0, [x0]\n\tret");}
STATIC UINT64 __attribute__((naked)) GpuRead64Stub(UINT64 Address) {__asm__ volatile("ldr x0, [x0]\n\tret");}
BOOLEAN EFIAPI HoujiGpuHandleReadFault(EFI_EXCEPTION_TYPE Type,EFI_SYSTEM_CONTEXT_AARCH64 *C) {
 if(Type!=EXCEPT_AARCH64_SYNCHRONOUS_EXCEPTIONS || !C)return FALSE;
 HOUJI_READ_TRACE(0x40f0,C->ELR,C->ESR);
 struct hrf_request Request=mGpuReadRequest;
 if(Request.pc!=(UINTN)GpuRead32Stub && Request.pc!=(UINTN)GpuRead64Stub)return FALSE;
 if(*((CONST UINT32 *)(UINTN)Request.pc+1)!=0xd65f03c0u)return FALSE;
 if(!hrf_expected(&Request,C->ELR,C->X0,C->ESR,C->FAR,*(CONST UINT32 *)(UINTN)Request.pc))return FALSE;
 mGpuReadRequest.failed=1;mGpuReadFaults++;
 if(!mGpuReadFirstFault.valid)mGpuReadFirstFault=(struct hrf_fault){C->ELR,Request.address,C->ESR,C->FAR,C->LR,Request.width,1};
 HOUJI_READ_TRACE(0x40f1,Request.address,Request.width);
 C->X0=0;C->ELR+=4;return TRUE; // Exact RET, wrapper rejects the placeholder.
}
STATIC int GpuReadBegin(UINT64 Address,unsigned Width,UINTN Pc) {
 HOUJI_READ_TRACE(0x4000,Address,Width);
 if(!hrf_address(Address,Width) || mGpuReadRequest.armed ||
  Pc!=(Width==32?(UINTN)GpuRead32Stub:(UINTN)GpuRead64Stub) ||
  *(CONST UINT32 *)Pc!=(Width==32?0xb9400000u:0xf9400000u) ||
  *((CONST UINT32 *)Pc+1)!=0xd65f03c0u) {
  HOUJI_READ_TRACE(0x4001,Address,Width);return 1;
 }
 mGpuReadRequest=(struct hrf_request){Pc,Address,1,Width,0};mGpuReadCalls++;
 HOUJI_READ_TRACE(0x4002,Address,Width);
 __asm__ volatile("dsb sy":::"memory");
 HOUJI_READ_TRACE(0x4003,Address,Width);return 0;
}
STATIC int GpuTryRead32(UINT64 Address,uint32_t *Value) {
 HOUJI_READ_TRACE(0x4010,Address,32);
 if(!Value || GpuReadBegin(Address,32,(UINTN)GpuRead32Stub)) {
  HOUJI_READ_TRACE(0x4011,Address,32);return 1;
 }
 HOUJI_READ_TRACE(0x4012,Address,32);
 UINT32 V=GpuRead32Stub(Address);
 HOUJI_READ_TRACE(0x4013,Address,V);
 HOUJI_READ_TRACE(0x4014,Address,32);
 __asm__ volatile("dsb sy":::"memory");
 HOUJI_READ_TRACE(0x4015,Address,32);
 mGpuReadRequest.armed=0;HOUJI_READ_TRACE(0x4016,Address,32);
 if(mGpuReadRequest.failed) {HOUJI_READ_TRACE(0x4017,Address,32);return 2;}
 *Value=V;HOUJI_READ_TRACE(0x4018,Address,V);return 0;
}
STATIC int GpuTryRead64(UINT64 Address,uint64_t *Value) {
 HOUJI_READ_TRACE(0x4010,Address,64);
 if(!Value || GpuReadBegin(Address,64,(UINTN)GpuRead64Stub)) {
  HOUJI_READ_TRACE(0x4011,Address,64);return 1;
 }
 HOUJI_READ_TRACE(0x4012,Address,64);
 UINT64 V=GpuRead64Stub(Address);
 HOUJI_READ_TRACE(0x4013,Address,V);
 HOUJI_READ_TRACE(0x4014,Address,64);
 __asm__ volatile("dsb sy":::"memory");
 HOUJI_READ_TRACE(0x4015,Address,64);
 mGpuReadRequest.armed=0;HOUJI_READ_TRACE(0x4016,Address,64);
 if(mGpuReadRequest.failed) {HOUJI_READ_TRACE(0x4017,Address,64);return 2;}
 *Value=V;HOUJI_READ_TRACE(0x4018,Address,V);return 0;
}
STATIC VOID GpuReadFaultReport(VOID) {
 Print(L"HOUJI GPU READ FAULT: calls=%u faults=%u first-valid=%u width=%u PC=%lx address=%lx ESR=%lx FAR=%lx LR=%lx; exact read leaf only, failed output invalid, no SError or write resume\n",mGpuReadCalls,mGpuReadFaults,mGpuReadFirstFault.valid,mGpuReadFirstFault.width,mGpuReadFirstFault.pc,mGpuReadFirstFault.address,mGpuReadFirstFault.esr,mGpuReadFirstFault.far,mGpuReadFirstFault.lr);
}
#undef HOUJI_READ_TRACE
#endif
