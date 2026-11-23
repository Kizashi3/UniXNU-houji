/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef HOUJI_GPU_CP_INIT_NATIVE_H
#define HOUJI_GPU_CP_INIT_NATIVE_H
#include "GpuCpInit.h"
#include "GpuCpPoll.h"
STATIC struct hci_result mCpInit;
STATIC struct ggs_state mCpAperture;
STATIC unsigned mCpApertureCalled,mCpApertureResult,mCpApertureValid;
STATIC UINT64 mCpApertureElapsed;
STATIC BOOLEAN mCpPollArmed;
STATIC UINT64 mCpPollRoots[HCF_ROOTS];
STATIC struct hcf_result mCpPoll;
STATIC int CpLeaseOwned(VOID) {
 return mGen7Mapped && mCodeReady && !mGen7.code && mGen7.phase==6 && mGen7.record_ready &&
  mGxMapped && mGxStart.gx_ready && mGxStart.acked && mGxStart.clear_confirmed &&
  mFirmwareHeld && mStockCalled && mFirmwareMemory.retained==HFM_ALL &&
  mStockResult.fw_ready && mStockResult.hfi_ready && mStockResult.query_ack &&
  mScratchAssigned && mScratchReady && mScratchResult.attached && mDmaZeroRetained &&
  mSecureAssigned && mSecureDomainReady && mSecureTableOwned && mSecureContext.attached &&
  mSecureMemory.owned && mSecureMemory.revoked && mSecureMemory.result_valid &&
  !mSecureMemory.status_a0 && !mSecureMemory.status_a1 &&
  !mSecureCx.quarantined && mSecureCx.init_succeeded && !mCpAperture.quarantined;
}
STATIC int CpFastHealth(VOID) {
 if(!mCpPollArmed || !CpLeaseOwned())return 0;
 struct hcf_snapshot S={0};mCpPoll.calls++;unsigned Index=0,Reason=0;
 for(unsigned I=0;I<HCF_POWER_REGS;I++) {
  if(GpuTryRead32(hcf_reg(I),&S.regs[I])){Reason=6;Index=I;break;}S.valid_regs|=1u<<I;
 }
 __asm__ volatile("dsb sy":::"memory");if(!Reason)Reason=hcf_power(&S,&Index);
 if(!Reason) {
  for(unsigned I=HCF_POWER_REGS;I<HCF_REGS;I++) {
   if(GpuTryRead32(hcf_reg(I),&S.regs[I])){Reason=6;Index=I;break;}S.valid_regs|=1u<<I;
  }
  for(unsigned I=0;!Reason && I<HCF_ROOTS;I++) {
   if(GpuTryRead64(hcf_root(I),&S.roots[I])){Reason=6;Index=HCF_REGS+I;break;}S.valid_roots|=1u<<I;
  }
  __asm__ volatile("dsb sy":::"memory");if(!Reason)Reason=hcf_check(&S,mCpPollRoots,&Index);
 }
 mCpPoll.last=S;
 if(Reason && !mCpPoll.failed){mCpPoll.first_fault=S;mCpPoll.failed=1;mCpPoll.failed_index=Index;mCpPoll.reason=Reason;}
 return !Reason;
}
STATIC int CpHealth(VOID *Cookie) {
 (VOID)Cookie;if(!CpLeaseOwned())return 0;
 if(mCpPollArmed)return CpFastHealth();
 return GxQualified(NULL) || (MmioRead32(0x3d7e340)&3) || MmioRead32(0x3d8ec40)?0:1;
}
STATIC int CpReady(VOID *Cookie) {(VOID)Cookie;return !CpHealth(NULL) || Gen7Guard(NULL);}
STATIC int ArmCpPolling(VOID) {
 if(mCpPollArmed || CpReady(NULL) || ScratchAudit() || SecureDomainAudit())return 1;
 for(unsigned I=0;I<HCF_ROOTS;I++)if(GpuTryRead64(hcf_root(I),&mCpPollRoots[I]))return 1;
 mCpPollArmed=TRUE;UINT64 Begin=BatchCounter();
 for(unsigned I=0;I<16;I++)if(!CpFastHealth())return 1;
 UINT64 Fast=BatchMicroseconds(Begin);Begin=BatchCounter();if(Gen7Guard(NULL))return 1;
 Print(L"HOUJI GPU CP POLL LEASE: armed=1 fast16-us=%lu full-guard-us=%lu roots=%lx/%lx/%lx/%lx/%lx/%lx; all graph/table allocations pinned, no graph/FS operation during RAW; fresh roots/power/faults every poll\n",
 Fast,BatchMicroseconds(Begin),mCpPollRoots[0],mCpPollRoots[1],mCpPollRoots[2],mCpPollRoots[3],mCpPollRoots[4],mCpPollRoots[5]);return 0;
}
STATIC int CpApertureCall(VOID *Cookie,struct ggs_regs *R) {
 (VOID)Cookie;mCpApertureValid=0;if(!R || !CpHealth(NULL) || Gen7Guard(NULL) || R->x[1]!=4 || R->x[2]!=0xffff0000u ||
  R->x[3]!=0xffffffffu || R->x[4]!=0xffffffffu || R->x[5]!=0xffffffffu || R->x[7])return 1;
 if(!((R->x[0]==0x42000c1b && !R->x[6]) || (R->x[0]==1 && mCpAperture.last_output.x[0]==1 &&
   R->x[6]==mCpAperture.last_output.x[6])))return 1;
 mCpApertureCalled++;UINT64 Begin=BatchCounter();int Result=ggs_aarch64_call(NULL,R);
 mCpApertureElapsed+=BatchMicroseconds(Begin);mCpApertureValid=!Result;return Result;
}
STATIC int CpAperture(VOID *Cookie) {
 (VOID)Cookie;if(!(mSecureMemory.available&2) || CpReady(NULL))return 1;
 mCpAperture=mSecureCx; // Same verified epoch/convention/quarantine; independent counters.
 mCpAperture.calls=0;mCpAperture.busy_retries=0;mCpAperture.interrupt_resumes=0;
 CONST struct ggs_ops Io={NULL,CpApertureCall,SecureCxDelay,NULL};
 CONST struct ggs_regs Request={{0x42000c1b,4,0xffff0000u,0xffffffffu,0xffffffffu,0xffffffffu,0,0}};
 mCpApertureResult=ggs_exchange_frame(&Io,&mCpAperture,&Request);
 // qcom_scm_kgsl_set_smmu_aperture passes NULL result: only real transport a0
 // determines success. Preserve a1 raw; it is not an assigned ownership status.
 if(mCpApertureResult || !mCpApertureValid || CpReady(NULL))return 1;
 return CpPreRawCheckpoint();
}
STATIC int CpRead(VOID *Cookie,uint32_t Address,uint32_t *Value) {
 (VOID)Cookie;if(!Value || !(Address==0x3d8ec30 || Address==0x3d00840 || Address==0x3d02020 || Address==0x3d00804) || !CpHealth(NULL))return 1;
 return GpuTryRead32(Address,Value)?1:0;
}
STATIC inline unsigned RunCpInit(struct hhb_result *Bootstrap) {
 CONST struct hci_io Io={{NULL,CpHealth,StockBootstrapSend,StockBootstrapReceive,StockBootstrapDoorbell,ContextDelay,NULL},CpReady,CpAperture,CpRead};
 return hci_run(&Io,&mCpInit,&Bootstrap->next_sequence);
}
STATIC VOID CpInitReport(VOID) {
 CONST struct hhb_record *Raw=&mCpInit.raw.record[0];
 GpuReadFaultReport();
 GpuDoorbellFaultReport();
 CpSplitReport();
 Print(L"HOUJI GPU CP POLLED IRQ: code=%u GIC-mapped=%u GIC-group=%x enable=%x local-before=%x after=%x expected=%x; no GIC writes\n",mCpIrqPrepCode,mCpGicMapped,mCpGicGroup,mCpGicEnable,mCpIrqBefore,mCpIrqAfter,mCpIrqMask);
 Print(L"HOUJI GPU CP APERTURE: attempted=%u code=%u actual-calls=%u raw-valid=%u a0=%lx a1=%lx busy=%u resumed=%u elapsed-us=%lu; fixed bank0, no PAS/ZAP\n",
 mCpInit.aperture_attempted,mCpApertureResult,mCpApertureCalled,mCpApertureValid,mCpAperture.last_output.x[0],mCpAperture.last_output.x[1],mCpAperture.busy_retries,mCpAperture.interrupt_resumes,mCpApertureElapsed);
 Print(L"HOUJI GPU CP INIT: code=%u phase=%u aperture=%u RAW-attempted=%u exchange=%u sent=%u ack=%u words=%u value=%x status-present=%u status=%x idle=%u polls=%u RBBM=%x SQE=%x INT=%x last=%x/%x valid=%u; initialization only, no PAS/unsecure/fence/Metal\n",
 mCpInit.code,mCpInit.phase,mCpInit.aperture_ok,mCpInit.raw_attempted,mCpInit.raw.code,Raw->sent,Raw->ack,Raw->count,Raw->value,Raw->status_present,Raw->status,mCpInit.idle,mCpInit.polls,mCpInit.rbbm,mCpInit.sqe,mCpInit.interrupt_status,mCpInit.last_address,mCpInit.last_value,mCpInit.value_valid);
 for(unsigned I=0;I<Raw->count && I<HHB_WORDS;I++)Print(L"HOUJI GPU CP INIT REPLY: word=%u value=%08x\n",I,Raw->reply[I]);
 for(unsigned I=0;I<mCpInit.debug_count && I<8;I++)for(unsigned J=0;J<mCpInit.debug[I].count && J<HHB_WORDS;J++)Print(L"HOUJI GPU CP INIT DEBUG: message=%u word=%u value=%08x\n",I,J,mCpInit.debug[I].words[J]);
 if(mCodeReady)for(unsigned I=0;I<12;I++)Print(L"HOUJI GPU CP INIT RECORD RAW: word=%u value=%08x; non-atomic owned NormalNC sample\n",I,((volatile uint32_t *)((UINTN)mCodeMemory.cpu+HCC_RECORD_OFFSET))[I]);
 Print(L"HOUJI GPU CP POLL RESULT: armed=%u calls=%u failed=%u reason=%u index=%u; first failing snapshot retained, no fault clear\n",mCpPollArmed,mCpPoll.calls,mCpPoll.failed,mCpPoll.reason,mCpPoll.failed_index);
 for(unsigned I=0;I<HCF_REGS;I++)Print(L"HOUJI GPU CP POLL REG: i=%u address=%x first=%x last=%x valid=%x/%x\n",I,hcf_reg(I),mCpPoll.first_fault.regs[I],mCpPoll.last.regs[I],mCpPoll.first_fault.valid_regs,mCpPoll.last.valid_regs);
 for(unsigned I=0;I<HCF_ROOTS;I++)Print(L"HOUJI GPU CP POLL ROOT: i=%u address=%x expected=%lx first=%lx last=%lx valid=%x/%x\n",I,hcf_root(I),mCpPollRoots[I],mCpPoll.first_fault.roots[I],mCpPoll.last.roots[I],mCpPoll.first_fault.valid_roots,mCpPoll.last.valid_roots);
}
#endif
