/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * No-RAW control after ALL r105 preflight log guards have returned. Repeat an
 * already proven ordinary property query with the local HWSCHED mask retained,
 * then let the same outer confirmed-reset path save results. No extra live FS.
 */
#ifndef HOUJI_GPU_CP_POLLED_EXIT_NATIVE_H
#define HOUJI_GPU_CP_POLLED_EXIT_NATIVE_H
STATIC struct hhb_result mCpExitQuery;
STATIC unsigned RunCpPolledExit(struct hhb_result *Bootstrap) {
 if(!Bootstrap || Bootstrap->next_sequence<2 || Bootstrap->next_sequence>4093 ||
  !mCpPreflightValid || mCpPreflightLog.code || mCpPreflightLog.phase!=5 ||
  !mCpPreflightLog.restored || mCpInit.phase!=2 || mCpInit.raw_attempted ||
  mCpTransport.started || mCpTransport.published || CpPreflightGuard(NULL))return HCI_GUARD;
 Print(L"HOUJI GPU CP NO-RAW EXIT: preflight snapshot returned, guards=3 TPL restored; ordinary query next; RAW never published\n");
 CONST struct hhb_io Io={NULL,CpPolledHealthy,StockBootstrapSend,StockBootstrapReceive,
  StockBootstrapDoorbell,ContextDelay,NULL};
 CONST uint32_t Query[]={125,0};mCpExitQuery.next_sequence=Bootstrap->next_sequence;
 mCpExitQuery.code=hhb_exchange(&Io,&mCpExitQuery,0,12,Query,2,1,0);
 Bootstrap->next_sequence=mCpExitQuery.next_sequence;
 CONST struct hhb_record *R=&mCpExitQuery.record[0];
 Print(L"HOUJI GPU CP NO-RAW EXIT: query-code=%u sent=%u ACK=%u value=%x status=%x present=%u header=%x phase=%u RAW-attempted=%u; outer confirmed reset next\n",
  mCpExitQuery.code,R->sent,R->ack,R->value,R->status,R->status_present,R->header,mCpPreflightLog.phase,mCpInit.raw_attempted);
 if(mCpExitQuery.code || !R->ack || R->value!=1 || !R->status_present || R->status)return HCI_EXCHANGE;
 mCpInit.phase=8;return HCI_OK;
}
#endif
