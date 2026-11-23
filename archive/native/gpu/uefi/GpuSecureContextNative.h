/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Separate secure graph: HLOS RW / CP_PIXEL R page tables; CP_PIXEL-only
 * data whose CPU access was revoked before assignment. No ordinary aliases.
 */
#ifndef HOUJI_GPU_SECURE_CONTEXT_NATIVE_H
#define HOUJI_GPU_SECURE_CONTEXT_NATIVE_H
#include "GpuSecureContext.h"
STATIC EFI_PHYSICAL_ADDRESS mSecureTableRaw;
STATIC UINT64 mSecureTablePhysical,*mSecureTables;
STATIC ArmSmmu4KConfig mSecureConfig;
STATIC ArmSmmu4KRange mSecureRange;
STATIC ArmSmmu4KResult mSecureBuilt;
STATIC struct hsc_result mSecureContext={.retained=1};
STATIC BOOLEAN mSecureTableOwned,mSecureDomainReady,mSecureAssigned;
STATIC int SecureDescriptor(VOID *Cookie,uint64_t Pa,uint64_t *Value) {
 (VOID)Cookie;if(!mSecureTables || Pa<mSecureTablePhysical || (Pa&7) || Pa-mSecureTablePhysical>=HSE_TABLE_PAGES*4096)return 1;
 *Value=((volatile UINT64 *)mSecureTables)[(Pa-mSecureTablePhysical)/8];return 0;
}
STATIC int SecureDomainAudit(VOID) {
 if(mGpuOnlyMemory.physical<mSecureMemory.memory.data+HSM_BYTES && mSecureMemory.memory.data<mGpuOnlyMemory.physical+HSC_POOL_BYTES)return 1;
 if(mCodeMemory.physical<mSecureMemory.memory.data+HSM_BYTES && mSecureMemory.memory.data<mCodeMemory.physical+HCC_BYTES)return 1;
 if(!mSecureMemory.owned || !mSecureMemory.revoked || !mSecureMemory.result_valid || mSecureMemory.status_a0 || mSecureMemory.status_a1 ||
  mSecureRange.physical!=mSecureMemory.memory.data || mSecureRange.iova!=HSE_IOVA || mSecureRange.bytes!=HSE_BYTES ||
  mSecureRange.permissions!=11 || mSecureRange.writeback || mSecureRange.shareability!=3)return 1;
 for(unsigned I=0;I<mFirmwareMemory.count;I++) {
  CONST ArmSmmu4KRange *M=&mFirmwareMemory.ranges[I];
  if(M->physical<mSecureMemory.memory.data+HSM_BYTES && mSecureMemory.memory.data<M->physical+M->bytes)return 1;
 }
 unsigned char Seen[HSE_TABLE_PAGES]={0};ArmSmmu4KTableIo Io={NULL,SecureDescriptor};ArmSmmu4KTableAuditResult Audit;
 ArmSmmu4KAuditRegion Region={&mSecureRange,1,HSE_TABLE_PAGES,HSE_TABLE_PAGES*512,Seen,sizeof(Seen)};
 return ArmSmmu4KAuditTables(&Io,&mSecureConfig,&mSecureBuilt,&Region,mSecureTablePhysical,&Audit) || !Audit.complete;
}
STATIC unsigned RunSecureDomainPrepare(VOID) {
 if(!mSecureMemory.owned || !SecureCxPrerequisites(NULL,GGS_INIT) ||
  SecureMemoryAllocate(HSE_TABLE_PAGES,16384,&mSecureTableRaw,&mSecureTablePhysical))return HGB_RETAIN;
 mSecureTables=(VOID *)(UINTN)mSecureTablePhysical;
 if((mSecureTablePhysical<mSecureMemory.memory.data+HSM_BYTES && mSecureMemory.memory.data<mSecureTablePhysical+HSE_TABLE_PAGES*4096) ||
  (mSecureTablePhysical<mSecureMemory.memory.control+HSM_CONTROL_BYTES && mSecureMemory.memory.control<mSecureTablePhysical+HSE_TABLE_PAGES*4096))return HGB_RETAIN;
 for(unsigned I=0;I<=mFirmwareMemory.count;I++) {
  CONST struct hfm_allocation *M=&mFirmwareMemory.memory[I];
  if(mSecureTablePhysical<M->physical+(UINT64)M->pages*4096 && M->physical<mSecureTablePhysical+HSE_TABLE_PAGES*4096)return HGB_RETAIN;
 }
 CONST UINT64 OtherPa[]={mScratchTablePhysical,mTableOwned.table_physical,mTableOwned.data_physical,mDmaZeroPhysical};
 CONST UINT64 OtherBytes[]={HSC_GPU_TABLE_PAGES*4096,3*4096,4096,4096};
 for(unsigned I=0;I<4;I++)if(!OtherPa[I] || (mSecureTablePhysical<OtherPa[I]+OtherBytes[I] && OtherPa[I]<mSecureTablePhysical+HSE_TABLE_PAGES*4096))return HGB_RETAIN;
 if(mSecureTablePhysical<mGpuOnlyMemory.physical+HSC_POOL_BYTES && mGpuOnlyMemory.physical<mSecureTablePhysical+HSE_TABLE_PAGES*4096)return HGB_RETAIN;
 if(mSecureTablePhysical<mCodeMemory.physical+HCC_BYTES && mCodeMemory.physical<mSecureTablePhysical+HSE_TABLE_PAGES*4096)return HGB_RETAIN;
 if(FirmwareVerifyPages(mSecureTablePhysical,mSecureTables,HSE_TABLE_PAGES,0))return HGB_RETAIN;
 mSecureConfig=(ArmSmmu4KConfig){32,36,mSecureTablePhysical,HSE_PAGES};
 mSecureRange=(ArmSmmu4KRange){HSE_IOVA,mSecureMemory.memory.data,HSE_BYTES,11,0,3};
 unsigned Build=ArmSmmu4KBuild(&mSecureConfig,&mSecureRange,1,mSecureTables,HSE_TABLE_PAGES,&mSecureBuilt);
 Print(L"HOUJI GPU SECURE TABLE PLAN: IOVA=%lx physical=%lx bytes=%lx build=%u tables=%u leaves=%u; expected32-bit IOVA, before table ownership/MMIO\n",
  mSecureRange.iova,mSecureRange.physical,mSecureRange.bytes,Build,(UINT32)mSecureBuilt.table_pages,(UINT32)mSecureBuilt.leaf_pages);
 if(Build || mSecureBuilt.table_pages!=HSE_TABLE_PAGES || mSecureBuilt.leaf_pages!=HSE_PAGES)return HGB_RETAIN;
 int Audit=SecureDomainAudit();Print(L"HOUJI GPU SECURE TABLE PLAN: actual graph audit=%d\n",Audit);if(Audit)return HGB_RETAIN;
 struct hfm_allocation Tables={mSecureTablePhysical,mSecureTables,HSE_TABLE_PAGES,0,0};
 int Published=FirmwarePublish(NULL,&Tables);Print(L"HOUJI GPU SECURE TABLE PLAN: CPU publication=%d\n",Published);if(Published)return HGB_RETAIN;
 struct ggs_regs Frame;int Encoded=hse_table_frame(&mSecureMemory.memory,mSecureTablePhysical,&Frame);
 Print(L"HOUJI GPU SECURE TABLE PLAN: descriptor encoding=%d\n",Encoded);
 if(Encoded || SecureMemoryPublish(NULL,&mSecureMemory.memory))return HGB_RETAIN;
 Print(L"HOUJI GPU SECURE TABLES: PA=%lx pages=%u leaves=%u IOVA=%x logical=%x; HLOS RW plus CP_PIXEL R requested, no data access\n",mSecureTablePhysical,HSE_TABLE_PAGES,HSE_PAGES,HSE_IOVA,HSE_BYTES);
 if(EFI_ERROR(SecureMemorySave("before-secure-table-share")))return HGB_RETAIN;
 CONST struct ggs_ops Io={NULL,SecureCxCall,SecureCxDelay,SecureCxPrerequisites};
 int Code=ggs_exchange_frame(&Io,&mSecureCx,&Frame);
 BOOLEAN Valid=Code!=GGS_TRANSPORT && Code!=GGS_QUARANTINED;
 Print(L"HOUJI GPU SECURE TABLE SHARE: code=%d result-valid=%u a0=%lx a1=%lx; all backing retained until cold reset\n",Code,Valid,mSecureCx.last_output.x[0],mSecureCx.last_output.x[1]);
 if(Code || mSecureCx.last_output.x[1])return HGB_RETAIN;mSecureTableOwned=TRUE;
 if(SecureDomainAudit() || EFI_ERROR(SecureMemorySave("after-secure-table-share")))return HGB_RETAIN;
 mSecureDomainReady=TRUE;return 0;
}
STATIC int SecureExpected(ArmSmmu4KContextImage *Image) {
 ArmSmmu4KContextConfig C={&mSecureConfig,NULL,&mSecureBuilt,NULL,0x4c017e18,0x5511,0x753,0,0,0};return ArmSmmu4KEncodeContext(&C,Image);
}
STATIC int SecureDomainGuard(VOID *Cookie) {
 (VOID)Cookie;if(!mSecureAssigned || !mSecureDomainReady || !mSecureTableOwned || !mScratchResult.attached ||
  ScratchGuard(NULL) || SecureDomainAudit())return 1;
 if(mSecureContext.attached) {
  ArmSmmu4KContextImage I;if(SecureExpected(&I) || MmioRead64(0x3dc3020)!=I.ttbr0 || MmioRead64(0x3dc3028)!=I.ttbr1)return 1;
 }
 return 0;
}
STATIC int SecureRead32(VOID *Cookie,uint32_t Address,uint32_t *Value) {
 (VOID)Cookie;BOOLEAN Allowed=Address==0x3da0020 || Address==0x3da0024 || Address==0x3da0028 || Address==0x3da0048 ||
  (Address>=0x3da0800 && Address<0x3da0860 && !(Address&3)) || (Address>=0x3da0c00 && Address<0x3da0c60 && !(Address&3)) ||
  (Address>=0x3dc0000 && Address<=0x3dd5000 && !((Address-0x3dc0000)&4095)) ||
  Address==0x3dc3004 || Address==0x3dc3058 || Address==0x3dc37f4;
 for(unsigned I=0;I<9;I++)if(I!=5 && I!=6 && Address==hse_address(I))Allowed=TRUE;
 if(!mSecureAssigned || !mSecureTableOwned || !Allowed || !StockBootstrapHealthy(NULL))return 1;
 *Value=MmioRead32(Address);__asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC int SecureRead64(VOID *Cookie,uint32_t Address,uint64_t *Value) {
 (VOID)Cookie;if(!mSecureAssigned || !mSecureTableOwned || (Address!=0x3dc3020 && Address!=0x3dc3028) || !StockBootstrapHealthy(NULL))return 1;
 *Value=MmioRead64(Address);__asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC int SecureWrite32(VOID *Cookie,uint32_t Address,uint32_t Value) {
 (VOID)Cookie;if(!mSecureAssigned || !mSecureDomainReady || !mSecureTableOwned || !StockBootstrapHealthy(NULL))return 1;
 ArmSmmu4KContextImage Image;if(SecureExpected(&Image))return 1;
 BOOLEAN Allowed=(Address==0x3dc3000 && (Value==0 || Value==0x1027)) || (Address==0x3dc3004 && Value==0x32b) ||
  (Address==0x3dc3618 && Value==0) || (Address==0x3dc37f0 && Value==0xffffffffu) ||
  (Address==0x3da0c08 && Value==3) || (Address==0x3da0808 && Value==0x80000002u);
 CONST UINT32 Fields[]={0,Image.cba2r,Image.cbar,Image.tcr2,Image.tcr,0,0,Image.mair0,Image.mair1};
 for(unsigned I=1;I<9;I++)if(I!=5 && I!=6 && Address==hse_address(I) && Value==Fields[I])Allowed=TRUE;
 if(!Allowed)return 1;MmioWrite32(Address,Value);__asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC int SecureWrite64(VOID *Cookie,uint32_t Address,uint64_t Value) {
 (VOID)Cookie;if(!mSecureAssigned || !mSecureDomainReady || !mSecureTableOwned || !StockBootstrapHealthy(NULL))return 1;
 ArmSmmu4KContextImage Image;if(SecureExpected(&Image) ||
  !((Address==0x3dc3020 && Value==Image.ttbr0) || (Address==0x3dc3028 && Value==Image.ttbr1)))return 1;
 MmioWrite64(Address,Value);__asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC int StockSecureResource(VOID *Cookie,CONST uint32_t *Request,unsigned Words,uint32_t *Response) {
 (VOID)Cookie;if(!hse_request(Request,Words) || !Response)return 1;
 if(mSecureAssigned)return -1;mSecureAssigned=TRUE;mSecureContext.code=HSC_GUARD;
 if(SecureDomainGuard(NULL))return -1;
 CONST struct hgp_io Io={NULL,SecureRead32,SecureRead64,SecureWrite32,SecureWrite64,ContextDelay,SecureDomainGuard,NULL};
 if(hse_run(&Io,&mSecureConfig,&mSecureBuilt,&mSecureContext) || SecureDomainGuard(NULL))return -1;
 for(unsigned I=0;I<11;I++)Response[I]=Request[I];
 Response[2]=HSE_IOVA;Response[3]=0;Response[6]=Request[7];Response[8]=0;return 0;
}
STATIC VOID SecureDomainReport(BOOLEAN PowerSafe) {
 UINT32 Valid=0,Fsr=0,Fsynr=0;UINT64 Far=0;
 if(PowerSafe && mSecureAssigned) {Fsr=MmioRead32(0x3dc3058);Fsynr=MmioRead32(0x3dc3068);Far=MmioRead64(0x3dc3060);__asm__ volatile("dsb sy":::"memory");Valid=7;}
 Print(L"HOUJI GPU SECURE DOMAIN: ready=%u table-owned=%u requested=%u code=%u phase=%u enabled=%u attached=%u retained=%u reads=%u writes=%u polls=%u last=%x/%lx observed-valid=%u; hardware translation/CP/fence not qualified\n",
  mSecureDomainReady,mSecureTableOwned,mSecureAssigned,mSecureContext.code,mSecureContext.phase,mSecureContext.enabled,mSecureContext.attached,mSecureContext.retained,
  mSecureContext.reads,mSecureContext.writes,mSecureContext.polls,mSecureContext.last_address,mSecureContext.last_wide,mSecureContext.observed_valid);
 Print(L"HOUJI GPU SECURE FAULT: valid=%x FSR=%08x FAR=%lx FSYNR=%08x; interpret only valid active fault bits\n",Valid,Fsr,Far,Fsynr);
}
#endif
