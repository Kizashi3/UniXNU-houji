/** @file
  Opt-in Ace 5 touch clock handoff through the board's own ClockDxe.
  No raw GCC/PLL writes, GPIO changes, reset, or controller firmware upload.
  SPDX-License-Identifier: BSD-2-Clause-Patent
**/
#include <Uefi.h>
#include <Library/DebugLib.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Protocol/EFIClock.h>
#include "PayloadIdentity.h"

VOID GiuliaTouchClockSchedule (VOID);

#if defined(GIULIA_TOUCH_CLOCK) && GIULIA_TOUCH_CLOCK
STATIC EFI_EVENT mClockEvent;
STATIC VOID *mClockRegistration;
STATIC BOOLEAN mClockAttempted;

STATIC VOID EFIAPI TouchClockReady (EFI_EVENT Event, VOID *Context)
{
  EFI_CLOCK_PROTOCOL *Clock;
  EFI_STATUS Status;
  UINTN Id[3];
  UINTN Index;
  UINT32 Hz = 0;
  BOOLEAN On;
  CONST CHAR8 *Names[3] = {
    "gcc_qupv3_wrap_1_m_ahb_clk", "gcc_qupv3_wrap_1_s_ahb_clk",
    "gcc_qupv3_wrap1_s4_clk"
  };
  if (mClockAttempted) { return; }
  Status = gBS->LocateProtocol (&gEfiClockProtocolGuid, NULL, (VOID **)&Clock);
  if (EFI_ERROR (Status)) { return; }
  mClockAttempted = TRUE;
  if (mClockEvent != NULL) { gBS->CloseEvent (mClockEvent); mClockEvent = NULL; }
  /* Names are present in giulia's pinned ClockDxe binary and independently
     match the vendor GCC driver. Resolve every ID before making a request. */
  for (Index = 0; Index < 3; Index++) {
    Status = Clock->GetClockID (Clock, Names[Index], &Id[Index]);
    DEBUG ((DEBUG_ERROR, "GIULIA TOUCH CLOCK: lookup %a: %r\n", Names[Index], Status));
    if (EFI_ERROR (Status)) { return; }
  }
  /* A low supported XO rate; ClockDxe owns source and voltage sequencing. */
  Status = Clock->SetClockFreqHz (Clock, Id[2], 19200000,
      EFI_CLOCK_FREQUENCY_HZ_EXACT, &Hz);
  DEBUG ((DEBUG_ERROR, "GIULIA TOUCH CLOCK: rate %u: %r\n", Hz, Status));
  if (EFI_ERROR (Status) || Hz != 19200000) { return; }
  for (Index = 0; Index < 3; Index++) {
    Status = Clock->EnableClock (Clock, Id[Index]);
    On = FALSE;
    if (!EFI_ERROR (Status)) { Status = Clock->IsClockOn (Clock, Id[Index], &On); }
    DEBUG ((DEBUG_ERROR, "GIULIA TOUCH CLOCK: enable %a on=%u: %r\n", Names[Index], On, Status));
    if (EFI_ERROR (Status) || !On) { return; }
  }
  /* Intentionally retain the votes across ExitBootServices for XNU. */
}
#endif

VOID GiuliaTouchClockSchedule (VOID)
{
#if defined(GIULIA_TOUCH_CLOCK) && GIULIA_TOUCH_CLOCK
  EFI_STATUS Status;
  Status = gBS->CreateEvent (EVT_NOTIFY_SIGNAL, TPL_CALLBACK, TouchClockReady,
      NULL, &mClockEvent);
  if (EFI_ERROR (Status)) { return; }
  Status = gBS->RegisterProtocolNotify (&gEfiClockProtocolGuid, mClockEvent,
      &mClockRegistration);
  if (EFI_ERROR (Status)) { gBS->CloseEvent (mClockEvent); mClockEvent = NULL; return; }
  TouchClockReady (NULL, NULL);
#endif
}
