/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef HOUJI_GPU_GX_START_NATIVE_H
#define HOUJI_GPU_GX_START_NATIVE_H
#include "GpuGxStart.h"
#include "GpuHostProfile.h"
STATIC struct hgx_result mGxStart;
STATIC BOOLEAN mGxMapped;
STATIC int PrepareGxMapping(VOID) {
 CONST UINT64 Addresses[]={0x3d00840,0x3d0084c,0x3d02020};UINT64 SavedPar,Par=0;BOOLEAN Good=TRUE;
 EFI_TPL Tpl=gBS->RaiseTPL(TPL_HIGH_LEVEL);__asm__ volatile("mrs %0,par_el1":"=r"(SavedPar));
 for(unsigned I=0;I<3;I++) {
  __asm__ volatile("at s1e1r,%1; isb; mrs %0,par_el1":"=r"(Par):"r"(Addresses[I]):"memory");
  if((Par&1) || (Par&0x0000fffffffff000ULL)!=(Addresses[I]&~4095ULL) || ((Par>>56)!=0 && (Par>>56)!=4))Good=FALSE;
 }
 __asm__ volatile("msr par_el1,%0; isb"::"r"(SavedPar):"memory");gBS->RestoreTPL(Tpl);
 mGxMapped=Good;Print(L"HOUJI GPU GX MAP: CPU identity Device=%u last-PAR=%lx; AT only, no GX register read\n",Good,Par);return Good?0:1;
}
STATIC int GxQualified(VOID *Cookie) {
 if(mHostProfileReady)return HostContextQualified();
 (VOID)Cookie;if(!mGxMapped || !mSecureContext.attached || ScratchGuard(NULL) || SecureDomainGuard(NULL))return 1;
 return ((MmioRead32(0x3dc0058)|MmioRead32(0x3dc3058))&0xc00001feu)?1:0;
}
STATIC int GxRead(VOID *Cookie,uint32_t Address,uint32_t *Value) {
 (VOID)Cookie;BOOLEAN Gx=Address==0x3d00840 || Address==0x3d0084c || Address==0x3d02020;
 BOOLEAN Always=Address==0x3d7e340 || Address==0x3d7e648 || Address==0x3d7e658 || Address==0x3d8ec40 || Address==0x3d8ec30;
 if(!mGxMapped || (!Gx && !Always) || !StockBootstrapHealthy(NULL))return 1;
 if(Gx && mHostProfileReady && HostContextQualified())return 1;
 // Recheck GX power/clock and AHB access immediately before EACH gated read.
 if(Gx && (!mGxStart.gx_ready || !mGxStart.acked || !mGxStart.clear_confirmed ||
  (MmioRead32(0x3d7e340)&3) || MmioRead32(0x3d8ec40) || (MmioRead32(0x3d8ec30)&(1u<<23)) ||
  ((MmioRead32(0x3dc0058)|(mHostProfileReady?0:MmioRead32(0x3dc3058)))&0xc00001feu)))return 1;
 *Value=MmioRead32(Address);__asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC int GxWrite(VOID *Cookie,uint32_t Address,uint32_t Value) {
 (VOID)Cookie;if(!mGxMapped || !StockBootstrapHealthy(NULL) ||
  !((Address==0x3d7e650 && Value==HGX_SET && mGxStart.requested && !mGxStart.acked) ||
    (Address==0x3d7e644 && Value==HGX_ACK && mGxStart.acked && mGxStart.clear_attempted)))return 1;
 MmioWrite32(Address,Value);__asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC unsigned RunGxStart(struct hhb_result *Bootstrap) {
 if(!Bootstrap || Bootstrap->code || Bootstrap->completed!=(mHostProfileReady?HHP_STEPS:HHB_STEPS))return HGX_GUARD;
 CONST struct hgx_io Io={{NULL,StockBootstrapHealthy,StockBootstrapSend,StockBootstrapReceive,StockBootstrapDoorbell,ContextDelay,NULL},GxRead,GxWrite,GxQualified};
 return hgx_run(&Io,&Bootstrap->next_sequence,&mGxStart);
}
STATIC VOID GxStartReport(VOID) {
 CONST struct hhb_record *Vote=&mGxStart.vote.record[0];
 Print(L"HOUJI GPU GX START: code=%u phase=%u qualified=%u requested=%u ack=%u clear=%u/%u ready=%u retained=%u reads=%u writes=%u polls=%u last=%x/%x observed-valid=%u; no CP/PM4/PAS, OOB lease retained until cold reset\n",
 mGxStart.code,mGxStart.phase,mGxStart.qualified,mGxStart.requested,mGxStart.acked,mGxStart.clear_attempted,mGxStart.clear_confirmed,mGxStart.gx_ready,mGxStart.retained,mGxStart.reads,mGxStart.writes,mGxStart.polls,mGxStart.last_address,mGxStart.last_value,mGxStart.observed_valid);
 Print(L"HOUJI GPU GX VALUES: valid=%x before=%x after=%x IRQ-before=%x host-before=%x IRQ-ack=%x IRQ-after=%x fence=%x busy=%x RBBM=%x RBBM3=%x SQE-control=%x; raw fields require valid bits\n",
 mGxStart.valid,mGxStart.gx_before,mGxStart.gx_after,mGxStart.irq_before,mGxStart.host_before,mGxStart.irq_ack,mGxStart.irq_after,mGxStart.fence,mGxStart.busy,mGxStart.rbbm,mGxStart.rbbm3,mGxStart.sqe);
 Print(L"HOUJI GPU GX VOTE: code=%u header=%x sent=%u ack=%u value=%x status=%x status-present=%u words=%u polls=%u; fixed ack_type1 frequency-index1 BW-index1, configured target only\n",
 mGxStart.vote.code,Vote->header,Vote->sent,Vote->ack,Vote->value,Vote->status,Vote->status_present,Vote->count,Vote->polls);
 for(unsigned I=0;I<Vote->count && I<16;I++)Print(L"HOUJI GPU GX VOTE REPLY: word=%u value=%08x\n",I,Vote->reply[I]);
}
#endif
