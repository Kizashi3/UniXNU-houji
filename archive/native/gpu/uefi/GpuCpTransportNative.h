/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * First CP exchange diagnostic: after publishing the fixed RAW, poll pinned
 * Normal-NC HFI RAM only. No GPU/GIC/SMMU MMIO polling and no idle claim.
 * Full current hardware/graph guards precede publication. RAM ownership and
 * allocations remain pinned throughout; outer confirmed CM3 reset saves the
 * reply before any fault MMIO. Do not use this as normal GPU health policy.
 */
#ifndef HOUJI_GPU_CP_TRANSPORT_NATIVE_H
#define HOUJI_GPU_CP_TRANSPORT_NATIVE_H
STATIC struct {
 unsigned started,published,send_calls,send_code,doorbell_calls,doorbell_code;
 unsigned before_checks,ram_checks,receive_calls;
} mCpTransport;
STATIC int CpTransportHealthy(VOID *Cookie) {
 (VOID)Cookie;
 if(!mCpTransport.published){mCpTransport.before_checks++;return CpPolledHealthy(NULL);}
 mCpTransport.ram_checks++;
 return mCpTransport.started && CpLeaseOwned() && mCpPollArmed && !mCpPoll.failed &&
  mCpPreflightValid && !mCpPreflightLog.code && mCpPreflightLog.phase==5 &&
  mCpPreflightLog.restored && mCpIrqMask==HCI_GPU_ERROR_MASK && mCpGicMapped;
}
STATIC int CpTransportSend(VOID *Cookie,CONST uint32_t *Words,unsigned Count) {
 (VOID)Cookie;
 if(!mCpTransport.started || mCpTransport.published || mCpTransport.send_calls ||
  !Words || Count!=11 || Words[0]!=mCpInit.raw.record[0].header ||
  !CpTransportHealthy(NULL))return 1;
 for(unsigned I=0;I<10;I++)if(Words[I+1]!=hci_cp_word(I))return 1;
 mCpTransport.send_calls++;
 // Set conservatively before queue publication: even a failed send can have
 // partially modified the queue. No gated read is safe to assume afterwards.
 mCpTransport.published=1;
 mCpTransport.send_code=StockBootstrapSend(NULL,Words,Count);
 return mCpTransport.send_code;
}
STATIC int CpTransportDoorbell(VOID *Cookie) {
 (VOID)Cookie;
 if(!CpTransportHealthy(NULL) || !mCpTransport.published ||
  mCpTransport.send_calls!=1 || mCpTransport.send_code || mCpTransport.doorbell_calls)return 1;
#ifdef HOUJI_CP_SUPPRESS_DOORBELL
 // Isolation control: the queue is published, so spontaneous firmware polling
 // is still possible. Do not claim no execution. Return to the outer CM3
 // reset immediately; no doorbell, reply wait or filesystem operation here.
 return 1;
#else
 mCpTransport.doorbell_calls++;
 mCpTransport.doorbell_code=StockBootstrapDoorbell(NULL); // Same AO write, no reads.
#ifdef HOUJI_CP_STOP_AFTER_DOORBELL
 return 1; // Intentional stop after the real write returns; no reply wait.
#else
 return mCpTransport.doorbell_code;
#endif
#endif
}
STATIC int CpTransportReceive(VOID *Cookie,unsigned Queue,uint32_t *Words,unsigned *Count) {
 (VOID)Cookie;if(!mCpTransport.published || !CpTransportHealthy(NULL))return GGH_INVALID;
 mCpTransport.receive_calls++;return StockBootstrapReceive(NULL,Queue,Words,Count);
}
STATIC inline unsigned RunCpTransport(struct hhb_result *Bootstrap) {
 if(!Bootstrap || Bootstrap->next_sequence<2 || Bootstrap->next_sequence>4093 ||
  mCpTransport.started || !mCpPreflightValid ||
  mCpPreflightLog.code || mCpPreflightLog.phase!=5 || !mCpPreflightLog.restored ||
  CpPreflightGuard(NULL) || CpReuseAperture(NULL))return HCI_GUARD;
 mCpTransport.started=1;
 mCpInit=(struct hci_result){.phase=3,.aperture_attempted=1,.aperture_ok=1,.raw_attempted=1};
 mCpInit.raw.next_sequence=Bootstrap->next_sequence;
 uint32_t Payload[10];for(unsigned I=0;I<10;I++)Payload[I]=hci_cp_word(I);
 CONST struct hci_io Io={{NULL,CpTransportHealthy,CpTransportSend,CpTransportReceive,
  CpTransportDoorbell,ContextDelay,NULL},CpPolledReady,CpReuseAperture,CpRead};
 mCpInit.raw.code=hci_exchange(&Io,&mCpInit,Payload);
 Bootstrap->next_sequence=mCpInit.raw.next_sequence;
 mCpInit.code=mCpInit.raw.code?HCI_EXCHANGE:HCI_OK;
#ifdef HOUJI_CP_SUPPRESS_DOORBELL
 Print(L"HOUJI GPU CP DOORBELL CONTROL: suppressed=1 published=%u sent-code=%u actual-doorbell-writes=%u; no reply wait; spontaneous GMU consumption not excluded; outer reset now\n",
  mCpTransport.published,mCpTransport.send_code,mCpTransport.doorbell_calls);
#endif
#ifdef HOUJI_CP_STOP_AFTER_DOORBELL
 Print(L"HOUJI GPU CP DOORBELL RETURN CONTROL: actual-writes=%u write-code=%u published=%u; intentional stop after real AO write returned, no reply wait, outer reset now\n",
  mCpTransport.doorbell_calls,mCpTransport.doorbell_code,mCpTransport.published);
#endif
 Print(L"HOUJI GPU CP TRANSPORT: code=%u RAW-code=%u published=%u send=%u/%u doorbell=%u/%u pre-checks=%u RAM-checks=%u receives=%u ACK=%u debug=%u; no post-publish GPU/GIC/SMMU reads; idle NOT checked; outer reset next\n",
  mCpInit.code,mCpInit.raw.code,mCpTransport.published,mCpTransport.send_calls,
  mCpTransport.send_code,mCpTransport.doorbell_calls,mCpTransport.doorbell_code,
  mCpTransport.before_checks,mCpTransport.ram_checks,mCpTransport.receive_calls,
  mCpInit.raw.record[0].ack,mCpInit.debug_count);
 return mCpInit.code;
}
#endif
