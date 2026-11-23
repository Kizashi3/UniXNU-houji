/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Read-only OEM-to-native handoff inventory. A fault in the explicitly armed
 * single-load stub is recorded and returned to normal context, then scanning
 * stops. It never skips an OEM/XNU fault or accesses Boot Services in a handler.
 */
#include "HandoffReadPolicy.h"
STATIC BOOLEAN mHandoffReadArmed, mHandoffReadFault;
STATIC UINT64 mHandoffReadAddress, mHandoffFaultEsr, mHandoffFaultFar;

STATIC UINT32 __attribute__((naked))
HandoffReadStub (UINT64 Address)
{
  __asm__ volatile ("ldr w0, [x0]\n\tret");
}

STATIC BOOLEAN
HandleHandoffReadFault (EFI_EXCEPTION_TYPE Type, EFI_SYSTEM_CONTEXT_AARCH64 *C)
{
  if (Type != EXCEPT_AARCH64_SYNCHRONOUS_EXCEPTIONS ||
      !HandoffFaultExpected (mHandoffReadArmed, (UINTN)HandoffReadStub, mHandoffReadAddress,
        C->ELR, C->ESR, C->FAR, *(CONST UINT32 *)(UINTN)HandoffReadStub)) { return FALSE; }
  mHandoffReadFault = TRUE;
  mHandoffFaultEsr = C->ESR; mHandoffFaultFar = C->FAR;
  C->X0 = 0; C->ELR += 4; // RET to the normal caller with explicit failure flag.
  return TRUE;
}

STATIC BOOLEAN
HandoffRead (UINT64 Address, CONST CHAR16 *Name, UINT32 *Value)
{
  if (!HandoffAddressAllowed (Address) || mHandoffReadArmed ||
      *(CONST UINT32 *)(UINTN)HandoffReadStub != 0xB9400000U ||
      *((CONST UINT32 *)(UINTN)HandoffReadStub + 1) != 0xD65F03C0U) { return FALSE; }
  mHandoffReadFault = FALSE; mHandoffReadAddress = Address; mHandoffReadArmed = TRUE;
  __asm__ volatile ("dsb sy" ::: "memory");
  UINT32 Result = HandoffReadStub (Address);
  __asm__ volatile ("dsb sy" ::: "memory");
  mHandoffReadArmed = FALSE;
  if (mHandoffReadFault) {
    Print (L"HOUJI HANDOFF: READ-ABORT %s address=%08lx ESR=%016lx FAR=%08lx; scan stopped\n",
      Name, Address, mHandoffFaultEsr, mHandoffFaultFar);
    return FALSE;
  }
  *Value = Result;
  Print (L"HOUJI HANDOFF: %s [%08lx]=%08x\n", Name, Address, Result);
  return TRUE;
}

STATIC EFI_STATUS
RunUfsHandoffProbe (VOID)
{
  Print (L"HOUJI HANDOFF r23: read-only HCI/SMMU inventory; no queue or routing writes\n");
  UINT32 Value;
  CONST UINT32 Hci[] = {0, 8, 0x18, 0x20, 0x24, 0x30, 0x34, 0x50, 0x54, 0x58, 0x60, 0x70, 0x74, 0x78, 0x80};
  for (UINTN I = 0; I < ARRAY_SIZE (Hci); I++) {
    if (!HandoffRead (0x1D84000 + Hci[I], L"HCI", &Value)) { return EFI_DEVICE_ERROR; }
  }
  UINT32 Id0, Id1, Id2;
  if (!HandoffRead (0x15000020, L"SMMU IDR0", &Id0) ||
      !HandoffRead (0x15000024, L"SMMU IDR1", &Id1) ||
      !HandoffRead (0x15000028, L"SMMU IDR2", &Id2)) { return EFI_DEVICE_ERROR; }
  UINTN Count = Id0 & 255, Banks = Id1 & 255, Pages = 1U << (((Id1 >> 28) & 7) + 1);
  if (!Count || Count > 128 || Banks < 2 || Banks > 128 || (Id1 >> 31) ||
      (Pages + Banks) * 4096 > 0xD0000) { return EFI_UNSUPPORTED; }
  UINT32 Smr[128];
  UINTN Valid = 0, UfsMatches = 0;
  UINT32 UfsBank = 0xFFFFFFFFU;
  // Exactly one SMR pass. Cache results instead of rereading fault-prone banks.
  for (UINTN I = 0; I < Count; I++) {
    if (!HandoffRead (0x15000800 + 4 * I, L"SMR", &Smr[I])) { return EFI_DEVICE_ERROR; }
  }
  for (UINTN I = 0; I < Count; I++) {
    if (!(Smr[I] & 0x80000000U)) { continue; }
    UINT32 Route;
    if (!HandoffRead (0x15000C00 + 4 * I, L"S2CR valid", &Route)) { return EFI_DEVICE_ERROR; }
    Valid++;
    if (!((Smr[I] ^ 0x60U) & 0xFFFFU & ~((Smr[I] >> 16) & 0x7FFFU))) {
      UfsMatches++; UfsBank = Route & 255;
      Print (L"HOUJI HANDOFF: UFS SID60 slot=%u SMR=%08x S2CR=%08x\n", I, Smr[I], Route);
    }
  }
  Print (L"HOUJI HANDOFF: groups=%u valid=%u banks=%u pages=%u UFS-matches=%u\n",
    Count, Valid, Banks, Pages, UfsMatches);
  for (UINTN Bank = 0; Bank < Banks; Bank++) {
    if (Bank + 8 < Banks && Bank != UfsBank) { continue; }
    Print (L"HOUJI HANDOFF: inspecting context bank %u\n", Bank);
    if (!HandoffRead (0x15000000 + (Pages + Bank) * 4096, L"SCTLR", &Value) ||
        !HandoffRead (0x15001000 + Bank * 4, L"CBAR", &Value) ||
        !HandoffRead (0x15001800 + Bank * 4, L"CBA2R", &Value)) { return EFI_DEVICE_ERROR; }
  }
  Print (L"HOUJI HANDOFF: inventory complete; all peripheral accesses were reads\n");
  return EFI_SUCCESS;
}
