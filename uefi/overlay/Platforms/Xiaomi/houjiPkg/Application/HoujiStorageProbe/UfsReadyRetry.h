/* SPDX-License-Identifier: BSD-2-Clause-Patent */
typedef INT32 (EFIAPI *HOUJI_UFS_READY_FN)(UINTN Handle);
typedef INT32 (EFIAPI *HOUJI_UFS_POWER_FN)(UINTN Handle, UINT32 Mode);
typedef VOID (*HOUJI_UFS_RETRY_REPORT)(UINTN Stage, INT32 Status);

STATIC BOOLEAN
UfsSenseNeedsActive (CONST UINT8 *Sense, UINTN Bytes)
{
  return Sense && Bytes >= 14 && (Sense[0] & 0x7F) == 0x70 &&
    (Sense[2] & 0x0F) == 2 && Sense[12] == 4 && Sense[13] == 2;
}

STATIC BOOLEAN
UfsReadyHandleValid (UINT64 Base, UINT64 Bytes, UINT64 Handle)
{
  // Original bbd4 allocates twenty 16-byte handles at RVA 22978, immediately
  // before the controller object at 22ac0. Validate before dereferencing.
  if (!Base || Bytes != 0x25000 || Handle < Base + 0x22978 ||
      Handle >= Base + 0x22AB8 || (Handle - Base - 0x22978) % 16) { return FALSE; }
  CONST UINT8 *H = (CONST UINT8 *)(UINTN)Handle;
  return *(CONST UINT64 *)H == Base + 0x22AC0 && H[8] == 0xF0 &&
    H[9] == 0 && H[10] == 0xD0 && *(CONST UINT32 *)(H + 12) == 0x105189ABU;
}

STATIC INT32
UfsReadyRetry (UINTN Handle, CONST UINT8 *Sense, HOUJI_UFS_READY_FN Ready,
               HOUJI_UFS_POWER_FN Power, HOUJI_UFS_RETRY_REPORT Report)
{
  INT32 Result = Ready (Handle);
  if (!Result || !UfsSenseNeedsActive (Sense, 16)) { return Result; }
  if (Report) { Report (0, Result); }
  // The original CB78 function constructs START STOP UNIT with active power
  // condition 1 in CDB[4] bits 7:4. No storage data or provisioning request.
  Result = Power (Handle, 1);
  if (Report) { Report (1, Result); }
  if (Result) { return Result; }
  Result = Ready (Handle);
  if (Report) { Report (2, Result); }
  return Result;
}
