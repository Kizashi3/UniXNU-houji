/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Diagnostic split of the SAME two vendor PM4 packets: THREAD_CONTROL then
 * ME_INIT. Not a vendor-framed coldboot equivalence claim. Only after real
 * prefix ACK, idle, zero IRQ/RBBM and complete retained-graph snapshot can
 * ME_INIT follow in the same boot. No new opcode, NOP, PAS or secure exit.
 */
#ifndef HOUJI_GPU_CP_SPLIT_NATIVE_H
#define HOUJI_GPU_CP_SPLIT_NATIVE_H
STATIC struct {
 unsigned mode,published,sends[2],bells[2],bell_codes[2],result;
 struct hci_result prefix;
 struct hll_result checkpoint;
} mCpSplit;
STATIC int CpSplitHealthy(VOID *Cookie) {
 (VOID)Cookie;
 if(!mCpSplit.published)return CpPolledHealthy(NULL);
 return CpLeaseOwned() && mCpPollArmed && !mCpPoll.failed &&
  mCpPreflightValid && !mCpPreflightLog.code && mCpPreflightLog.phase==5 &&
  mCpPreflightLog.restored && mCpIrqMask==HCI_GPU_ERROR_MASK && mCpGicMapped;
}
STATIC int CpSplitSend(VOID *Cookie,CONST uint32_t *Words,unsigned Count) {
 (VOID)Cookie;unsigned Mode=mCpSplit.mode,Body=Mode==1?2:8;
 if((Mode!=1 && Mode!=2) || !Words || Count!=Body+1 || mCpSplit.sends[Mode-1] ||
  Words[0]!=mCpInit.raw.record[0].header || !CpSplitHealthy(NULL))return 1;
 for(unsigned I=0;I<Body;I++)if(Words[I+1]!=hci_cp_word(I+(Mode==2?2:0)))return 1;
 mCpSplit.published=1;mCpSplit.sends[Mode-1]++;
 return StockBootstrapSend(NULL,Words,Count);
}
STATIC int CpSplitDoorbell(VOID *Cookie) {
 (VOID)Cookie;unsigned Mode=mCpSplit.mode;
 if((Mode!=1 && Mode!=2) || mCpSplit.sends[Mode-1]!=1 || mCpSplit.bells[Mode-1] ||
  !mCpSplit.published || !CpSplitHealthy(NULL))return 1;
 mCpSplit.bells[Mode-1]++;mCpSplit.bell_codes[Mode-1]=StockBootstrapDoorbell(NULL);
 return mCpSplit.bell_codes[Mode-1];
}
STATIC int CpSplitReceive(VOID *Cookie,unsigned Queue,uint32_t *Words,unsigned *Count) {
 (VOID)Cookie;if(!mCpSplit.published || !CpSplitHealthy(NULL))return GGH_INVALID;
 return StockBootstrapReceive(NULL,Queue,Words,Count);
}
STATIC unsigned CpSplitIdle(VOID) {
 if(!mCpInit.raw.record[0].ack || mCpInit.raw.code || !mCpInit.raw.completed)return HCI_GUARD;
 mCpInit.phase=4;
 for(unsigned I=0;I<20000;I++) {
  mCpInit.polls++;
  if(!CpPolledHealthy(NULL) || GpuTryRead32(0x3d8ec30,&mCpInit.busy))return HCI_IO;
  if(!(mCpInit.busy&(1u<<23))){mCpInit.idle=1;break;}
  if(ContextDelay(NULL,10))return HCI_IO;
 }
 if(!mCpInit.idle)return HCI_TIMEOUT;
 uint32_t *Values[]={&mCpInit.rbbm,&mCpInit.sqe,&mCpInit.interrupt_status};
 CONST uint32_t Addresses[]={0x3d00840,0x3d02020,0x3d00804};
 for(unsigned I=0;I<3;I++)if(!CpPolledHealthy(NULL) || GpuTryRead32(Addresses[I],Values[I]))return HCI_IO;
 mCpInit.phase=5;return 0;
}
STATIC int CpSplitPrefixGuard(VOID *Cookie) {
 (VOID)Cookie;CONST struct hci_result *R=&mCpSplit.prefix;
 if(mCpSplit.mode!=1 || mCpSplit.sends[0]!=1 || mCpSplit.bells[0]!=1 || mCpSplit.bell_codes[0] ||
  R->code || R->phase!=5 || !R->idle || R->rbbm || R->interrupt_status ||
  R->raw.code || !R->raw.completed || !R->raw.record[0].ack ||
  mGen7.code || mGen7.phase!=6 || !mGen7.record_ready || !mCodeReady ||
  !CpPolledHealthy(NULL) || ScratchAudit() || SecureDomainGuard(NULL))return 1;
 uint32_t Value;
 CONST uint32_t Addresses[]={0x3d8ec30,0x3d00840,0x3d00804,0x3d02020};
 for(unsigned I=0;I<4;I++) {
  if(!CpPolledHealthy(NULL) || GpuTryRead32(Addresses[I],&Value))return 1;
  if(I==0?(Value&(1u<<23)):(I==3?Value!=R->sqe:Value!=0))return 1;
 }
 struct ggh_io Hfi={mFirmwareMemory.memory[5].cpu,GGH_BYTES,GGH_IOVA,NULL,StockHfiBarrier};
 for(unsigned I=0;I<GGH_QUEUES;I++) {
  volatile uint32_t *Header,*Ring;unsigned Read,Write;
  if(ggh_queue(&Hfi,I,&Header,&Ring,&Read,&Write) || Read!=Write)return 1;
 }
 for(unsigned I=0;I<=mFirmwareMemory.count;I++) {
  CONST struct hfm_allocation *M=&mFirmwareMemory.memory[I];
  if(FirmwareVerifyPages(M->physical,M->cpu,M->pages,M->nc))return 1;
 }
 return FirmwareVerifyPages(mCodeMemory.physical,mCodeMemory.cpu,HCC_PAGES,1) ||
  FirmwareVerifyPages(mGpuOnlyMemory.physical,mGpuOnlyMemory.cpu,HSC_POOL_PAGES,1) ||
  FirmwareVerifyPages(mScratchTablePhysical,mScratchTables,HSC_GPU_TABLE_PAGES,0);
}
STATIC uint64_t CpSplitPrefixSave(VOID *Cookie) {
 (VOID)Cookie;return ProbeCheckpoint("THREAD-CONTROL-ACK-idle-before-ME-INIT");
}
STATIC VOID CpSplitReport(VOID) {
 CONST struct hci_result *R=&mCpSplit.prefix;
 Print(L"HOUJI GPU CP SPLIT: mode=%u result=%u prefix-code=%u phase=%u ACK=%u idle=%u RBBM=%x SQE=%x IRQ=%x prefix-send=%u bell=%u/%u ME-send=%u bell=%u/%u checkpoint=%u/%u restored=%u; same vendor2+8 PM4 words, no PAS/fence/Metal\n",
  mCpSplit.mode,mCpSplit.result,R->code,R->phase,R->raw.record[0].ack,R->idle,R->rbbm,R->sqe,
  R->interrupt_status,mCpSplit.sends[0],mCpSplit.bells[0],mCpSplit.bell_codes[0],
  mCpSplit.sends[1],mCpSplit.bells[1],mCpSplit.bell_codes[1],mCpSplit.checkpoint.code,
  mCpSplit.checkpoint.phase,mCpSplit.checkpoint.restored);
 for(unsigned I=0;I<R->raw.record[0].count && I<HHB_WORDS;I++)Print(L"HOUJI GPU CP PREFIX REPLY: i=%u value=%08x\n",I,R->raw.record[0].reply[I]);
 for(unsigned I=0;I<R->debug_count && I<8;I++)for(unsigned J=0;J<R->debug[I].count && J<HHB_WORDS;J++)Print(L"HOUJI GPU CP PREFIX DEBUG: message=%u i=%u value=%08x\n",I,J,R->debug[I].words[J]);
}
STATIC unsigned CpSplitPacket(struct hhb_result *Bootstrap,unsigned Mode) {
 mCpSplit.mode=Mode;mCpInit=(struct hci_result){.phase=3,.aperture_attempted=1,.aperture_ok=1,.raw_attempted=1};
 mCpInit.raw.next_sequence=Bootstrap->next_sequence;
 unsigned Count=Mode==1?2:8;uint32_t Words[10];for(unsigned I=0;I<Count;I++)Words[I]=hci_cp_word(I+(Mode==2?2:0));
 CONST struct hci_io Io={{NULL,CpSplitHealthy,CpSplitSend,CpSplitReceive,CpSplitDoorbell,ContextDelay,NULL},CpPolledReady,CpReuseAperture,CpRead};
 mCpInit.raw.code=hci_exchange_words(&Io,&mCpInit,Words,Count);Bootstrap->next_sequence=mCpInit.raw.next_sequence;
 mCpInit.code=mCpInit.raw.code?HCI_EXCHANGE:CpSplitIdle();return mCpInit.code;
}
STATIC unsigned RunCpSplit(struct hhb_result *Bootstrap) {
 if(!Bootstrap || Bootstrap->next_sequence<2 || Bootstrap->next_sequence>4091 || mCpSplit.mode ||
  !mCpPreflightValid || mCpPreflightLog.code || mCpPreflightLog.phase!=5 || !mCpPreflightLog.restored ||
  CpPreflightGuard(NULL) || CpReuseAperture(NULL))return HCI_GUARD;
 unsigned Code=CpSplitPacket(Bootstrap,1);mCpSplit.prefix=mCpInit;
 mCpSplit.result=Code;CpSplitReport();if(Code)return Code;
 CONST struct hll_io Log={NULL,LiveLogTpl,LiveLogLower,LiveLogRestore,CpSplitPrefixGuard,CpSplitPrefixSave};
 if(hll_run(&Log,&mCpSplit.checkpoint))return mCpSplit.result=HCI_GUARD;
 Code=CpSplitPacket(Bootstrap,2);mCpSplit.result=Code;
 if(!Code)mCpInit.phase=6;CpSplitReport();return Code;
}
#endif
