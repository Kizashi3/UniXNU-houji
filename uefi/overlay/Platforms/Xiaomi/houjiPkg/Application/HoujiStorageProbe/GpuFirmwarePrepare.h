/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * EFI adapter for inactive firmware preparation. Reads only this application's
 * RAMdisk; no physical phone filesystem is opened. Never publishes TTBRs.
 */
#ifndef HOUJI_GPU_FIRMWARE_PREPARE_H
#define HOUJI_GPU_FIRMWARE_PREPARE_H
#include <Protocol/LoadedImage.h>
#include <Protocol/SimpleFileSystem.h>
#include "GpuFirmwareMemory.h"
STATIC struct hfm_result mFirmwareMemory;
STATIC VOID *mFirmwareImage;
STATIC BOOLEAN mFirmwareHeld;
STATIC struct {UINT64 Pa,Bytes,Original;BOOLEAN Changed;} mFirmwareAttributes[HFM_MAX+3];
STATIC unsigned mFirmwareAttributeCount;
STATIC UINT64 BatchCounter(VOID) {UINT64 T;__asm__ volatile("mrs %0,cntpct_el0":"=r"(T));return T;}
STATIC UINT64 BatchMicroseconds(UINT64 Before) {
  UINT64 F;__asm__ volatile("mrs %0,cntfrq_el0":"=r"(F));
  return F?(BatchCounter()-Before)*1000000/F:MAX_UINT64;
}
STATIC int FirmwareAllocate(VOID *Cookie,unsigned Pages,uint64_t *Physical,VOID **Cpu) {
  (VOID)Cookie;EFI_PHYSICAL_ADDRESS Address=0xfffffffffULL;
  if(!Pages || Pages>HSC_LARGE_PAGES || mFirmwareAttributeCount>=sizeof(mFirmwareAttributes)/sizeof(mFirmwareAttributes[0]))return 1;
  if(EFI_ERROR(gBS->AllocatePages(AllocateMaxAddress,EfiBootServicesData,Pages,&Address)))return 1;
  mFirmwareAttributes[mFirmwareAttributeCount].Pa=Address;
  mFirmwareAttributes[mFirmwareAttributeCount++].Bytes=(UINT64)Pages*4096;
  *Physical=Address;*Cpu=(VOID *)(UINTN)Address;return 0;
}
STATIC int FirmwareVerifyPagesCore(uint64_t Physical,VOID *Cpu,unsigned Pages,unsigned Nc,unsigned ReportSuccess) {
  UINT64 Length=(UINT64)Pages*4096,El,Par=0,SavedPar;EFI_GCD_MEMORY_SPACE_DESCRIPTOR Desc;
  if(!Pages || Pages>HSC_LARGE_PAGES || Physical!=(UINTN)Cpu || (Physical&4095) || Nc>1)return 1;
  EFI_STATUS Status=gDS->GetMemorySpaceDescriptor(Physical,&Desc);
  if(EFI_ERROR(Status) || Desc.GcdMemoryType!=EfiGcdMemoryTypeSystemMemory ||
    Physical<Desc.BaseAddress || Length>Desc.Length || Physical-Desc.BaseAddress>Desc.Length-Length ||
    (Desc.Attributes&(EFI_MEMORY_UC|EFI_MEMORY_WC|EFI_MEMORY_WT|EFI_MEMORY_WB))!=(Nc?EFI_MEMORY_WC:EFI_MEMORY_WB))return 1;
  __asm__ volatile("mrs %0,CurrentEL":"=r"(El));if(El!=4)return 1;
  EFI_TPL Tpl=gBS->RaiseTPL(TPL_HIGH_LEVEL);__asm__ volatile("mrs %0,par_el1":"=r"(SavedPar));
  BOOLEAN Good=TRUE;
  for(UINT64 Offset=0;Good && Offset<Length;Offset+=4096) {
    UINT64 Address=Physical+Offset;
    for(unsigned Write=0;Write<2;Write++) {
      if(Write)__asm__ volatile("at s1e1w,%1\n\tisb\n\tmrs %0,par_el1":"=r"(Par):"r"(Address):"memory");
      else __asm__ volatile("at s1e1r,%1\n\tisb\n\tmrs %0,par_el1":"=r"(Par):"r"(Address):"memory");
      if((Par&1) || (Par&0x0000fffffffff000ULL)!=Address || (Par>>56)!=(Nc?0x44u:0xffu) ||
        (!Nc && ((Par>>7)&3)!=3))Good=FALSE;
    }
  }
  __asm__ volatile("msr par_el1,%0\n\tisb"::"r"(SavedPar):"memory");gBS->RestoreTPL(Tpl);
  if(ReportSuccess || !Good)Print(L"HOUJI GPU FW RAM: PA=%lx pages=%u Normal-NC=%u identity-RW-attributes=%u last-PAR=%lx\n",
    Physical,Pages,Nc,Good,Par);return Good?0:1;
}
STATIC int FirmwareVerifyPages(uint64_t Physical,VOID *Cpu,unsigned Pages,unsigned Nc) {
  return FirmwareVerifyPagesCore(Physical,Cpu,Pages,Nc,1);
}
// The original allocation qualification remains verbose. Repeated owner
// checks execute identical GCD/AT validation, retaining failure output while
// avoiding thousands of duplicate success lines in the fixed log slot.
STATIC int FirmwareVerifyPagesQuiet(uint64_t Physical,VOID *Cpu,unsigned Pages,unsigned Nc) {
  return FirmwareVerifyPagesCore(Physical,Cpu,Pages,Nc,0);
}
STATIC int FirmwareValidate(VOID *Cookie,uint64_t Physical,VOID *Cpu,unsigned Pages,unsigned Nc) {
  (VOID)Cookie;EFI_GCD_MEMORY_SPACE_DESCRIPTOR Desc;
  UINT64 Length=(UINT64)Pages*4096;unsigned Slot;
  if(Physical!=(UINTN)Cpu || (Physical&4095) || !Pages || Pages>HSC_LARGE_PAGES || Nc>1)return 1;
  for(Slot=0;Slot<mFirmwareAttributeCount;Slot++)if(mFirmwareAttributes[Slot].Pa==Physical &&
    mFirmwareAttributes[Slot].Bytes==Length)break;
  if(Slot==mFirmwareAttributeCount)return 1;
  EFI_STATUS Status=gDS->GetMemorySpaceDescriptor(Physical,&Desc);
  if(EFI_ERROR(Status) || Desc.GcdMemoryType!=EfiGcdMemoryTypeSystemMemory ||
    Physical<Desc.BaseAddress || Length>Desc.Length || Physical-Desc.BaseAddress>Desc.Length-Length ||
    (Desc.Attributes&(EFI_MEMORY_UC|EFI_MEMORY_WC|EFI_MEMORY_WT|EFI_MEMORY_WB))!=EFI_MEMORY_WB)return 1;
  mFirmwareAttributes[Slot].Original=Desc.Attributes;
  if(Nc) {
    // In the pinned ArmMmuLib WC encodes NORMAL NC; UC encodes DEVICE.
    // Record the attempt first: an error may have partially changed pages.
    mFirmwareAttributes[Slot].Changed=TRUE;
    Status=gDS->SetMemorySpaceAttributes(Physical,Length,
      (Desc.Attributes&~(EFI_MEMORY_UC|EFI_MEMORY_WC|EFI_MEMORY_WT|EFI_MEMORY_WB))|EFI_MEMORY_WC);
    Print(L"HOUJI GPU FW RAM: set Normal-NC PA=%lx bytes=%lx status=%r original=%lx caps=%lx\n",
      Physical,Length,Status,Desc.Attributes,Desc.Capabilities);
    if(EFI_ERROR(Status))return 1;
  }
  return FirmwareVerifyPages(Physical,Cpu,Pages,Nc);
}

STATIC int FirmwarePublish(VOID *Cookie,CONST struct hfm_allocation *Memory) {
  (VOID)Cookie;UINT64 Ctr;__asm__ volatile("mrs %0,ctr_el0":"=r"(Ctr));
  unsigned Line=4u<<((Ctr>>16)&15);if(Line<16 || Line>4096)return 1;
  if(!Memory->nc)for(UINTN Offset=0;Offset<(UINTN)Memory->pages*4096;Offset+=Line)
    __asm__ volatile("dc cvac,%0"::"r"((UINTN)Memory->cpu+Offset):"memory");
  __asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC int FirmwareRelease(VOID *Cookie,uint64_t Physical,VOID *Cpu,unsigned Pages) {
  (VOID)Cookie;if(Physical!=(UINTN)Cpu)return 1;
  for(unsigned I=0;I<mFirmwareAttributeCount;I++)if(mFirmwareAttributes[I].Pa==Physical &&
    mFirmwareAttributes[I].Bytes==(UINT64)Pages*4096) {
    if(mFirmwareAttributes[I].Changed && EFI_ERROR(gDS->SetMemorySpaceAttributes(Physical,
      mFirmwareAttributes[I].Bytes,mFirmwareAttributes[I].Original)))return 1;
    mFirmwareAttributes[I].Changed=FALSE;
    return EFI_ERROR(gBS->FreePages(Physical,Pages))?1:0;
  }
  return 1;
}
STATIC int FirmwareLogWalk(UINT32 Iova) {
  UINT64 Table=mFirmwareMemory.built.root_physical,Descriptor=0;
  for(unsigned Level=mFirmwareMemory.built.start_level;Level<=3;Level++) {
    unsigned Shift=39-9*Level;
    UINT64 At=Table+8*((Iova>>Shift)&(Level==1?3u:511u));
    if(hfm_descriptor(&mFirmwareMemory,At,&Descriptor))return 1;
    Print(L"HOUJI GPU FW WALK: IOVA=%08x level=%u descriptor-PA=%lx raw=%lx AP=%u PXN=%u UXN=%u\n",
      Iova,Level,At,Descriptor,(UINT32)((Descriptor>>6)&3),(UINT32)((Descriptor>>53)&1),(UINT32)((Descriptor>>54)&1));
    if((Descriptor&3)!=3)return 1;
    Table=Descriptor&0x0000fffffffff000ULL;
  }
  return 0;
}
STATIC unsigned PrepareFirmwareBatch(EFI_HANDLE ImageHandle,BOOLEAN Retain) {
  EFI_LOADED_IMAGE_PROTOCOL *Loaded=NULL;EFI_SIMPLE_FILE_SYSTEM_PROTOCOL *Fs=NULL;
  EFI_FILE_PROTOCOL *Root=NULL,*File=NULL;VOID *Firmware=NULL;EFI_STATUS Status;
  UINT64 Begin=BatchCounter();UINT32 Crc=0;UINTN Bytes=HFM_FW_BYTES;unsigned Code=HFM_ARGUMENT;
  Print(L"HOUJI GPU BATCH: BEGIN firmware-memory; inactive tables, 17 HFI queues, no stock execution\n");
  Status=ProbeCheckpoint("before-firmware-memory-batch");if(EFI_ERROR(Status))return HFM_PLAN;
  Status=gBS->HandleProtocol(ImageHandle,&gEfiLoadedImageProtocolGuid,(VOID **)&Loaded);
  if(EFI_ERROR(Status) || !Loaded || !Loaded->DeviceHandle)goto Done;
  Status=gBS->HandleProtocol(Loaded->DeviceHandle,&gEfiSimpleFileSystemProtocolGuid,(VOID **)&Fs);
  if(EFI_ERROR(Status) || !Fs)goto Done;
  Status=Fs->OpenVolume(Fs,&Root);if(EFI_ERROR(Status) || !Root)goto Done;
  Status=Root->Open(Root,&File,L"\\Payloads\\gmu_gen70900.bin",EFI_FILE_MODE_READ,0);
  if(EFI_ERROR(Status) || !File)goto Done;
  Status=gBS->AllocatePool(EfiBootServicesData,Bytes,&Firmware);if(EFI_ERROR(Status))goto Done;
  Status=File->Read(File,&Bytes,Firmware);if(EFI_ERROR(Status) || Bytes!=HFM_FW_BYTES)goto Done;
  UINT8 Extra=0;UINTN ExtraBytes=1;Status=File->Read(File,&ExtraBytes,&Extra);
  if(EFI_ERROR(Status) || ExtraBytes)goto Done;
  Status=gBS->CalculateCrc32(Firmware,Bytes,&Crc);
  if(EFI_ERROR(Status) || Crc!=0x5d67ec17u)goto Done;
  CONST struct hfm_io Io={NULL,FirmwareAllocate,FirmwareValidate,FirmwarePublish,FirmwareRelease};
  Code=hfm_prepare(&Io,Firmware,Bytes,&mFirmwareMemory);
  Print(L"HOUJI GPU FW PLAN: result=%u records=%u reservations=%u allocations=%u allocated=%x validated=%x RAM-payload=%u TCM-deferred=%u HFI-queues=%u HFI-init=%u published=%u build=%u audit=%u tables=%u leaves=%u descriptors=%u\n",
    Code,mFirmwareMemory.records,mFirmwareMemory.reservations,mFirmwareMemory.count,
    mFirmwareMemory.allocated,mFirmwareMemory.validated,mFirmwareMemory.bytes_loaded,
    mFirmwareMemory.tcm_bytes_deferred,mFirmwareMemory.hfi_queues,mFirmwareMemory.hfi_initialized,
    mFirmwareMemory.published,mFirmwareMemory.build_status,mFirmwareMemory.audit_status,
    (UINT32)mFirmwareMemory.built.table_pages,(UINT32)mFirmwareMemory.built.leaf_pages,
    (UINT32)mFirmwareMemory.audit.descriptor_reads);
  for(unsigned I=0;I<mFirmwareMemory.count;I++) {
    Print(L"HOUJI GPU FW ALLOCATION: IOVA=%08x PA=%lx pages=%u Normal-NC=%u permissions=%x device-WB=%u shareability=%u; not yet installed\n",
      mFirmwareMemory.memory[I].iova,mFirmwareMemory.memory[I].physical,mFirmwareMemory.memory[I].pages,mFirmwareMemory.memory[I].nc,
      mFirmwareMemory.ranges[I].permissions,mFirmwareMemory.ranges[I].writeback,mFirmwareMemory.ranges[I].shareability);
    if(!Code && FirmwareLogWalk(mFirmwareMemory.memory[I].iova))Code=HFM_TABLES;
  }
  if(!Retain || Code)Code=hfm_release(&Io,&mFirmwareMemory);
  else {mFirmwareImage=Firmware;mFirmwareHeld=TRUE;Firmware=NULL;}
Done:
  if(File){EFI_STATUS S=File->Close(File);if(EFI_ERROR(S) && !Code)Code=HFM_RELEASE;}
  if(Root){EFI_STATUS S=Root->Close(Root);if(EFI_ERROR(S) && !Code)Code=HFM_RELEASE;}
  if(Firmware)gBS->FreePool(Firmware);
  Print(L"HOUJI GPU BATCH: END firmware-memory result=%u file-status=%r bytes=%u crc=%08x released=%x retained=%x elapsed-us=%lu; stock executed=0 retain-for-next-stage=%u\n",
    Code,Status,(UINT32)Bytes,Crc,mFirmwareMemory.released,mFirmwareMemory.retained,BatchMicroseconds(Begin),mFirmwareHeld);
  if(EFI_ERROR(ProbeCheckpoint("after-firmware-memory-batch")) && !Code)Code=HFM_PLAN;
  return Code;
}
#endif
