// SPDX-License-Identifier: BSD-2-Clause-Patent
enum : uint32_t {
  kUcdOffset = 4096,
  kRspOffset = 512,
  kPrdtOffset = 1024,
  kDataOffset = 8192,
  kDataMax = 1048576,   /* one SCSI READ per MiB instead of per 128 KiB */
  kDmaBytes = kDataOffset + kDataMax,
};
