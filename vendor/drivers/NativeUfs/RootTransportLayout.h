// SPDX-License-Identifier: BSD-2-Clause-Patent
enum : uint32_t {
  kUcdOffset = 4096,
  kRspOffset = 512,
  kPrdtOffset = 1024,
  kDataOffset = 8192,
  /* 256 KiB is legal in the PRDT field, but the first run with it did not reach
   * launchd; keep the 128 KiB value that produced the first frame until the
   * larger transfer is proven on the device. */
  kDataMax = 131072,
  kDmaBytes = kDataOffset + kDataMax,
};
