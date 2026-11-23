// SPDX-License-Identifier: BSD-2-Clause-Patent
// Complete the architectural protocol set without firmware update support.
#include <Uefi.h>
#include <Protocol/Capsule.h>
#include <Library/DebugLib.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Library/UefiRuntimeServicesTableLib.h>

STATIC EFI_STATUS EFIAPI
RejectUpdateCapsule (
  IN EFI_CAPSULE_HEADER **CapsuleHeaderArray,
  IN UINTN CapsuleCount,
  IN EFI_PHYSICAL_ADDRESS ScatterGatherList OPTIONAL
  )
{
  return EFI_UNSUPPORTED;
}

STATIC EFI_STATUS EFIAPI
RejectQueryCapsuleCapabilities (
  IN EFI_CAPSULE_HEADER **CapsuleHeaderArray,
  IN UINTN CapsuleCount,
  OUT UINT64 *MaximumCapsuleSize,
  OUT EFI_RESET_TYPE *ResetType
  )
{
  if (MaximumCapsuleSize != NULL) {
    *MaximumCapsuleSize = 0;
  }
  if (ResetType != NULL) {
    *ResetType = EfiResetCold;
  }
  return EFI_UNSUPPORTED;
}

EFI_STATUS EFIAPI
NoCapsuleEntry (IN EFI_HANDLE ImageHandle, IN EFI_SYSTEM_TABLE *SystemTable)
{
  EFI_STATUS Status;
  EFI_HANDLE Handle = NULL;

  gRT->UpdateCapsule = RejectUpdateCapsule;
  gRT->QueryCapsuleCapabilities = RejectQueryCapsuleCapabilities;
  gRT->Hdr.CRC32 = 0;
  Status = gBS->CalculateCrc32 (gRT, gRT->Hdr.HeaderSize, &gRT->Hdr.CRC32);
  if (EFI_ERROR (Status)) {
    return Status;
  }
  Status = gBS->InstallMultipleProtocolInterfaces (
    &Handle, &gEfiCapsuleArchProtocolGuid, NULL, NULL);
  DEBUG ((EFI_D_WARN, "HOUJI: capsule architectural protocol ready; all updates unsupported: %r\n", Status));
  return Status;
}
