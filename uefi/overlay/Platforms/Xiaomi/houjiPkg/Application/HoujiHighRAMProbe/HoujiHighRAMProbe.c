/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Opt-in CPU-only probe. All candidate RAM remains EFI Reserved, so firmware
 * allocators cannot place a driver, stack or pool there before this test.
 * Each 16 KiB page is saved, tested through PoC, restored, and checked again.
 * No BlockIO, USB, SCM, disk or partition operation exists in this app.
 */
#include <Uefi.h>
#include <Library/BaseLib.h>
#include <Library/BaseMemoryLib.h>
#include <Library/CacheMaintenanceLib.h>
#include <Library/MemoryAllocationLib.h>
#include <Library/PcdLib.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Library/UefiLib.h>
#include <Library/HoujiRootRAMPolicy.h>
#include <Library/HoujiRootRAMMap.h>
#include <Protocol/HoujiRootRAM.h>

#define PROBE_PAGE 0x4000U
STATIC CONST UINT64 mPages[] = {
  0x8C0000000ULL, 0x900000000ULL, 0x9FFFFC000ULL,
  0xA00000000ULL, 0xA81E08000ULL, 0xBEA3FC000ULL
};

STATIC BOOLEAN
ReservedWbPage (CONST VOID *Map, UINTN Bytes, UINTN Stride, UINT64 Address)
{
  if (Stride < sizeof (EFI_MEMORY_DESCRIPTOR) || !Stride || Bytes % Stride ||
      Address < HOUJI_ROOT_RAM_LOW || Address > HOUJI_ROOT_RAM_HIGH - PROBE_PAGE ||
      (Address & (PROBE_PAGE - 1))) { return FALSE; }
  UINTN Matches = 0;
  for (UINTN Offset = 0; Offset < Bytes; Offset += Stride) {
    CONST EFI_MEMORY_DESCRIPTOR *D = (CONST VOID *)((CONST UINT8 *)Map + Offset);
    if (D->NumberOfPages > (MAX_UINT64 >> EFI_PAGE_SHIFT)) { return FALSE; }
    UINT64 Length = D->NumberOfPages << EFI_PAGE_SHIFT;
    if (Length > MAX_UINT64 - D->PhysicalStart) { return FALSE; }
    UINT64 End = D->PhysicalStart + Length;
    if (Address < End && D->PhysicalStart < Address + PROBE_PAGE) {
      if (D->PhysicalStart > Address || End < Address + PROBE_PAGE ||
          D->Type != EfiReservedMemoryType || !(D->Attribute & EFI_MEMORY_WB) ||
          (D->Attribute & (EFI_MEMORY_UC | EFI_MEMORY_WC | EFI_MEMORY_WT |
                           EFI_MEMORY_UCE | EFI_MEMORY_RUNTIME))) { return FALSE; }
      Matches++;
    }
  }
  return Matches == 1;
}

STATIC BOOLEAN
TranslationWb (UINT64 Address)
{
  UINT64 Par, El;
  __asm__ volatile ("mrs %0, CurrentEL" : "=r" (El));
  if (El != 4) { Print (L"  refused: expected EL1, CurrentEL=%lx\n", El); return FALSE; }
  __asm__ volatile ("at s1e1w, %1\n\tisb\n\tmrs %0, par_el1" : "=r" (Par) : "r" (Address) : "memory");
  Print (L"  translation PAR=%016lx\n", Par);
  return !(Par & 1) && (Par & 0x0000FFFFFFFFF000ULL) == Address && (Par >> 56) == 0xFF;
}

STATIC BOOLEAN
TestPage (UINT64 Address, UINT64 *Saved)
{
  volatile UINT64 *Ram = (volatile UINT64 *)(UINTN)Address;
  WriteBackInvalidateDataCacheRange ((VOID *)(UINTN)Address, PROBE_PAGE);
  for (UINTN N = 0; N < PROBE_PAGE / sizeof (UINT64); N++) { Saved[N] = Ram[N]; }
  BOOLEAN Good = TRUE;
  for (UINTN Pass = 0; Pass < 2; Pass++) {
    UINT64 Seed = Pass ? 0xA55A0FF0F00F5AA5ULL : 0x5AA5F00F0FF0A55AULL;
    for (UINTN N = 0; N < PROBE_PAGE / sizeof (UINT64); N++) { Ram[N] = Seed ^ Address ^ (N * 8); }
    WriteBackInvalidateDataCacheRange ((VOID *)(UINTN)Address, PROBE_PAGE);
    for (UINTN N = 0; N < PROBE_PAGE / sizeof (UINT64); N++) {
      if (Ram[N] != (Seed ^ Address ^ (N * 8))) { Good = FALSE; break; }
    }
    if (!Good) { break; }
  }
  for (UINTN N = 0; N < PROBE_PAGE / sizeof (UINT64); N++) { Ram[N] = Saved[N]; }
  WriteBackInvalidateDataCacheRange ((VOID *)(UINTN)Address, PROBE_PAGE);
  for (UINTN N = 0; N < PROBE_PAGE / sizeof (UINT64); N++) {
    if (Ram[N] != Saved[N]) { Print (L"  RESTORE MISMATCH at word %u\n", N); return FALSE; }
  }
  return Good;
}

EFI_STATUS EFIAPI
HoujiHighRAMProbeEntry (EFI_HANDLE ImageHandle, EFI_SYSTEM_TABLE *SystemTable)
{
  (VOID)ImageHandle; (VOID)SystemTable;
  if (!FeaturePcdGet (PcdHoujiHighRAMProbeEnable) ||
      FeaturePcdGet (PcdHoujiHighRAMEnable) || FeaturePcdGet (PcdHoujiRootRAMEnable)) {
    return EFI_UNSUPPORTED;
  }
  if (gST->ConOut) { gST->ConOut->ClearScreen (gST->ConOut); }
  Print (L"HOUJI HIGH RAM: reserved CPU probe r1\n");
  Print (L"No disk I/O. Six 16 KiB pages only.\n");
  Print (L"Range 8C0000000 .. BEA400000 remains RESERVED\n\n");
  VOID *Map = NULL;
  UINTN Bytes = 0, Stride = 0;
  EFI_STATUS Status = HoujiRootGetMap (&Map, &Bytes, &Stride);
  UINT64 *Saved = AllocatePool (PROBE_PAGE);
  UINTN Passed = 0;
  if (!EFI_ERROR (Status) && Saved) {
    for (UINTN N = 0; N < ARRAY_SIZE (mPages); N++) {
      Print (L"HOUJI RAM: page %u/%u PA=%lx\n", N + 1, ARRAY_SIZE (mPages), mPages[N]);
      if (!ReservedWbPage (Map, Bytes, Stride, mPages[N])) { Print (L"  refused: EFI ownership/cache map\n"); break; }
      if (!TranslationWb (mPages[N])) { Print (L"  refused: translation/cache attributes\n"); break; }
      if (!TestPage (mPages[N], Saved)) { Print (L"  FAILED; original page restored if execution continued\n"); break; }
      Passed++;
      Print (L"  PASS: both patterns and original bytes restored\n");
    }
  } else { Print (L"Map/allocation failed: %r\n", Status); }
  if (Saved) { FreePool (Saved); }
  if (Map) { FreePool (Map); }
  Print (L"\nHOUJI RAM: %u/%u pages passed. No root volume uploaded.\n", Passed, ARRAY_SIZE (mPages));
  Print (L"Hold power to return to Android.\n");
  (VOID)gBS->SetWatchdogTimer (0, 0, 0, NULL);
  for (;;) { gBS->Stall (1000000); }
}
