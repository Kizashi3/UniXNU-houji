/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * UEFI owner for an isolated secure candidate allocation, kept until cold reset.
 * No ordinary GPU/GMU graph includes these pages. CPU access is revoked and
 * AT read/write faults verified before the physical ownership request.
 */
#ifndef HOUJI_GPU_SECURE_MEMORY_NATIVE_H
#define HOUJI_GPU_SECURE_MEMORY_NATIVE_H
#include "GpuSecureMemory.h"
STATIC struct hsm_result mSecureMemory;
STATIC EFI_PHYSICAL_ADDRESS mSecureDataRaw,mSecureControlRaw;
STATIC int SecureMemoryAllocate(unsigned Pages,UINT64 Alignment,EFI_PHYSICAL_ADDRESS *Raw,UINT64 *Aligned) {
 *Raw=0xffffffff;EFI_STATUS Status=gBS->AllocatePages(AllocateMaxAddress,EfiBootServicesData,Pages+Alignment/4096-1,Raw);
 if(EFI_ERROR(Status))return 1;*Aligned=(*Raw+Alignment-1)&~(Alignment-1);return 0;
}
STATIC int SecureMemoryPrepare(VOID *Cookie,struct hsm_memory *Memory) {
 (VOID)Cookie;UINT64 Data,Control;
 if(!mFirmwareHeld || ScratchAudit() || SecureMemoryAllocate(HSM_BYTES/4096,65536,&mSecureDataRaw,&Data) ||
  SecureMemoryAllocate(HSM_CONTROL_BYTES/4096,16384,&mSecureControlRaw,&Control))return 1;
 *Memory=(struct hsm_memory){Data,Control,(VOID *)(UINTN)Control};if(!hsm_valid_memory(Memory))return 1;
 // Check the exact physical ranges against every other owned device graph.
 for(unsigned I=0;I<=mFirmwareMemory.count;I++) {
  CONST struct hfm_allocation *M=&mFirmwareMemory.memory[I];UINT64 End=M->physical+(UINT64)M->pages*4096;
  if((Data<End && M->physical<Data+HSM_BYTES) || (Control<End && M->physical<Control+HSM_CONTROL_BYTES))return 1;
 }
 if((Data<mScratchTablePhysical+HSC_GPU_TABLE_PAGES*4096 && mScratchTablePhysical<Data+HSM_BYTES) ||
  (Control<mScratchTablePhysical+HSC_GPU_TABLE_PAGES*4096 && mScratchTablePhysical<Control+HSM_CONTROL_BYTES))return 1;
 CONST UINT64 OtherPa[]={mTableOwned.table_physical,mTableOwned.data_physical,mDmaZeroPhysical};
 CONST UINT64 OtherBytes[]={3*4096,4096,4096};
 for(unsigned I=0;I<3;I++)if(!OtherPa[I] ||
  (Data<OtherPa[I]+OtherBytes[I] && OtherPa[I]<Data+HSM_BYTES) ||
  (Control<OtherPa[I]+OtherBytes[I] && OtherPa[I]<Control+HSM_CONTROL_BYTES))return 1;
 if((Data<mGpuOnlyMemory.physical+HSC_POOL_BYTES && mGpuOnlyMemory.physical<Data+HSM_BYTES) || (Control<mGpuOnlyMemory.physical+HSC_POOL_BYTES && mGpuOnlyMemory.physical<Control+HSM_CONTROL_BYTES))return 1;
 if((Data<mCodeMemory.physical+HCC_BYTES && mCodeMemory.physical<Data+HSM_BYTES) || (Control<mCodeMemory.physical+HCC_BYTES && mCodeMemory.physical<Control+HSM_CONTROL_BYTES))return 1;
 if(FirmwareVerifyPages(Data,(VOID *)(UINTN)Data,HSM_BYTES/4096,0) ||
  FirmwareVerifyPages(Control,Memory->control_cpu,HSM_CONTROL_BYTES/4096,0))return 1;
 EFI_GCD_MEMORY_SPACE_DESCRIPTOR Desc;EFI_STATUS Status=gDS->GetMemorySpaceDescriptor(Control,&Desc);
 if(EFI_ERROR(Status) || Control<Desc.BaseAddress || Control-Desc.BaseAddress>Desc.Length ||
  HSM_CONTROL_BYTES>Desc.Length-(Control-Desc.BaseAddress))return 1;
 Status=gDS->SetMemorySpaceAttributes(Control,HSM_CONTROL_BYTES,
  (Desc.Attributes&~(EFI_MEMORY_UC|EFI_MEMORY_WC|EFI_MEMORY_WT|EFI_MEMORY_WB))|EFI_MEMORY_WC);
 Print(L"HOUJI GPU SECURE MEMORY: private PA=%lx bytes=%x control=%lx NormalNC=%r; no ordinary GPU/GMU alias\n",Data,HSM_BYTES,Control,Status);
 if(EFI_ERROR(Status) || FirmwareVerifyPages(Control,Memory->control_cpu,HSM_CONTROL_BYTES/4096,1))return 1;
 return 0;
}
STATIC int SecureMemoryPublish(VOID *Cookie,CONST struct hsm_memory *Memory) {
 (VOID)Cookie;if(FirmwareVerifyPages(Memory->control,Memory->control_cpu,HSM_CONTROL_BYTES/4096,1))return 1;
 __asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC int SecureMemoryRevoke(VOID *Cookie,CONST struct hsm_memory *Memory) {
 (VOID)Cookie;EFI_GCD_MEMORY_SPACE_DESCRIPTOR Desc;EFI_STATUS Status=gDS->GetMemorySpaceDescriptor(Memory->data,&Desc);
 if(EFI_ERROR(Status) || Memory->data<Desc.BaseAddress || Memory->data-Desc.BaseAddress>Desc.Length ||
  HSM_BYTES>Desc.Length-(Memory->data-Desc.BaseAddress))return 1;
 UINT64 Ctr;__asm__ volatile("mrs %0,ctr_el0":"=r"(Ctr));unsigned Line=4u<<((Ctr>>16)&15);
 if(Line<16 || Line>4096)return 1;
 for(UINT64 Offset=0;Offset<HSM_BYTES;Offset+=Line)__asm__ volatile("dc civac,%0"::"r"(Memory->data+Offset):"memory");
 __asm__ volatile("dsb sy":::"memory");
 Status=gDS->SetMemorySpaceAttributes(Memory->data,HSM_BYTES,Desc.Attributes|EFI_MEMORY_RP|EFI_MEMORY_XP);
 Print(L"HOUJI GPU SECURE MEMORY: revoke CPU PA=%lx bytes=%x status=%r; no data dereference/zero/copy\n",Memory->data,HSM_BYTES,Status);
 if(EFI_ERROR(Status))return 1;
 unsigned Faults=0;UINT64 ReadPar=0,WritePar=0,SavedPar;BOOLEAN Good=TRUE;
 EFI_TPL Tpl=gBS->RaiseTPL(TPL_HIGH_LEVEL);__asm__ volatile("mrs %0,par_el1":"=r"(SavedPar));
 for(UINT64 Offset=0;Good && Offset<HSM_BYTES;Offset+=4096) {
  UINT64 Address=Memory->data+Offset;
  __asm__ volatile("at s1e1r,%1; isb; mrs %0,par_el1":"=r"(ReadPar):"r"(Address):"memory");
  __asm__ volatile("at s1e1w,%1; isb; mrs %0,par_el1":"=r"(WritePar):"r"(Address):"memory");
  if(!(ReadPar&1) || !(WritePar&1))Good=FALSE;else Faults++;
 }
 __asm__ volatile("msr par_el1,%0; isb"::"r"(SavedPar):"memory");gBS->RestoreTPL(Tpl);
 Print(L"HOUJI GPU SECURE MEMORY: CPU revoke verified=%u pages last-read-PAR=%lx last-write-PAR=%lx; backing retained, no CPU/GMU data access\n",Faults,ReadPar,WritePar);
 return Good?0:1;
}
// Native GPU work holds TPL_NOTIFY; durable filesystem I/O requires
// application TPL. Reset/ownership is rechecked before temporarily lowering.
STATIC EFI_STATUS SecureMemorySave(CONST CHAR8 *Stage) {
 EFI_TPL Tpl=gBS->RaiseTPL(TPL_HIGH_LEVEL);gBS->RestoreTPL(Tpl);
 if(Tpl!=TPL_NOTIFY || !SecureCxPrerequisites(NULL,GGS_INIT))return EFI_UNSUPPORTED;
 gBS->RestoreTPL(TPL_APPLICATION);EFI_STATUS Status=ProbeCheckpoint(Stage);
 gBS->RaiseTPL(TPL_NOTIFY);
 Print(L"HOUJI GPU SECURE CHECKPOINT: %a status=%r; TPL restored\n",Stage,Status);return Status;
}
STATIC int SecureMemoryCheckpoint(VOID *Cookie,CONST struct hsm_result *Result) {
 (VOID)Cookie;Print(L"HOUJI GPU SECURE OWNERSHIP: phase=%u queried=%x available=%x prepared=%u revoked=%u attempted=%u owned=%u calls=%u result-valid=%u a0=%lx a1=%lx; bank3 inactive, no secure resource ACK\n",
 Result->phase,Result->queried,Result->available,Result->prepared,Result->revoked,Result->attempted,Result->owned,Result->calls,Result->result_valid,Result->status_a0,Result->status_a1);
 return EFI_ERROR(SecureMemorySave(Result->owned?"after-secure-memory-owner":"before-secure-memory-owner"))?1:0;
}
STATIC unsigned RunSecureMemoryBatch(VOID) {
 CONST struct hsm_io Io={{NULL,SecureCxCall,SecureCxDelay,SecureCxPrerequisites},SecureMemoryPrepare,SecureMemoryRevoke,SecureMemoryPublish,SecureMemoryCheckpoint};
 unsigned Code=hsm_run(&Io,&mSecureCx,&mSecureMemory);
 Print(L"HOUJI GPU SECURE MEMORY RESULT: code=%u phase=%u available=%x revoked=%u attempted=%u owned=%u retained=%u result-valid=%u a0=%lx a1=%lx; data mapping/CP/PAS not executed\n",
 Code,mSecureMemory.phase,mSecureMemory.available,mSecureMemory.revoked,mSecureMemory.attempted,mSecureMemory.owned,mSecureMemory.retained,mSecureMemory.result_valid,mSecureMemory.status_a0,mSecureMemory.status_a1);
 if(EFI_ERROR(SecureMemorySave("after-secure-memory-batch")))return HGB_RETAIN;
 return Code?HGB_RETAIN:0;
}
#endif
