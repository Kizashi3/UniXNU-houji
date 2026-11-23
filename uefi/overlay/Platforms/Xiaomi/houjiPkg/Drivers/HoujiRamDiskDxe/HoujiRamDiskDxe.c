// SPDX-License-Identifier: BSD-2-Clause-Patent
// Read-only RAM block device. Bounds follow the captured houji Kernel reservation.
// Block I/O design follows UniXNU's BSD-licensed GiuliaInitrdDxe/ShengBootMemoryDxe.
#include <Uefi.h>
#include <Library/BaseLib.h>
#include <Library/BaseMemoryLib.h>
#include <Library/DebugLib.h>
#include <Library/MemoryMapHelperLib.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Protocol/BlockIo.h>
#include <Protocol/DevicePath.h>
#include "PayloadIdentity.h"

// Retain an identity in the actual PE/firmware for the host packer to inspect.
// Volatile reads keep the final linked identity authoritative under LTO.
typedef struct {
  UINT8 Magic[8];
  UINT32 Bytes;
  UINT32 Crc32;
} HOUJI_RAM_IDENTITY;
STATIC CONST volatile HOUJI_RAM_IDENTITY mPayloadIdentity = {
  {'H','J','R','A','M','I','D','1'}, HOUJI_PAYLOAD_BYTES, HOUJI_PAYLOAD_CRC32
};
STATIC_ASSERT (sizeof (HOUJI_RAM_IDENTITY) == 16, "RAM payload identity layout");

STATIC UINT8 *mRamBase;
STATIC EFI_BLOCK_IO_MEDIA mMedia;

#pragma pack(1)
typedef struct {
  VENDOR_DEVICE_PATH Vendor;
  EFI_DEVICE_PATH_PROTOCOL End;
} RAM_DEVICE_PATH;
#pragma pack()

STATIC RAM_DEVICE_PATH mPath = {
  {{HARDWARE_DEVICE_PATH, HW_VENDOR_DP, {sizeof (VENDOR_DEVICE_PATH), 0}},
   {0x28930256, 0xC7FA, 0x5628, {0x9C,0x1A,0x82,0xDC,0x45,0xDB,0x70,0x05}}},
  {END_DEVICE_PATH_TYPE, END_ENTIRE_DEVICE_PATH_SUBTYPE, {sizeof (EFI_DEVICE_PATH_PROTOCOL), 0}}
};

STATIC EFI_STATUS EFIAPI
RamReset (IN EFI_BLOCK_IO_PROTOCOL *This, IN BOOLEAN ExtendedVerification)
{
  return EFI_SUCCESS;
}

STATIC EFI_STATUS EFIAPI
RamRead (IN EFI_BLOCK_IO_PROTOCOL *This, IN UINT32 MediaId, IN EFI_LBA Lba,
         IN UINTN BufferSize, OUT VOID *Buffer)
{
  if (Buffer == NULL) {
    return EFI_INVALID_PARAMETER;
  }
  if (MediaId != mMedia.MediaId) {
    return EFI_MEDIA_CHANGED;
  }
  if ((BufferSize % 512) != 0) {
    return EFI_BAD_BUFFER_SIZE;
  }
  if ((Lba > mMedia.LastBlock) || (BufferSize / 512 > mMedia.LastBlock + 1 - Lba)) {
    return EFI_INVALID_PARAMETER;
  }
  CopyMem (Buffer, mRamBase + Lba * 512, BufferSize);
  return EFI_SUCCESS;
}

STATIC EFI_STATUS EFIAPI
RamWrite (IN EFI_BLOCK_IO_PROTOCOL *This, IN UINT32 MediaId, IN EFI_LBA Lba,
          IN UINTN BufferSize, IN VOID *Buffer)
{
  return EFI_WRITE_PROTECTED;
}

STATIC EFI_STATUS EFIAPI
RamFlush (IN EFI_BLOCK_IO_PROTOCOL *This)
{
  return EFI_SUCCESS;
}

STATIC EFI_BLOCK_IO_PROTOCOL mBlock = {
  EFI_BLOCK_IO_PROTOCOL_REVISION, &mMedia, RamReset, RamRead, RamWrite, RamFlush
};

EFI_STATUS EFIAPI
HoujiRamDiskEntry (IN EFI_HANDLE ImageHandle, IN EFI_SYSTEM_TABLE *SystemTable)
{
  EFI_MEMORY_REGION_DESCRIPTOR Region = {0};
  EFI_STATUS Status;
  EFI_HANDLE Handle = NULL;
  UINT64 At;
  UINT8 *Sector;
  UINT32 Crc;
  UINT32 PayloadBytes = mPayloadIdentity.Bytes;
  UINT32 PayloadCrc = mPayloadIdentity.Crc32;

  Status = LocateMemoryRegionByName ("Kernel", &Region);
  if (EFI_ERROR (Status) || Region.Address != 0xA8000000 || Region.Length != 0x10000000 ||
      PayloadBytes < 0x2000000 || PayloadBytes > 0x8000000 ||
      (PayloadBytes & 511) != 0) {
    DEBUG ((DEBUG_ERROR, "HOUJI RAM: unqualified memory window or payload size\n"));
    return EFI_UNSUPPORTED;
  }
  DEBUG ((DEBUG_WARN, "HOUJI RAM: search reserved Kernel window A8000000-B8000000 for %u bytes, CRC %08x\n", PayloadBytes, PayloadCrc));
  for (At = Region.Address; At <= Region.Address + Region.Length - PayloadBytes; At += 512) {
    Sector = (UINT8 *)(UINTN)At;
    if (Sector[510] != 0x55 || Sector[511] != 0xAA ||
        ReadUnaligned16 ((CONST UINT16 *)(Sector + 11)) != 512 ||
        CompareMem (Sector + 82, "FAT32   ", 8) != 0 ||
        CompareMem (Sector + 71, "HOUJIESP   ", 11) != 0 ||
        (UINT64)ReadUnaligned32 ((CONST UINT32 *)(Sector + 32)) * 512 != PayloadBytes) {
      continue;
    }
    Status = gBS->CalculateCrc32 (Sector, PayloadBytes, &Crc);
    if (EFI_ERROR (Status) || Crc != PayloadCrc) {
      continue;
    }
    mRamBase = Sector;
    mMedia.MediaId = 1;
    mMedia.MediaPresent = TRUE;
    mMedia.ReadOnly = TRUE;
    mMedia.BlockSize = 512;
    mMedia.IoAlign = 1;
    mMedia.LastBlock = PayloadBytes / 512 - 1;
    Status = gBS->InstallMultipleProtocolInterfaces (
      &Handle, &gEfiDevicePathProtocolGuid, &mPath, &gEfiBlockIoProtocolGuid, &mBlock, NULL);
    DEBUG ((DEBUG_WARN, "HOUJI RAM: read-only FAT payload at %lx, CRC %08x, %r\n", At, Crc, Status));
    return Status;
  }
  DEBUG ((DEBUG_ERROR, "HOUJI RAM: payload not found in qualified reserved memory\n"));
  // Keep the failure visible before UniXNU clears the framebuffer for its menu.
  gBS->Stall (15000000);
  return EFI_NOT_FOUND;
}
