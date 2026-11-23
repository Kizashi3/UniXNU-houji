/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Native firmware interfaces adapted from the pinned Ace 5 TouchClock/Power.
 * Houji live DT: ldob9 3.0 V, ldob12 1.8 V; no direct PMIC/GCC/RSC writes.
 */
#include <Protocol/EFIClock.h>
typedef struct { UINT64 Version; VOID *Methods[24]; } HJ_RPMH;
typedef struct { UINT64 Version; VOID *Methods[8]; } HJ_CMDDB;
typedef EFI_STATUS (EFIAPI *HJ_QUERY)(HJ_CMDDB *, CONST CHAR8 *, UINT32 *);
typedef EFI_STATUS (EFIAPI *HJ_DRV_VALID)(UINT32, BOOLEAN *);
typedef EFI_STATUS (EFIAPI *HJ_CREATE)(UINT32, CONST CHAR8 *, VOID **);
typedef EFI_STATUS (EFIAPI *HJ_ISSUE)(VOID *, UINT32, BOOLEAN, UINT32, UINT32, UINT32 *);
typedef EFI_STATUS (EFIAPI *HJ_WAIT)(VOID *, UINT32);
STATIC BOOLEAN mTouchHandoffReady;
STATIC VOID *mTouchPowerClient;
STATIC EFI_STATUS PrepareTouchHandoff (VOID) {
  EFI_CLOCK_PROTOCOL *Clock = NULL;
  HJ_RPMH *Rpmh = NULL;
  HJ_CMDDB *Db = NULL;
  CONST CHAR8 *Names[3] = {"gcc_qupv3_wrap_1_m_ahb_clk", "gcc_qupv3_wrap_1_s_ahb_clk", "gcc_qupv3_wrap1_s4_clk"};
  CONST CHAR8 *Resources[2] = {"ldob9", "ldob12"};
  CONST UINT32 Millivolts[2] = {3000,1800};
  UINTN Ids[3]={0};
  UINT32 Address[2],Slave[2];
  EFI_STATUS Status = gBS->LocateProtocol (&gEfiClockProtocolGuid,NULL,(VOID **)&Clock);
  Print (L"HOUJI TOUCH UEFI: Clock locate=%r\n",Status);
  if (EFI_ERROR(Status) || !Clock || !Clock->GetClockID || !Clock->SetClockFreqHz || !Clock->EnableClock || !Clock->IsClockOn) { return EFI_NOT_READY; }
  Status = gBS->LocateProtocol (&mProvidesRpmhDxe,NULL,(VOID **)&Rpmh);
  if (EFI_ERROR(Status)) { return Status; }
  Status = gBS->LocateProtocol (&mCmdDb,NULL,(VOID **)&Db);
  if (EFI_ERROR(Status)) { return Status; }
  Print (L"HOUJI TOUCH UEFI: Clock=%lx RPMh=%lx CmdDb=%lx\n",Clock->Version,Rpmh->Version,Db->Version);
  if (Rpmh->Version!=0x10001 || Db->Version!=0x10000 || !Rpmh->Methods[1] ||
      !Rpmh->Methods[5] || !Rpmh->Methods[18] || !Rpmh->Methods[11] || !Db->Methods[1] || !Db->Methods[7]) { return EFI_UNSUPPORTED; }
  // Resolve every clock and both exact DT resources before making requests.
  for (UINTN I=0;I<3;I++) {
    Status=Clock->GetClockID(Clock,Names[I],&Ids[I]);
    Print (L"HOUJI TOUCH UEFI: clock %a id=%lx lookup=%r\n",Names[I],Ids[I],Status);
    if (EFI_ERROR(Status)) { return Status; }
  }
  for (UINTN I=0;I<2;I++) {
    Address[I]=Slave[I]=0;
    Status=((HJ_QUERY)Db->Methods[1])(Db,Resources[I],&Address[I]);
    if (!EFI_ERROR(Status)) { Status=((HJ_QUERY)Db->Methods[7])(Db,Resources[I],&Slave[I]); }
    Print (L"HOUJI TOUCH UEFI: %a address=%x slave=%u query=%r\n",Resources[I],Address[I],Slave[I],Status);
    if (EFI_ERROR(Status) || Slave[I]!=4 || (Address[I]>>16)!=4 || (Address[I]&15) ||
        Address[I]==0 || (I && Address[0]==Address[1])) { return EFI_UNSUPPORTED; }
  }
  BOOLEAN Valid=FALSE;
  Status=((HJ_DRV_VALID)Rpmh->Methods[1])(2,&Valid);
  if (EFI_ERROR(Status) || !Valid) { return EFI_UNSUPPORTED; }
  Status=((HJ_CREATE)Rpmh->Methods[5])(2,"houji-touch-vdd",&mTouchPowerClient);
  if (EFI_ERROR(Status) || !mTouchPowerClient) { return EFI_NOT_READY; }
  for (UINTN I=0;I<2;I++) {
    CONST UINT32 Offsets[3]={0,8,4};
    CONST UINT32 Values[3]={Millivolts[I],7,1}; // pmic5-ldo HPM=7; voltage, mode, enable.
    for (UINTN J=0;J<3;J++) {
      UINT32 Request=0;
      Status=((HJ_ISSUE)Rpmh->Methods[18])(mTouchPowerClient,0,TRUE,Address[I]+Offsets[J],Values[J],&Request);
      if (!EFI_ERROR(Status) && Request) { Status=((HJ_WAIT)Rpmh->Methods[11])(mTouchPowerClient,Request); }
      Print (L"HOUJI TOUCH UEFI: %a+%u=%u request=%u result=%r\n",Resources[I],Offsets[J],Values[J],Request,Status);
      if (EFI_ERROR(Status)) { return Status; }
    }
  }
  UINT32 Hz=0;
  Status=Clock->SetClockFreqHz(Clock,Ids[2],19200000,EFI_CLOCK_FREQUENCY_HZ_EXACT,&Hz);
  Print (L"HOUJI TOUCH UEFI: SE clock %u Hz result=%r\n",Hz,Status);
  if (EFI_ERROR(Status) || Hz!=19200000) { return EFI_UNSUPPORTED; }
  for (UINTN I=0;I<3;I++) {
    BOOLEAN On=FALSE;
    Status=Clock->EnableClock(Clock,Ids[I]);
    if (!EFI_ERROR(Status)) { Status=Clock->IsClockOn(Clock,Ids[I],&On); }
    Print (L"HOUJI TOUCH UEFI: clock %a on=%u result=%r\n",Names[I],On,Status);
    if (EFI_ERROR(Status) || !On) { return EFI_NOT_READY; }
  }
  mTouchHandoffReady=TRUE;
  Print (L"HOUJI TOUCH UEFI: firmware handoff ready; native votes retained\n");
  return EFI_SUCCESS;
}
