/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * DarwinBoot pre-EBS scalar import. Included after the normal UEFI libraries.
 * Called only after AdtNode validated the complete private ReadFile buffer.
 * No files, protocols, hardware, Request ABI or memory-window state changes.
 */
#ifndef DARWIN_BOOT_GPU_POWER_HANDOFF_H
#define DARWIN_BOOT_GPU_POWER_HANDOFF_H
#include "GpuPowerHandoffAdt.h"
#include "GpuPowerHandoffGuid.h"
#include "GpuPowerOnlyHandoff.h"
typedef char DarwinGpuPowerWireSize[(HPA_RECORD_BYTES==HPH_RECORD_BYTES)?1:-1];

/* Presence-only structural walk retains the OLD no-slot/no-GUID behavior.
 * Do not interpret an HPA_SLOT failure as absence: wrong-sized or misplaced
 * target properties also fail strict validation. Canonical names, zero data,
 * uniqueness and the entire strict tree are required once transport is used.
 * Here legacy field-name comparison matches existing AdtNode's terminated
 * 32-byte AsciiStrCmp behavior, including recognizing a malformed target. */
STATIC BOOLEAN
DarwinGpuHandoffPresence (CONST UINT8 *Data, UINTN Size, UINTN *Offset,
                         UINTN Depth, BOOLEAN *Present)
{
  UINT32 Properties;
  UINT32 Children;
  UINT32 Length;
  UINTN Index;
  if ((Depth > 64) || (*Offset > Size) || (Size - *Offset < 8)) { return FALSE; }
  Properties = hpa_u32 (Data + *Offset);
  Children = hpa_u32 (Data + *Offset + 4);
  *Offset += 8;
  if (Properties > (Size - *Offset) / 36) { return FALSE; }
  for (Index = 0; Index < Properties; Index++) {
    if (Size - *Offset < 36) { return FALSE; }
    if (ScanMem8 (Data + *Offset, 32, 0) == NULL) { return FALSE; }
    if (AsciiStrCmp ((CONST CHAR8 *)(Data + *Offset), HPA_PROPERTY) == 0) { *Present = TRUE; }
    Length = hpa_u32 (Data + *Offset + 32);
    *Offset += 36;
    if (Length > Size - *Offset) { return FALSE; }
    *Offset += Length;
    if (ALIGN_VALUE (*Offset, 4) > Size) { return FALSE; }
    *Offset = ALIGN_VALUE (*Offset, 4);
  }
  if (Children > (Size - *Offset) / 8) { return FALSE; }
  for (Index = 0; Index < Children; Index++) {
    if (!DarwinGpuHandoffPresence (Data, Size, Offset, Depth + 1, Present)) { return FALSE; }
  }
  return TRUE;
}

STATIC EFI_STATUS
DarwinGpuBindPowerHandoff (VOID *Tree, UINTN TreeSize)
{
  STATIC CONST EFI_GUID Guid = HOUJI_GPU_POWER_HANDOFF_GUID;
  CONST VOID *Source;
  UINTN Matches;
  UINTN Index;
  UINTN Offset;
  BOOLEAN Present;
  struct hpa_slot Slot;
  struct hph_record Record;

  if ((Tree == NULL) || (TreeSize == 0) || !hpa_span ((uintptr_t)Tree, TreeSize) || (gST == NULL) ||
      ((gST->NumberOfTableEntries != 0) && (gST->ConfigurationTable == NULL)) ||
      (gST->NumberOfTableEntries > MAX_UINTN / sizeof (EFI_CONFIGURATION_TABLE)) ||
      !hpa_span ((uintptr_t)gST->ConfigurationTable,
                 gST->NumberOfTableEntries * sizeof (EFI_CONFIGURATION_TABLE))) {
    return EFI_INVALID_PARAMETER;
  }
  Source = NULL;
  Matches = 0;
  for (Index = 0; Index < gST->NumberOfTableEntries; Index++) {
    if (CompareGuid (&gST->ConfigurationTable[Index].VendorGuid, &Guid)) {
      Matches++;
      Source = gST->ConfigurationTable[Index].VendorTable;
    }
  }
  Offset = 0;
  Present = FALSE;
  if (!DarwinGpuHandoffPresence ((CONST UINT8 *)Tree, TreeSize, &Offset, 0, &Present) ||
      (Offset != TreeSize)) { return EFI_COMPROMISED_DATA; }
  if (!Present && (Matches == 0)) { return EFI_SUCCESS; }
  if (!Present || (Matches != 1) || (Source == NULL)) { return EFI_COMPROMISED_DATA; }
  if (hpa_find (Tree, TreeSize, &Slot) != HPA_OK ||
      !hpa_span ((uintptr_t)Source, HPH_RECORD_BYTES) ||
      hpa_overlap ((uintptr_t)Source, HPH_RECORD_BYTES, (uintptr_t)Tree, TreeSize)) {
    return EFI_COMPROMISED_DATA;
  }
  /* Decode copies to independent stack scalars; failed/incomplete diagnostic
   * records are valid log records but cannot qualify a power handoff. */
  if (!hph_decode (Source, HPH_RECORD_BYTES, &Record) || (Record.complete != 1)) {
    return EFI_COMPROMISED_DATA;
  }
  if (hpa_bind (Tree, TreeSize, &Record, sizeof (Record), &Slot) != HPA_OK) {
    return EFI_COMPROMISED_DATA;
  }
  Print (L"DARWINBOOT: GPU power scalar handoff copied, bytes=%u ADT-offset=%lu; no EFI pointer retained\n",
         (UINT32)Slot.bytes, (UINT64)Slot.offset);
  return EFI_SUCCESS;
}
#endif
