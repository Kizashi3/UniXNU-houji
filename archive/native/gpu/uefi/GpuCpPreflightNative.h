/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Exercise the actual hci_run ready/aperture/health/packet path in RAM first.
 * The capture send callback never publishes a queue, rings a doorbell or sends
 * another SCM call. Preserve the real sequence. Fail closed unless execution
 * stopped at exactly that send callback with the fixed vendor wire image.
 */
#ifndef HOUJI_GPU_CP_PREFLIGHT_NATIVE_H
#define HOUJI_GPU_CP_PREFLIGHT_NATIVE_H
STATIC struct hci_result mCpPreflight;
STATIC struct hll_result mCpPreflightLog;
STATIC unsigned mCpPreflightCalls,mCpPreflightValid;
STATIC uint32_t mCpPreflightWords[11];
STATIC int CpPreflightSend(VOID *Cookie,CONST uint32_t *Words,unsigned Count) {
 (VOID)Cookie;mCpPreflightCalls++;
 if(mCpPreflightCalls!=1 || !Words || Count!=11 || !CpPolledHealthy(NULL))return 1;
 for(unsigned I=0;I<11;I++)mCpPreflightWords[I]=Words[I];
 return 1; // Intentional rejection before ANY HFI queue/doorbell operation.
}
STATIC int CpPreflightGuard(VOID *Cookie) {
 (VOID)Cookie;return !mCpPreflightValid || CpIrqLogGuard(NULL);
}
STATIC uint64_t CpPreflightSave(VOID *Cookie) {
 (VOID)Cookie;if(CpNotifySnapshot())return UINT64_C(0x8000000000000015);
 return ProbeCheckpoint("CP-pre-send-guards-and-packet-PASS-before-real-RAW");
}
STATIC unsigned RunCpPreflight(struct hhb_result *Bootstrap) {
 if(!Bootstrap || mCpPreflightCalls || CpIrqLogGuard(NULL) ||
  mCpIrqLog.code || mCpIrqLog.phase!=5 || !mCpIrqLog.restored)return HCI_GUARD;
 unsigned Original=Bootstrap->next_sequence,Local=Original;
 CONST struct hci_io Io={{NULL,CpPolledHealthy,CpPreflightSend,StockBootstrapReceive,
  StockBootstrapDoorbell,ContextDelay,NULL},CpPolledReady,CpReuseAperture,CpRead};
 unsigned Code=hci_run(&Io,&mCpPreflight,&Local);
 CONST uint32_t Expected[11]={(Original<<20)|(11u<<8)|131u,
  hci_packet(0x17,1),1u<<27,hci_packet(0x48,7),0x94b,3,0x20000000,2,
  HCC_IOVA+HCC_RECORD_OFFSET,0,1u<<31};
 if(Code!=HCI_EXCHANGE || mCpPreflight.phase!=3 || mCpPreflightCalls!=1 ||
  !mCpPreflight.aperture_ok || !mCpPreflight.raw_attempted ||
  mCpPreflight.raw.code!=HHB_IO || !mCpPreflight.raw.record[0].attempted ||
  mCpPreflight.raw.record[0].sent || mCpPreflight.raw.record[0].ack ||
  mCpPreflight.raw.completed || mCpPreflight.debug_count ||
  Local!=Original+1 || Bootstrap->next_sequence!=Original)return HCI_GUARD;
 for(unsigned I=0;I<11;I++)if(mCpPreflightWords[I]!=Expected[I])return HCI_GUARD;
 mCpPreflightValid=1;
 Print(L"HOUJI GPU CP PREFLIGHT: valid=1 stopped-at-send=1 actual-hci-path=1 phase=%u expected-rejection=%u/%u real-sequence=%u unchanged=1 queue-published=0 doorbell=0 extra-SCM=0\n",
  mCpPreflight.phase,Code,mCpPreflight.raw.code,Original);
 for(unsigned I=0;I<11;I++)Print(L"HOUJI GPU CP PREFLIGHT WORD: i=%u value=%08x\n",I,mCpPreflightWords[I]);
 CONST struct hll_io Log={NULL,LiveLogTpl,LiveLogLower,LiveLogRestore,CpPreflightGuard,CpPreflightSave};
 return hll_run(&Log,&mCpPreflightLog)?HCI_IO:0;
}
#endif
