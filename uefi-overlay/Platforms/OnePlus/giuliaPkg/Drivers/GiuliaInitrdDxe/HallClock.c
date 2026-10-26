/** @file
  Opt-in Ace 5 I2C hub8 clocks through pinned native ClockDxe.
  Exact names occur in the stock ClockDxe and vendor GCC driver.
  No raw clock/pin/reset programming. SPDX-License-Identifier: BSD-2-Clause-Patent
**/
#include <Uefi.h>
#include <Library/DebugLib.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Library/UefiRuntimeServicesTableLib.h>
#include <Protocol/EFIClock.h>
#include "PayloadIdentity.h"
#define GHP_FIRMWARE_TYPES
#include "HallPreparePolicy.h"

VOID GiuliaHallClockSchedule (VOID);
BOOLEAN GiuliaHallClockIsReady (VOID);

#if defined(GIULIA_HALL_PREPARE) && GIULIA_HALL_PREPARE
STATIC EFI_EVENT mHallClockEvent;
STATIC VOID *mHallClockRegistration;
STATIC EFI_CLOCK_PROTOCOL *mHallClock;
STATIC UINTN mHallClockId[3];
STATIC BOOLEAN mHallClockAttempted, mHallClockScheduled;
STATIC struct ghp_result mHallClockResult;
STATIC CONST CHAR8 *mHallClockNames[3] = {
  "gcc_qupv3_i2c_core_clk", "gcc_qupv3_i2c_s_ahb_clk", "gcc_qupv3_i2c_s8_clk"
};
STATIC EFI_GUID mHallClockStatusGuid = {0x1c87b711,0xeaa6,0x42cb,{0xa3,0xd5,0x8c,0x21,0x19,0x65,0x21,0x31}};
STATIC VOID HallClockReport (UINT32 Stage, UINT32 Index, EFI_STATUS Status)
{
  struct { UINT32 Stage, Index; UINT64 Status; } Value = {Stage,Index,(UINT64)Status};
  (VOID)gRT->SetVariable(L"GiuliaHallClockStatus",&mHallClockStatusGuid,
      EFI_VARIABLE_BOOTSERVICE_ACCESS | EFI_VARIABLE_RUNTIME_ACCESS,sizeof(Value),&Value);
}
STATIC GHP_U64 HallClockResolve (VOID *Context)
{
  EFI_STATUS Status;
  UINTN Index;
  (VOID)Context;
  if (mHallClock->Version!=0x1000a || !mHallClock->GetClockID || !mHallClock->SetClockFreqHz ||
      !mHallClock->GetClockFreqHz || !mHallClock->EnableClock || !mHallClock->IsClockOn) { return EFI_UNSUPPORTED; }
  for (Index=0;Index<3;Index++) {
    mHallClockResult.address=(UINT32)Index;
    Status=mHallClock->GetClockID(mHallClock,mHallClockNames[Index],&mHallClockId[Index]);
    DEBUG ((DEBUG_ERROR,"GIULIA HALL CLOCK: lookup %a status=%r\n",mHallClockNames[Index],Status));
    if (EFI_ERROR(Status)) { return Status; }
  }
  return EFI_SUCCESS;
}
STATIC GHP_U64 HallClockRate (VOID *Context, GHP_U32 Hz, GHP_U32 *Actual)
{
  EFI_STATUS Status;
  (VOID)Context;
  Status=mHallClock->SetClockFreqHz(mHallClock,mHallClockId[2],Hz,EFI_CLOCK_FREQUENCY_HZ_EXACT,Actual);
  DEBUG ((DEBUG_ERROR,"GIULIA HALL CLOCK: set rate actual=%u status=%r\n",*Actual,Status));
  return Status;
}
STATIC GHP_U64 HallClockGetRate (VOID *Context, GHP_U32 *Actual)
{
  (VOID)Context;
  return mHallClock->GetClockFreqHz(mHallClock,mHallClockId[2],Actual);
}
STATIC GHP_U64 HallClockEnable (VOID *Context, unsigned Index)
{
  (VOID)Context;
  return mHallClock->EnableClock(mHallClock,mHallClockId[Index]);
}
STATIC GHP_U64 HallClockOn (VOID *Context, unsigned Index, GHP_U32 *On)
{
  EFI_STATUS Status;
  BOOLEAN IsOn=FALSE;
  (VOID)Context;
  Status=mHallClock->IsClockOn(mHallClock,mHallClockId[Index],&IsOn);
  *On=IsOn ? 1 : 0;
  DEBUG ((DEBUG_ERROR,"GIULIA HALL CLOCK: enable %a on=%u status=%r\n",mHallClockNames[Index],*On,Status));
  return Status;
}
STATIC VOID EFIAPI HallClockNotify (EFI_EVENT Event, VOID *Context)
{
  EFI_STATUS Status;
  CONST struct ghp_clock_io Io={NULL,HallClockResolve,HallClockRate,HallClockGetRate,HallClockEnable,HallClockOn};
  (VOID)Event; (VOID)Context;
  if (mHallClockAttempted) { return; }
  Status=gBS->LocateProtocol(&gEfiClockProtocolGuid,NULL,(VOID **)&mHallClock);
  if (EFI_ERROR(Status)) { HallClockReport(1,0,Status);return; }
  mHallClockAttempted=TRUE;
  if (mHallClockEvent) { gBS->CloseEvent(mHallClockEvent);mHallClockEvent=NULL; }
  (VOID)ghp_clock_prepare(&Io,&mHallClockResult);
  Status=(EFI_STATUS)mHallClockResult.status;
  if (mHallClockResult.code && !EFI_ERROR(Status)) { Status=EFI_UNSUPPORTED; }
  HallClockReport(mHallClockResult.stage,mHallClockResult.address,Status);
  /* Keep native votes through kernel handoff, including partial/unknown results. */
  DEBUG ((DEBUG_ERROR,"GIULIA HALL CLOCK: stage=%u ready=%u code=%u status=%r\n",
      mHallClockResult.stage,mHallClockResult.ready,mHallClockResult.code,Status));
}
#endif

BOOLEAN GiuliaHallClockIsReady (VOID)
{
#if defined(GIULIA_HALL_PREPARE) && GIULIA_HALL_PREPARE
  return mHallClockResult.ready != 0;
#else
  return FALSE;
#endif
}
VOID GiuliaHallClockSchedule (VOID)
{
#if defined(GIULIA_HALL_PREPARE) && GIULIA_HALL_PREPARE
  EFI_STATUS Status;
  if (mHallClockScheduled) { return; }
  mHallClockScheduled=TRUE;
  HallClockReport(0,0,EFI_NOT_READY);
  Status=gBS->CreateEvent(EVT_NOTIFY_SIGNAL,TPL_CALLBACK,HallClockNotify,NULL,&mHallClockEvent);
  if (EFI_ERROR(Status)) { HallClockReport(0,0,Status);return; }
  Status=gBS->RegisterProtocolNotify(&gEfiClockProtocolGuid,mHallClockEvent,&mHallClockRegistration);
  if (EFI_ERROR(Status)) { gBS->CloseEvent(mHallClockEvent);mHallClockEvent=NULL;HallClockReport(0,0,Status);return; }
  HallClockNotify(NULL,NULL);
#endif
}
