// SPDX-License-Identifier: BSD-2-Clause-Patent
#ifndef HOUJI_ROOT_RAM_PROTOCOL_H
#define HOUJI_ROOT_RAM_PROTOCOL_H
#include <Uefi.h>

#define HOUJI_ROOT_RAM_LOW    0x8C0000000ULL
#define HOUJI_ROOT_RAM_HIGH   0xBEA400000ULL
#define HOUJI_ROOT_RAM_PACKED 6046045653ULL
#define HOUJI_ROOT_RAM_BYTES  6046056448ULL
#define HOUJI_ROOT_RAM_ALIGN  0x4000ULL
#define HOUJI_ROOT_RAM_MAGIC  0x314D415254524A48ULL /* HJRTRAM1 */
#define HOUJI_ROOT_RAM_EMPTY  1U
#define HOUJI_ROOT_RAM_WIMG   2U
#define HOUJI_ROOT_RAM_SIG    0x52524A48U /* HJRR */
#define HOUJI_ROOT_RAM_EXPECTED_SHA256_HEX "2c2f6985b5e9cec542db521a895df44e2c41e9785a64c6d07ee056f2c1b2ef23"
#define HOUJI_ROOT_RAM_EXPECTED_SHA256_BYTES { \
  0x2c,0x2f,0x69,0x85,0xb5,0xe9,0xce,0xc5,0x42,0xdb,0x52,0x1a,0x89,0x5d,0xf4,0x4e, \
  0x2c,0x41,0xe9,0x78,0x5a,0x64,0xc6,0xd0,0x7e,0xe0,0x56,0xf2,0xc1,0xb2,0xef,0x23 }

// Firmware-owned descriptor, never a host-supplied PA. No payload is loaded.
// The ADT Info property serializes these exact 48 little-endian bytes.
typedef struct {
  UINT64 Magic;
  UINT32 Version;
  UINT32 StructBytes;
  UINT64 PhysicalAddress;
  UINT64 AllocationBytes;
  UINT64 PackedBytes;
  UINT32 State;
  UINT32 Wimg;
} HOUJI_ROOT_RAM_PROTOCOL;
STATIC_ASSERT (sizeof (HOUJI_ROOT_RAM_PROTOCOL) == 48, "RootRAM ABI");
extern EFI_GUID gHoujiRootRamProtocolGuid;

#endif
