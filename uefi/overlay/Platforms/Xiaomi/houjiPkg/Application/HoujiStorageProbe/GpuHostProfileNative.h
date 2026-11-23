/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef HOUJI_GPU_HOST_PROFILE_NATIVE_H
#define HOUJI_GPU_HOST_PROFILE_NATIVE_H
#include "GpuHostProfile.h"
STATIC unsigned RunHostProfile(struct hhb_result *Result,VOID *Cookie) {
 mHostProfileReady=0;
 CONST struct hhb_io Io={Cookie,StockBootstrapHealthy,StockBootstrapSend,StockBootstrapReceive,
  StockBootstrapDoorbell,ContextDelay,NULL};
 Print(L"HOUJI GPU HOST PROFILE: begin PERF4/BW3/CORE14/START10/QUERY12; no HWSCHED/AQE enable, no RAW or GPU MMIO; same retained17queue transport\n");
 unsigned Code=hhp_run(&Io,Result);
 Print(L"HOUJI GPU HOST PROFILE: result=%u stage=%u completed=%u resources=%u handled=%u next-sequence=%u; ordinary HFI only, no CP execution/mode-selection proof\n",
  Code,Result->stage,Result->completed,Result->resource_count,Result->resource_acks,Result->next_sequence);
 for(unsigned I=0;I<HHP_STEPS;I++) {
  CONST struct hhb_record *R=&Result->record[I];
  Print(L"HOUJI GPU HOST PROFILE STEP: i=%u header=%08x sent=%u ACK=%u value=%08x status=%08x present=%u words=%u polls=%u\n",
   I,R->header,R->sent,R->ack,R->value,R->status,R->status_present,R->count,R->polls);
  for(unsigned J=0;J<R->count && J<HHB_WORDS;J++)Print(L"HOUJI GPU HOST PROFILE REPLY: i=%u word=%u value=%08x\n",I,J,R->reply[J]);
 }
 if(!Code && (Result->completed!=HHP_STEPS || Result->resource_count ||
  !Result->record[4].ack || Result->record[4].value!=1 || !Result->record[4].status_present ||
  Result->record[4].status))Code=HHB_REJECTED;
 mHostProfileReady=!Code;
 return Code;
}
#endif
