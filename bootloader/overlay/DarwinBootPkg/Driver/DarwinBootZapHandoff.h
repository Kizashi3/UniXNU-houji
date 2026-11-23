/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Include after normal UEFI libraries. Call once before EBS and before this
 * boot's GMU/SQE/PAS execution. All acquired pages survive every return path.
 */
#ifndef DARWIN_BOOT_ZAP_HANDOFF_H
#define DARWIN_BOOT_ZAP_HANDOFF_H
#include "HoujiZapHandoff.h"
#include "HoujiZapTrial.h"
#ifndef HOUJI_ZAP_LOADER_HOST_TEST
#include <PiDxe.h>
#include <Library/DxeServicesTableLib.h>
#endif
struct HzrLoaderState {
 unsigned started,raw_retained,nc_attempted,ready,code;
 EFI_STATUS allocate_status,map_status,gcd_status,nc_status;
 EFI_PHYSICAL_ADDRESS raw,metadata;
 EFI_GCD_MEMORY_SPACE_DESCRIPTOR metadata_gcd,target_gcd;
 HzrRecord record;
};
STATIC struct HzrLoaderState mHzrLoader;
STATIC union {UINT64 alignment;UINT8 bytes[65536];} mHzrMap;
#ifndef HOUJI_ZAP_LOADER_HOST_TEST
STATIC int HzrLoaderAt(UINT64 Physical,UINT64*Read,UINT64*Write){
 UINT64 El,Tcr,Daif,Par;__asm__ volatile("mrs %0,CurrentEL":"=r"(El));if(El!=4)return 1;
 __asm__ volatile("mrs %0,tcr_el1":"=r"(Tcr));if((Physical&4095)||(Tcr&(3ULL<<14))||(Tcr&(1ULL<<7))||(Tcr&63)<16||(Tcr&63)>32)return 1;
 __asm__ volatile("mrs %0,daif\n\tmrs %1,par_el1\n\tmsr daifset,#0xf":"=r"(Daif),"=r"(Par)::"memory");
 __asm__ volatile("at s1e1r,%1\n\tisb\n\tmrs %0,par_el1":"=r"(*Read):"r"(Physical):"memory");
 __asm__ volatile("at s1e1w,%1\n\tisb\n\tmrs %0,par_el1":"=r"(*Write):"r"(Physical):"memory");
 __asm__ volatile("msr par_el1,%0\n\tmsr daif,%1\n\tisb"::"r"(Par),"r"(Daif):"memory");return 0;
}
STATIC VOID*HzrLoaderPointer(UINT64 Physical){return (VOID*)(UINTN)Physical;}
STATIC VOID HzrLoaderBarrier(VOID){__asm__ volatile("dsb sy":::"memory");}
#else
STATIC int HzrLoaderAt(UINT64,UINT64*,UINT64*);
STATIC VOID*HzrLoaderPointer(UINT64);
STATIC VOID HzrLoaderBarrier(VOID);
#endif
STATIC unsigned HzrLoaderCoverage(UINT64 Base,UINT64 Bytes,UINT64 Wanted){
 unsigned Mask=0;if(!hzr_span(Base,Bytes))return 0;for(unsigned I=0;I<4;I++)if(hzr_covers(Base,Bytes,Wanted+I*4096,4096))Mask|=1u<<I;return Mask;
}
STATIC EFI_STATUS HzrLoaderCaptureMap(VOID){
 UINTN Bytes=sizeof(mHzrMap.bytes),Key=0,Stride=0;UINT32 Version=0;
 mHzrLoader.map_status=gBS->GetMemoryMap(&Bytes,(EFI_MEMORY_DESCRIPTOR*)mHzrMap.bytes,&Key,&Stride,&Version);
 if(EFI_ERROR(mHzrLoader.map_status))return mHzrLoader.map_status;
 if(!Bytes||Bytes>sizeof(mHzrMap.bytes)||Stride<sizeof(EFI_MEMORY_DESCRIPTOR)||(Stride&7)||Stride>Bytes||Bytes%Stride||Version!=EFI_MEMORY_DESCRIPTOR_VERSION)return EFI_COMPROMISED_DATA;
 unsigned Meta=0,Target=0,Records=0;
 for(UINTN Offset=0;Offset<Bytes;Offset+=Stride){
  EFI_MEMORY_DESCRIPTOR D;CopyMem(&D,mHzrMap.bytes+Offset,sizeof D);
  if((D.PhysicalStart&4095)||!D.NumberOfPages||D.NumberOfPages>(MAX_UINT64>>12)||D.NumberOfPages-1>((MAX_UINT64-D.PhysicalStart)>>12))return EFI_COMPROMISED_DATA;
  UINT64 Span=D.NumberOfPages<<12;unsigned M=HzrLoaderCoverage(D.PhysicalStart,Span,mHzrLoader.metadata),T=HzrLoaderCoverage(D.PhysicalStart,Span,HZR_TARGET_PAGE);
  if(M){if((Meta&M)||D.Type!=EfiLoaderData)return EFI_ACCESS_DENIED;Meta|=M;}
  if(T){if((Target&T)||D.Type!=EfiReservedMemoryType)return EFI_ACCESS_DENIED;Target|=T;Records++;}
 }
 if(Meta!=15||Target!=15)return EFI_ACCESS_DENIED;
 HzrRecord*R=&mHzrLoader.record;hzr_set64(R,HZR_MAP_KEY_O,Key);hzr_set64(R,HZR_MAP_BYTES_O,Bytes);hzr_set64(R,HZR_MAP_STRIDE_O,Stride);hzr_set32(R,HZR_MAP_VERSION_O,Version);
 hzr_set32(R,HZR_META_COVERAGE_O,Meta);hzr_set32(R,HZR_TARGET_COVERAGE_O,Target);hzr_set32(R,HZR_TARGET_RECORDS_O,Records);return EFI_SUCCESS;
}
STATIC EFI_STATUS HzrLoaderCaptureGcd(unsigned After){
 EFI_GCD_MEMORY_SPACE_DESCRIPTOR*D=&mHzrLoader.metadata_gcd;EFI_STATUS S=gDS->GetMemorySpaceDescriptor(mHzrLoader.metadata,D);mHzrLoader.gcd_status=S;
 CONST UINT64 Mask=EFI_MEMORY_UC|EFI_MEMORY_WC|EFI_MEMORY_WT|EFI_MEMORY_WB|EFI_MEMORY_UCE;
 if(EFI_ERROR(S))return S;
 if(D->GcdMemoryType!=EfiGcdMemoryTypeSystemMemory||!hzr_covers(D->BaseAddress,D->Length,mHzrLoader.metadata,16384)||!(D->Capabilities&EFI_MEMORY_WC)||
  (D->Attributes&Mask)!=(After?EFI_MEMORY_WC:EFI_MEMORY_WB)||(D->Attributes&(EFI_MEMORY_RP|EFI_MEMORY_RO)))return EFI_ACCESS_DENIED;
 HzrRecord*R=&mHzrLoader.record;if(!After)hzr_set64(R,HZR_META_ORIGINAL_O,D->Attributes);
 hzr_set64(R,HZR_META_GCD_BASE_O,D->BaseAddress);hzr_set64(R,HZR_META_GCD_BYTES_O,D->Length);hzr_set64(R,HZR_META_ATTR_O,D->Attributes);hzr_set64(R,HZR_META_CAP_O,D->Capabilities);
 for(unsigned I=0;I<4;I++){
  EFI_GCD_MEMORY_SPACE_DESCRIPTOR T;S=gDS->GetMemorySpaceDescriptor(HZR_TARGET_PAGE+I*4096,&T);if(EFI_ERROR(S))return S;
  if(T.GcdMemoryType!=EfiGcdMemoryTypeReserved||T.BaseAddress!=HZR_PIL_BASE||T.Length!=HZR_PIL_BYTES||T.Attributes||
   (T.Capabilities&Mask)!=EFI_MEMORY_UC||T.ImageHandle||T.DeviceHandle)return EFI_ACCESS_DENIED;
  if(!I)mHzrLoader.target_gcd=T;
 }
 D=&mHzrLoader.target_gcd;hzr_set64(R,HZR_TARGET_GCD_BASE_O,D->BaseAddress);hzr_set64(R,HZR_TARGET_GCD_BYTES_O,D->Length);hzr_set64(R,HZR_TARGET_ATTR_O,D->Attributes);hzr_set64(R,HZR_TARGET_CAP_O,D->Capabilities);return EFI_SUCCESS;
}
STATIC EFI_STATUS DarwinPrepareZapHandoff(VOID*Tree,UINTN TreeBytes,UINT64 KernelPhysical,UINT64 WindowBytes){
 struct HzrLoaderState*P=&mHzrLoader;UINTN Slot=0;EFI_STATUS S=EFI_NOT_READY;
 if(P->started)return EFI_ALREADY_STARTED;P->started=1;
 if(!gBS||!gDS||!gBS->AllocatePages||!gBS->GetMemoryMap||!gDS->GetMemorySpaceDescriptor||!gDS->SetMemorySpaceAttributes||
  !hzr_span(KernelPhysical,WindowBytes)||KernelPhysical<UINT64_C(0x8c0000000)||!hzr_adt_find(Tree,TreeBytes,&Slot)||!hzr_zero((UINT8*)Tree+Slot,HZR_BYTES))return EFI_INVALID_PARAMETER;
 ZeroMem(&P->record,sizeof P->record);P->raw=0xffffffffULL;
 /* Seven EFI pages contain one aligned complete CPU16K page. Retain ALL seven;
  * no prefix/suffix free can create a neighbouring ownership ambiguity. */
 P->allocate_status=gBS->AllocatePages(AllocateMaxAddress,EfiLoaderData,7,&P->raw);
 if(EFI_ERROR(P->allocate_status)){P->code=1;return P->allocate_status;}P->raw_retained=1;
 if(!P->raw||(P->raw&4095)||P->raw>UINT64_C(0x100000000)-7*4096){P->code=2;return EFI_COMPROMISED_DATA;}
 P->metadata=(P->raw+16383)&~UINT64_C(16383);
 if(!hzr_covers(P->raw,7*4096,P->metadata,16384)||P->metadata>0xffffc000ULL||hzr_overlap(P->raw,7*4096,HZR_TARGET_PAGE,16384)||
  hzr_overlap(P->raw,7*4096,KernelPhysical,WindowBytes)||hzr_overlap(P->raw,7*4096,(UINTN)Tree,TreeBytes)){P->code=3;return EFI_ACCESS_DENIED;}
 S=HzrLoaderCaptureMap();if(EFI_ERROR(S)){P->code=4;return S;}S=HzrLoaderCaptureGcd(0);if(EFI_ERROR(S)){P->code=5;return S;}
 ZeroMem(HzrLoaderPointer(P->metadata),16384);WriteBackInvalidateDataCacheRange(HzrLoaderPointer(P->metadata),16384);HzrLoaderBarrier();
 P->nc_attempted=1;CONST UINT64 Mask=EFI_MEMORY_UC|EFI_MEMORY_WC|EFI_MEMORY_WT|EFI_MEMORY_WB|EFI_MEMORY_UCE;
 P->nc_status=gDS->SetMemorySpaceAttributes(P->metadata,16384,(P->metadata_gcd.Attributes&~Mask)|EFI_MEMORY_WC);
 if(EFI_ERROR(P->nc_status)){P->code=6;return P->nc_status;}HzrLoaderBarrier();
 S=HzrLoaderCaptureGcd(1);if(EFI_ERROR(S)){P->code=7;return S;}S=HzrLoaderCaptureMap();if(EFI_ERROR(S)){P->code=8;return S;}
 HzrRecord*R=&P->record;
 for(unsigned I=0;I<4;I++){
  UINT64 MR=0,MW=0,TR=0,TW=0;if(HzrLoaderAt(P->metadata+I*4096,&MR,&MW)||HzrLoaderAt(HZR_TARGET_PAGE+I*4096,&TR,&TW)||
   MR!=MW||TR!=TW||!hzr_par(MR,P->metadata+I*4096)||!hzr_par(TR,HZR_TARGET_PAGE+I*4096)){P->code=9;return EFI_NO_MAPPING;}
  hzr_set64(R,HZR_META_RPAR_O+I*8,MR);hzr_set64(R,HZR_META_WPAR_O+I*8,MW);hzr_set64(R,HZR_TARGET_RPAR_O+I*8,TR);hzr_set64(R,HZR_TARGET_WPAR_O+I*8,TW);
 }
 hzr_set64(R,HZR_MAGIC_O,HZR_MAGIC);hzr_set32(R,HZR_VERSION_O,1);hzr_set32(R,HZR_LENGTH_O,HZR_BYTES);CopyMem(R->bytes+HZR_TRIAL_O,kHoujiZapTrial,16);hzr_set32(R,HZR_FLAGS_O,HZR_FLAGS_READY);
 hzr_set64(R,HZR_METADATA_PA_O,P->metadata);hzr_set64(R,HZR_OWNED_O,16384);hzr_set64(R,HZR_LOGICAL_O,4096);
 hzr_set64(R,HZR_TARGET_PAGE_O,HZR_TARGET_PAGE);hzr_set64(R,HZR_TARGET_BYTES_O,16384);hzr_set64(R,HZR_GPU_BASE_O,HZR_TARGET_GPU);hzr_set64(R,HZR_GPU_BYTES_O,8192);hzr_set64(R,HZR_COPY_BASE_O,HZR_TARGET_GPU);hzr_set64(R,HZR_COPY_BYTES_O,1072);
 hzr_set64(R,HZR_RAW_BASE_O,P->raw);hzr_set64(R,HZR_RAW_BYTES_O,7*4096);hzr_set32(R,HZR_META_EFI_O,EfiLoaderData);hzr_set32(R,HZR_TARGET_EFI_O,EfiReservedMemoryType);hzr_set32(R,HZR_META_GCD_O,EfiGcdMemoryTypeSystemMemory);hzr_set32(R,HZR_TARGET_GCD_O,EfiGcdMemoryTypeReserved);hzr_finish(R);
 if(!hzr_valid(R,sizeof *R,kHoujiZapTrial)){P->code=10;return EFI_COMPROMISED_DATA;}
 CopyMem((UINT8*)Tree+Slot,R,HZR_BYTES);P->ready=1;P->code=0;return EFI_SUCCESS;
}
#endif
