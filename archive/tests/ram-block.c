// SPDX-License-Identifier: BSD-2-Clause-Patent
// Exercise the real RAM Block I/O callbacks with host memory and sanitizers.
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#undef NULL
#include <Uefi.h>
#include <Library/BaseMemoryLib.h>
#include <Library/BaseLib.h>
#include <Library/MemoryMapHelperLib.h>

EFI_BOOT_SERVICES *gBS;
EFI_GUID gEfiDevicePathProtocolGuid;
EFI_GUID gEfiBlockIoProtocolGuid;

VOID *EFIAPI CopyMem (VOID *Destination, CONST VOID *Source, UINTN Length)
{ return memcpy (Destination, Source, Length); }
INTN EFIAPI CompareMem (CONST VOID *A, CONST VOID *B, UINTN Length)
{ return memcmp (A, B, Length); }
UINT16 EFIAPI ReadUnaligned16 (CONST VOID *A)
{ UINT16 Value; memcpy (&Value, A, sizeof (Value)); return Value; }
UINT32 EFIAPI ReadUnaligned32 (CONST VOID *A)
{ UINT32 Value; memcpy (&Value, A, sizeof (Value)); return Value; }
EFI_STATUS EFIAPI LocateMemoryRegionByName (CHAR8 *Name, EFI_MEMORY_REGION_DESCRIPTOR *Region)
{ return EFI_NOT_FOUND; }

#include HOUJI_RAM_SOURCE

#define CHECK(C) do { if (!(C)) { fprintf(stderr, "check failed at %d: %s\n", __LINE__, #C); return 1; } } while (0)

int main (void)
{
  UINT8 ram[1536], saved[1536], out[1536];
  for (unsigned i = 0; i < sizeof (ram); ++i) ram[i] = (UINT8)(i ^ (i >> 8));
  memcpy (saved, ram, sizeof (ram));
  memset (out, 0xa5, sizeof (out));
  mRamBase = ram;
  mMedia.MediaId = 7;
  mMedia.ReadOnly = TRUE;
  mMedia.BlockSize = 512;
  mMedia.LastBlock = 2;
  CHECK (RamRead (&mBlock, 7, 1, 512, out + 512) == EFI_SUCCESS);
  CHECK (memcmp (out + 512, ram + 512, 512) == 0);
  CHECK (out[511] == 0xa5 && out[1024] == 0xa5);
  CHECK (RamRead (&mBlock, 7, 2, 512, out) == EFI_SUCCESS);
  CHECK (RamRead (&mBlock, 7, 2, 1024, out) == EFI_INVALID_PARAMETER);
  CHECK (RamRead (&mBlock, 7, 3, 512, out) == EFI_INVALID_PARAMETER);
  CHECK (RamRead (&mBlock, 7, MAX_UINT64, 512, out) == EFI_INVALID_PARAMETER);
  CHECK (RamRead (&mBlock, 7, 0, 511, out) == EFI_BAD_BUFFER_SIZE);
  CHECK (RamRead (&mBlock, 8, 0, 512, out) == EFI_MEDIA_CHANGED);
  CHECK (RamRead (&mBlock, 7, 0, 512, NULL) == EFI_INVALID_PARAMETER);
  CHECK (RamRead (&mBlock, 7, 0, MAX_UINTN & ~(UINTN)511, out) == EFI_INVALID_PARAMETER);
  CHECK (RamWrite (&mBlock, 7, 0, sizeof (out), out) == EFI_WRITE_PROTECTED);
  CHECK (memcmp (ram, saved, sizeof (ram)) == 0);
  puts ("RAM Block I/O: valid reads, canaries, overflow/bounds, wrong media, and write protection passed.");
  return 0;
}
