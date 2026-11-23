/** @file
  Explicit SM8650 CX/GMU-clock preparation through the pinned ClockDxe.
  Native GDSC/RCG waits are not preemptible: begin/end diagnostics and the
  GPP_PROVIDER_UNBOUNDED flag state this limitation. Policy-owned polls and
  the AOP transaction have fixed bounds. The native power policy does not
  release reset. A separate, guarded ITCM/DTCM-only CM3 diagnostic briefly
  releases reset then restores TCM. The separate retained-resource batch
  starts stock GMU/HFI and bounded HWSCHED setup, stopping at resource requests.
  The qualified ordinary host profile now attempts bounded fixed CP initialization
  and two GPU writebacks; no PAS, shader or desktop acceleration is claimed.
  SPDX-License-Identifier: BSD-2-Clause-Patent
**/
#include <Uefi.h>
#include <PiDxe.h>
#include <Library/BaseLib.h>
#include <Library/BaseMemoryLib.h>
#include <Library/DebugLib.h>
#include <Library/DxeServicesTableLib.h>
#include <Library/IoLib.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Protocol/EFIClock.h>
#include <Protocol/Cpu.h>
#include <Library/UefiLib.h>
// Use the application's single capture buffer across translation units.
UINTN EFIAPI ProbePrint(CONST CHAR16 *Format,...);
EFI_STATUS EFIAPI ProbeCheckpoint(CONST CHAR8 *Stage);
#include "GpuCallTrace.h"
#define HOUJI_CALL_TRACE_NATIVE 1
#define HOUJI_CALL_TRACE(step,address,value) HoujiGpuCallTrace((step),(UINT64)(UINTN)(address),(UINT64)(value))
#define Print ProbePrint
#define HOUJI_GPU_POWER 1
#define HFM_WITH_SCRATCH 1
#define HGKI_PROGRESS 1

VOID HoujiGpuPowerPrepare (EFI_HANDLE ImageHandle);

#if defined(HOUJI_GPU_POWER) && HOUJI_GPU_POWER
#define GPP_FIRMWARE_TYPES 1
#include "GpuPowerPolicy.h"
#include "GpuQmpTransport.h"
#include "GpuBusProbe.h"
#include "GpuGmuProbe.h"
#include "GpuSmmuPrepare.h"
#include "GpuSmmuContext.h"
#include "GpuCachePublish.h"
#include "GpuSmmuPlatform.h"
#include "GpuDmaProbe.h"
#include "GpuFirmwarePrepare.h"
#include "vendor/Ace5Gmu/giulia_gpu_scm.h"
#include "GpuStockGmu.h"
#include "GpuReadFaultNative.h"
#include "GpuDoorbellFaultNative.h"

typedef struct {
  UINT64 Version;
  EFI_STATUS (EFIAPI *Prepare)(struct gpp_report *,UINTN);
} GPP_PROTOCOL;


/* The pinned ClockDxe's optional QMP client uses this GLink protocol. The
 * giulia DXE profile excludes GLinkDxe; never bypass an installed provider.
 */
STATIC EFI_GUID mGlinkGuid={0x3bfcf64d,0x00cd,0x41cb,{0xbe,0xa5,0xa7,0x6c,0x3a,0x24,0x3d,0xed}};
STATIC EFI_CLOCK_PROTOCOL *mClock;
STATIC UINTN mIds[GPP_RESOURCE_COUNT];
STATIC BOOLEAN mAttempted,mQmpTouched,mQmpUncertain;
STATIC UINT64 mCounterFrequency;
STATIC struct gpp_report mReport;
STATIC struct qpt_state mQmp;
STATIC CONST VOID *mQmpLease;

STATIC EFI_STATUS MapMmio (UINT64 Base,UINT64 Length)
{
  EFI_GCD_MEMORY_SPACE_DESCRIPTOR Desc;
  EFI_STATUS Status=gDS->GetMemorySpaceDescriptor(Base,&Desc);
  if(EFI_ERROR(Status))return Status;
  if(Base<Desc.BaseAddress || Length>Desc.Length || Base-Desc.BaseAddress>Desc.Length-Length)
    return EFI_UNSUPPORTED;
  if(Desc.GcdMemoryType==EfiGcdMemoryTypeNonExistent) {
    Status=gDS->AddMemorySpace(EfiGcdMemoryTypeMemoryMappedIo,Base,Length,EFI_MEMORY_UC);
    if(EFI_ERROR(Status))return Status;
  } else if(Desc.GcdMemoryType!=EfiGcdMemoryTypeMemoryMappedIo)return EFI_ACCESS_DENIED;
  return gDS->SetMemorySpaceAttributes(Base,Length,EFI_MEMORY_UC);
}

STATIC VOID CallBegin (CONST CHAR8 *Operation,unsigned Resource,UINT32 Requested)
{
  Print(L"HOUJI GPU POWER: native begin op=%a resource=%u name=%a requested=%u provider_wait=not-preemptible\n",
    Operation,Resource,gpp_resource_name(Resource),Requested);
}
STATIC VOID CallEnd (CONST CHAR8 *Operation,unsigned Resource,EFI_STATUS Status,UINT32 Actual)
{
  Print(L"HOUJI GPU POWER: native end op=%a resource=%u status=%lx actual=%u\n",
    Operation,Resource,(UINT64)Status,Actual);
}

STATIC GPP_U64 Resolve (VOID *Cookie)
{
  EFI_STATUS Status;
  UINTN I,J;
  BOOLEAN Enabled=FALSE,On=FALSE;
  CONST UINT64 Maps[][2]={{0x171000,0x1000},{0x3d90000,0xa000},
    {0x3d7e000,0x1000},{QPT_MSGRAM_PA,0x1000},{0x406000,0x1000}};
  (VOID)Cookie;
  Status=gBS->LocateProtocol(&gEfiClockProtocolGuid,NULL,(VOID **)&mClock);
  Print(L"HOUJI GPU POWER: ClockDxe locate status=%lx\n",(UINT64)Status);
  if(EFI_ERROR(Status))return Status;
  if(mClock==NULL || mClock->Version!=0x1000a || !mClock->GetClockID ||
     !mClock->GetClockPowerDomainID || !mClock->EnableClockPowerDomain ||
     !mClock->EnableClock || !mClock->SetClockFreqHz || !mClock->GetClockFreqHz ||
     !mClock->IsClockEnabled || !mClock->IsClockOn)return EFI_UNSUPPORTED;
  Print(L"HOUJI GPU POWER: ClockDxe ABI=%lx; native GDSC/RCG waits may not return; policy polls alone are bounded\n",mClock->Version);
  for(I=0;I<GPP_ACD;I++) {
    CallBegin("resolve",(unsigned)I,0);
    Status=I==GPP_CX ? mClock->GetClockPowerDomainID(mClock,gpp_resource_name((unsigned)I),&mIds[I]) :
      mClock->GetClockID(mClock,gpp_resource_name((unsigned)I),&mIds[I]);
    CallEnd("resolve",(unsigned)I,Status,(UINT32)mIds[I]);
    if(EFI_ERROR(Status))return Status;
    /* The audited 1.0.a provider tags clock IDs with type 1 and domains with
     * type 2. Duplicate rate/branch aliases must resolve to the same object.
     */
    if(mIds[I]>MAX_UINT32 || (mIds[I]&0xffff0000u)!=(I==GPP_CX?0x20000u:0x10000u))
      return EFI_COMPROMISED_DATA;
    for(J=0;J<I;J++)if(mIds[I]==mIds[J] &&
      !((I==GPP_GMU_CLK && J==GPP_GMU_RATE) || (I==GPP_HUB_CLK && J==GPP_HUB_RATE)))
      return EFI_COMPROMISED_DATA;
  }
  if(mIds[GPP_GMU_RATE]!=mIds[GPP_GMU_CLK] || mIds[GPP_HUB_RATE]!=mIds[GPP_HUB_CLK])
    return EFI_COMPROMISED_DATA;
  for(I=0;I<ARRAY_SIZE(Maps);I++) {
    Status=MapMmio(Maps[I][0],Maps[I][1]);
    Print(L"HOUJI GPU POWER: map base=%lx bytes=%lx status=%lx\n",Maps[I][0],Maps[I][1],(UINT64)Status);
    if(EFI_ERROR(Status))return Status;
  }
  /* Only CFG can be queried before the policy proves config-access enabled.
   * GPUCC-dependent branch/frequency queries are deferred to resource calls.
   */
  CallBegin("is-enabled",GPP_CFG,0);
  Status=mClock->IsClockEnabled(mClock,mIds[GPP_CFG],&Enabled);
  CallEnd("is-enabled",GPP_CFG,Status,Enabled);
  if(EFI_ERROR(Status))return Status;
  CallBegin("is-on",GPP_CFG,0);
  Status=mClock->IsClockOn(mClock,mIds[GPP_CFG],&On);
  CallEnd("is-on",GPP_CFG,Status,On);
  if(EFI_ERROR(Status))return Status;
  __asm__ volatile("mrs %0,cntfrq_el0":"=r"(mCounterFrequency));
  if(!mCounterFrequency || mCounterFrequency>1000000000ULL)return EFI_UNSUPPORTED;
  return EFI_SUCCESS;
}

STATIC GPP_U64 Resource (VOID *Cookie,unsigned Id,unsigned Operation,UINT32 Requested,UINT32 *Actual)
{
  EFI_STATUS Status;
  BOOLEAN Enabled=FALSE,On=FALSE;
  UINT32 Previous=0;
  (VOID)Cookie;
  if(Id>=GPP_ACD || Actual==NULL)return EFI_INVALID_PARAMETER;
  *Actual=0;
  if(Operation==GPP_ENABLE) {
    if(Id==GPP_CX) {
      CallBegin("enable-domain",Id,Requested);
      Status=mClock->EnableClockPowerDomain(mClock,mIds[Id]);
      CallEnd("enable-domain",Id,Status,0);
      return Status;
    }
    if(Id==GPP_GMU_RATE || Id==GPP_HUB_RATE)return EFI_INVALID_PARAMETER;
    CallBegin("is-enabled",Id,0);
    Status=mClock->IsClockEnabled(mClock,mIds[Id],&Enabled);
    CallEnd("is-enabled",Id,Status,Enabled);
    if(EFI_ERROR(Status))return Status;
    CallBegin("is-on",Id,0);
    Status=mClock->IsClockOn(mClock,mIds[Id],&On);
    CallEnd("is-on",Id,Status,On);
    if(EFI_ERROR(Status))return Status;
    if(Enabled) {
      Print(L"HOUJI GPU POWER: inherited enabled resource=%u on=%u; retaining native state\n",Id,On);
      return EFI_SUCCESS;
    }
    CallBegin("enable-clock",Id,Requested);
    Status=mClock->EnableClock(mClock,mIds[Id]);
    CallEnd("enable-clock",Id,Status,0);
    return Status;
  }
  if(Id!=GPP_GMU_RATE && Id!=GPP_HUB_RATE)return EFI_INVALID_PARAMETER;
  if(Operation==GPP_SET_RATE) {
    CallBegin("get-previous-configured-hz",Id,0);
    Status=mClock->GetClockFreqHz(mClock,mIds[Id],&Previous);
    CallEnd("get-previous-configured-hz",Id,Status,Previous);
    if(EFI_ERROR(Status))return Status;
    CallBegin("set-configured-hz-exact",Id,Requested);
    Status=mClock->SetClockFreqHz(mClock,mIds[Id],Requested,EFI_CLOCK_FREQUENCY_HZ_EXACT,Actual);
    CallEnd("set-configured-hz-exact",Id,Status,*Actual);
    return Status;
  }
  if(Operation==GPP_GET_RATE) {
    CallBegin("get-configured-hz",Id,0);
    Status=mClock->GetClockFreqHz(mClock,mIds[Id],Actual);
    CallEnd("get-configured-hz",Id,Status,*Actual);
    return Status;
  }
  return EFI_INVALID_PARAMETER;
}

STATIC GPP_U64 Read (VOID *Cookie,unsigned Reg,UINT32 *Value)
{
  UINT64 Address=gpp_register_address(Reg);
  (VOID)Cookie;
  if(!Address || Value==NULL)return EFI_INVALID_PARAMETER;
  *Value=MmioRead32((UINTN)Address);
  __asm__ volatile("dsb sy":::"memory");
  return EFI_SUCCESS;
}
STATIC GPP_U64 Delay (VOID *Cookie,unsigned Microseconds)
{
  (VOID)Cookie;
  return gBS->Stall(Microseconds);
}

STATIC uint32_t QmpRead (VOID *Cookie,uint32_t Offset)
{
  (VOID)Cookie;
  if((Offset&3) || Offset>QPT_MSGRAM_BYTES-4)return MAX_UINT32;
  return MmioRead32(QPT_MSGRAM_PA+Offset);
}
STATIC VOID QmpWrite (VOID *Cookie,uint32_t Offset,uint32_t Value)
{
  (VOID)Cookie;
  if(!(Offset&3) && Offset<=QPT_MSGRAM_BYTES-4)MmioWrite32(QPT_MSGRAM_PA+Offset,Value);
}
STATIC VOID QmpBarrier (VOID *Cookie)
{ (VOID)Cookie;__asm__ volatile("dsb sy":::"memory"); }
STATIC VOID QmpKick (VOID *Cookie)
{ (VOID)Cookie;MmioWrite32(QPT_DOORBELL_PA,QPT_DOORBELL_VALUE); }
STATIC uint64_t QmpNow (VOID *Cookie)
{
  UINT64 Ticks;
  (VOID)Cookie;
  __asm__ volatile("mrs %0,cntpct_el0":"=r"(Ticks));
  return (Ticks/mCounterFrequency)*1000000ULL+
    ((Ticks%mCounterFrequency)*1000000ULL)/mCounterFrequency;
}
STATIC VOID QmpDelay (VOID *Cookie,unsigned Microseconds)
{ (VOID)Cookie;(VOID)gBS->Stall(Microseconds); }
STATIC int QmpClaim (VOID *Cookie,CONST VOID *Owner)
{
  (VOID)Cookie;
  if(mQmpLease!=NULL)return 0;
  mQmpLease=Owner;return 1;
}
STATIC int QmpOwns (VOID *Cookie,CONST VOID *Owner)
{ (VOID)Cookie;return mQmpLease==Owner; }
STATIC VOID QmpRelease (VOID *Cookie,CONST VOID *Owner)
{ (VOID)Cookie;if(mQmpLease==Owner)mQmpLease=NULL; }

STATIC GPP_U64 Acd (VOID *Cookie)
{
  EFI_STATUS Status;
  EFI_TPL OldTpl;
  VOID *NativeProvider=NULL;
  unsigned Error;
  /* Linux gen7_gmu_aop_send_acd_state(false), including trailing NUL and zero
   * alignment padding: "{class: gpu, res: acd, val: 0}" is 32 wire bytes.
   */
  STATIC CONST uint32_t Message[8]={0x616c637bu,0x203a7373u,0x2c757067u,0x73657220u,
    0x6361203au,0x76202c64u,0x203a6c61u,0x00007d30u};
  CONST struct qpt_io Io={NULL,QPT_MSGRAM_BYTES,QmpRead,QmpWrite,QmpBarrier,QmpKick,
    QmpNow,QmpDelay,QmpClaim,QmpOwns,QmpRelease};
  (VOID)Cookie;
  Status=gBS->LocateProtocol(&mGlinkGuid,NULL,&NativeProvider);
  Print(L"HOUJI GPU POWER: AOP native-provider query status=%lx present=%u\n",
    (UINT64)Status,NativeProvider!=NULL);
  if(Status!=EFI_NOT_FOUND) {
    mQmpUncertain=TRUE;
    return EFI_ERROR(Status)?Status:EFI_ACCESS_DENIED;
  }
  /* This late Boot Services entry is called at application TPL after other
   * loader work. Exclude firmware event callbacks for the whole transaction;
   * provider absence plus a stable closed APSS channel are both required.
   * Never take over a live firmware provider or an inherited open channel.
   */
  OldTpl=gBS->RaiseTPL(TPL_NOTIFY);
  Status=gBS->LocateProtocol(&mGlinkGuid,NULL,&NativeProvider);
  if(Status!=EFI_NOT_FOUND) {
    mQmpUncertain=TRUE;
    gBS->RestoreTPL(OldTpl);
    return EFI_ERROR(Status)?Status:EFI_ACCESS_DENIED;
  }
  mQmpTouched=TRUE;
  Error=qpt_open(&Io,&mQmp);
  Print(L"HOUJI GPU POWER: AOP open code=%u phase=%u leased=%u owned=%u\n",
    Error,mQmp.phase,mQmp.leased,mQmp.owned);
  if(!Error) {
    Error=qpt_send(&Io,&mQmp,Message,sizeof(Message));
    Print(L"HOUJI GPU POWER: AOP acd=0 send code=%u phase=%u pending=%u publication=%u elapsed_us=%Lu\n",
      Error,mQmp.phase,mQmp.pending,mQmp.publication_verified,mQmp.wait_elapsed_us);
  }
  if(!Error) {
    Error=qpt_close(&Io,&mQmp);
    Print(L"HOUJI GPU POWER: AOP close code=%u phase=%u leased=%u owned=%u pending=%u\n",
      Error,mQmp.phase,mQmp.leased,mQmp.owned,mQmp.pending);
  }
  /* Even a refusal before our channel write can mean inherited ownership or
   * an invalid shared descriptor. Do not let a later XNU client reinterpret
   * a transiently empty channel as permission to take it over.
   */
  if(Error)mQmpUncertain=TRUE;
  gBS->RestoreTPL(OldTpl);
  if(Error) {
    Print(L"HOUJI GPU POWER: AOP failed code=%u phase=%u last_offset=%x last_value=%x retain=%u; CX blocked\n",
      Error,mQmp.phase,mQmp.last_offset,mQmp.last_value,mQmpUncertain);
    return Error==QPT_TIMEOUT?EFI_TIMEOUT:Error==QPT_BUSY?EFI_ACCESS_DENIED:EFI_DEVICE_ERROR;
  }
  Print(L"HOUJI GPU POWER: AOP acd=0 consumed and channel closed; transport acknowledgement is not ACD hardware readback\n");
  return EFI_SUCCESS;
}

STATIC EFI_STATUS EFIAPI Prepare (struct gpp_report *Result,UINTN Bytes)
{
  unsigned Code;
  CONST struct gpp_io Io={NULL,Resolve,Acd,Resource,Read,Delay};
  if(Result==NULL || Bytes!=sizeof(*Result))return EFI_INVALID_PARAMETER;
  if(mAttempted) {
    CopyMem(Result,&mReport,sizeof(mReport));return EFI_ALREADY_STARTED;
  }
  if(!gpp_report_requested(Result))return EFI_INVALID_PARAMETER;
  mAttempted=TRUE;
  CopyMem(&mReport,Result,sizeof(mReport));
  Print(L"HOUJI GPU POWER: explicit native preparation begin; no reset release or SMMU writes; firmware waits may not return\n");
  Code=gpp_prepare(&Io,&mReport);
  mReport.flags|=GPP_PROVIDER_UNBOUNDED;
  if(mQmpUncertain)mReport.flags|=GPP_QMP_UNCERTAIN;
  if(mQmpTouched) {
    mReport.values[14]=(mQmp.phase&0xffu)|((mQmp.error&0xffu)<<8)|
      ((!!mQmp.pending)<<16)|((!!mQmp.publication_verified)<<17);
    mReport.values[15]=mQmp.last_offset;
    mReport.valid_reads|=(1u<<14)|(1u<<15);
  }
  gpp_report_seal(&mReport);
  CopyMem(Result,&mReport,sizeof(mReport));
  Print(L"HOUJI GPU POWER: result code=%u phase=%u attempted=%x confirmed=%x retained=%u flags=%x status=%lx hardware_ready=0 acceleration=0\n",
    Code,mReport.phase,mReport.attempted,mReport.confirmed,mReport.retained,mReport.flags,mReport.firmware_status);
  return Code?EFI_DEVICE_ERROR:EFI_SUCCESS;
}
#endif
STATIC GPP_U64 BusRead(VOID *Cookie,GPP_U32 Address,GPP_U32 *Value) {
  unsigned I;
  (VOID)Cookie;
  for(I=0;I<HGB_REGS;I++)if(hgb_address(I)==Address) {
    if(hrf_address(Address,32))return GpuTryRead32(Address,Value)?EFI_DEVICE_ERROR:0;
    *Value=MmioRead32(Address);__asm__ volatile("dsb sy":::"memory");return 0;
  }
  if(hgb_survey_address(Address)) {
    if(hrf_address(Address,32))return GpuTryRead32(Address,Value)?EFI_DEVICE_ERROR:0;
    *Value=MmioRead32(Address);__asm__ volatile("dsb sy":::"memory");return 0;
  }
  return EFI_ACCESS_DENIED;
}
STATIC GPP_U64 BusWrite(VOID *Cookie,GPP_U32 Address,GPP_U32 Value) {
  UINT32 Mask,Before;
  (VOID)Cookie;
  if(Address==0x171004 || Address==0x171010)Mask=2;
  else if(Address==0x3d97000)Mask=1;
  else return EFI_ACCESS_DENIED;
  Before=MmioRead32(Address);
  // Bit 31 is a read-only, asynchronously changing halt indication.
  if((Before^Value)&~(Mask|0x80000000u))return EFI_ACCESS_DENIED;
  MmioWrite32(Address,Value);__asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC struct hgd_result mGmuResult;
STATIC BOOLEAN mGmuCalled;
STATIC struct hgt_owned mTableOwned;
STATIC struct hgt_result mTableResult;
STATIC struct hgp_result mContextResult;
STATIC struct hgc_result mCacheResult;
STATIC struct hgs_result mPlatformResult;
STATIC struct hga_result mDmaResult;
STATIC VOID *mDmaZero;
STATIC uint64_t mDmaZeroPhysical;
STATIC BOOLEAN mDmaZeroRetained,mDmaCalled;
STATIC BOOLEAN mContextCalled,mGpuMustStop;
STATIC unsigned RunDisabledContext(VOID);
STATIC unsigned RunSecureCxBatch(VOID);
STATIC unsigned RunSecureMemoryBatch(VOID);
STATIC unsigned RunSecureDomainPrepare(VOID);
STATIC unsigned RunStockGmuBatch(VOID);
STATIC int DmaRead64(VOID *Cookie,uint32_t Address,uint64_t *Value);
STATIC int ContextDelay(VOID *Cookie,unsigned Us);
STATIC BOOLEAN mGpuSaveAllowed=TRUE,mStockCalled;
STATIC struct hgf_result mStockResult;
STATIC UINT64 mGpuBatchStart,mLastGpuCheckpoint;
STATIC GPP_U64 GmuCheckpoint(VOID *Cookie,unsigned Stage) {
  STATIC CONST CHAR8 *Names[]={"before-TCM-mapping","before-TCM-backup",
    "after-TCM-backup-before-load","after-TCM-load-before-CM3-release",
    "before-native-HUB-200MHz","after-native-HUB-200MHz",
    "after-CM3-control-backup-before-configuration","after-CM3-reset-write-before-mailbox",
    "after-CM3-mailbox-before-reset-assert","before-disabled-SMMU-context-config",
    "after-disabled-SMMU-context-config","after-disabled-SMMU-retirement",
    "before-SMMU-platform-RO","after-SMMU-platform-RO",
    "before-GMU-owned-DMA","after-GMU-owned-DMA",
    "before-secure-CX-batch","after-secure-CX-batch",
    "before-stock-GMU-registers","before-stock-GMU-reset-release"};
  (VOID)Cookie;
  if(Stage>=ARRAY_SIZE(Names))return EFI_INVALID_PARAMETER;
  UINT64 Begin=BatchCounter();
  BOOLEAN Durable=(Stage==3 || Stage==9 || Stage==14 || Stage==15 || Stage>=16);
  Print(L"HOUJI GPU BATCH: phase=%u name=%a since-start-us=%lu since-previous-us=%lu persist=%u\n",
    Stage,Names[Stage],BatchMicroseconds(mGpuBatchStart),mLastGpuCheckpoint?BatchMicroseconds(mLastGpuCheckpoint):0,Durable);
  mLastGpuCheckpoint=Begin;
  EFI_TPL Tpl=gBS->RaiseTPL(TPL_HIGH_LEVEL);gBS->RestoreTPL(Tpl);
  if(Tpl!=TPL_NOTIFY)return EFI_UNSUPPORTED;
  // Stages 7/8 run only the exact internal-TCM loop with masked IRQs. All
  // earlier stages keep reset held. No external DMA can be exposed here.
  if(Stage==6)Print(L"HOUJI GMU CONTROL: saved=%u FAL=%08x NEXT=%08x BOOT=%08x CFG=%08x BUS=%08x ICACHE=%08x DCACHE=%08x HFI_MASK=%08x AO_MASK=%08x\n",
    mGmuResult.control_backup,mGmuResult.control_saved[0],mGmuResult.control_saved[1],
    mGmuResult.control_saved[2],mGmuResult.control_saved[3],mGmuResult.control_saved[4],
    mGmuResult.control_saved[5],mGmuResult.control_saved[6],mGmuResult.control_saved[7],mGmuResult.control_saved[8]);
  if(Stage==8)Print(L"HOUJI GMU EXEC: mailbox=%08x,%08x,%08x GFSR=%08x; internal-only diagnostic, no GPU jobs\n",
    mGmuResult.mailbox[0],mGmuResult.mailbox[1],mGmuResult.mailbox[2],mGmuResult.gfsr);
  if(Stage==10)Print(L"HOUJI GPU CONTEXT IMAGE: SCTLR=%lx CBA2R=%lx CBAR=%lx TCR2=%lx TCR=%lx TTBR0=%lx TTBR1=%lx MAIR=%lx/%lx; M=0, streams FAULT\n",
    mContextResult.configured[0],mContextResult.configured[1],mContextResult.configured[2],
    mContextResult.configured[3],mContextResult.configured[4],mContextResult.configured[5],
    mContextResult.configured[6],mContextResult.configured[7],mContextResult.configured[8]);
  if(Stage==11)Print(L"HOUJI GPU CONTEXT RETIRE: mask=%x; known disabled fields, TTBR0=0 TTBR1=0 readback verified, bank TLB synchronized; initial unknown fields not replayed\n",mContextResult.retired);
  if(Stage==14)Print(L"HOUJI GPU DMA PREPARED: phase=%u backup=%u controls=%u published=%u PRR-zero-PA=%lx code-bytes=%u; bank%u ASID750 slot0 SID5, only IOVA60000000/4096 mapped; CFIE=0 CFCFG=0\n",
    mDmaResult.phase,mDmaResult.backed_up,mDmaResult.control_backup,mDmaResult.published,mDmaZeroPhysical,(UINT32)sizeof(hga_code),HGP_CONTEXT_BANK);
  if(Stage==15)Print(L"HOUJI GPU DMA CHECKPOINT: phase=%u positive=%u negative=%u FSR=%08x FAR=%lx FSYNR=%08x CPU=%08x verified=%u restored=%u detached=%u platform-retired=%u TCM-restored=%u control-restored=%x\n",
    mDmaResult.phase,mDmaResult.positive,mDmaResult.negative,mDmaResult.fsr,mDmaResult.far,mDmaResult.fsynr,
    mDmaResult.cpu.observed,mDmaResult.cpu.verified,mDmaResult.cpu.restored,mDmaResult.detached,
    mDmaResult.platform_retired,mDmaResult.restored,mDmaResult.control_restored);
  // Already-qualified baseline detail stays in the same RAM log. The next
  // durable snapshot contains it all, without repeating FAT I/O every step.
  if(!Durable)return 0;
  gBS->RestoreTPL(TPL_APPLICATION);
  EFI_STATUS Status=ProbeCheckpoint(Names[Stage]);
  gBS->RaiseTPL(TPL_NOTIFY);
  Print(L"HOUJI GPU BATCH: phase=%u checkpoint-status=%r checkpoint-us=%lu\n",Stage,Status,BatchMicroseconds(Begin));
  return Status;
}
STATIC GPP_U64 GmuRead(VOID *Cookie,GPP_U32 Address,GPP_U32 *Value) {
  if(hgd_tcm_address_valid(Address) || hgd_control_address_valid(Address) || Address==0x3d7e000 || Address==0x3d9913c ||
     Address==0x3d99144 || Address==0x3d993e8 || Address==0x3d993ec || Address==0x3d993f0) {
    return GpuTryRead32(Address,Value)?EFI_DEVICE_ERROR:0;
  }
  return BusRead(Cookie,Address,Value);
}
STATIC GPP_U64 GmuWrite(VOID *Cookie,GPP_U32 Address,GPP_U32 Value) {
  (VOID)Cookie;
  if(!hgd_tcm_address_valid(Address) && !hgd_control_address_valid(Address) && !(Address==0x3d7e000 && Value<=1))
    return EFI_ACCESS_DENIED;
  MmioWrite32(Address,Value);__asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC int HostPreparationGuard(VOID *Cookie);
#include "GpuClockWitnessNative.h"
STATIC EFI_STATUS PrepareGmuHub(CONST struct gpp_report *Power,CONST struct hgb_result *Bus) {
  UINT32 BeforeHz=0,Actual=0,Readback=0,Branch=0,Cmd=0,Cfg=0;
  BOOLEAN Enabled=FALSE,On=FALSE;
  EFI_STATUS Status;
  if(!hgb_owned(Power) || !hgd_bus_complete(Bus) || !mClock ||
     !mClock->SetClockFreqHz || !mClock->GetClockFreqHz || !mClock->EnableClock ||
     !mClock->IsClockEnabled || !mClock->IsClockOn)return EFI_ACCESS_DENIED;
  Status=GmuCheckpoint(NULL,4);
  if(EFI_ERROR(Status))return Status;
  // Cold CX is owned this boot, every stream is FAULT and every bank M=0.
  // Refuse an inherited HUB source/branch rather than retuning a live clock.
  if((MmioRead32(0x171004)&0x80000003u)!=1 ||
     (MmioRead32(0x171010)&0x80000003u)!=1 ||
     (MmioRead32(0x171018)&0x80000001u)!=1 ||
     (MmioRead32(0x3d97000)&0x80000001u)!=1 ||
     (MmioRead32(0x3d99108)&1) || !(MmioRead32(0x3d99168)&0x80000000u) ||
     (MmioRead32(0x3d9911c)&0x80000000u) || MmioRead32(0x3d7e000)!=1 ||
     MmioRead32(0x3d7e070)!=0 || MmioRead32(0x3d7e340)!=3 ||
     MmioRead32(0x3d993e8)!=0 || MmioRead32(0x3d993ec)!=0 ||
     MmioRead32(0x3d993f0)!=0)return EFI_ACCESS_DENIED;
  // Match the other native ClockDxe calls: allow provider events at application
  // TPL while CM3 remains held reset; restore our bus critical section on ALL
  // return paths. The following firmware waits still cannot be preempted.
  EFI_TPL Tpl=gBS->RaiseTPL(TPL_HIGH_LEVEL);gBS->RestoreTPL(Tpl);
  if(Tpl!=TPL_NOTIFY)return EFI_UNSUPPORTED;
  gBS->RestoreTPL(TPL_APPLICATION);
  Status=mClock->GetClockFreqHz(mClock,mIds[GPP_HUB_RATE],&BeforeHz);
  Print(L"HOUJI GPU HUB: before configured=%u status=%r; exact cold source required\n",BeforeHz,Status);
  if(Status!=EFI_NOT_STARTED || BeforeHz) {Status=EFI_ACCESS_DENIED;goto NativeDone;}
  CallBegin("set-cold-HUB-hz-exact",GPP_HUB_RATE,200000000);
  Status=mClock->SetClockFreqHz(mClock,mIds[GPP_HUB_RATE],200000000,EFI_CLOCK_FREQUENCY_HZ_EXACT,&Actual);
  CallEnd("set-cold-HUB-hz-exact",GPP_HUB_RATE,Status,Actual);
  if(EFI_ERROR(Status) || Actual!=200000000) {Status=EFI_DEVICE_ERROR;goto NativeDone;}
  Status=mClock->GetClockFreqHz(mClock,mIds[GPP_HUB_RATE],&Readback);
  if(EFI_ERROR(Status) || Readback!=200000000) {Status=EFI_DEVICE_ERROR;goto NativeDone;}
  CallBegin("enable-cold-HUB",GPP_HUB_CLK,1);
  Status=mClock->EnableClock(mClock,mIds[GPP_HUB_CLK]);
  CallEnd("enable-cold-HUB",GPP_HUB_CLK,Status,0);
  if(EFI_ERROR(Status))goto NativeDone;
  Status=mClock->IsClockEnabled(mClock,mIds[GPP_HUB_CLK],&Enabled);
  if(EFI_ERROR(Status))goto NativeDone;
  Status=mClock->IsClockOn(mClock,mIds[GPP_HUB_CLK],&On);
  if(EFI_ERROR(Status))goto NativeDone;
  Branch=MmioRead32(0x3d993e8);Cmd=MmioRead32(0x3d993ec);Cfg=MmioRead32(0x3d993f0);
  Print(L"HOUJI GPU HUB: configured=%u enabled=%u on=%u CBCR=%08x CMD=%08x CFG=%08x; configured, not measured; retained until reset\n",
    Readback,Enabled,On,Branch,Cmd,Cfg);
  if(!On || (Branch&0x80000000u) || (Cmd&0x80000001u) ||
     (Cfg&0x71fu)!=0x505u || MmioRead32(0x3d7e000)!=1)Status=EFI_DEVICE_ERROR;
NativeDone:
  gBS->RaiseTPL(TPL_NOTIFY);
  if(EFI_ERROR(Status))return Status;
  return GmuCheckpoint(NULL,5);
}
STATIC unsigned RunGmuProbe(VOID *Cookie,CONST struct hgb_result *Bus) {
  CONST struct hgd_io Io={NULL,GmuRead,GmuWrite,Delay,GmuCheckpoint};
  EFI_STATUS Hub=PrepareGmuHub((CONST struct gpp_report *)Cookie,Bus);
  Print(L"HOUJI GPU HUB: cold preparation result=%r; no GMU clock retune\n",Hub);
  if(EFI_ERROR(Hub))return HGB_ACTION;
  // A failed witness may mean access/ownership disappeared. Do not revoke
  // gates through hgb_probe cleanup; the existing retained-stop checkpoint
  // saves the report before the app returns to recovery. No CM3 was released.
  if(GpuClockWitnessR0((CONST struct gpp_report *)Cookie,Bus))return HGB_RETAIN;
  if(GmuCheckpoint(NULL,0))return HGB_ACTION;
  EFI_STATUS Config=MapMmio(0x3d7d000,0x1000),Ao=MapMmio(0x3d8e000,0x1000);
  if(EFI_ERROR(Config) || EFI_ERROR(Ao))return HGB_ACTION;
  EFI_STATUS Itcm=MapMmio(0x3d6d000,0x4000),Dtcm=MapMmio(0x3d71000,0x4000);
  Print(L"HOUJI GMU TCM: maps ITCM=%r DTCM=%r; internal-only diagnostic, no DMA; disabled-context test is separate\n",Itcm,Dtcm);
  if(EFI_ERROR(Itcm) || EFI_ERROR(Dtcm))return HGB_ACTION;
  mGmuCalled=TRUE;
  unsigned Code=hgd_probe(&Io,(CONST struct gpp_report *)Cookie,Bus,&mGmuResult);
  if(!mGmuResult.reset_held)return HGB_RETAIN;
  if(Code)return HGB_ACTION;
  unsigned Context=RunDisabledContext();
  // Even a pre-write guard refusal can mean another owner activated a bank.
  // Keep the bus lease on EVERY context error; never gate a foreign master.
  if(Context || !mContextResult.safe_to_release)return HGB_RETAIN;
  if(RunSecureCxBatch())return HGB_RETAIN;
  // The host-ring profile does not request HWSCHED secure contexts. Keep the
  // old providers type-checked, without allocating, revoking or assigning them.
  (VOID)RunSecureMemoryBatch;(VOID)RunSecureDomainPrepare;
  Print(L"HOUJI GPU HOST MODE: omit HWSCHED secure-data/table preparation; normalGPU bank0 and GMU bank2 only, no MP_ASSIGN or PAS\n");
  if(RunStockGmuBatch())return HGB_RETAIN;
  return 0;
}
STATIC int TableAllocate(VOID *Cookie,unsigned Pages,uint64_t *Physical,VOID **Cpu) {
  (VOID)Cookie;
  if(Pages!=1 && Pages!=3)return 1;
  EFI_PHYSICAL_ADDRESS Address=0xfffffffffULL;
  EFI_STATUS Status=gBS->AllocatePages(AllocateMaxAddress,EfiBootServicesData,Pages,&Address);
  if(EFI_ERROR(Status))return 1;
  *Physical=Address;*Cpu=(VOID *)(UINTN)Address;return 0;
}
STATIC int TableValidate(VOID *Cookie,uint64_t Physical,VOID *Cpu,unsigned Pages) {
  (VOID)Cookie;
  UINT64 El,Par=0,SavedPar=0;
  EFI_GCD_MEMORY_SPACE_DESCRIPTOR Desc;
  if((Pages!=1 && Pages!=3) || Physical!=(UINTN)Cpu || (Physical&4095))return 1;
  EFI_STATUS Status=gDS->GetMemorySpaceDescriptor(Physical,&Desc);
  if(EFI_ERROR(Status) || Desc.GcdMemoryType!=EfiGcdMemoryTypeSystemMemory ||
     Physical<Desc.BaseAddress || Desc.Length<Pages*4096u ||
     Physical-Desc.BaseAddress>Desc.Length-Pages*4096u || !(Desc.Attributes&EFI_MEMORY_WB))return 1;
  __asm__ volatile("mrs %0, CurrentEL":"=r"(El));
  Print(L"HOUJI GPU TABLE RAM: PA=%lx pages=%u currentEL=%u GCD-attributes=%lx\n",Physical,Pages,(UINT32)(El>>2),Desc.Attributes);
  // Refuse other translation regimes until their board contract is checked.
  if(El!=4)return 1;
  EFI_TPL Tpl=gBS->RaiseTPL(TPL_HIGH_LEVEL);
  __asm__ volatile("mrs %0, par_el1":"=r"(SavedPar));
  BOOLEAN Valid=TRUE;
  for(unsigned Page=0;Page<Pages && Valid;Page++) {
    UINT64 Address=Physical+Page*4096u;
    __asm__ volatile("at s1e1r, %1\n\tisb\n\tmrs %0, par_el1":"=r"(Par):"r"(Address):"memory");
    if(!hgt_page_attributes(Par,Address)) {Valid=FALSE;break;}
    __asm__ volatile("at s1e1w, %1\n\tisb\n\tmrs %0, par_el1":"=r"(Par):"r"(Address):"memory");
    if(!hgt_page_attributes(Par,Address))Valid=FALSE;
  }
  __asm__ volatile("msr par_el1, %0\n\tisb"::"r"(SavedPar):"memory");
  gBS->RestoreTPL(Tpl);
  Print(L"HOUJI GPU TABLE RAM: identity-RW-WB-inner-shareable=%u last-PAR=%lx; allocated memory only\n",Valid,Par);
  return Valid?0:1;
}
STATIC int TableRelease(VOID *Cookie,uint64_t Physical,unsigned Pages) {
  (VOID)Cookie;
  return EFI_ERROR(gBS->FreePages(Physical,Pages))?1:0;
}
STATIC VOID ReleaseOwnedTables(VOID) {
  if(mDmaZeroRetained) {
    if(TableRelease(NULL,mDmaZeroPhysical,1)==0) {mDmaZero=NULL;mDmaZeroRetained=FALSE;}
    else mGpuMustStop=TRUE;
  }
  if(TableRelease(NULL,mTableOwned.data_physical,1)==0) {
    mTableOwned.data=NULL;mTableResult.released|=2;mTableResult.retained&=~2u;
  } else mGpuMustStop=TRUE;
  if(TableRelease(NULL,mTableOwned.table_physical,3)==0) {
    mTableOwned.tables=NULL;mTableResult.released|=1;mTableResult.retained&=~1u;
  } else mGpuMustStop=TRUE;
}
STATIC int CacheCleanLine(VOID *Cookie,uintptr_t Address) {
  (VOID)Cookie;
  uintptr_t Tables=(uintptr_t)mTableOwned.tables,Data=(uintptr_t)mTableOwned.data,Zero=(uintptr_t)mDmaZero;
  unsigned Line=mCacheResult.line_bytes;
  if(Line<16 || Line>4096 || (Address&(Line-1)) ||
     !((Address>=Tables && Address-Tables<12288) ||
       (Address>=Data && Address-Data<4096) ||
       (mDmaZeroRetained && Address>=Zero && Address-Zero<4096)))return 1;
  __asm__ volatile("dc cvac, %0"::"r"(Address):"memory");return 0;
}
STATIC int CachePublishBarrier(VOID *Cookie) {
  (VOID)Cookie;__asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC int ContextRead32(VOID *Cookie,uint32_t Address,uint32_t *Value) {
  (VOID)Cookie;int Field=hgp_field_index(Address);
  BOOLEAN Allowed=(Field>=0 && Field!=5 && Field!=6) ||
    Address==0x3da0020 || Address==0x3da0024 || Address==0x3da0028 ||
    Address==0x3da0048 || Address==HGP_CB(0x58) || Address==HGP_CB(0x68) || Address==HGP_CB(0x7f4) ||
    Address==HGP_CB(0x4) || Address==0x3da6008 || Address==0x3da600c ||
    (Address>=0x3da0800 && Address<0x3da0860 && !(Address&3)) ||
    (Address>=0x3da0c00 && Address<0x3da0c60 && !(Address&3)) ||
    (Address>=0x3dc0000 && Address<=0x3dd5000 && !(Address&4095));
  if(!Allowed)return 1;
  return GpuTryRead32(Address,Value)?2:0;
}
STATIC int ContextRead64(VOID *Cookie,uint32_t Address,uint64_t *Value) {
  (VOID)Cookie;if(Address!=HGP_CB(0x20) && Address!=HGP_CB(0x28))return 1;
  return GpuTryRead64(Address,Value)?2:0;
}
STATIC int ContextWrite32(VOID *Cookie,uint32_t Address,uint32_t Value) {
  (VOID)Cookie;int Field=hgp_field_index(Address);
  if(Field>=0 && Field!=5 && Field!=6) {if(!Field && (Value&1))return 1;}
  else if(!((Address==HGP_CB(0x618) && !Value) || (Address==HGP_CB(0x7f0) && Value==0xffffffffu)))return 1;
  MmioWrite32(Address,Value);__asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC int ContextWrite64(VOID *Cookie,uint32_t Address,uint64_t Value) {
  (VOID)Cookie;if(Address!=HGP_CB(0x20) && Address!=HGP_CB(0x28))return 1;
  MmioWrite64(Address,Value);__asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC int ContextPowerGuard(VOID *Cookie) {
  (VOID)Cookie;struct hgd_result Result;ZeroMem(&Result,sizeof(Result));
  CONST struct hgd_io Io={NULL,GmuRead,GmuWrite,Delay,NULL};return hgd_guard(&Io,&Result)?0:1;
}
STATIC struct ggs_state mSecureCx;
STATIC int SecureCxPrerequisites(VOID *Cookie,unsigned Operation) {
  (VOID)Cookie;(VOID)Operation;
  CONST struct hgp_io Io={.read32=ContextRead32,.power_guard=ContextPowerGuard};
  struct hgp_result Guard={0};
  return mDmaCalled && mDmaResult.complete && !mDmaResult.must_retain &&
    mContextResult.safe_to_release && mContextResult.retired==0x1ff && hgp_guard(&Io,&Guard);
}
STATIC int SecureCxDelay(VOID *Cookie,unsigned Ms) {(VOID)Cookie;return EFI_ERROR(gBS->Stall((UINTN)Ms*1000))?1:0;}
STATIC VOID BatchFaultSnapshot(CONST CHAR8 *Phase) {
  // Every address is in an already-qualified CX/GMU/SMMU window. No GX,
  // shader/CP register or clear-on-read diagnostics are accessed here.
  CONST UINT32 Addresses[]={0x3da0048,HGP_CB(0),HGP_CB(4),HGP_CB(0x58),HGP_CB(0x68),
    0x3da6008,0x3da600c,0x3da0800,0x3da0c00,0x3dc0000,0x3dc1000,
    0x3d7e000,0x3d7e070,0x3d7e340,0x3d7e600,0x3d7e648,0x3d7e64c,0x3d8ec14,0x3d8ec18};
  for(unsigned I=0;I<ARRAY_SIZE(Addresses);I++)Print(L"HOUJI GPU BATCH SNAPSHOT: phase=%a address=%08x value=%08x\n",
    Phase,Addresses[I],MmioRead32(Addresses[I]));
  Print(L"HOUJI GPU BATCH SNAPSHOT: phase=%a FAR=%lx TTBR0=%lx TTBR1=%lx\n",Phase,
    MmioRead64(HGP_CB(0x60)),MmioRead64(HGP_CB(0x20)),MmioRead64(HGP_CB(0x28)));
  __asm__ volatile("dsb sy":::"memory");
}
STATIC int SecureCxCall(VOID *Cookie,struct ggs_regs *Registers) {
  (VOID)Cookie;
  Print(L"HOUJI GPU SCM BEGIN: call=%u x0=%lx x1=%lx x2=%lx cookie=%lx; native SMC time not preemptible\n",
    mSecureCx.calls,Registers->x[0],Registers->x[1],Registers->x[2],Registers->x[6]);
  if(GmuCheckpoint(NULL,16))return 1;
  if(!SecureCxPrerequisites(NULL,GGS_INIT))return 1;
  UINT64 Begin=BatchCounter();int Status=ggs_aarch64_call(NULL,Registers);
  Print(L"HOUJI GPU SCM END: transport=%d x0=%lx x1=%lx x2=%lx x3=%lx x4=%lx x5=%lx x6=%lx x7=%lx elapsed-us=%lu\n",
    Status,Registers->x[0],Registers->x[1],Registers->x[2],Registers->x[3],Registers->x[4],Registers->x[5],Registers->x[6],Registers->x[7],BatchMicroseconds(Begin));
  return Status;
}
STATIC unsigned RunSecureCxBatch(VOID) {
  CONST struct ggs_ops Io={NULL,SecureCxCall,SecureCxDelay,SecureCxPrerequisites};
  if(!SecureCxPrerequisites(NULL,GGS_INIT))return HGB_RETAIN;
  BatchFaultSnapshot("after-bank2-DMA-before-SCM");
  UINT64 Begin=BatchCounter();unsigned Result=ggs_run(&Io,&mSecureCx,GGS_INIT);
  Print(L"HOUJI GPU BATCH: secure-CX result=%u phase=%u convention=%u available=%u initialized=%u quarantined=%u calls=%u busy=%u interrupted=%u elapsed-us=%lu; no PAS/ZAP or secure buffers\n",
    Result,mSecureCx.phase,mSecureCx.convention_verified,mSecureCx.available,mSecureCx.init_succeeded,
    mSecureCx.quarantined,mSecureCx.calls,mSecureCx.busy_retries,mSecureCx.interrupt_resumes,BatchMicroseconds(Begin));
  // Snapshot only after fresh ownership checks. An INIT failure or unresolved
  // wait-queue is not proof that no secure-side state changed.
  if(!SecureCxPrerequisites(NULL,GGS_INIT))return HGB_RETAIN;
  BatchFaultSnapshot("after-SCM");
  if(GmuCheckpoint(NULL,17))return HGB_RETAIN;
  if(mSecureCx.quarantined || (Result && mSecureCx.phase==GGS_PHASE_INIT))return HGB_RETAIN;
  return 0;
}
STATIC int StockRead32(VOID *Cookie,uint32_t Address,uint32_t *Value) {
  int Context=ContextRead32(Cookie,Address,Value);if(!Context)return 0;if(Context>1)return 1;
  BOOLEAN Allowed=(Address>=0x3d6d000 && Address<0x3d75000 && !(Address&3)) ||
    Address==0x3d50404 || Address==0x3d7e200 || Address==0x3d7e600 ||
    Address==0x3d7e648 || Address==0x3d8ec14;
  for(unsigned I=0;I<ARRAY_SIZE(hgf_rsc);I++)if(hgf_rsc[I].address==Address)Allowed=TRUE;
  for(unsigned I=0;I<ARRAY_SIZE(hgf_boot);I++)if(hgf_boot[I].address==Address)Allowed=TRUE;
  if(Allowed) {
    if(hrf_address(Address,32))return GpuTryRead32(Address,Value)?1:0;
    *Value=MmioRead32(Address);__asm__ volatile("dsb sy":::"memory");return 0;
  }
  return GmuRead(Cookie,Address,Value)?1:0;
}
STATIC int StockWrite32(VOID *Cookie,uint32_t Address,uint32_t Value) {
  (VOID)Cookie;if(!mStockCalled || !mFirmwareHeld || !mFirmwareImage || !mSecureCx.init_succeeded)return 1;
  if(Address==0x3d7e650)return Value==1?GpuDoorbellWrite(Address,Value):1;
  BOOLEAN Allowed=(Address==0x3d7e000 && Value<=1) ||
    (Address==0x3d7e618 && Value<=1) || (Address==0x3d7e650 && Value==1) ||
    (Address==HGP_CB(0) && (Value==0 || Value==0x1027)) ||
    (Address==HGP_CB(4) && Value==0x32b) ||
    (Address==0x3da6008 && Value==(UINT32)mDmaZeroPhysical) ||
    (Address==0x3da600c && Value==(UINT32)(mDmaZeroPhysical>>32)) ||
    (Address==0x3da0c00 && Value==HGP_CONTEXT_BANK) ||
    (Address==0x3da0800 && Value==0x80000005u) ||
    (Address==HGP_CB(0x618) && !Value) ||
    (Address==HGP_CB(0x7f0) && Value==0xffffffffu);
  // Only payload words from the fixed verified firmware may reach TCM.
  if(mFirmwareImage) {
    struct gg_fw_block Blocks[GG_FW_MAX_BLOCKS];size_t Count=0;
    if(gg_fw_plan(mFirmwareImage,HFM_FW_BYTES,Blocks,GG_FW_MAX_BLOCKS,&Count))return 1;
    for(size_t I=0;I<Count;I++) {
      CONST struct gg_fw_block *B=&Blocks[I];if(!B->size || (B->region!=GG_ITCM && B->region!=GG_DTCM))continue;
      UINT32 A=B->region==GG_ITCM?0x3d6d000+B->address:0x3d71000+B->address-0x10004000;
      if(Address>=A && Address-A<B->size && !(Address&3) &&
        Value==gg_le32((CONST UINT8 *)mFirmwareImage+B->payload_offset+Address-A))Allowed=TRUE;
    }
  }
  for(unsigned I=0;I<ARRAY_SIZE(hgf_rsc);I++)if(hgf_rsc[I].address==Address && hgf_rsc[I].value==Value)Allowed=TRUE;
  for(unsigned I=0;I<ARRAY_SIZE(hgf_boot);I++)if(hgf_boot[I].address==Address && hgf_boot[I].value==Value)Allowed=TRUE;
  if(!Allowed) {
    int Field=hgp_field_index(Address);
    if(Field<1 || Field==5 || Field==6)return 1;
    // Encoded, audited native4K field writes only; no arbitrary captured image.
    ArmSmmu4KContextConfig Config={&mFirmwareMemory.config,NULL,&mFirmwareMemory.built,NULL,
      0x4c017e18,0x5511,0x750,0,0,0};ArmSmmu4KContextImage Image;
    if(ArmSmmu4KEncodeContext(&Config,&Image))return 1;
    CONST UINT32 Values[]={0,Image.cba2r,Image.cbar,Image.tcr2,Image.tcr,0,0,Image.mair0,Image.mair1};
    if(Value!=Values[Field])return 1;
  }
  MmioWrite32(Address,Value);__asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC int StockWrite64(VOID *Cookie,uint32_t Address,uint64_t Value) {
  (VOID)Cookie;
  if(!mStockCalled || !mFirmwareHeld || !mFirmwareImage || !mSecureCx.init_succeeded ||
    !((Address==HGP_CB(0x20) && Value==((UINT64)0x750<<48|mFirmwareMemory.built.root_physical)) ||
      (Address==HGP_CB(0x28) && Value==((UINT64)0x750<<48))))return 1;
  MmioWrite64(Address,Value);__asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC int StockPrerequisite(VOID *Cookie) {
  (VOID)Cookie;return mFirmwareHeld && mFirmwareImage && mFirmwareMemory.retained==HFM_ALL &&
    mSecureCx.init_succeeded && SecureCxPrerequisites(NULL,GGS_INIT);
}
STATIC VOID StockHfiBarrier(VOID *Cookie) {(VOID)Cookie;__asm__ volatile("dsb sy":::"memory");}
STATIC int StockPublish(VOID *Cookie) {
  (VOID)Cookie;if(!mFirmwareHeld || !mFirmwareImage || mFirmwareMemory.retained!=HFM_ALL)return 1;
  for(unsigned I=0;I<=mFirmwareMemory.count;I++) {
    CONST struct hfm_allocation *M=&mFirmwareMemory.memory[I];
    if(FirmwareVerifyPages(M->physical,M->cpu,M->pages,M->nc) || FirmwarePublish(NULL,M))return 1;
  }
  unsigned char Visited[HFM_TABLE_PAGES]={0};ArmSmmu4KTableIo Actual={&mFirmwareMemory,hfm_descriptor};
  ArmSmmu4KAuditRegion Region={mFirmwareMemory.ranges,mFirmwareMemory.count,HFM_TABLE_PAGES,
    HFM_TABLE_PAGES*512,Visited,sizeof(Visited)};ArmSmmu4KTableAuditResult Audit;
  if(ArmSmmu4KAuditTables(&Actual,&mFirmwareMemory.config,&mFirmwareMemory.built,&Region,
    mFirmwareMemory.built.root_physical,&Audit) || !Audit.complete)return 1;
  for(unsigned I=0;I<17;I++) {
    struct ggh_io Hfi={mFirmwareMemory.memory[5].cpu,GGH_BYTES,GGH_IOVA,NULL,StockHfiBarrier};
    volatile uint32_t *Head,*Ring;unsigned ReadIndex,WriteIndex;
    if(ggh_queue(&Hfi,I,&Head,&Ring,&ReadIndex,&WriteIndex) || ReadIndex || WriteIndex)return 1;
    for(unsigned N=0;N<1024;N++)if(Ring[N])return 1;
  }
  struct gg_fw_block Blocks[GG_FW_MAX_BLOCKS];size_t Count=0;
  if(gg_fw_plan(mFirmwareImage,HFM_FW_BYTES,Blocks,GG_FW_MAX_BLOCKS,&Count))return 1;
  for(size_t I=0;I<Count;I++) {
    CONST struct gg_fw_block *B=&Blocks[I];if(!B->size || B->region==GG_ITCM || B->region==GG_DTCM)continue;
    unsigned J;for(J=0;J<5;J++)if(B->address>=mFirmwareMemory.memory[J].iova &&
      B->size<=mFirmwareMemory.memory[J].pages*4096 &&
      B->address-mFirmwareMemory.memory[J].iova<=mFirmwareMemory.memory[J].pages*4096-B->size)break;
    if(J==5)return 1;
    volatile UINT8 *Cpu=(volatile UINT8 *)mFirmwareMemory.memory[J].cpu+B->address-mFirmwareMemory.memory[J].iova;
    for(unsigned N=0;N<B->size;N++)if(Cpu[N]!=((CONST UINT8 *)mFirmwareImage)[B->payload_offset+N])return 1;
  }
  if(!hga_zero_valid(&mTableOwned,mDmaZeroPhysical,mDmaZero))return 1;
  return CachePublishBarrier(NULL);
}
STATIC int StockCheckpoint(VOID *Cookie,unsigned Stage) {return GmuCheckpoint(Cookie,Stage+17)?1:0;}
STATIC int StockBootstrapHealthy(VOID *Cookie) {
  (VOID)Cookie;return mFirmwareHeld && mStockResult.fw_ready && mStockResult.hfi_ready &&
    mStockResult.query_ack && hgf_health(&(struct hgf_io){.cookie=NULL,.read=StockRead32},&mStockResult);
}
STATIC int StockBootstrapSend(VOID *Cookie,CONST uint32_t *Request,unsigned Words) {
  (VOID)Cookie;struct ggh_io Hfi={mFirmwareMemory.memory[5].cpu,GGH_BYTES,GGH_IOVA,NULL,StockHfiBarrier};
  return ggh_send(&Hfi,Request,Words);
}
STATIC int StockBootstrapReceive(VOID *Cookie,unsigned Queue,uint32_t *Reply,unsigned *Words) {
  (VOID)Cookie;struct ggh_io Hfi={mFirmwareMemory.memory[5].cpu,GGH_BYTES,GGH_IOVA,NULL,StockHfiBarrier};
  return ggh_receive(&Hfi,Queue,Reply,255,Words);
}
STATIC int StockBootstrapDoorbell(VOID *Cookie) {
  CONST struct hgf_io Io={.cookie=Cookie,.read=StockRead32,.write=StockWrite32,.barrier=CachePublishBarrier};
  return hgf_write(&Io,&mStockResult,0x3d7e650,1,0)?0:1;
}
STATIC int StockSecureResource(VOID *Cookie,CONST uint32_t *Request,unsigned Words,uint32_t *Response);
STATIC unsigned mHostProfileReady;
STATIC int HostContextQualified(VOID);
STATIC BOOLEAN mHostRingUnsafe;
STATIC VOID HostRingReport(VOID);
#include "GpuScratchNative.h"
#include "GpuSecureMemoryNative.h"
#include "GpuSecureContextNative.h"
#include "GpuGxStartNative.h"
#include "GpuCodeBindNative.h"
#include "GpuGen7Native.h"
STATIC unsigned CpPreRawCheckpoint(VOID);
STATIC UINT32 mCpIrqMask,mCpIrqBefore,mCpGicGroup,mCpGicEnable,mCpIrqAfter,mCpIrqPrepCode;
STATIC BOOLEAN mCpGicMapped;
STATIC int CpPolledHealthy(VOID *Cookie);
STATIC VOID CpSplitReport(VOID);
STATIC int PrepareGraphicsPrerequisites(VOID);
#include "GpuCpInitNative.h"
#include "GpuLiveLogNative.h"
#include "GpuCpBoundaryNative.h"
#include "GpuCpPolledIrqNative.h"
#include "GpuHostProfileNative.h"
#include "GpuHostPreparationNative.h"
#include "GpuHostRingNative.h"
#include "GpuPasProbeNative.h"
#include "GpuZapLoadNative.h"
#include "GpuKnownImage2dNative.h"
STATIC int GraphicsRuntimeCheck(unsigned RequireIdle);
#include "GpuGraphicsStallNative.h"
#include "GpuFirstContextNative.h"
STATIC int GraphicsRuntimeCheck(unsigned RequireIdle) {
  if(!mHostRing.enabled || !mHostRing.init_idle || mHostRing.phase!=4 ||
    !mHostRingPrepared || !mHostDirectReady || !mHostRingUnsafe || mGpuSaveAllowed ||
    mHostRing.code || mHostRingCpFailed || mHostWriteFaults || mHostBusStop.stage ||
    HostRingGuard(NULL))return 1;
  uint32_t Rptr=0,Status=0,Irq=0,Fault=0;
  if(HostRingRead(NULL,0x3d02018,&Rptr) || HostRingRead(NULL,0x3d00840,&Status) ||
    HostRingRead(NULL,0x3d00804,&Irq) || HostRingRead(NULL,0x3d02084,&Fault))return 1;
  return Irq || Fault || !mHostRingBusy.valid ||
    (RequireIdle && (Rptr!=mHostRing.wptr || (Status&~1u) || (mHostRingBusy.last&(1u<<23))));
}
STATIC int GraphicsRuntimeIdle(VOID) {
  return GraphicsRuntimeCheck(1);
}
STATIC int AuthenticatedZapOwner(VOID *Cookie,unsigned Phase) {
  (VOID)Cookie;(VOID)Phase;
  if(!mHostRing.enabled)return !mHostRingUnsafe && !mHostWriteCalls &&
    !mHostRingPrepared && !mHostRing.started && mGpuSaveAllowed && !HostPreparationGuard(NULL);
  return !GraphicsRuntimeIdle();
}
STATIC int KnownImageOwner(VOID *Cookie,unsigned Phase) {
  (VOID)Cookie;
  // Immediately after the IB doorbell, normal GPU busy/RPTR progress must
  // reach the existing bounded idle callback rather than be rejected early.
  if(Phase==4 && mHostImage.submitted && !mHostImage.idle)return GraphicsRuntimeCheck(0);
  return GraphicsRuntimeIdle();
}
STATIC int HostRingLoadAuthenticatedZap(VOID) {
  return (int)RunZapLoadNative(&mSecureCx,&mPasProbe);
}
STATIC int HostRingBuildFirstContext(VOID) {
  // The fixed profile has never installed preemption/save/queue state.
  return (int)FirstContextNativeBuild(1);
}
STATIC CONST uint32_t *HostRingFirstContextWords(VOID) {
  return mFirstContextNative.ready?mFirstContextNative.words:NULL;
}
STATIC int HostRingFirstContextMatch(CONST uint32_t *Words,unsigned Count) {
  return FirstContextNativePacketMatches(Words,Count)?0:1;
}
STATIC int HostRingRunKnownImage(VOID) {
  if(mHostImage.started || !mHostMode.complete || !mHostContext.complete || GraphicsRuntimeIdle())return 1;
  mHostImage.started=1;mHostImage.phase=1;
  mHostImage.stall_code=CaptureGraphicsStall(0);
  if(mHostImage.stall_code)return 1;
  CONST struct hgki_native_owner Owner={NULL,KnownImageOwner,HostKnownImageSubmit,HostKnownImageIdle};
  // This fixed host profile has never initialized KMD preemption, scheduled
  // contexts, installed their save buffers, or issued CONTEXT_SWITCH_YIELD.
  // This is a driver-policy fact, not an inferred hardware register value.
  unsigned Code=RunKnownImage2d(&Owner,1);mHostImage.code=Code;
  if(!Code){mHostImage.complete=1;mHostImage.phase=5;}
  return Code?1:0;
}
STATIC int PrepareGraphicsPrerequisites(VOID) {
  unsigned Code=RunPasProbe();
  PasProbeReport();
  CONST struct hzl_native_owner Owner={NULL,AuthenticatedZapOwner};
  if(!Code)Code=ZapLoadNativePrepare(&Owner,mHostRingUnsafe,mHostRing.enabled,mHostWriteCalls);
  ZapLoadNativeReport();
  if(!Code)Code=KnownImage2dNativePrepare();
  KnownImage2dReport();
  return Code?1:0;
}
STATIC unsigned StockBootstrap(VOID *Cookie,struct hhb_result *Result) {
  // Keep historical diagnostic helpers type-checked; none is invoked by the
  // host-protocol-only profile. LTO removes these address-only references.
  (VOID)StockScratchResource;(VOID)RunGxStart;(VOID)RunCodeBind;(VOID)RunGen7Config;
  (VOID)RunLiveLogCanary;(VOID)RunCpBoundary;(VOID)RunCpPolledIrq;(VOID)CpIdleCheckpoint;
  unsigned Code=RunHostProfile(Result,Cookie);
  if(!Code)Code=RunHostPreparation(Result);
  return Code?Code:RunHostRing();
}
STATIC unsigned RunStockGmuBatch(VOID) {
  if(!mFirmwareHeld || !mSecureCx.init_succeeded) {
    Print(L"HOUJI GPU STOCK: skipped; qualified firmware memory or secure-CX missing\n");return 0;
  }
  UINT64 Begin=BatchCounter();mStockCalled=TRUE;
  CONST struct hgf_io Io={
    {NULL,StockRead32,DmaRead64,StockWrite32,StockWrite64,ContextDelay,ContextPowerGuard,NULL},
    NULL,StockRead32,StockWrite32,CachePublishBarrier,ContextDelay,StockPrerequisite,StockPublish,StockCheckpoint,StockBootstrap,CpStoppedCheckpoint};
  unsigned Result=hgf_run(&Io,&mFirmwareMemory,mFirmwareImage,HFM_FW_BYTES,mDmaZeroPhysical,&mStockResult);
  mGpuSaveAllowed=(!mStockResult.release_attempted || mStockResult.reset_held) && !mHostRingUnsafe;
  UINT32 ScratchFsr=0,ScratchFsynr=0,ScratchDiag=0;UINT64 ScratchFar=0;
  if(mScratchAssigned && mStockResult.reset_held && hgf_power(&Io,&mStockResult)) {
    ScratchFsr=MmioRead32(0x3dc0058);ScratchFsynr=MmioRead32(0x3dc0068);ScratchFar=MmioRead64(0x3dc0060);
    __asm__ volatile("dsb sy":::"memory");ScratchDiag=7;
  }
  SecureDomainReport(mStockResult.reset_held && hgf_power(&Io,&mStockResult));
  GxStartReport();
  CodeBindReport();
  Gen7Report();
  CpInitReport();
  LiveLogReport();
  HostRingReport();
  PasProbeReport();
  ZapLoadNativeReport();
  if(mKnownImage2d.started && mHostImage.submitted)(VOID)KnownImage2dIsolatedCapture();
  KnownImage2dReport();
  GraphicsStallReport();
  FirstContextNativeReport();
  UINT32 ShadowCrc=0;EFI_STATUS ShadowStatus=gBS->CalculateCrc32(mStockResult.tcm_before,
    (UINTN)mStockResult.tcm_backup_words*4,&ShadowCrc);
  Print(L"HOUJI GPU STOCK TCM SHADOW: words=%u bytes=%u crc=%08x status=%r; CPU backup retained until platform reset\n",
    mStockResult.tcm_backup_words,mStockResult.tcm_backup_words*4,ShadowCrc,ShadowStatus);
  Print(L"HOUJI GPU STOCK: result=%u phase=%u attempted=%u fw-ready=%u fw-status=%08x HFI-ready=%u HFI-status=%08x query-sent=%u query-ack=%u query-value=%u query-status=%u reset-held=%u retained-until-platform-reset=1 elapsed-us=%lu\n",
    Result,mStockResult.phase,mStockResult.attempted,mStockResult.fw_ready,mStockResult.fw_status,
    mStockResult.hfi_ready,mStockResult.hfi_status,mStockResult.query_sent,mStockResult.query_ack,
    mStockResult.query_value,mStockResult.query_status,mStockResult.reset_held,BatchMicroseconds(Begin));
  Print(L"HOUJI GPU STOCK DETAIL: failed-phase=%u address=%08x value=%08x reads=%u writes=%u polls=%u TCM-backup=%u TCM-loaded=%u RSC-attempted=%u boot-attempted=%u stream-attached=%u counter=%08x/%08x GFSR=%08x FSR=%08x FAR=%lx FSYNR=%08x IRQ=%08x AO-IRQ=%08x save-allowed=%u\n",
    mStockResult.failed_phase,mStockResult.failed_address,mStockResult.failed_value,mStockResult.reads,
    mStockResult.writes,mStockResult.polls,mStockResult.tcm_backup_words,mStockResult.tcm_loaded_words,
    mStockResult.rsc_attempted,mStockResult.boot_attempted,mStockResult.stream_attached,mStockResult.counter_before,
    mStockResult.counter_after,mStockResult.gfsr,mStockResult.fsr,mStockResult.far,mStockResult.fsynr,
    mStockResult.irq,mStockResult.ao_irq,mGpuSaveAllowed);
  Print(L"HOUJI GPU STOCK FAILURE META: op=%u observed-valid=%u diagnostic-mask=%x last-SMMU=%08x/%lx; unknown read values are not evidence\n",
    mStockResult.failed_operation,mStockResult.failed_observed_valid,mStockResult.diagnostic_mask,
    mStockResult.context.last_address,mStockResult.context.last_value);
  for(unsigned I=0;I<mStockResult.reply_count;I++)Print(L"HOUJI GPU STOCK HFI REPLY: word=%u value=%08x\n",I,mStockResult.reply[I]);
  CONST struct hhb_result *Bootstrap=&mStockResult.bootstrap;
  Print(L"HOUJI GPU HWSCHED: result=%u stage=%u completed=%u debug=%u resource-request=%u resource-words=%u; bootstrap result, see separate CP INIT report\n",
    Bootstrap->code,Bootstrap->stage,Bootstrap->completed,Bootstrap->debug_count,
    Bootstrap->resource_request,Bootstrap->resource_words);
  for(unsigned I=0;I<HHB_STEPS;I++) {
    CONST struct hhb_record *R=&Bootstrap->record[I];if(!R->attempted)break;
    Print(L"HOUJI GPU HWSCHED STEP: stage=%u header=%08x sent=%u ack=%u value=%08x status=%08x status-present=%u legacy-contract=%u count=%u polls=%u\n",
      I+1,R->header,R->sent,R->ack,R->value,R->status,R->status_present,R->legacy_contract,R->count,R->polls);
    for(unsigned J=0;J<R->count && J<HHB_WORDS;J++)Print(L"HOUJI GPU HWSCHED REPLY: stage=%u word=%u value=%08x\n",I+1,J,R->reply[J]);
  }
  Print(L"HOUJI GPU SCRATCH CONTEXT: code=%u phase=%u attempted=%u enabled=%u attached=%u retained=%u reads=%u writes=%u polls=%u FSR=%08x last=%08x/%08x wide=%lx resource-seen=%u resource-acks=%u\n",
    mScratchResult.code,mScratchResult.phase,mScratchResult.attempted,mScratchResult.enabled,mScratchResult.attached,
    mScratchResult.retained,mScratchResult.reads,mScratchResult.writes,mScratchResult.polls,mScratchResult.fsr,
    mScratchResult.last_address,mScratchResult.last_value,mScratchResult.last_wide,Bootstrap->resource_count,Bootstrap->resource_acks);
  Print(L"HOUJI GPU SCRATCH META: op=%u observed-valid=%u; failed read output is not evidence\n",mScratchResult.last_operation,mScratchResult.observed_valid);
  Print(L"HOUJI GPU SCRATCH ROUTES: LPAC-profile=%u SID0-proof=%u LPAC-proof=%u SID0-SMR=%08x S2CR=%08x LPAC-SMR=%08x S2CR=%08x; normal bank0 only, secure SID2 remains FAULT; no observed SQE SID\n",
    mScratchResult.lpac,mScratchResult.sid0_attached,mScratchResult.lpac_attached,
    mScratchResult.sid0_smr,mScratchResult.sid0_s2cr,mScratchResult.lpac_smr,mScratchResult.lpac_s2cr);
  Print(L"HOUJI GPU SCRATCH FAULT: valid=%x FSR=%08x FAR=%lx FSYNR=%08x; raw values require valid mask and active fault bits\n",ScratchDiag,ScratchFsr,ScratchFar,ScratchFsynr);
  Print(L"HOUJI GPU SHARED ARENA: bytes=%u allocated=%u cursors=%u/%u/%u/%u; four exact GFX permission classes, all pages retained until platform reset\n",
    HSC_POOL_BYTES,mSharedCount,mSharedNext[0],mSharedNext[1],mSharedNext[2],mSharedNext[3]);
  Print(L"HOUJI GPU GMU-ONLY ARENA: IOVA=%08x bytes=%u cursor=%u; no GPU alias, privileged RW-executable device mapping follows vendor get_attrs; no CPU executable mapping requested\n",HSC_GMU_ONLY_IOVA,HSC_POOL_BYTES,mGmuOnlyNext);
  Print(L"HOUJI GPU LARGE SHARED ARENA: IOVA=%08x bytes=%u cursor=%u; privileged RW NX in both device graphs, retained until reset\n",HSC_LARGE_IOVA,HSC_LARGE_BYTES,mLargeNext);
  for(unsigned I=0;I<HSC_CLASSES;I++)Print(L"HOUJI GPU GPU-ONLY ARENA: class=%u IOVA=%08x cursor=%u GMU-alias=0\n",I,HSC_GPU_ONLY_IOVA,mGpuOnlyNext[I]);
  for(unsigned I=0;I<Bootstrap->resource_count && I<HSC_MAX_RESOURCES;I++) {
    Print(L"HOUJI GPU RESOURCE: index=%u words=%u handled=%u ACK-sent=%u\n",I,Bootstrap->resources[I].count,Bootstrap->resources[I].handled,Bootstrap->resources[I].sent);
    for(unsigned J=0;J<Bootstrap->resources[I].count && J<HHB_WORDS;J++)Print(L"HOUJI GPU RESOURCE REQUEST: index=%u word=%u value=%08x\n",I,J,Bootstrap->resources[I].request[J]);
    if(Bootstrap->resources[I].handled)for(unsigned J=0;J<11;J++)Print(L"HOUJI GPU RESOURCE RESPONSE: index=%u word=%u value=%08x\n",I,J,Bootstrap->resources[I].response[J]);
  }
  // Shared log and queue snapshots touch only retained Normal-NC host RAM.
  // CM3 reset was attempted above; these diagnostics never read GX registers.
  if(mFirmwareHeld && mFirmwareMemory.retained==HFM_ALL) {
    volatile UINT32 *Log=mFirmwareMemory.memory[6].cpu;
    for(unsigned I=0;I<256;I++)Print(L"HOUJI GPU FW LOG: word=%u value=%08x\n",I,Log[I]);
    struct ggh_io Hfi={mFirmwareMemory.memory[5].cpu,GGH_BYTES,GGH_IOVA,NULL,StockHfiBarrier};
    for(unsigned I=0;I<17;I++) {
      volatile UINT32 *Header=NULL,*Ring=NULL;unsigned Read=0,Write=0;
      int QueueStatus=ggh_queue(&Hfi,I,&Header,&Ring,&Read,&Write);
      Print(L"HOUJI GPU HWSCHED QUEUE: q=%u code=%u read=%u write=%u\n",I,QueueStatus,Read,Write);
    }
  }
  // Retain both diagnostic PRR pages and stock memory/gates until reset,
  // irrespective of the result. No outstanding-DMA drain is assumed.
  return HGB_RETAIN;
}
STATIC int ContextDelay(VOID *Cookie,unsigned Us) {return Delay(Cookie,Us)?1:0;}
STATIC int ContextCheckpoint(VOID *Cookie,unsigned Stage) {return GmuCheckpoint(Cookie,Stage+8)?1:0;}
STATIC int DmaRead64(VOID *Cookie,uint32_t Address,uint64_t *Value) {
  if(Address!=HGP_CB(0x60))return ContextRead64(Cookie,Address,Value);
  return GpuTryRead64(Address,Value)?1:0;
}
STATIC int DmaWrite32(VOID *Cookie,uint32_t Address,uint32_t Value) {
  (VOID)Cookie;
  if(!mDmaCalled || !mDmaZeroRetained)return 1;
  BOOLEAN Allowed=(Address==HGP_CB(0) && (Value==0 || Value==0x1027)) ||
    (Address==HGP_CB(0x4) && (Value==3 || Value==0x32b)) ||
    (Address==0x3da6008 && (Value==0 || Value==(UINT32)mDmaZeroPhysical)) ||
    (Address==0x3da600c && (Value==0 || Value==(UINT32)(mDmaZeroPhysical>>32))) ||
    (Address==0x3da0800 && (Value==0 || Value==0x80000005u)) ||
    (Address==0x3da0c00 && (Value==HGP_CONTEXT_BANK || Value==0x20000)) ||
    (Address==HGP_CB(0x58) && Value==2) || (Address==HGP_CB(0x618) && Value==0) ||
    (Address==HGP_CB(0x7f0) && Value==0xffffffffu);
  if(!Allowed)return 1;
  MmioWrite32(Address,Value);__asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC GPP_U64 DmaGmuRead(VOID *Cookie,GPP_U32 Address,GPP_U32 *Value) {
  if(!hga_tcm_address_valid(Address))return GmuRead(Cookie,Address,Value);
  *Value=MmioRead32(Address);__asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC GPP_U64 DmaGmuWrite(VOID *Cookie,GPP_U32 Address,GPP_U32 Value) {
  if(!hga_tcm_address_valid(Address))return GmuWrite(Cookie,Address,Value);
  MmioWrite32(Address,Value);__asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC int PublishDmaMemory(VOID *Cookie,CONST struct hgt_owned *Owned,uint64_t Zero,VOID *ZeroCpu) {
  (VOID)Cookie;UINT64 Ctr=0;
  if(Owned!=&mTableOwned || Zero!=mDmaZeroPhysical || ZeroCpu!=mDmaZero ||
     !mDmaZeroRetained || TableValidate(NULL,Zero,ZeroCpu,1) ||
     !hga_zero_valid(Owned,Zero,ZeroCpu))return 1;
  __asm__ volatile("mrs %0, ctr_el0":"=r"(Ctr));
  CONST struct hgc_io Publish={NULL,TableValidate,CacheCleanLine,CachePublishBarrier};
  if(hgc_publish(&Publish,Owned,Ctr,&mCacheResult))return 1;
  for(unsigned Offset=0;Offset<4096;Offset+=mCacheResult.line_bytes)
    if(CacheCleanLine(NULL,(uintptr_t)ZeroCpu+Offset))return 1;
  if(CachePublishBarrier(NULL) || !hga_zero_valid(Owned,Zero,ZeroCpu))return 1;
  return 0;
}
STATIC int DmaInvalidateLine(VOID *Cookie,uintptr_t Address) {
  (VOID)Cookie;uintptr_t Data=(uintptr_t)mTableOwned.data;unsigned Line=mCacheResult.line_bytes;
  if(!mDmaCalled || !mDmaZeroRetained || Line<16 || Line>4096 ||
     (Address&(Line-1)) || Address<Data || Address-Data>=4096)return 1;
  __asm__ volatile("dc ivac, %0"::"r"(Address):"memory");return 0;
}
STATIC int DmaCpuFinish(VOID *Cookie,CONST struct hgt_owned *Owned,struct hga_cpu_result *Result) {
  (VOID)Cookie;if(Owned!=&mTableOwned)return 1;
  CONST struct hga_cpu_io Io={NULL,mCacheResult.line_bytes,DmaInvalidateLine,CacheCleanLine,CachePublishBarrier};
  return hga_cpu_finish(&Io,Owned,Result);
}
STATIC int DmaCheckpoint(VOID *Cookie,unsigned Stage) {return GmuCheckpoint(Cookie,Stage+13)?1:0;}
STATIC unsigned RunDmaVisitor(VOID *Cookie,CONST struct hgp_io *Context,
    CONST struct hgt_owned *Owned,CONST uint64_t *Image) {
  (VOID)Cookie;(VOID)Context;
  CONST struct hga_io Io={
    {NULL,ContextRead32,DmaRead64,DmaWrite32,ContextWrite64,ContextDelay,ContextPowerGuard,NULL},
    {NULL,DmaGmuRead,DmaGmuWrite,Delay,NULL},NULL,PublishDmaMemory,DmaCpuFinish,DmaCheckpoint};
  mDmaCalled=TRUE;
  return hga_probe(&Io,Owned,Image,mDmaZeroPhysical,mDmaZero,&mDmaResult);
}
STATIC unsigned RunDisabledContext(VOID) {
  CONST struct hgp_io Io={NULL,ContextRead32,ContextRead64,ContextWrite32,ContextWrite64,
    ContextDelay,ContextPowerGuard,ContextCheckpoint};
  mContextCalled=TRUE;
  if(GmuCheckpoint(NULL,12))return mContextResult.code=HGP_IO;
  unsigned Platform=hgs_snapshot(&Io,&mPlatformResult);
  Print(L"HOUJI GPU PLATFORM RO: result=%u stable=%u reads=%u ACTLR=%08x PRR-low=%08x PRR-high=%08x; observed only, no platform register writes\n",
    Platform,mPlatformResult.stable,mPlatformResult.reads,mPlatformResult.actlr,
    mPlatformResult.prr_low,mPlatformResult.prr_high);
  if(Platform)return mContextResult.code=Platform;
  if(GmuCheckpoint(NULL,13))return mContextResult.code=HGP_IO;
  return hgp_disabled_context_visit(&Io,&mTableOwned,&mContextResult,RunDmaVisitor,NULL);
}
STATIC VOID HoujiGpuBusProbe(CONST struct gpp_report *Report) {
  struct hgb_result Result;
  CONST struct hgb_io Io={(VOID *)Report,BusRead,BusWrite,Delay,RunGmuProbe};
  EFI_STATUS Status;
  if(!hgb_owned(Report))return;
  Status=MapMmio(0x3da0000,0x40000);
  Print(L"HOUJI GPU BUS: map=%r; temporary CFG/MEMNOC HWCG and SMMU clock vote; separate guarded CM3 internal diagnostic\n",Status);
  if(EFI_ERROR(Status))return;
  CONST struct hgt_io Tables={NULL,TableAllocate,TableValidate,TableRelease};
  if(EFI_ERROR(ProbeCheckpoint("before-owned-native4K-tables")))return;
  unsigned Prepared=hgt_prepare_owned(&Tables,&mTableResult,&mTableOwned);
  Print(L"HOUJI GPU OWNED TABLES: result=%u allocated=%x validated=%x retained=%x table-PA=%lx data-PA=%lx descriptor-reads=%u; not activated\n",
    Prepared,mTableResult.allocated,mTableResult.validated,mTableResult.retained,
    mTableResult.table_physical,mTableResult.data_physical,(UINT32)mTableResult.descriptor_reads);
  if(Prepared) {mGpuMustStop=mTableResult.retained!=0;(VOID)ProbeCheckpoint("owned-native4K-prepare-failed");return;}
  UINT64 Ctr=0;__asm__ volatile("mrs %0, ctr_el0":"=r"(Ctr));
  CONST struct hgc_io Publish={NULL,TableValidate,CacheCleanLine,CachePublishBarrier};
  unsigned Cache=hgc_publish(&Publish,&mTableOwned,Ctr,&mCacheResult);
  Print(L"HOUJI GPU CACHE PUBLISH: result=%u line=%u validated=%x lines=%u barriers=%u audits=%u descriptors=%u; CPU clean to PoC only, device DMA not qualified\n",
    Cache,mCacheResult.line_bytes,mCacheResult.validated,mCacheResult.cleaned_lines,
    mCacheResult.barriers,mCacheResult.audits,(UINT32)mCacheResult.descriptor_reads);
  if(Cache) {
    ReleaseOwnedTables();(VOID)ProbeCheckpoint("owned-native4K-publish-failed");return;
  }
  if(TableAllocate(NULL,1,&mDmaZeroPhysical,&mDmaZero)) {
    ReleaseOwnedTables();(VOID)ProbeCheckpoint("owned-PRR-allocation-failed");return;
  }
  mDmaZeroRetained=TRUE;
  if(TableValidate(NULL,mDmaZeroPhysical,mDmaZero,1)) {
    ReleaseOwnedTables();(VOID)ProbeCheckpoint("owned-PRR-mapping-failed");return;
  }
  for(unsigned I=0;I<1024;I++)((volatile UINT32 *)mDmaZero)[I]=0;
  Print(L"HOUJI GPU PRR: owned zero page PA=%lx; not installed until exclusive disabled-bank check\n",mDmaZeroPhysical);
  Status=ProbeCheckpoint("after-owned-native4K-tables");
  if(EFI_ERROR(Status)) {mGpuMustStop=TRUE;return;}
  EFI_TPL OldTpl=gBS->RaiseTPL(TPL_NOTIFY);
  unsigned Code=hgb_probe(&Io,Report,&Result);
  gBS->RestoreTPL(OldTpl);
  Print(L"HOUJI GPU BUS: result=%u failed-reg=%u valid=%x reads=%u polls=%u attempted=%x restored=%x acceleration=0\n",
    Code,Result.failed_reg,Result.valid,Result.reads,Result.polls,Result.attempted,Result.restored);
  if(mContextCalled)Print(L"HOUJI GPU CONTEXT WRAPPER: result=%u reads=%u writes=%u polls=%u backup=%u attempted=%x retired=%x safe-release=%u FSR=%08x last=%08x/%lx; separate owned DMA visitor\n",
    mContextResult.code,mContextResult.reads,mContextResult.writes,mContextResult.polls,
    mContextResult.backed_up,mContextResult.attempted,mContextResult.retired,mContextResult.safe_to_release,
    mContextResult.fsr,mContextResult.last_address,mContextResult.last_value);
  if(mDmaCalled)Print(L"HOUJI GPU DMA RESULT: result=%u phase=%u complete=%u retain=%u positive=%u negative=%u FSR=%08x FAR=%lx FSYNR=%08x CPU=%08x verified=%u restored=%u reset=%u detached=%u platform-retired=%u TCM=%u/%u controls=%x last-SMMU=%08x/%lx last-CM3=%08x/%08x; no GPU jobs\n",
    mDmaResult.code,mDmaResult.phase,mDmaResult.complete,mDmaResult.must_retain,mDmaResult.positive,mDmaResult.negative,
    mDmaResult.fsr,mDmaResult.far,mDmaResult.fsynr,mDmaResult.cpu.observed,mDmaResult.cpu.verified,mDmaResult.cpu.restored,
    mDmaResult.cm3.reset_held,mDmaResult.detached,mDmaResult.platform_retired,mDmaResult.restored,mDmaResult.backed_up,
    mDmaResult.control_restored,mDmaResult.regs.last_address,mDmaResult.regs.last_value,
    mDmaResult.cm3.last_address,mDmaResult.cm3.last_value);
  if(mDmaCalled)Print(L"HOUJI GPU DMA MAILBOX: %08x %08x %08x %08x %08x %08x %08x %08x; bank=%u GPU-banks0/1 untouched\n",
    mDmaResult.mailbox[0],mDmaResult.mailbox[1],mDmaResult.mailbox[2],mDmaResult.mailbox[3],
    mDmaResult.mailbox[4],mDmaResult.mailbox[5],mDmaResult.mailbox[6],mDmaResult.mailbox[7],HGP_CONTEXT_BANK);
  if(Code==HGB_RETAIN || (mContextCalled && !mContextResult.safe_to_release) ||
     (mDmaCalled && mDmaResult.must_retain))mGpuMustStop=TRUE;
  if(!mGpuMustStop)ReleaseOwnedTables();
  Print(L"HOUJI GPU OWNED TABLES: released=%x retained=%x PRR-zero-retained=%u must-stop=%u; GMU owned-page diagnostic only\n",mTableResult.released,mTableResult.retained,mDmaZeroRetained,mGpuMustStop);
  if(mGmuCalled)Print(L"HOUJI GMU TCM: result=%u reads=%u writes=%u polls=%u backup=%u modified=%u release-attempted=%u reset-held=%u restored=%u retained=%u last-address=%08x last-value=%08x mailbox=%08x,%08x,%08x GFSR=%08x acceleration=0\n",
    mGmuResult.code,mGmuResult.reads,mGmuResult.writes,mGmuResult.polls,mGmuResult.backup_words,
    mGmuResult.modified,mGmuResult.release_attempted,mGmuResult.reset_held,mGmuResult.restored_words,
    mGmuResult.retained,mGmuResult.last_address,mGmuResult.last_value,mGmuResult.mailbox[0],
    mGmuResult.mailbox[1],mGmuResult.mailbox[2],mGmuResult.gfsr);
  if(mGmuCalled)Print(L"HOUJI GMU CONTROL: attempted=%x restored=%x IRQ-masks-retained=%x until reset\n",
    mGmuResult.control_attempted,mGmuResult.control_restored,mGmuResult.control_attempted&0x180u);
  if(mGmuResult.verify_address)Print(L"HOUJI GMU CONTROL VERIFY: address=%08x value=%08x expected=%08x mask=%08x\n",
    mGmuResult.verify_address,mGmuResult.verify_value,mGmuResult.verify_expected,mGmuResult.verify_mask);
  if((Result.valid&0x1f00)==0x1f00)
    Print(L"HOUJI GPU BUS: SMMU ID0=%08x ID1=%08x ID2=%08x CR0=%08x GFSR=%08x; survey captured before separate context test\n",
      Result.values[HGB_ID0],Result.values[HGB_ID1],Result.values[HGB_ID2],Result.values[HGB_CR0],Result.values[HGB_GFSR]);
  Print(L"HOUJI GPU BUS: survey streams=%u/24 banks=%u/22 active-streams=%u nonfault-routes=%u active-banks=%u FWINIT=%08x GXPOWER=%08x valid=%x\n",
    Result.streams_seen,Result.banks_seen,Result.active_streams,Result.nonfault_routes,Result.active_banks,
    Result.values[HGB_FWINIT],Result.values[HGB_GXPOWER],Result.valid);
  for(unsigned I=0;I<Result.streams_seen;I++)
    Print(L"HOUJI GPU BUS: stream=%u SMR=%08x S2CR=%08x\n",I,Result.smr[I],Result.s2cr[I]);
  for(unsigned I=0;I<Result.banks_seen;I++)
    Print(L"HOUJI GPU BUS: bank=%u SCTLR=%08x\n",I,Result.sctlr[I]);
}
BOOLEAN HoujiGpuMayBoot(VOID) {return !mGpuMustStop;}
BOOLEAN HoujiGpuMaySave(VOID) {return mGpuSaveAllowed;}
VOID HoujiGpuPowerPrepare(EFI_HANDLE ImageHandle) {
  struct gpp_report Report;
  mGpuBatchStart=BatchCounter();
  EFI_STATUS Pdc=MapMmio(0xb284000,0x2000);
  Print(L"HOUJI GPU STOCK: PDC map=%r; own FDT gmu_pdc 0xb280000/0x10000\n",Pdc);
  unsigned Firmware=PrepareFirmwareBatch(ImageHandle,TRUE);
  Print(L"HOUJI GPU BATCH: firmware-memory result=%u; independent power/DMA diagnostics follow unless memory cleanup uncertain\n",Firmware);
  if(Firmware){mGpuMustStop=TRUE;return;}
  if(PrepareGxMapping()) {mGpuMustStop=TRUE;return;}
  if(Gen7PrepareMapping()) {mGpuMustStop=TRUE;return;}
  if(PrepareScratchMemory(ImageHandle)) {
    Print(L"HOUJI GPU SCRATCH MEMORY: failed; any allocated tables and firmware pages retained until reset\n");mGpuMustStop=TRUE;return;
  }
  if(EFI_ERROR(Pdc)){mGpuMustStop=TRUE;return;}
  if(EFI_ERROR(ProbeCheckpoint("before-native-GPU-power")))return;
  // Requests are the pristine zero-result structure; only returned reports are sealed.
  gpp_report_init(&Report);
  EFI_STATUS Status=Prepare(&Report,sizeof(Report));
  Print(L"HOUJI GPU POWER: preparation=%r code=%u phase=%u resource=%u attempted=%x confirmed=%x flags=%x native-status=%lx preparation-reset-not-released=1 acceleration=0\n",
    Status,Report.code,Report.phase,Report.resource,Report.attempted,Report.confirmed,Report.flags,Report.firmware_status);
  if(EFI_ERROR(ProbeCheckpoint("after-native-GPU-power-before-bus")))return;
  // A live branch is not permission to retune it. Inspect this known partial
  // result using only configured-rate queries and CX AHB observations.
  if(Report.code==GPP_ERR_INITIAL && Report.phase==GPP_PHASE_CLOCKS &&
     Report.resource==GPP_GMU_CLK && (Report.confirmed&0x1002)==0x1002 &&
     mClock && mClock->GetClockFreqHz) {
    UINT32 GmuHz=0,HubHz=0;
    EFI_STATUS GmuStatus=mClock->GetClockFreqHz(mClock,mIds[GPP_GMU_RATE],&GmuHz);
    EFI_STATUS HubStatus=mClock->GetClockFreqHz(mClock,mIds[GPP_HUB_RATE],&HubHz);
    Print(L"HOUJI GPU INHERITED RO: GMU configured=%u status=%r HUB configured=%u status=%r; configured value is not measured frequency\n",
      GmuHz,GmuStatus,HubHz,HubStatus);
    UINT32 Cx=MmioRead32(0x3d99108),Hw=MmioRead32(0x3d99168),Ahb=MmioRead32(0x3d9911c);
    if(!(Cx&1) && (Hw&0x80000000u) && !(Ahb&0x80000000u)) {
      Print(L"HOUJI GPU INHERITED RO: CM3_SYSRESET=%08x GMU_RCG_CMD=%08x GMU_RCG_CFG=%08x HUB_RCG_CMD=%08x HUB_RCG_CFG=%08x; no resets or rate writes\n",
        MmioRead32(0x3d7e000),MmioRead32(0x3d99318),MmioRead32(0x3d9931c),
        MmioRead32(0x3d993ec),MmioRead32(0x3d993f0));
    } else {
      Print(L"HOUJI GPU INHERITED RO: CX/AHB guard refused CM3 read; CX=%08x HW=%08x AHB=%08x\n",Cx,Hw,Ahb);
    }
  }
  HoujiGpuBusProbe(&Report);
}

// r140 power-only entry: existing helpers are defined above; no full GPU path.
#include "GpuPowerOnlyAdapter.inc"
