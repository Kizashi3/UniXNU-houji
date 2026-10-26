/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef GIULIA_GPU_GUNYAH_HANDOFF_H
#define GIULIA_GPU_GUNYAH_HANDOFF_H
#define GGR_FIRMWARE_TYPES 1
#include "GpuGunyahReport.h"
#include "GpuPowerAdt.h"

static int ggr_gpu_enabled(const CHAR8 *line,UINTN capacity)
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
        if(++found!=1 || end-start!=sizeof(key)+1 || line[start+sizeof(key)-1]!='=' ||
           line[start+sizeof(key)]<'1' || line[start+sizeof(key)]>'3')return 0;
      }
    }
  }
  return at<capacity && found==1;
}

static EFI_STATUS GiuliaGpuGunyahHandoff(void *tree,UINTN bytes,const CHAR8 *line,UINTN capacity)
{
  typedef struct {
    UINT64 Version;
    EFI_STATUS (EFIAPI *Capture)(struct ggr_report *,UINTN);
  } GPU_GUNYAH_PROTOCOL;
  EFI_GUID guid=GGR_PROTOCOL_GUID;
  GPU_GUNYAH_PROTOCOL *protocol=NULL;
  struct ggr_report report;
  EFI_STATUS status;
  UINTN offset=0;
  if(!ggr_gpu_enabled(line,capacity))return EFI_NOT_STARTED;
  if(gpa_adt_find_named(tree,bytes,sizeof(report),"giulia-gpu-gunyah",&offset)!=GPA_ADT_PRESENT)
    return EFI_COMPROMISED_DATA;
  CopyMem(&report,(UINT8 *)tree+offset,sizeof(report));
  if(!ggr_report_requested(&report)) {
    status=EFI_COMPROMISED_DATA;
  } else {
    status=gBS->LocateProtocol(&guid,NULL,(VOID **)&protocol);
    if(!EFI_ERROR(status)) {
      if(!protocol || protocol->Version!=GGR_PROTOCOL_VERSION || !protocol->Capture)
        status=EFI_UNSUPPORTED;
      else status=protocol->Capture(&report,sizeof(report));
    }
    if(!EFI_ERROR(status) && !ggr_report_valid(&report))status=EFI_COMPROMISED_DATA;
  }
  /* Failure removes even a stale CRC-valid previous result from this slot.
   * No bootargs, cached DTS or loader constant can substitute capabilities. */
  if(EFI_ERROR(status))ZeroMem(&report,sizeof(report));
  CopyMem((UINT8 *)tree+offset,&report,sizeof(report));
  DEBUG((DEBUG_INFO,"GIULIA GUNYAH: boot FDT report status=%r captured=%u irq_lease=0 hypervisor_verified=0\n",
    status,!EFI_ERROR(status)));
  return status;
}
#endif
