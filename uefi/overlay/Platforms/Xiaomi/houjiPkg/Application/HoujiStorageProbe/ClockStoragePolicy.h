/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Temporary storage-bringup policy for the pinned, relocated houji Clock PE.
 * Omit CESTA camera/PCIe initialization by configuring its list as absent.
 * This changes two writable BSP fields before the driver's entry point runs.
 */
STATIC BOOLEAN
ClockStoragePolicy (UINT8 *Image, UINTN Bytes, BOOLEAN Requested)
{
  if (!Requested) { return TRUE; }
  if (!Image || Bytes != 0x38000) { return FALSE; }
  UINT64 Base = (UINTN)Image;
  UINT64 *List = (UINT64 *)(Image + 0x2BC50);
  UINT32 *Count = (UINT32 *)(Image + 0x2BC58);
  CONST UINT64 *Nodes = (CONST UINT64 *)(Image + 0x2BB98);
  // Validate all fields before writing anything. These are relocated pointers
  // in .data; never write a zero pointer into the on-disk relocation target.
  if (*List != Base + 0x2BB98 || *Count != 2 ||
      Nodes[0] != Base + 0x343F8 || Nodes[1] != Base + 0x34480) { return FALSE; }
  *Count = 0;
  *List = 0;
  return TRUE;
}
