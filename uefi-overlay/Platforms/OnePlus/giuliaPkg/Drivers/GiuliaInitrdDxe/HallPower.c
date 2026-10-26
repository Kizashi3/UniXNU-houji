/** @file
  Opt-in Ace 5 AK09970 VCC preparation through native CmdDb and RPMh.
  Board evidence: running-device.dts magnachip@10 -> pm_humu_l1 -> ldob1.
  ABI evidence: the same pinned firmware interfaces used by TouchPower.c.
  SPDX-License-Identifier: BSD-2-Clause-Patent
**/
#include <Uefi.h>
#include <Library/DebugLib.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Library/UefiRuntimeServicesTableLib.h>
#include "PayloadIdentity.h"
#define GHP_FIRMWARE_TYPES
#include "HallPreparePolicy.h"

VOID GiuliaHallPowerSchedule (VOID);
BOOLEAN GiuliaHallPowerIsReady (VOID);

#if defined(GIULIA_HALL_PREPARE) && GIULIA_HALL_PREPARE
typedef struct { UINT64 Version; VOID *Methods[24]; } HALL_RPMH;
typedef struct { UINT64 Version; VOID *Methods[8]; } HALL_CMDDB;
typedef EFI_STATUS (EFIAPI *HALL_QUERY)(HALL_CMDDB *, CONST CHAR8 *, UINT32 *);
typedef EFI_STATUS (EFIAPI *HALL_DRV_VALID)(UINT32, BOOLEAN *);
typedef EFI_STATUS (EFIAPI *HALL_CREATE)(UINT32, CONST CHAR8 *, VOID **);
typedef EFI_STATUS (EFIAPI *HALL_ISSUE)(VOID *, UINT32, BOOLEAN, UINT32, UINT32, UINT32 *);
typedef EFI_STATUS (EFIAPI *HALL_WAIT)(VOID *, UINT32);
STATIC EFI_GUID mHallRpmhGuid = {0xe1d0b573,0xf29f,0x495d,{0x93,0x52,0xca,0x0d,0xd4,0x2a,0x0a,0x74}};
STATIC EFI_GUID mHallCmdGuid = {0x1c34f691,0xd33d,0x4e14,{0xb8,0xf8,0x32,0xc6,0xc0,0x29,0xe9,0x5b}};
STATIC EFI_GUID mHallPowerStatusGuid = {0x1c87b711,0xeaa6,0x42cb,{0xa3,0xd5,0x8c,0x21,0x19,0x65,0x21,0x31}};
STATIC EFI_EVENT mHallPowerEvent[2];
STATIC VOID *mHallPowerRegistration[2], *mHallPowerClient;
STATIC HALL_RPMH *mHallRpmh;
STATIC HALL_CMDDB *mHallDb;
STATIC BOOLEAN mHallPowerAttempted, mHallPowerScheduled;
STATIC struct ghp_result mHallPowerResult;

STATIC VOID HallPowerReport (UINT32 Stage, UINT32 Address, EFI_STATUS Status)
{
  struct { UINT32 Stage, Address; UINT64 Status; } Value = {Stage,Address,(UINT64)Status};
  (VOID)gRT->SetVariable (L"GiuliaHallPowerStatus",&mHallPowerStatusGuid,
      EFI_VARIABLE_BOOTSERVICE_ACCESS | EFI_VARIABLE_RUNTIME_ACCESS,sizeof(Value),&Value);
}
STATIC GHP_U64 HallPowerResolve (VOID *Context, GHP_U32 *Address, GHP_U32 *Slave)
{
  EFI_STATUS Status;
  (VOID)Context;
  if (mHallRpmh->Version != 0x10001 || mHallDb->Version != 0x10000 ||
      !mHallRpmh->Methods[1] || !mHallRpmh->Methods[5] ||
      !mHallRpmh->Methods[18] || !mHallRpmh->Methods[11] ||
      !mHallDb->Methods[1] || !mHallDb->Methods[7]) { return EFI_UNSUPPORTED; }
  Status = ((HALL_QUERY)mHallDb->Methods[1])(mHallDb,"ldob1",Address);
  if (EFI_ERROR (Status)) { return Status; }
  Status = ((HALL_QUERY)mHallDb->Methods[7])(mHallDb,"ldob1",Slave);
  DEBUG ((DEBUG_ERROR,"GIULIA HALL POWER: ldob1 address=%x slave=%u status=%r\n",*Address,*Slave,Status));
  return Status;
}
STATIC GHP_U64 HallPowerCreate (VOID *Context)
{
  EFI_STATUS Status;
  BOOLEAN Valid = FALSE;
  (VOID)Context;
  Status = ((HALL_DRV_VALID)mHallRpmh->Methods[1])(2,&Valid);
  if (EFI_ERROR (Status) || !Valid) { return EFI_ERROR (Status) ? Status : EFI_UNSUPPORTED; }
  Status = ((HALL_CREATE)mHallRpmh->Methods[5])(2,"giulia-hall-vcc",&mHallPowerClient);
  return (!EFI_ERROR (Status) && !mHallPowerClient) ? EFI_DEVICE_ERROR : Status;
}
STATIC GHP_U64 HallPowerIssue (VOID *Context, GHP_U32 Address, GHP_U32 Value, GHP_U32 *Request)
{
  EFI_STATUS Status;
  (VOID)Context;
  Status = ((HALL_ISSUE)mHallRpmh->Methods[18])(mHallPowerClient,0,TRUE,Address,Value,Request);
  DEBUG ((DEBUG_ERROR,"GIULIA HALL POWER: address=%x value=%u request=%u status=%r\n",Address,Value,*Request,Status));
  return Status;
}
STATIC GHP_U64 HallPowerWait (VOID *Context, GHP_U32 Request)
{
  (VOID)Context;
  /* Native churn_single completes this request; barrier_single is a stub. */
  return ((HALL_WAIT)mHallRpmh->Methods[11])(mHallPowerClient,Request);
}
STATIC VOID EFIAPI HallPowerNotify (EFI_EVENT Event, VOID *Context)
{
  EFI_STATUS Status;
  UINTN Index;
  CONST struct ghp_power_io Io = {NULL,HallPowerResolve,HallPowerCreate,HallPowerIssue,HallPowerWait};
  (VOID)Event; (VOID)Context;
  if (mHallPowerAttempted) { return; }
  Status = gBS->LocateProtocol (&mHallRpmhGuid,NULL,(VOID **)&mHallRpmh);
  if (EFI_ERROR (Status)) { HallPowerReport(1,0,Status);return; }
  Status = gBS->LocateProtocol (&mHallCmdGuid,NULL,(VOID **)&mHallDb);
  if (EFI_ERROR (Status)) { HallPowerReport(2,0,Status);return; }
  mHallPowerAttempted = TRUE;
  for (Index=0;Index<2;Index++) {
    if (mHallPowerEvent[Index]) { gBS->CloseEvent(mHallPowerEvent[Index]);mHallPowerEvent[Index]=NULL; }
  }
  (VOID)ghp_power_prepare(&Io,&mHallPowerResult);
  Status = (EFI_STATUS)mHallPowerResult.status;
  if (mHallPowerResult.code && !EFI_ERROR(Status)) { Status=EFI_UNSUPPORTED; }
  HallPowerReport(mHallPowerResult.stage,mHallPowerResult.address,Status);
  /* Retain successful and uncertain ACTIVE votes; do not disable a shared rail. */
  DEBUG ((DEBUG_ERROR,"GIULIA HALL POWER: stage=%u ready=%u code=%u status=%r\n",
      mHallPowerResult.stage,mHallPowerResult.ready,mHallPowerResult.code,Status));
}
#endif

BOOLEAN GiuliaHallPowerIsReady (VOID)
{
#if defined(GIULIA_HALL_PREPARE) && GIULIA_HALL_PREPARE
  return mHallPowerResult.ready != 0;
#else
  return FALSE;
#endif
}
VOID GiuliaHallPowerSchedule (VOID)
{
#if defined(GIULIA_HALL_PREPARE) && GIULIA_HALL_PREPARE
  EFI_STATUS Status;
  EFI_GUID *Guids[2] = {&mHallRpmhGuid,&mHallCmdGuid};
  UINTN Index;
  if (mHallPowerScheduled) { return; }
  mHallPowerScheduled=TRUE;
  HallPowerReport(0,0,EFI_NOT_READY);
  for (Index=0;Index<2;Index++) {
    Status=gBS->CreateEvent(EVT_NOTIFY_SIGNAL,TPL_CALLBACK,HallPowerNotify,NULL,&mHallPowerEvent[Index]);
    if (EFI_ERROR(Status)) { HallPowerReport(0,0,Status);break; }
    Status=gBS->RegisterProtocolNotify(Guids[Index],mHallPowerEvent[Index],&mHallPowerRegistration[Index]);
    if (EFI_ERROR(Status)) { gBS->CloseEvent(mHallPowerEvent[Index]);mHallPowerEvent[Index]=NULL;HallPowerReport(0,0,Status);break; }
  }
  HallPowerNotify(NULL,NULL);
#endif
}
