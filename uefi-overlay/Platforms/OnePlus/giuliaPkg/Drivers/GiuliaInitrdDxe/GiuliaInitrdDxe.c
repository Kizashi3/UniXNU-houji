/** @file
  Read-only GIULIAESP FAT payload from the Android bootloader initrd.
  Block I/O callbacks adapted from UniXNU uefi-sheng ShengBootMemoryDxe.
  SPDX-License-Identifier: BSD-2-Clause-Patent

  Does not add RAM or access UFS. Searches the Kernel reservation first, then
  verified high DDR banks intersected with readable UEFI data/free memory.
*/
#include <Uefi.h>
#include <Library/BaseLib.h>
#include <Library/BaseMemoryLib.h>
#include <Library/DebugLib.h>
#include <Library/FdtLib.h>
#include <Library/HobLib.h>
#include <Library/MemoryAllocationLib.h>
#include <Library/PrintLib.h>
#include <Library/UefiRuntimeServicesTableLib.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Protocol/BlockIo.h>
#include <Protocol/DevicePath.h>
#include "PayloadIdentity.h"
#include "ScanPolicy.h"
VOID GiuliaTouchClockSchedule (VOID);
VOID GiuliaTouchPowerSchedule (VOID);
VOID GiuliaHallPowerSchedule (VOID);
VOID GiuliaHallClockSchedule (VOID);
VOID GiuliaWifiInstall (VOID);
VOID GiuliaGpuPowerInstall (VOID);
VOID GiuliaGpuGunyahInstall (CONST VOID *Fdt);

#define RAM_BLOCK_SIZE  512

STATIC VOID Report (UINTN Stage, UINT64 Start, UINT64 End, EFI_STATUS Status)
{
  EFI_GUID Guid = {0x1c87b711,0xeaa6,0x42cb,{0xa3,0xd5,0x8c,0x21,0x19,0x65,0x21,0x31}};
  CHAR16 Text[128];
  UnicodeSPrint (Text, sizeof (Text), L"initrd S%u %lx-%lx %r", (UINT32)Stage, Start, End, Status);
  // Volatile only: no EFI_VARIABLE_NON_VOLATILE attribute.
  gRT->SetVariable (L"GiuliaInitrdStatus", &Guid,
      EFI_VARIABLE_BOOTSERVICE_ACCESS | EFI_VARIABLE_RUNTIME_ACCESS, StrSize (Text), Text);
}

#pragma pack(1)
typedef struct {
  VENDOR_DEVICE_PATH          Vendor;
  EFI_DEVICE_PATH_PROTOCOL    End;
} RAM_BLOCK_DEVICE_PATH;
#pragma pack()

STATIC RAM_BLOCK_DEVICE_PATH  mDevicePath = {
  {
    { HARDWARE_DEVICE_PATH, HW_VENDOR_DP, { (UINT8)sizeof (VENDOR_DEVICE_PATH), (UINT8)(sizeof (VENDOR_DEVICE_PATH) >> 8) } },
    { 0xA9C6827D, 0x1BD8, 0x410C, { 0x88, 0x5A, 0xC4, 0x65, 0x00, 0xF7, 0xD8, 0x36 } }
  },
  { END_DEVICE_PATH_TYPE, END_ENTIRE_DEVICE_PATH_SUBTYPE, { sizeof (EFI_DEVICE_PATH_PROTOCOL), 0 } }
};

STATIC UINT8                    *mRamBase;
STATIC EFI_BLOCK_IO_MEDIA       mMedia;

STATIC
EFI_STATUS
EFIAPI
RamBlockReset (
  IN EFI_BLOCK_IO_PROTOCOL  *This,
  IN BOOLEAN                ExtendedVerification
  )
{
  return EFI_SUCCESS;
}

STATIC
EFI_STATUS
EFIAPI
RamBlockRead (
  IN  EFI_BLOCK_IO_PROTOCOL  *This,
  IN  UINT32                 MediaId,
  IN  EFI_LBA                Lba,
  IN  UINTN                  BufferSize,
  OUT VOID                   *Buffer
  )
{
  if (Buffer == NULL) {
    return EFI_INVALID_PARAMETER;
  }

  if (MediaId != mMedia.MediaId) {
    return EFI_MEDIA_CHANGED;
  }

  if ((BufferSize % RAM_BLOCK_SIZE) != 0) {
    return EFI_BAD_BUFFER_SIZE;
  }

  if ((Lba > mMedia.LastBlock) || ((BufferSize / RAM_BLOCK_SIZE) > (mMedia.LastBlock + 1 - Lba))) {
    return EFI_INVALID_PARAMETER;
  }

  CopyMem (Buffer, mRamBase + Lba * RAM_BLOCK_SIZE, BufferSize);
  return EFI_SUCCESS;
}

STATIC
EFI_STATUS
EFIAPI
RamBlockWrite (
  IN EFI_BLOCK_IO_PROTOCOL  *This,
  IN UINT32                 MediaId,
  IN EFI_LBA                Lba,
  IN UINTN                  BufferSize,
  IN VOID                   *Buffer
  )
{
  return EFI_WRITE_PROTECTED;
}

STATIC
EFI_STATUS
EFIAPI
RamBlockFlush (
  IN EFI_BLOCK_IO_PROTOCOL  *This
  )
{
  return EFI_SUCCESS;
}

STATIC EFI_BLOCK_IO_PROTOCOL  mBlockIo = {
  EFI_BLOCK_IO_PROTOCOL_REVISION,
  &mMedia,
  RamBlockReset,
  RamBlockRead,
  RamBlockWrite,
  RamBlockFlush
};

STATIC
UINT64
ReadAddress (IN CONST VOID *Property, IN INT32 Length)
{
  if (Length == 8) {
    return Fdt64ToCpu (ReadUnaligned64 ((CONST UINT64 *)Property));
  }
  return Fdt32ToCpu (ReadUnaligned32 ((CONST UINT32 *)Property));
}

STATIC EFI_STATUS ScanRamRange (UINT64 Start, UINT64 End, BOOLEAN Copy, UINTN Stage)
{
  UINT64 At;
  UINT64 Bytes;
  UINT8 *Sector;
  UINT32 Crc;
  EFI_STATUS Status;
  EFI_HANDLE Handle;
  EFI_PHYSICAL_ADDRESS Owned = 0;
  UINTN Pages = EFI_SIZE_TO_PAGES (GIULIA_PAYLOAD_BYTES);
  if ((End <= Start) || (End - Start < GIULIA_PAYLOAD_BYTES)) {
    return EFI_NOT_FOUND;
  }
  for (At = ALIGN_VALUE (Start, RAM_BLOCK_SIZE); At <= End - GIULIA_PAYLOAD_BYTES; At += RAM_BLOCK_SIZE) {
    Sector = (UINT8 *)(UINTN)At;
    if ((Sector[510] != 0x55) || (Sector[511] != 0xAA) ||
        (ReadUnaligned16 ((CONST UINT16 *)(Sector + 11)) != RAM_BLOCK_SIZE) ||
        (CompareMem (Sector + 82, "FAT32   ", 8) != 0) ||
        (CompareMem (Sector + 71, "GIULIAESP  ", 11) != 0)) {
      continue;
    }
    Bytes = (UINT64)ReadUnaligned32 ((CONST UINT32 *)(Sector + 32)) * RAM_BLOCK_SIZE;
    if (Bytes != GIULIA_PAYLOAD_BYTES) { continue; }
    Status = gBS->CalculateCrc32 (Sector, (UINTN)Bytes, &Crc);
    if (EFI_ERROR (Status) || Crc != GIULIA_PAYLOAD_CRC32) { continue; }
    if (Copy) {
      Status = gBS->AllocatePages (AllocateAnyPages, EfiBootServicesData, Pages, &Owned);
      if (EFI_ERROR (Status)) { Report (15, At, End, Status); return Status; }
      CopyMem ((VOID *)(UINTN)Owned, Sector, (UINTN)Bytes);
      Sector = (UINT8 *)(UINTN)Owned;
      Status = gBS->CalculateCrc32 (Sector, (UINTN)Bytes, &Crc);
      if (EFI_ERROR (Status) || Crc != GIULIA_PAYLOAD_CRC32) {
        gBS->FreePages (Owned, Pages);
        Report (16, At, End, EFI_COMPROMISED_DATA);
        return EFI_COMPROMISED_DATA;
      }
    }
    mRamBase = Sector;
    mMedia.MediaId = 1;
    mMedia.MediaPresent = TRUE;
    mMedia.ReadOnly = TRUE;
    mMedia.BlockSize = RAM_BLOCK_SIZE;
    mMedia.IoAlign = 1;
    mMedia.LastBlock = Bytes / RAM_BLOCK_SIZE - 1;
    Handle = NULL;
    Status = gBS->InstallMultipleProtocolInterfaces (&Handle,
        &gEfiDevicePathProtocolGuid, &mDevicePath,
        &gEfiBlockIoProtocolGuid, &mBlockIo, NULL);
    if (EFI_ERROR (Status) && Copy) { gBS->FreePages (Owned, Pages); }
    Report (Stage, At, At + Bytes, Status);
    return Status;
  }
  return EFI_NOT_FOUND;
}

STATIC EFI_STATUS ScanBootRam (VOID)
{
  EFI_MEMORY_DESCRIPTOR *Map;
  EFI_MEMORY_DESCRIPTOR *Entry;
  UINTN Size = 0, Key, DescriptorSize, At, Bank;
  UINT32 Version;
  UINT64 Start, End;
  EFI_STATUS Status;
  Status = gBS->GetMemoryMap (&Size, NULL, &Key, &DescriptorSize, &Version);
  if (Status != EFI_BUFFER_TOO_SMALL) { return Status; }
  Size += 8 * DescriptorSize;
  Map = AllocatePool (Size);
  if (Map == NULL) { return EFI_OUT_OF_RESOURCES; }
  Status = gBS->GetMemoryMap (&Size, Map, &Key, &DescriptorSize, &Version);
  if (EFI_ERROR (Status)) { FreePool (Map); return Status; }
  if (DescriptorSize < sizeof (*Entry)) { FreePool (Map); return EFI_COMPROMISED_DATA; }
  for (At = 0; At + DescriptorSize <= Size; At += DescriptorSize) {
    Entry = (EFI_MEMORY_DESCRIPTOR *)((UINT8 *)Map + At);
    for (Bank = 0; Bank < ARRAY_SIZE (mScanBanks); Bank++) {
      if (!GiuliaScanIntersection (Entry->PhysicalStart, Entry->NumberOfPages,
          Entry->Type, Entry->Attribute, Bank, GIULIA_PAYLOAD_BYTES, &Start, &End)) {
        continue;
      }
      DEBUG ((DEBUG_INFO, "GIULIAINITRD: bounded scan 0x%lx-0x%lx\n", Start, End));
      Status = ScanRamRange (Start, End, TRUE, 14);
      if (Status != EFI_NOT_FOUND) { FreePool (Map); return Status; }
    }
  }
  FreePool (Map);
  Report (17, 0, 0, EFI_NOT_FOUND);
  return EFI_NOT_FOUND;
}

EFI_STATUS
EFIAPI
GiuliaInitrdDxeEntry (IN EFI_HANDLE ImageHandle, IN EFI_SYSTEM_TABLE *SystemTable)
{
  EFI_HOB_GUID_TYPE *Hob;
  CONST VOID *Fdt;
  CONST VOID *StartProp;
  CONST VOID *EndProp;
  INT32 Chosen;
  INT32 StartLength;
  INT32 EndLength;
  UINT64 Start;
  UINT64 End;
  UINT64 At;
  UINT64 Bytes;
  UINT64 Dtb;
  UINT8 *Sector;
  EFI_HANDLE Handle;
  EFI_STATUS Status;
  UINT32 ExpectedBytes;
  UINT32 ExpectedCrc;
  UINT32 ActualCrc;
  UINTN Pass;

  Report (1, 0, 0, EFI_NOT_READY);
  GiuliaTouchClockSchedule ();
  GiuliaTouchPowerSchedule ();
  GiuliaHallPowerSchedule ();
  GiuliaHallClockSchedule ();
  GiuliaWifiInstall ();
  GiuliaGpuPowerInstall ();
  Hob = GetFirstGuidHob (&gSiliciumEntryArgHobGuid);
  if ((Hob == NULL) || (GET_GUID_HOB_DATA_SIZE (Hob) < sizeof (UINT64))) {
    Report (2, 0, 0, EFI_NOT_FOUND);
    return EFI_NOT_FOUND;
  }
  Dtb = ReadUnaligned64 ((CONST UINT64 *)GET_GUID_HOB_DATA (Hob));
  if ((Dtb == 0) || ((Dtb & 3) != 0)) {
    Report (3, Dtb, 0, EFI_NOT_FOUND);
    return EFI_NOT_FOUND;
  }
  Fdt = (CONST VOID *)(UINTN)Dtb;
  if (FdtCheckHeader (Fdt) != 0) {
    Report (4, Dtb, 0, EFI_COMPROMISED_DATA);
    return EFI_COMPROMISED_DATA;
  }
  GiuliaGpuGunyahInstall (Fdt);
  Chosen = FdtPathOffset (Fdt, "/chosen");
  if (Chosen < 0) {
    Report (5, Dtb, 0, EFI_NOT_FOUND);
    return EFI_NOT_FOUND;
  }
  // ABL can pass its vendor DT instead of the appended DT. Bind this build to
  // the independently hash-checked payload rather than trusting stale /chosen.
  ExpectedBytes = GIULIA_PAYLOAD_BYTES;
  ExpectedCrc = GIULIA_PAYLOAD_CRC32;
  StartProp = FdtGetProp (Fdt, Chosen, "linux,initrd-start", &StartLength);
  EndProp = FdtGetProp (Fdt, Chosen, "linux,initrd-end", &EndLength);
  if ((StartProp == NULL) || (EndProp == NULL) ||
      ((StartLength != 4) && (StartLength != 8)) ||
      ((EndLength != 4) && (EndLength != 8))) {
    Report (6, Dtb, 0, EFI_NOT_FOUND);
    return EFI_NOT_FOUND;
  }
  Start = ReadAddress (StartProp, StartLength);
  End = ReadAddress (EndProp, EndLength);
  // Restrict reads to giulia's already-reserved Kernel region. Do not guess
  // about an initrd outside it or add arbitrary physical memory to the GCD.
  if ((Start < 0xA8000000ULL) || (End > 0xB8000000ULL) ||
      (End <= Start) || ((End - Start) < RAM_BLOCK_SIZE)) {
    DEBUG ((DEBUG_ERROR, "GIULIAINITRD: rejected range 0x%lx-0x%lx\n", Start, End));
    Report (7, Start, End, EFI_UNSUPPORTED);
    Start = 0xA8000000ULL;
    End = 0xB8000000ULL;
  }
  // Android v4 loaders may prepend the vendor ramdisk. Search sector-aligned
  // offsets for our FAT32 volume rather than treating that prefix as a disk.
  for (Pass = 0; Pass < 2; Pass++) {
    if (Pass == 1) {
      // Only the platform's reserved Kernel RAM, never arbitrary RAM or MMIO.
      // CRC is an accidental-stale-data check, not a signature/trust bypass.
      Start = 0xA8000000ULL;
      End = 0xB8000000ULL;
    }
  for (At = Start; At <= End - RAM_BLOCK_SIZE; At += RAM_BLOCK_SIZE) {
    Sector = (UINT8 *)(UINTN)At;
    if ((Sector[510] != 0x55) || (Sector[511] != 0xAA) ||
        (ReadUnaligned16 ((CONST UINT16 *)(Sector + 11)) != RAM_BLOCK_SIZE) ||
        (CompareMem (Sector + 82, "FAT32   ", 8) != 0) ||
        (CompareMem (Sector + 71, "GIULIAESP  ", 11) != 0)) {
      continue;
    }
    Bytes = (UINT64)ReadUnaligned32 ((CONST UINT32 *)(Sector + 32)) * RAM_BLOCK_SIZE;
    if ((Bytes != ExpectedBytes) || (Bytes > End - At)) {
      continue;
    }
    Status = gBS->CalculateCrc32 (Sector, (UINTN)Bytes, &ActualCrc);
    if (EFI_ERROR (Status) || (ActualCrc != ExpectedCrc)) {
      continue;
    }
    mRamBase = Sector;
    mMedia.MediaId = 1;
    mMedia.MediaPresent = TRUE;
    mMedia.ReadOnly = TRUE;
    mMedia.BlockSize = RAM_BLOCK_SIZE;
    mMedia.IoAlign = 1;
    mMedia.LastBlock = Bytes / RAM_BLOCK_SIZE - 1;
    Handle = NULL;
    Status = gBS->InstallMultipleProtocolInterfaces (&Handle,
        &gEfiDevicePathProtocolGuid, &mDevicePath,
        &gEfiBlockIoProtocolGuid, &mBlockIo, NULL);
    DEBUG ((DEBUG_ERROR, "GIULIAINITRD: FAT at 0x%lx size 0x%lx: %r\n", At, Bytes, Status));
    Report (Pass == 0 ? 9 : 12, At, At + Bytes, Status);
    return Status;
  }
  }
  DEBUG ((DEBUG_ERROR, "GIULIAINITRD: no complete GIULIAESP FAT volume\n"));
  Report (11, Start, End, EFI_NOT_FOUND);
  return ScanBootRam ();
}

