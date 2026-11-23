/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * EFI binding for the bounded ordinary shared-data arena. Included
 * after stock HFI callbacks. Actual table walks precede every activation/ACK.
 */
#ifndef HOUJI_GPU_SCRATCH_NATIVE_H
#define HOUJI_GPU_SCRATCH_NATIVE_H
#include "GpuScratchContext.h"
STATIC EFI_PHYSICAL_ADDRESS mScratchTablePhysical;
STATIC UINT64 *mScratchTables;
STATIC ArmSmmu4KConfig mScratchConfig;
STATIC ArmSmmu4KResult mScratchBuilt;
STATIC ArmSmmu4KRange mScratchRanges[HSC_GPU_RANGES];
STATIC struct hsc_result mScratchResult;
STATIC struct hfm_allocation mGpuOnlyMemory;
STATIC UINT32 mGpuOnlyNext[HSC_CLASSES]={0,HSC_CLASS_BYTES,2*HSC_CLASS_BYTES,3*HSC_CLASS_BYTES};
STATIC BOOLEAN mScratchReady,mScratchAssigned;
STATIC UINT32 mSharedNext[HSC_CLASSES]={0,HSC_CLASS_BYTES,2*HSC_CLASS_BYTES,3*HSC_CLASS_BYTES},mSharedCount;
STATIC UINT32 mGmuOnlyNext,mLargeNext;
STATIC struct {UINT32 Kind,Handle,Offset,Bytes,LogicalBytes,Arena;} mSharedAllocations[HSC_MAX_RESOURCES];
// Code loader shares the separate lifetime ledger, not the GMU graph.
#include "GpuCodePrepare.h"
STATIC int ScratchDescriptor(VOID *Cookie,uint64_t Pa,uint64_t *Value) {
 (VOID)Cookie;if(!mScratchTables || Pa<mScratchTablePhysical || (Pa&7) || Pa-mScratchTablePhysical>=HSC_GPU_TABLE_PAGES*4096)return 1;
 *Value=((volatile UINT64 *)mScratchTables)[(Pa-mScratchTablePhysical)/8];return 0;
}
STATIC int ScratchAudit(VOID) {
 if(!mScratchReady || !mFirmwareHeld || mFirmwareMemory.count!=HFM_MAX ||
    mFirmwareMemory.retained!=HFM_ALL || mFirmwareMemory.memory[8].physical!=mScratchRanges[0].physical ||
    mFirmwareMemory.memory[8].iova!=HFM_SCRATCH_IOVA || mFirmwareMemory.memory[8].pages!=HSC_POOL_PAGES ||
    !mFirmwareMemory.memory[8].nc || mFirmwareMemory.memory[10].physical!=mScratchRanges[HSC_CLASSES].physical ||
    mFirmwareMemory.memory[10].iova!=HSC_LARGE_IOVA || mFirmwareMemory.memory[10].pages!=HSC_LARGE_PAGES ||
    !mFirmwareMemory.memory[10].nc || mGpuOnlyMemory.physical!=mScratchRanges[HSC_CLASSES+1].physical ||
    mGpuOnlyMemory.pages!=HSC_POOL_PAGES || !mGpuOnlyMemory.nc || mGpuOnlyMemory.iova!=HSC_GPU_ONLY_IOVA || !mCodeReady || mCodeMemory.pages!=HCC_PAGES || !mCodeMemory.nc ||
    mScratchRanges[HSC_DATA_RANGES].physical!=mCodeMemory.physical+HCC_SQE_OFFSET)return 1;
 for(unsigned I=0;I<mFirmwareMemory.count;I++)if(mFirmwareMemory.ranges[I].physical<mGpuOnlyMemory.physical+HSC_POOL_BYTES &&
  mGpuOnlyMemory.physical<mFirmwareMemory.ranges[I].physical+mFirmwareMemory.ranges[I].bytes)return 1;
 unsigned char Seen[HFM_TABLE_PAGES]={0};ArmSmmu4KTableAuditResult Result;
 ArmSmmu4KTableIo Io={NULL,ScratchDescriptor};
 ArmSmmu4KAuditRegion Region={mScratchRanges,HSC_GPU_RANGES,HSC_GPU_TABLE_PAGES,HSC_GPU_TABLE_PAGES*512,Seen,sizeof(Seen)};
 if(ArmSmmu4KAuditTables(&Io,&mScratchConfig,&mScratchBuilt,&Region,mScratchTablePhysical,&Result) || !Result.complete)return 1;
 ZeroMem(Seen,sizeof(Seen));Io=(ArmSmmu4KTableIo){&mFirmwareMemory,hfm_descriptor};
 Region=(ArmSmmu4KAuditRegion){mFirmwareMemory.ranges,mFirmwareMemory.count,HFM_TABLE_PAGES,HFM_TABLE_PAGES*512,Seen,sizeof(Seen)};
 return ArmSmmu4KAuditTables(&Io,&mFirmwareMemory.config,&mFirmwareMemory.built,&Region,
  mFirmwareMemory.built.root_physical,&Result) || !Result.complete;
}
STATIC int PrepareScratchMemory(EFI_HANDLE ImageHandle) {
 if(!mFirmwareHeld || mFirmwareMemory.count!=HFM_MAX || mFirmwareMemory.retained!=HFM_ALL)return 1;
 mScratchTablePhysical=0xffffffff;
 EFI_STATUS Status=gBS->AllocatePages(AllocateMaxAddress,EfiBootServicesData,HSC_GPU_TABLE_PAGES,&mScratchTablePhysical);
 if(EFI_ERROR(Status))return 1;mScratchTables=(VOID *)(UINTN)mScratchTablePhysical;
 if(FirmwareVerifyPages(mScratchTablePhysical,mScratchTables,HSC_GPU_TABLE_PAGES,0))return 1;
 for(unsigned I=0;I<=mFirmwareMemory.count;I++) {
  CONST struct hfm_allocation *M=&mFirmwareMemory.memory[I];UINT64 Length=(UINT64)M->pages*4096;
  if(mScratchTablePhysical<M->physical+Length && M->physical<mScratchTablePhysical+HSC_GPU_TABLE_PAGES*4096)return 1;
 }
 mGpuOnlyMemory=(struct hfm_allocation){.pages=HSC_POOL_PAGES,.nc=1,.iova=HSC_GPU_ONLY_IOVA};
 if(FirmwareAllocate(NULL,HSC_POOL_PAGES,&mGpuOnlyMemory.physical,&mGpuOnlyMemory.cpu) ||
  FirmwareValidate(NULL,mGpuOnlyMemory.physical,mGpuOnlyMemory.cpu,HSC_POOL_PAGES,1))return 1;
 for(unsigned I=0;I<=mFirmwareMemory.count;I++) {
  CONST struct hfm_allocation *M=&mFirmwareMemory.memory[I];
  if(mGpuOnlyMemory.physical<M->physical+(UINT64)M->pages*4096 && M->physical<mGpuOnlyMemory.physical+HSC_POOL_BYTES)return 1;
 }
 if(mGpuOnlyMemory.physical<mScratchTablePhysical+HSC_GPU_TABLE_PAGES*4096 && mScratchTablePhysical<mGpuOnlyMemory.physical+HSC_POOL_BYTES)return 1;
 ZeroMem(mGpuOnlyMemory.cpu,HSC_POOL_BYTES);if(FirmwarePublish(NULL,&mGpuOnlyMemory))return 1;
 if(PrepareCodeMemory(ImageHandle))return 1;
 if(hsc_pool_ranges(mFirmwareMemory.memory[8].physical,mScratchRanges) ||
  hsc_large_range(mFirmwareMemory.memory[10].physical,&mScratchRanges[HSC_CLASSES]) ||
  hsc_gpu_only_ranges(mGpuOnlyMemory.physical,&mScratchRanges[HSC_CLASSES+1]) ||
  hcc_ranges(mCodeMemory.physical,&mScratchRanges[HSC_DATA_RANGES]))return 1;
 mScratchConfig=(ArmSmmu4KConfig){32,36,mScratchTablePhysical,HSC_GPU_LEAF_PAGES};ZeroMem(mScratchTables,HSC_GPU_TABLE_PAGES*4096);
 if(ArmSmmu4KBuild(&mScratchConfig,mScratchRanges,HSC_GPU_RANGES,mScratchTables,HSC_GPU_TABLE_PAGES,&mScratchBuilt))return 1;
 struct hfm_allocation Tables={mScratchTablePhysical,mScratchTables,HSC_GPU_TABLE_PAGES,0,0};
 if(FirmwarePublish(NULL,&Tables))return 1;mScratchReady=TRUE;
 if(ScratchAudit())return 1;
 Print(L"HOUJI GPU SCRATCH MEMORY: ready=1 IOVA=%08x PA=%lx GPU-root=%lx tables=%u leaves=%u; bank0 inactive, same GMU/CPU arena, retained until reset\n",
  HFM_SCRATCH_IOVA,mScratchRanges[0].physical,mScratchTablePhysical,(UINT32)mScratchBuilt.table_pages,(UINT32)mScratchBuilt.leaf_pages);
 for(unsigned I=0;I<=HSC_CLASSES;I++)Print(L"HOUJI GPU SHARED CLASS: class=%u IOVA=%lx PA=%lx bytes=%lu GFX-permissions=%x GMU-permissions=B\n",
  I,mScratchRanges[I].iova,mScratchRanges[I].physical,mScratchRanges[I].bytes,mScratchRanges[I].permissions);
 for(unsigned I=0;I<HSC_CLASSES;I++)Print(L"HOUJI GPU GPU-ONLY CLASS: class=%u IOVA=%lx PA=%lx bytes=%lu permissions=%x GMU-alias=0\n",I,mScratchRanges[HSC_CLASSES+1+I].iova,mScratchRanges[HSC_CLASSES+1+I].physical,mScratchRanges[HSC_CLASSES+1+I].bytes,mScratchRanges[HSC_CLASSES+1+I].permissions);
 return 0;
}
STATIC int ScratchRead32(VOID *Cookie,uint32_t Address,uint32_t *Value) {
 (VOID)Cookie;BOOLEAN Allowed=(Address==0x3da0020 || Address==0x3da0024 || Address==0x3da0028 || Address==0x3da0048) ||
  (Address>=0x3da0800 && Address<0x3da0860 && !(Address&3)) ||
  (Address>=0x3da0c00 && Address<0x3da0c60 && !(Address&3)) ||
  (Address>=0x3dc0000 && Address<=0x3dd5000 && !((Address-0x3dc0000)&4095));
 for(unsigned I=0;I<9;I++)if(I!=5 && I!=6 && Address==hsc_address(I))Allowed=TRUE;
 if(Address==0x3dc0004 || Address==0x3dc0058 || Address==0x3dc07f4)Allowed=TRUE;
 if(!mScratchAssigned || !Allowed || !StockBootstrapHealthy(NULL))return 1;
 *Value=MmioRead32(Address);__asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC int ScratchRead64(VOID *Cookie,uint32_t Address,uint64_t *Value) {
 (VOID)Cookie;if(!mScratchAssigned || (Address!=0x3dc0020 && Address!=0x3dc0028) || !StockBootstrapHealthy(NULL))return 1;
 *Value=MmioRead64(Address);__asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC int ScratchExpected(ArmSmmu4KContextImage *Image) {
 ArmSmmu4KContextConfig Config={&mScratchConfig,NULL,&mScratchBuilt,NULL,0x4c017e18,0x5511,0x751,0,0,0};
 return ArmSmmu4KEncodeContext(&Config,Image);
}
STATIC int ScratchWrite32(VOID *Cookie,uint32_t Address,uint32_t Value) {
 (VOID)Cookie;if(!mScratchAssigned || !mScratchReady || !StockBootstrapHealthy(NULL))return 1;
 ArmSmmu4KContextImage Image;if(ScratchExpected(&Image))return 1;
 BOOLEAN Allowed=(Address==0x3dc0000 && (Value==0 || Value==0x1027)) ||
  (Address==0x3dc0004 && Value==0x32b) || (Address==0x3dc0618 && Value==0) ||
  (Address==0x3dc07f0 && Value==0xffffffffu) || (Address==0x3da0c04 && Value==0) ||
  (Address==0x3da0804 && Value==0x80000000u);
 if(mScratchResult.phase==4 && mScratchResult.lpac==1 && mScratchResult.enabled &&
  mScratchResult.sid0_attached && !mScratchResult.attached &&
  ((Address==0x3da0c08 && Value==0) || (Address==0x3da0808 && Value==0x80000001u)))Allowed=TRUE;
 CONST UINT32 Fields[]={0,Image.cba2r,Image.cbar,Image.tcr2,Image.tcr,0,0,Image.mair0,Image.mair1};
 for(unsigned I=1;I<9;I++)if(I!=5 && I!=6 && Address==hsc_address(I) && Value==Fields[I])Allowed=TRUE;
 if(!Allowed)return 1;MmioWrite32(Address,Value);__asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC int ScratchWrite64(VOID *Cookie,uint32_t Address,uint64_t Value) {
 (VOID)Cookie;if(!mScratchAssigned || !mScratchReady || !StockBootstrapHealthy(NULL))return 1;
 ArmSmmu4KContextImage Image;if(ScratchExpected(&Image) ||
  !((Address==0x3dc0020 && Value==Image.ttbr0) || (Address==0x3dc0028 && Value==Image.ttbr1)))return 1;
 MmioWrite64(Address,Value);__asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC int ScratchGuard(VOID *Cookie) {
 (VOID)Cookie;if(!mScratchAssigned || !StockBootstrapHealthy(NULL) || ScratchAudit() || !mDmaZeroRetained)return 1;
 if(MmioRead32(0x3da6008)!=(UINT32)mDmaZeroPhysical || MmioRead32(0x3da600c)!=(UINT32)(mDmaZeroPhysical>>32) ||
  MmioRead64(HGP_CB(0x20))!=((UINT64)0x750<<48|mFirmwareMemory.built.root_physical) ||
  MmioRead64(HGP_CB(0x28))!=((UINT64)0x750<<48))return 1;
 if(mScratchResult.enabled || mScratchResult.attached) {
  ArmSmmu4KContextImage Image;if(ScratchExpected(&Image) || MmioRead64(0x3dc0020)!=Image.ttbr0 ||
   MmioRead64(0x3dc0028)!=Image.ttbr1)return 1;
 }
 return 0;
}
STATIC int StockScratchResource(VOID *Cookie,CONST uint32_t *Request,unsigned Words,uint32_t *Response) {
 (VOID)Cookie;struct hsc_slice Slice;
 if(Request && Words==11 && (Request[4]&0x1000))return StockSecureResource(Cookie,Request,Words,Response);
 if(!Request || Words!=11 || mSharedCount>=HSC_MAX_RESOURCES)return 1;
 unsigned GpuClass=hsc_gpu_only_class(Request[4]),GpuOnly=GpuClass<HSC_CLASSES,Large=hsc_large_request(Request,Words),GmuOnly=hsc_gmu_only_flags(Request[4]),Class=hsc_resource_class(Request[4]);
 if(GpuOnly) {if(hsc_gpu_only_plan(Request,Words,mGpuOnlyNext[GpuClass],&Slice))return 1;}
 else if(Large) {if(hsc_large_plan(Request,Words,mLargeNext,&Slice))return 1;}
 else if(GmuOnly) {if(hsc_gmu_only_plan(Request,Words,mGmuOnlyNext,&Slice))return 1;}
 else if(Class>=HSC_CLASSES || hsc_resource_plan(Request,Words,mSharedNext[Class],&Slice))return 1;
 for(unsigned I=0;I<mSharedCount;I++)if(mSharedAllocations[I].Kind==Request[5] && mSharedAllocations[I].Handle==Request[7])return 1;
 if(mScratchAssigned && !mScratchResult.attached)return -1;
 BOOLEAN First=!mScratchAssigned;mScratchAssigned=TRUE;
 unsigned Memory=Large?10:GmuOnly?9:8;CONST struct hfm_allocation *Backing=GpuOnly?&mGpuOnlyMemory:&mFirmwareMemory.memory[Memory];
 VOID *Cpu=(UINT8 *)Backing->cpu+Slice.offset;
 if(ScratchGuard(NULL) || FirmwareVerifyPages(Backing->physical+Slice.offset,Cpu,Slice.bytes/4096,1))return -1;
 volatile UINT32 *Data=Cpu;for(unsigned I=0;I<Slice.bytes/4;I++)if(Data[I])return -1;
 if(First) {
  CONST struct hgp_io Io={NULL,ScratchRead32,ScratchRead64,ScratchWrite32,ScratchWrite64,ContextDelay,ScratchGuard,NULL};
  if(hsc_run(&Io,&mScratchConfig,&mScratchBuilt,&mScratchResult))return -1;
 }
 if(ScratchGuard(NULL))return -1;
 mSharedAllocations[mSharedCount].Kind=Request[5];mSharedAllocations[mSharedCount].Handle=Request[7];
 mSharedAllocations[mSharedCount].Offset=Slice.offset;mSharedAllocations[mSharedCount].Bytes=Slice.bytes;
 mSharedAllocations[mSharedCount].Arena=GpuOnly?3:Large?2:GmuOnly;mSharedAllocations[mSharedCount++].LogicalBytes=Request[9];
 if(GpuOnly)mGpuOnlyNext[GpuClass]=Slice.next;else if(Large)mLargeNext=Slice.next;else if(GmuOnly)mGmuOnlyNext=Slice.next;else mSharedNext[Class]=Slice.next;
 return hsc_resource_response(Request,Words,&Slice,Response)?-1:0;
}
#endif
