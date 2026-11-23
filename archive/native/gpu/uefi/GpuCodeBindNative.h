/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef HOUJI_GPU_CODE_BIND_NATIVE_H
#define HOUJI_GPU_CODE_BIND_NATIVE_H
#include "GpuCodeBind.h"
STATIC struct hcb_result mCodeBind;
STATIC int CodeBindGuard(VOID *Cookie) {
 (VOID)Cookie;if(!mCodeReady || !mGxStart.gx_ready || !mGxStart.acked || !mGxStart.clear_confirmed || GxQualified(NULL))return 1;
 return (MmioRead32(0x3d7e340)&3) || MmioRead32(0x3d8ec40) || (MmioRead32(0x3d8ec30)&(1u<<23)) || MmioRead32(0x3d02020)!=0;
}
STATIC int CodeBindRead(VOID *Cookie,uint32_t Address,uint32_t *Value) {
 (VOID)Cookie;BOOLEAN Allowed=Address==0x3d02020;for(unsigned I=0;I<4;I++)if(Address==hcb_address(I))Allowed=TRUE;
 if(!Allowed || CodeBindGuard(NULL))return 1;*Value=MmioRead32(Address);__asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC int CodeBindWrite(VOID *Cookie,uint32_t Address,uint32_t Value) {
 (VOID)Cookie;BOOLEAN Allowed=FALSE;for(unsigned I=0;I<4;I++)if(Address==hcb_address(I) && Value==hcb_value(I))Allowed=TRUE;
 if(!Allowed || CodeBindGuard(NULL))return 1;MmioWrite32(Address,Value);__asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC unsigned RunCodeBind(VOID) {
 CONST struct hcb_io Io={NULL,CodeBindRead,CodeBindWrite,CodeBindGuard};return hcb_run(&Io,&mCodeBind);
}
STATIC VOID CodeBindReport(VOID) {
 Print(L"HOUJI GPU CP CODE BIND: code=%u phase=%u attempted=%x verified=%x retained=%u reads=%u writes=%u SQE-before=%x after=%x last=%x/%x op=%u observed-valid=%u; no SQE enable, CP/RAW/PAS/trust change\n",
 mCodeBind.code,mCodeBind.phase,mCodeBind.attempted,mCodeBind.verified,mCodeBind.retained,mCodeBind.reads,mCodeBind.writes,mCodeBind.control_before,mCodeBind.control_after,mCodeBind.last_address,mCodeBind.last_value,mCodeBind.last_operation,mCodeBind.observed_valid);
}
#endif
