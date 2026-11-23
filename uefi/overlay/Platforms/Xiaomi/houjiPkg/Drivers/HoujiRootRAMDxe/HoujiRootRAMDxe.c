// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <Uefi.h>
#include <Library/DebugLib.h>
#include <Library/PcdLib.h>
#include <Library/HoujiRootRAMPolicy.h>
#include <Library/HoujiRootRAMMap.h>

STATIC HOUJI_ROOT_RAM_PROTOCOL mRoot;
STATIC EFI_HANDLE mHandle;

EFI_STATUS EFIAPI
HoujiRootRAMEntry (EFI_HANDLE ImageHandle, EFI_SYSTEM_TABLE *SystemTable)
{
  VOID *Map = NULL, *Existing = NULL;
  UINTN Size, Stride;
  EFI_PHYSICAL_ADDRESS Address = 0;
  EFI_STATUS Status;
  (VOID)ImageHandle; (VOID)SystemTable;
  if (!FeaturePcdGet (PcdHoujiHighRAMEnable) || !FeaturePcdGet (PcdHoujiRootRAMEnable)) { return EFI_UNSUPPORTED; }
  Status = gBS->LocateProtocol (&gHoujiRootRamProtocolGuid, NULL, &Existing);
  if (Status != EFI_NOT_FOUND) { return EFI_ALREADY_STARTED; }
  Status = HoujiRootGetMap (&Map, &Size, &Stride);
  if (EFI_ERROR (Status)) { return Status; }
  BOOLEAN Found = HoujiRootChoose (Map, Size, Stride, &Address);
  FreePool (Map); Map = NULL;
  if (!Found) { return EFI_OUT_OF_RESOURCES; }
  Status = gBS->AllocatePages (AllocateAddress, EfiLoaderData,
             (UINTN)(HOUJI_ROOT_RAM_BYTES >> EFI_PAGE_SHIFT), &Address);
  if (EFI_ERROR (Status)) { return Status; }
  mRoot = (HOUJI_ROOT_RAM_PROTOCOL){ HOUJI_ROOT_RAM_MAGIC, 1, sizeof (mRoot),
           Address, HOUJI_ROOT_RAM_BYTES, HOUJI_ROOT_RAM_PACKED,
           HOUJI_ROOT_RAM_EMPTY, HOUJI_ROOT_RAM_WIMG };
  Status = HoujiRootGetMap (&Map, &Size, &Stride);
  if (!EFI_ERROR (Status) && !HoujiRootMapOwns (Map, Size, Stride, &mRoot)) { Status = EFI_COMPROMISED_DATA; }
  if (Map) { FreePool (Map); }
  if (!EFI_ERROR (Status)) {
    Status = gBS->InstallProtocolInterface (&mHandle, &gHoujiRootRamProtocolGuid, EFI_NATIVE_INTERFACE, &mRoot);
  }
  if (EFI_ERROR (Status)) {
    EFI_STATUS FreeStatus = gBS->FreePages (Address, (UINTN)(HOUJI_ROOT_RAM_BYTES >> EFI_PAGE_SHIFT));
    if (EFI_ERROR (FreeStatus)) { DEBUG ((DEBUG_ERROR, "HOUJI ROOTRAM: cleanup failed %r; no protocol published\n", FreeStatus)); }
    mRoot = (HOUJI_ROOT_RAM_PROTOCOL){0};
    return Status;
  }
  DEBUG ((DEBUG_ERROR, "HOUJI ROOTRAM: owned EMPTY pa=0x%lx allocation=0x%lx packed=0x%lx\n",
          mRoot.PhysicalAddress, mRoot.AllocationBytes, mRoot.PackedBytes));
  // Deliberately no SetMem/CopyMem/read of the allocation. It is not a valid root yet.
  return EFI_SUCCESS;
}
