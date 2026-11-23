/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Restricted command policy for the pinned OEM UFSDxe diagnostic copy.
 * Offsets describe its internal request, not the packed on-wire UPIU.
 */
#define HOUJI_UFS_GUARD_RVA  0x11834U
#define HOUJI_UFS_GUARD_BRK  0xD4290A00U /* BRK #0x4850 */
#define HOUJI_UFS_GUARD_ISS  0x4850U
#define HOUJI_UFS_RETURN_RVA 0x1185CU

STATIC BOOLEAN
UfsCommandAllowed (CONST UINT8 *Request, UINTN Bytes)
{
  if (!Request || Bytes < 0xC8) { return FALSE; }
  UINT8 Type = Request[0x48], Op = Request[0x5C];
  // No data-out direction, async transfer, extended header or RPMB LUN.
  if (Request[1] == 1 || Request[1] > 2 || Request[5] ||
      Request[0x4A] == 0xC4 || Request[0x6C]) { return FALSE; }
  if (Type == 0) {
    return Request[1] == 0 && Request[0x88] == 0 && Request[0x89] == 0 &&
      Request[0x8A] == 0 && Request[0x8B] == 0;
  }
  if (Type == 0x16) {
    // Read descriptor/attribute/flag. Only fDeviceInit may be set: this is
    // volatile device initialization, never a descriptor or RPMB-key write.
    if (Op == 1 || Op == 3 || Op == 5) { return TRUE; }
    return Op == 6 && Request[0x5D] == 1 && Request[0x5E] == 0 && Request[0x5F] == 0;
  }
  if (Type != 1 || (Request[0x49] & 0x20) ||
      (Request[0x4A] > 7 && Request[0x4A] != 0xD0)) { return FALSE; }
  switch (Op) {
    case 0x00: // TEST UNIT READY
    case 0x03: // REQUEST SENSE
    case 0x12: // INQUIRY
    case 0x25: // READ CAPACITY(10)
    case 0x28: // READ(10)
    case 0x88: // READ(16)
    case 0xA0: // REPORT LUNS
      return TRUE;
    case 0x9E: // SERVICE ACTION IN: READ CAPACITY(16) only
      return Request[0x5D] == 0x10;
    case 0x1B: // START STOP UNIT: UFS active condition 1 in bits 7:4
      return Request[1] == 0 && Request[0x5D] == 0 &&
        Request[0x5E] == 0 && Request[0x5F] == 0 &&
        Request[0x60] == 0x10 && Request[0x61] == 0;
    default:
      return FALSE;
  }
}

// The guard replaces LDR W8,[X1,#0x88] after the real function prologue and
// canary store. Preserve SP and NZCV. A refusal uses the original epilogue;
// changing Context.SP is insufficient in Mu's exception return assembly.
STATIC VOID
UfsGuardResume (BOOLEAN Allowed, CONST UINT8 *Request, UINT64 Base,
                UINT64 *X0, UINT64 *X8, UINT64 *Pc)
{
  if (Allowed) {
    *X8 = (UINT32)Request[0x88] | ((UINT32)Request[0x89] << 8) |
      ((UINT32)Request[0x8A] << 16) | ((UINT32)Request[0x8B] << 24);
    *Pc = Base + HOUJI_UFS_GUARD_RVA + 4;
  } else {
    *X0 = 0xFFFFFFE2U; // the driver's int32 -EROFS, never success
    *Pc = Base + HOUJI_UFS_RETURN_RVA;
  }
}
