/** Bounded fallback search for PKG110, intersected with the live UEFI map.
 * SPDX-License-Identifier: BSD-2-Clause-Patent
 *
 * These high DDR banks come from the captured PKG110 /memory/reg and iomem.
 * Do not search low DDR: RamManagerDxe can label firmware carveouts as usable,
 * including tz_stat_region [0x82700000,0x82800000), which faults on reads.
 * The reserved Kernel window is handled separately by the direct initrd path.
 * This is a search policy, not a replacement platform memory map.
 */
#ifndef GIULIA_SCAN_POLICY_H
#define GIULIA_SCAN_POLICY_H

STATIC CONST UINT64 mScanBanks[][2] = {
  { 0x880000000ULL, 0x8AF900000ULL },
  { 0x8B0000000ULL, 0x8B7F00000ULL },
  { 0x8C0000000ULL, 0xB00000000ULL }
};

STATIC BOOLEAN
GiuliaScanIntersection (
  UINT64 Base, UINT64 Pages, UINT32 Type, UINT64 Attributes,
  UINTN Bank, UINT64 PayloadBytes, UINT64 *Start, UINT64 *End
  )
{
  UINT64 Limit;
  if ((Bank >= ARRAY_SIZE (mScanBanks)) || (PayloadBytes == 0) ||
      (Pages > (MAX_UINT64 - Base) / EFI_PAGE_SIZE) ||
      ((Type != EfiConventionalMemory) && (Type != EfiLoaderData) &&
       (Type != EfiBootServicesData)) ||
      ((Attributes & (EFI_MEMORY_RUNTIME | EFI_MEMORY_RP)) != 0)) {
    return FALSE;
  }
  Limit = Base + Pages * EFI_PAGE_SIZE;
  *Start = MAX (Base, mScanBanks[Bank][0]);
  *End = MIN (Limit, mScanBanks[Bank][1]);
  // Align only after bounding the address, so arbitrary descriptors cannot wrap.
  if ((*Start >= *End) || (*End - *Start < PayloadBytes)) {
    return FALSE;
  }
  *Start = ALIGN_VALUE (*Start, 512);
  return (*Start < *End) && (*End - *Start >= PayloadBytes);
}

#endif
