/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef HOUJI_FIRMWARE_H
#define HOUJI_FIRMWARE_H
#include <stdint.h>
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
/* ADSP worker only. Read the device's own modem_a, never a host-supplied or
 * alternate-slot image. The two permitted names are adsp and adsp_dtb. */
int houji_fw_open(const char *name, void **handle, uint64_t *size);
int houji_fw_read(void *handle, uint64_t offset, void *to, size_t length);
void houji_fw_close(void *handle);
/* UFS transport: nonzero success, no writes. Each request stays in the
 * validated modem_a partition, with at most 32 4-KiB blocks per transfer. */
int houji_modem_partition(uint64_t *blocks);
int houji_modem_read(uint64_t relative_lba, uint32_t blocks, void *to);
void houji_modem_status(unsigned *stage, uint32_t *result, uint32_t *sense);
#ifdef __cplusplus
}
#endif
#endif
