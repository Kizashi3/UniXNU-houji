// SPDX-License-Identifier: BSD-2-Clause-Patent
#ifndef HOUJI_ROOT_RAM_POLICY_H
#define HOUJI_ROOT_RAM_POLICY_H
#include <Protocol/HoujiRootRAM.h>

STATIC inline BOOLEAN
HoujiRootRecordValid (CONST HOUJI_ROOT_RAM_PROTOCOL *R)
{
  return R && R->Magic == HOUJI_ROOT_RAM_MAGIC && R->Version == 1 &&
    R->StructBytes == sizeof (*R) && R->AllocationBytes == HOUJI_ROOT_RAM_BYTES &&
    R->PackedBytes == HOUJI_ROOT_RAM_PACKED && R->State == HOUJI_ROOT_RAM_EMPTY &&
    R->Wimg == HOUJI_ROOT_RAM_WIMG && !(R->PhysicalAddress & (HOUJI_ROOT_RAM_ALIGN - 1)) &&
    R->PhysicalAddress >= HOUJI_ROOT_RAM_LOW && R->PhysicalAddress < HOUJI_ROOT_RAM_HIGH &&
    R->AllocationBytes <= HOUJI_ROOT_RAM_HIGH - R->PhysicalAddress;
}

STATIC inline BOOLEAN
HoujiRootDescriptor (CONST EFI_MEMORY_DESCRIPTOR *D, UINT64 *End)
{
  if (!D->NumberOfPages || D->NumberOfPages > (~(UINT64)0 >> EFI_PAGE_SHIFT)) { return FALSE; }
  UINT64 Bytes = D->NumberOfPages << EFI_PAGE_SHIFT;
  if ((D->PhysicalStart & EFI_PAGE_MASK) || D->PhysicalStart > ~(UINT64)0 - Bytes) { return FALSE; }
  // This MU map reports GCD capabilities. Require our board's WB-only policy;
  // the board MMU descriptor separately requests WRITE_BACK_XN. This check is
  // not a hardware page-table/cache probe. Permission capabilities may coexist.
  if (!(D->Attribute & EFI_MEMORY_WB) ||
      (D->Attribute & (EFI_MEMORY_UC | EFI_MEMORY_WC | EFI_MEMORY_WT | EFI_MEMORY_UCE | EFI_MEMORY_RUNTIME))) { return FALSE; }
  *End = D->PhysicalStart + Bytes;
  return TRUE;
}

STATIC inline BOOLEAN
HoujiRootMapShape (UINTN Size, UINTN Stride)
{
  return Stride >= sizeof (EFI_MEMORY_DESCRIPTOR) && Stride <= 1024 && !(Stride & 7) && Size &&
    Size <= 1024 * 1024 && Size % Stride == 0;
}

STATIC inline BOOLEAN
HoujiRootChoose (CONST VOID *Map, UINTN Size, UINTN Stride, UINT64 *Address)
{
  UINT64 Best = 0;
  if (!Map || !Address || !HoujiRootMapShape (Size, Stride)) { return FALSE; }
  for (UINTN O = 0; O < Size; O += Stride) {
    CONST EFI_MEMORY_DESCRIPTOR *D = (CONST VOID *)((CONST UINT8 *)Map + O);
    UINT64 End;
    if (D->Type != EfiConventionalMemory || !HoujiRootDescriptor (D, &End)) { continue; }
    UINT64 Low = D->PhysicalStart > HOUJI_ROOT_RAM_LOW ? D->PhysicalStart : HOUJI_ROOT_RAM_LOW;
    if (End > HOUJI_ROOT_RAM_HIGH) { End = HOUJI_ROOT_RAM_HIGH; }
    if (End <= Low || End - Low < HOUJI_ROOT_RAM_BYTES) { continue; }
    UINT64 Candidate = (End - HOUJI_ROOT_RAM_BYTES) & ~(HOUJI_ROOT_RAM_ALIGN - 1);
    if (Candidate >= Low && Candidate > Best) { Best = Candidate; }
  }
  if (!Best) { return FALSE; }
  *Address = Best;
  return TRUE;
}

STATIC inline BOOLEAN
HoujiRootMapOwns (CONST VOID *Map, UINTN Size, UINTN Stride, CONST HOUJI_ROOT_RAM_PROTOCOL *R)
{
  if (!Map || !HoujiRootMapShape (Size, Stride) || !HoujiRootRecordValid (R)) { return FALSE; }
  UINT64 Cursor = R->PhysicalAddress, Limit = Cursor + R->AllocationBytes;
  // Descriptors may be unsorted or split. Require exactly one covering LoaderData
  // descriptor at each step; overlapping/contradictory descriptors are rejected.
  while (Cursor < Limit) {
    UINT64 Next = 0;
    UINTN Matches = 0;
    for (UINTN O = 0; O < Size; O += Stride) {
      CONST EFI_MEMORY_DESCRIPTOR *D = (CONST VOID *)((CONST UINT8 *)Map + O);
      if (!D->NumberOfPages || D->NumberOfPages > (~(UINT64)0 >> EFI_PAGE_SHIFT)) { return FALSE; }
      UINT64 Bytes = D->NumberOfPages << EFI_PAGE_SHIFT;
      if (D->PhysicalStart > ~(UINT64)0 - Bytes) { return FALSE; }
      UINT64 End = D->PhysicalStart + Bytes;
      if (D->PhysicalStart < Limit && End > R->PhysicalAddress) {
        UINT64 CheckedEnd;
        if (D->Type != EfiLoaderData || !HoujiRootDescriptor (D, &CheckedEnd)) { return FALSE; }
        for (UINTN P = 0; P < O; P += Stride) {
          CONST EFI_MEMORY_DESCRIPTOR *Earlier = (CONST VOID *)((CONST UINT8 *)Map + P);
          UINT64 EEnd;
          if (!HoujiRootDescriptor (Earlier, &EEnd)) { continue; }
          if (Earlier->PhysicalStart < Limit && EEnd > R->PhysicalAddress &&
              Earlier->PhysicalStart < End && D->PhysicalStart < EEnd) { return FALSE; }
        }
        if (D->PhysicalStart <= Cursor && End > Cursor) { Matches++; Next = End; }
      }
    }
    if (Matches != 1) { return FALSE; }
    Cursor = Next < Limit ? Next : Limit;
  }
  return TRUE;
}

STATIC inline BOOLEAN
HoujiRootDisjoint (CONST HOUJI_ROOT_RAM_PROTOCOL *R, UINT64 Base, UINT64 Bytes)
{
  return HoujiRootRecordValid (R) && Bytes && Base <= ~(UINT64)0 - Bytes &&
    (Base + Bytes <= R->PhysicalAddress || Base >= R->PhysicalAddress + R->AllocationBytes);
}
#endif
