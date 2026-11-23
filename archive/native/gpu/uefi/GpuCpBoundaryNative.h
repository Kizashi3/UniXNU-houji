/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Distinguish aperture/post-snapshot/ordinary HFI/reset from first CP execution.
 * No RAW is queued by this profile. GET_VALUE125 is the proven initial query.
 */
#ifndef HOUJI_GPU_CP_BOUNDARY_NATIVE_H
#define HOUJI_GPU_CP_BOUNDARY_NATIVE_H
STATIC struct hhb_result mCpBoundaryQuery;
STATIC struct hll_result mCpBoundaryLog;
STATIC UINT32 mCpFirmwareVersion[5];
STATIC int CpBoundaryGuard(VOID *Cookie) {
 (VOID)Cookie;return mCpInit.phase!=2 || !mCpInit.aperture_ok || mCpInit.raw_attempted ||
  mCpBoundaryQuery.code || mCpBoundaryQuery.completed!=1 || !mCpBoundaryQuery.record[0].ack ||
  mCpBoundaryQuery.record[0].value!=1 || !mCpBoundaryQuery.record[0].status_present ||
  mCpBoundaryQuery.record[0].status || mLiveLog.code || mLiveLog.phase!=5 || !mLiveLog.restored ||
  CpReady(NULL) || LiveLogGuard(NULL);
}
STATIC uint64_t CpBoundarySave(VOID *Cookie) {(VOID)Cookie;return ProbeCheckpoint("aperture-complete-HFI-alive-NO-RAW-boundary");}
STATIC unsigned RunCpBoundary(struct hhb_result *Bootstrap) {
 mCpInit=(struct hci_result){0};mCpInit.phase=1;
 if(CpReady(NULL))return mCpInit.code=HCI_GUARD;
 mCpInit.phase=2;mCpInit.aperture_attempted=1;
 if(CpAperture(NULL))return mCpInit.code=HCI_APERTURE;mCpInit.aperture_ok=1;
 if(CpReady(NULL))return mCpInit.code=HCI_GUARD;
 CONST struct hhb_io Hfi={NULL,CpHealth,StockBootstrapSend,StockBootstrapReceive,StockBootstrapDoorbell,ContextDelay,NULL};
 CONST uint32_t Query[]={125,0};mCpBoundaryQuery.next_sequence=Bootstrap->next_sequence;
 mCpBoundaryQuery.code=hhb_exchange(&Hfi,&mCpBoundaryQuery,0,12,Query,2,1,0);
 Bootstrap->next_sequence=mCpBoundaryQuery.next_sequence;
 CONST struct hhb_record *R=&mCpBoundaryQuery.record[0];
 Print(L"HOUJI GPU CP BOUNDARY: ordinary-query-code=%u sent=%u ACK=%u value=%x status=%x present=%u header=%x; RAW-attempted=%u\n",mCpBoundaryQuery.code,R->sent,R->ack,R->value,R->status,R->status_present,R->header,mCpInit.raw_attempted);
 if(mCpBoundaryQuery.code || R->value!=1)return mCpInit.code=HCI_EXCHANGE;
 // Vendor gen7_gmu_version_info: DTCM register start0x1c400 +0xff8..0xffc,
 // GPU MMIO base0x3d00000, word offsets. No inferred version register.
 for(unsigned I=0;I<5;I++) {
  if(!CpHealth(NULL))return mCpInit.code=HCI_GUARD;
  mCpFirmwareVersion[I]=MmioRead32(0x3d74fe0+I*4);
  Print(L"HOUJI GPU GMU VERSION: index=%u address=%x value=%08x; raw core/core-dev/power/power-dev/HFI\n",I,0x3d74fe0+I*4,mCpFirmwareVersion[I]);
 }
 CONST struct hll_io Log={NULL,LiveLogTpl,LiveLogLower,LiveLogRestore,CpBoundaryGuard,CpBoundarySave};
 unsigned Code=hll_run(&Log,&mCpBoundaryLog);
 Print(L"HOUJI GPU CP BOUNDARY RESULT: code=%u phase=%u restored=%u guards=%u no-RAW=1; ordinary HFI only, outer CM3 reset next\n",Code,mCpBoundaryLog.phase,mCpBoundaryLog.restored,mCpBoundaryLog.guards);
 if(Code)return mCpInit.code=HCI_IO;
 mCpInit.phase=7;return 0;
}
#endif
