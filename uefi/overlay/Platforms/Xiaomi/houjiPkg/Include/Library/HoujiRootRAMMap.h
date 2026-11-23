// SPDX-License-Identifier: BSD-2-Clause-Patent
#ifndef HOUJI_ROOT_RAM_MAP_H
#define HOUJI_ROOT_RAM_MAP_H
#include <Library/MemoryAllocationLib.h>
#include <Library/UefiBootServicesTableLib.h>

// Bounded, fresh EFI map. The caller owns the returned pool and must FreePool.
STATIC EFI_STATUS
HoujiRootGetMap (VOID **Map, UINTN *Size, UINTN *Stride)
{
  UINTN Key, Capacity = 0;
  UINT32 Version;
  *Map = NULL; *Size = 0; *Stride = 0;
  for (UINTN Attempt = 0; Attempt < 8; Attempt++) {
    *Size = Capacity;
    EFI_STATUS Status = gBS->GetMemoryMap (Size, *Map, &Key, Stride, &Version);
    if (!EFI_ERROR (Status)) {
      if (!HoujiRootMapShape (*Size, *Stride)) { FreePool (*Map); *Map = NULL; return EFI_COMPROMISED_DATA; }
      return EFI_SUCCESS;
    }
    if (Status != EFI_BUFFER_TOO_SMALL || *Stride < sizeof (EFI_MEMORY_DESCRIPTOR) || *Stride > 1024 ||
        *Size > 1024 * 1024 - 8 * *Stride) {
      if (*Map) { FreePool (*Map); *Map = NULL; }
      return Status == EFI_BUFFER_TOO_SMALL ? EFI_BAD_BUFFER_SIZE : Status;
    }
    Capacity = *Size + 8 * *Stride;
    if (*Map) { FreePool (*Map); }
    *Map = AllocatePool (Capacity);
    if (!*Map) { return EFI_OUT_OF_RESOURCES; }
  }
  FreePool (*Map); *Map = NULL;
  return EFI_ABORTED;
}
#endif
