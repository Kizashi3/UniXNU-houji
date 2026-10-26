/** @file
  Ace 5 touch VDD: native RPMh ACTIVE vote for the DT's ldob4 at 1800 mV.
  This small interoperability adapter uses version-checked firmware interfaces;
  it contains no raw PMIC/RSC writes and never addresses another resource.
  ABI provenance: hardware/sm8650-touch.json. SPDX-License-Identifier: BSD-2-Clause-Patent
**/
#include <Uefi.h>
#include <Library/DebugLib.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Library/UefiRuntimeServicesTableLib.h>
#include "PayloadIdentity.h"

VOID GiuliaTouchPowerSchedule (VOID);

#if defined(GIULIA_TOUCH_POWER) && GIULIA_TOUCH_POWER
typedef struct { UINT64 Version; VOID *Methods[24]; } GIULIA_RPMH_INTERFACE;
typedef struct { UINT64 Version; VOID *Methods[8]; } GIULIA_CMD_INTERFACE;
typedef EFI_STATUS (EFIAPI *GIULIA_QUERY)(GIULIA_CMD_INTERFACE *, CONST CHAR8 *, UINT32 *);
typedef EFI_STATUS (EFIAPI *GIULIA_DRV_VALID)(UINT32, BOOLEAN *);
typedef EFI_STATUS (EFIAPI *GIULIA_CREATE)(UINT32, CONST CHAR8 *, VOID **);
typedef EFI_STATUS (EFIAPI *GIULIA_ISSUE)(VOID *, UINT32, BOOLEAN, UINT32, UINT32, UINT32 *);
typedef EFI_STATUS (EFIAPI *GIULIA_WAIT)(VOID *, UINT32);
STATIC EFI_GUID mRpmhGuid = {0xe1d0b573,0xf29f,0x495d,{0x93,0x52,0xca,0x0d,0xd4,0x2a,0x0a,0x74}};
STATIC EFI_GUID mCmdGuid = {0x1c34f691,0xd33d,0x4e14,{0xb8,0xf8,0x32,0xc6,0xc0,0x29,0xe9,0x5b}};
STATIC EFI_EVENT mPowerEvent[2];
STATIC VOID *mPowerRegistration[2];
STATIC VOID *mPowerClient;
STATIC BOOLEAN mPowerAttempted;
STATIC VOID PowerReport (UINT32 Stage, UINT32 Address, EFI_STATUS Status)
{
  EFI_GUID Guid = {0x1c87b711,0xeaa6,0x42cb,{0xa3,0xd5,0x8c,0x21,0x19,0x65,0x21,0x31}};
  struct { UINT32 Stage, Address; UINT64 Status; } Value = {Stage,Address,(UINT64)Status};
  gRT->SetVariable (L"GiuliaTouchPowerStatus",&Guid,
      EFI_VARIABLE_BOOTSERVICE_ACCESS | EFI_VARIABLE_RUNTIME_ACCESS,sizeof(Value),&Value);
}

STATIC VOID EFIAPI TouchPowerReady (EFI_EVENT Event, VOID *Context)
{
  GIULIA_RPMH_INTERFACE *Rpmh;
  GIULIA_CMD_INTERFACE *Db;
  EFI_STATUS Status;
  UINT32 Address = 0, Slave = 0, Request = 0;
  BOOLEAN Valid = FALSE;
  UINTN Index;
  CONST UINT32 Offsets[3] = {0,8,4};
  CONST UINT32 Values[3] = {1800,7,1}; /* mV, PMIC4 LDO HPM, enable */
  if (mPowerAttempted) { return; }
  Status = gBS->LocateProtocol (&mRpmhGuid, NULL, (VOID **)&Rpmh);
  PowerReport (1,0,Status);
  if (EFI_ERROR (Status)) { return; }
  Status = gBS->LocateProtocol (&mCmdGuid, NULL, (VOID **)&Db);
  PowerReport (2,0,Status);
  if (EFI_ERROR (Status)) { return; }
  mPowerAttempted = TRUE;
  for (Index = 0; Index < 2; Index++) {
    if (mPowerEvent[Index] != NULL) { gBS->CloseEvent (mPowerEvent[Index]); mPowerEvent[Index] = NULL; }
  }
  DEBUG ((DEBUG_ERROR, "GIULIA TOUCH POWER: RPMh=%lx CmdDb=%lx\n", Rpmh->Version, Db->Version));
  if (Rpmh->Version != 0x10001 || Db->Version != 0x10000 ||
      Rpmh->Methods[1] == NULL || Rpmh->Methods[5] == NULL ||
      Rpmh->Methods[18] == NULL || Rpmh->Methods[11] == NULL ||
      Db->Methods[1] == NULL || Db->Methods[7] == NULL) { PowerReport (3,(UINT32)Rpmh->Version,EFI_UNSUPPORTED); return; }
  Status = ((GIULIA_QUERY)Db->Methods[1])(Db,"ldob4",&Address);
  PowerReport (4,Address,Status);
  if (EFI_ERROR (Status)) { return; }
  Status = ((GIULIA_QUERY)Db->Methods[7])(Db,"ldob4",&Slave);
  DEBUG ((DEBUG_ERROR, "GIULIA TOUCH POWER: ldob4 address=%x slave=%u status=%r\n", Address, Slave, Status));
  if (EFI_ERROR (Status) || Slave != 4 || (Address >> 16) != 4 || (Address & 15) != 0) { PowerReport (4,Address,EFI_UNSUPPORTED); return; }
  /* Native mapping enum 2 = HLOS; never create a TZ/HYP client. */
  Status = ((GIULIA_DRV_VALID)Rpmh->Methods[1])(2,&Valid);
  PowerReport (5,Address,Valid ? Status : EFI_UNSUPPORTED);
  if (EFI_ERROR (Status) || !Valid) { return; }
  Status = ((GIULIA_CREATE)Rpmh->Methods[5])(2,"giulia-touch-vdd",&mPowerClient);
  PowerReport (6,Address,Status);
  if (EFI_ERROR (Status) || mPowerClient == NULL) { return; }
  for (Index = 0; Index < 3; Index++) {
    Request = 0;
    Status = ((GIULIA_ISSUE)Rpmh->Methods[18])(mPowerClient,0,TRUE,
        Address + Offsets[Index],Values[Index],&Request);
    if (!EFI_ERROR (Status) && Request != 0) {
      /* giulia's barrier_single slot is an EFI_UNSUPPORTED stub. Its native
         churn_single slot polls the request to completion in firmware. */
      Status = ((GIULIA_WAIT)Rpmh->Methods[11])(mPowerClient,Request);
    }
    DEBUG ((DEBUG_ERROR, "GIULIA TOUCH POWER: ldob4+%u=%u req=%u status=%r\n",
        Offsets[Index],Values[Index],Request,Status));
    PowerReport ((UINT32)Index+7,Address,Status);
    if (EFI_ERROR (Status)) { return; }
  }
  /* Retain this client and its ACTIVE vote for the kernel handoff. */
  DEBUG ((DEBUG_ERROR, "GIULIA TOUCH POWER: ldob4 1800 mV ACTIVE vote complete\n"));
  PowerReport (10,Address,EFI_SUCCESS);
}
#endif

VOID GiuliaTouchPowerSchedule (VOID)
{
#if defined(GIULIA_TOUCH_POWER) && GIULIA_TOUCH_POWER
  EFI_STATUS Status;
  EFI_GUID *Guids[2] = {&mRpmhGuid,&mCmdGuid};
  UINTN Index;
  PowerReport (0,0,EFI_NOT_READY);
  for (Index = 0; Index < 2; Index++) {
    Status = gBS->CreateEvent (EVT_NOTIFY_SIGNAL,TPL_CALLBACK,TouchPowerReady,NULL,&mPowerEvent[Index]);
    if (EFI_ERROR (Status)) { break; }
    Status = gBS->RegisterProtocolNotify (Guids[Index],mPowerEvent[Index],&mPowerRegistration[Index]);
    if (EFI_ERROR (Status)) {
      gBS->CloseEvent (mPowerEvent[Index]);mPowerEvent[Index] = NULL;break;
    }
  }
  TouchPowerReady (NULL,NULL);
#endif
}
