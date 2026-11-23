/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef HOUJI_GPU_CODE_PREPARE_H
#define HOUJI_GPU_CODE_PREPARE_H
#include "GpuCodeMemory.h"
STATIC struct hfm_allocation mCodeMemory;
STATIC BOOLEAN mCodeReady;
STATIC int CodeReadFile(EFI_FILE_PROTOCOL *Root,CONST CHAR16 *Name,UINTN Expected,VOID **Data) {
 EFI_FILE_PROTOCOL *File=NULL;EFI_STATUS Status=Root->Open(Root,&File,(CHAR16 *)Name,EFI_FILE_MODE_READ,0);if(EFI_ERROR(Status))return 1;
 Status=gBS->AllocatePool(EfiBootServicesData,Expected,Data);if(!EFI_ERROR(Status)) {
  UINTN Bytes=Expected;Status=File->Read(File,&Bytes,*Data);if(!EFI_ERROR(Status) && Bytes!=Expected)Status=EFI_BAD_BUFFER_SIZE;
  if(!EFI_ERROR(Status)){UINT8 Extra;UINTN Bytes=1;Status=File->Read(File,&Bytes,&Extra);if(!EFI_ERROR(Status) && Bytes)Status=EFI_BAD_BUFFER_SIZE;}
 }
 EFI_STATUS Close=File->Close(File);if(EFI_ERROR(Close))Status=Close;return EFI_ERROR(Status)?1:0;
}
STATIC int PrepareCodeMemory(EFI_HANDLE ImageHandle) {
 EFI_LOADED_IMAGE_PROTOCOL *Loaded=NULL;EFI_SIMPLE_FILE_SYSTEM_PROTOCOL *Fs=NULL;EFI_FILE_PROTOCOL *Root=NULL;
 VOID *Sqe=NULL,*Aqe=NULL;int Code=1;EFI_STATUS Status=gBS->HandleProtocol(ImageHandle,&gEfiLoadedImageProtocolGuid,(VOID **)&Loaded);
 if(EFI_ERROR(Status) || !Loaded || !Loaded->DeviceHandle)return 1;
 Status=gBS->HandleProtocol(Loaded->DeviceHandle,&gEfiSimpleFileSystemProtocolGuid,(VOID **)&Fs);if(EFI_ERROR(Status) || !Fs)return 1;
 Status=Fs->OpenVolume(Fs,&Root);if(EFI_ERROR(Status) || !Root)return 1;
 if(CodeReadFile(Root,L"\\Payloads\\gen70900_sqe.fw",HCC_SQE_BYTES,&Sqe) ||
  CodeReadFile(Root,L"\\Payloads\\gen70900_aqe.fw",HCC_AQE_BYTES,&Aqe))goto Done;
 if(hcc_firmware(Sqe,HCC_SQE_BYTES,0) || hcc_firmware(Aqe,HCC_AQE_BYTES,1))goto Done;
 mCodeMemory=(struct hfm_allocation){.pages=HCC_PAGES,.nc=1,.iova=HCC_IOVA};
 if(FirmwareAllocate(NULL,HCC_PAGES,&mCodeMemory.physical,&mCodeMemory.cpu) ||
  FirmwareValidate(NULL,mCodeMemory.physical,mCodeMemory.cpu,HCC_PAGES,1))goto Done;
 for(unsigned I=0;I<=mFirmwareMemory.count;I++) {
  CONST struct hfm_allocation *M=&mFirmwareMemory.memory[I];
  if(mCodeMemory.physical<M->physical+(UINT64)M->pages*4096 && M->physical<mCodeMemory.physical+HCC_BYTES)goto Done;
 }
 if((mCodeMemory.physical<mScratchTablePhysical+HSC_GPU_TABLE_PAGES*4096 && mScratchTablePhysical<mCodeMemory.physical+HCC_BYTES) ||
  (mCodeMemory.physical<mGpuOnlyMemory.physical+HSC_POOL_BYTES && mGpuOnlyMemory.physical<mCodeMemory.physical+HCC_BYTES))goto Done;
 if(hcc_copy(mCodeMemory.cpu,HCC_BYTES,Sqe,HCC_SQE_BYTES,Aqe,HCC_AQE_BYTES) || FirmwarePublish(NULL,&mCodeMemory))goto Done;
 Code=0;
Done:
 if(Root){EFI_STATUS Close=Root->Close(Root);if(EFI_ERROR(Close))Code=1;}
 if(Sqe)gBS->FreePool(Sqe);if(Aqe)gBS->FreePool(Aqe);mCodeReady=Code==0;
 Print(L"HOUJI GPU CP CODE MEMORY: code=%d ready=%u PA=%lx pages=%u SQE=%x/%u AQE=%x/%u record=%x/4096; original files CRC checked, payload skip4/readback, code RO-executable GPU-only; not started\n",
  Code,mCodeReady,mCodeMemory.physical,mCodeMemory.pages,HCC_IOVA+HCC_SQE_OFFSET,HCC_SQE_BYTES-4,HCC_IOVA+HCC_AQE_OFFSET,HCC_AQE_BYTES-4,HCC_IOVA+HCC_RECORD_OFFSET);
 return Code;
}
#endif
