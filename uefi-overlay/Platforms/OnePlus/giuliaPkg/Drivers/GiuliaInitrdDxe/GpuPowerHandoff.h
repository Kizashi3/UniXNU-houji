/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef GIULIA_GPU_POWER_HANDOFF_H
#define GIULIA_GPU_POWER_HANDOFF_H
#define GPP_FIRMWARE_TYPES 1
#include "GpuPowerReport.h"
#include "GpuPowerAdt.h"

/* Match one complete token. Duplicate settings and an unterminated or
 * non-printable command line never authorize a firmware transaction. */
static int gpa_gpu_mode3(const CHAR8 *line,UINTN capacity)
{
  UINTN at=0,start,end,i;unsigned found=0;
  const char key[]="giulia_gpu";
  if(!line || !capacity)return 0;
  while(at<capacity && line[at]) {
    if((UINT8)line[at]<32 || (UINT8)line[at]>126)return 0;
    if(line[at]==' '){++at;continue;}
    start=at;
    while(at<capacity && line[at] && line[at]!=' ') {
      if((UINT8)line[at]<32 || (UINT8)line[at]>126)return 0;
      ++at;
    }
    end=at;
    if(end-start>=sizeof(key)-1) {
      for(i=0;i<sizeof(key)-1 && line[start+i]==key[i];++i) {}
      if(i==sizeof(key)-1 && (end-start==sizeof(key)-1 || line[start+sizeof(key)-1]=='=')) {
        if(++found!=1 || end-start!=sizeof(key)+1 || line[start+sizeof(key)-1]!='=' || line[start+sizeof(key)]!='3')return 0;
      }
    }
  }
  return at<capacity && found==1;
}

static void gpa_loader_failure(struct gpp_report *report,EFI_STATUS native,unsigned operation)
{
  report->code=GPP_ERR_PROTOCOL;report->phase=GPP_PHASE_LOADER;
  report->operation=operation;report->failure_phase=GPP_PHASE_LOADER;
  report->failure_operation=operation;
  if(!report->firmware_status)report->firmware_status=(GPP_U64)native;
  report->last_firmware_status=(GPP_U64)native;
  report->flags&=~(GPP_U32)GPP_READY;
}

static EFI_STATUS GiuliaGpuPowerDiagnostic(void *tree,UINTN bytes,const CHAR8 *line,UINTN capacity)
{
  typedef struct {
    UINT64 Version;
    EFI_STATUS (EFIAPI *Prepare)(struct gpp_report *,UINTN);
  } GPU_POWER_PROTOCOL;
  EFI_GUID guid=GPP_PROTOCOL_GUID;
  GPU_POWER_PROTOCOL *protocol=NULL;
  struct gpp_report report;
  EFI_STATUS status;
  UINTN offset=0;
  int found;
  if(!gpa_gpu_mode3(line,capacity))return EFI_NOT_STARTED;
  found=gpa_adt_find(tree,bytes,sizeof(report),&offset);
  if(found!=GPA_ADT_PRESENT) {
    DEBUG((DEBUG_ERROR,"GIULIA GPU POWER: loader refused ADT result=%d; no GPU provider called\n",found));
    return found==GPA_ADT_ABSENT?EFI_NOT_FOUND:EFI_COMPROMISED_DATA;
  }
  /* ADT payloads are four-byte aligned; never dereference one as an eight-byte
   * aligned report. The provider receives a local bounded structure only. */
  CopyMem(&report,(UINT8 *)tree+offset,sizeof(report));
  if(!gpp_report_requested(&report)) {
    DEBUG((DEBUG_ERROR,"GIULIA GPU POWER: loader refused non-pristine request; no GPU provider called\n"));
    /* A stale CRC-valid READY result must not survive as this boot's result. */
    status=EFI_COMPROMISED_DATA;gpp_report_init(&report);
    gpa_loader_failure(&report,status,GPP_OP_VALIDATE);
    goto SealReport;
  }
  status=gBS->LocateProtocol(&guid,NULL,(VOID **)&protocol);
  if(EFI_ERROR(status) || !protocol || protocol->Version!=GPP_PROTOCOL_VERSION || !protocol->Prepare) {
    if(!EFI_ERROR(status))status=EFI_UNSUPPORTED;
    gpa_loader_failure(&report,status,GPP_OP_RESOLVE);
  } else {
    status=protocol->Prepare(&report,sizeof(report));
    if(!gpp_report_valid(&report) || gpp_report_requested(&report) || report.phase==GPP_PHASE_NONE) {
      /* Invalid results cannot carry trusted ownership or readiness facts. */
      gpp_report_init(&report);
      report.flags|=GPP_PROTOCOL_UNCERTAIN;report.retained=1;
      gpa_loader_failure(&report,EFI_COMPROMISED_DATA,GPP_OP_VALIDATE);
    } else if(EFI_ERROR(status) && report.code==GPP_OK) {
      report.flags|=GPP_PROTOCOL_UNCERTAIN;if(report.attempted)report.retained=1;
      gpa_loader_failure(&report,status,GPP_OP_VALIDATE);
    }
  }
SealReport:
  report.protocol_status=(GPP_U64)status;
  gpp_report_seal(&report);
  if(!gpp_report_valid(&report)) {
    DEBUG((DEBUG_ERROR,"GIULIA GPU POWER: loader could not seal diagnostic report; no ADT write\n"));
    return EFI_COMPROMISED_DATA;
  }
  CopyMem((UINT8 *)tree+offset,&report,sizeof(report));
  DEBUG((DEBUG_ERROR,"GIULIA GPU POWER: loader prepare=%r code=%u phase=%u attempted=%x confirmed=%x retained=%x; fixed ADT report written\n",
    status,report.code,report.phase,report.attempted,report.confirmed,report.retained));
  return status;
}
#endif
