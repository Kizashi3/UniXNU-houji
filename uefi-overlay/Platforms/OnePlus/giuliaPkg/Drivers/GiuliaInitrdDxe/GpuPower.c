/** @file
  Explicit SM8650 CX/GMU-clock preparation through the pinned ClockDxe.
  Native GDSC/RCG waits are not preemptible: begin/end diagnostics and the
  GPP_PROVIDER_UNBOUNDED flag state this limitation. Policy-owned polls and
  the AOP transaction have fixed bounds. No GPU reset release, SMMU writes,
  firmware execution, power removal or guessed regulator votes are performed.
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
#include "PayloadIdentity.h"

VOID GiuliaGpuPowerInstall (VOID);

#if defined(GIULIA_GPU_POWER) && GIULIA_GPU_POWER
#define GPP_FIRMWARE_TYPES 1
#include "GpuPowerPolicy.h"
#include "GpuQmpTransport.h"

typedef struct {
  UINT64 Version;
  EFI_STATUS (EFIAPI *Prepare)(struct gpp_report *,UINTN);
} GPP_PROTOCOL;

STATIC EFI_GUID mGpuPowerGuid=GPP_PROTOCOL_GUID;
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
  DEBUG((DEBUG_ERROR,"GIULIA GPU POWER: native begin op=%a resource=%u name=%a requested=%u provider_wait=not-preemptible\n",
    Operation,Resource,gpp_resource_name(Resource),Requested));
}
STATIC VOID CallEnd (CONST CHAR8 *Operation,unsigned Resource,EFI_STATUS Status,UINT32 Actual)
{
  DEBUG((DEBUG_ERROR,"GIULIA GPU POWER: native end op=%a resource=%u status=%lx actual=%u\n",
    Operation,Resource,(UINT64)Status,Actual));
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
  DEBUG((DEBUG_ERROR,"GIULIA GPU POWER: ClockDxe locate status=%lx\n",(UINT64)Status));
  if(EFI_ERROR(Status))return Status;
  if(mClock==NULL || mClock->Version!=0x1000a || !mClock->GetClockID ||
     !mClock->GetClockPowerDomainID || !mClock->EnableClockPowerDomain ||
     !mClock->EnableClock || !mClock->SetClockFreqHz || !mClock->GetClockFreqHz ||
     !mClock->IsClockEnabled || !mClock->IsClockOn)return EFI_UNSUPPORTED;
  DEBUG((DEBUG_ERROR,"GIULIA GPU POWER: ClockDxe ABI=%lx; native GDSC/RCG waits may not return; policy polls alone are bounded\n",mClock->Version));
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
    DEBUG((DEBUG_ERROR,"GIULIA GPU POWER: map base=%lx bytes=%lx status=%lx\n",Maps[I][0],Maps[I][1],(UINT64)Status));
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
      DEBUG((DEBUG_ERROR,"GIULIA GPU POWER: inherited enabled resource=%u on=%u; retaining native state\n",Id,On));
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
  DEBUG((DEBUG_ERROR,"GIULIA GPU POWER: AOP native-provider query status=%lx present=%u\n",
    (UINT64)Status,NativeProvider!=NULL));
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
  DEBUG((DEBUG_ERROR,"GIULIA GPU POWER: AOP open code=%u phase=%u leased=%u owned=%u\n",
    Error,mQmp.phase,mQmp.leased,mQmp.owned));
  if(!Error) {
    Error=qpt_send(&Io,&mQmp,Message,sizeof(Message));
    DEBUG((DEBUG_ERROR,"GIULIA GPU POWER: AOP acd=0 send code=%u phase=%u pending=%u publication=%u elapsed_us=%Lu\n",
      Error,mQmp.phase,mQmp.pending,mQmp.publication_verified,mQmp.wait_elapsed_us));
  }
  if(!Error) {
    Error=qpt_close(&Io,&mQmp);
    DEBUG((DEBUG_ERROR,"GIULIA GPU POWER: AOP close code=%u phase=%u leased=%u owned=%u pending=%u\n",
      Error,mQmp.phase,mQmp.leased,mQmp.owned,mQmp.pending));
  }
  /* Even a refusal before our channel write can mean inherited ownership or
   * an invalid shared descriptor. Do not let a later XNU client reinterpret
   * a transiently empty channel as permission to take it over.
   */
  if(Error)mQmpUncertain=TRUE;
  gBS->RestoreTPL(OldTpl);
  if(Error) {
    DEBUG((DEBUG_ERROR,"GIULIA GPU POWER: AOP failed code=%u phase=%u last_offset=%x last_value=%x retain=%u; CX blocked\n",
      Error,mQmp.phase,mQmp.last_offset,mQmp.last_value,mQmpUncertain));
    return Error==QPT_TIMEOUT?EFI_TIMEOUT:Error==QPT_BUSY?EFI_ACCESS_DENIED:EFI_DEVICE_ERROR;
  }
  DEBUG((DEBUG_ERROR,"GIULIA GPU POWER: AOP acd=0 consumed and channel closed; transport acknowledgement is not ACD hardware readback\n"));
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
  DEBUG((DEBUG_ERROR,"GIULIA GPU POWER: explicit native preparation begin; no reset release or SMMU writes; firmware waits may not return\n"));
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
  DEBUG((DEBUG_ERROR,"GIULIA GPU POWER: result code=%u phase=%u attempted=%x confirmed=%x retained=%u flags=%x status=%lx hardware_ready=0 acceleration=0\n",
    Code,mReport.phase,mReport.attempted,mReport.confirmed,mReport.retained,mReport.flags,mReport.firmware_status));
  return Code?EFI_DEVICE_ERROR:EFI_SUCCESS;
}
STATIC GPP_PROTOCOL mProtocol={GPP_PROTOCOL_VERSION,Prepare};
#endif

VOID GiuliaGpuPowerInstall (VOID)
{
#if defined(GIULIA_GPU_POWER) && GIULIA_GPU_POWER
  EFI_HANDLE Handle=NULL;
  EFI_STATUS Status=gBS->InstallMultipleProtocolInterfaces(&Handle,&mGpuPowerGuid,&mProtocol,NULL);
  DEBUG((DEBUG_ERROR,"GIULIA GPU POWER: prepare protocol v1 installed status=%lx\n",(UINT64)Status));
#endif
}
