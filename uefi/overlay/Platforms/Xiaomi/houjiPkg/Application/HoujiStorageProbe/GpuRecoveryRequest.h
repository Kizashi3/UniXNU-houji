/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * AOSP command/status/recovery/stage bytes only. This helper does NO I/O.
 * Exact no-wipe request; compare before any firmware recovery reset.
 */
#ifndef HOUJI_GPU_RECOVERY_REQUEST_H
#define HOUJI_GPU_RECOVERY_REQUEST_H
#include <stdint.h>
#include <stddef.h>
static inline int hgr_record(uint8_t *bytes,size_t count) {
  if(!bytes || count!=864)return 0;
  for(size_t i=0;i<count;i++)bytes[i]=0;
  static const char command[]="boot-recovery",arguments[]="recovery\n";
  for(size_t i=0;i<sizeof(command);i++)bytes[i]=(uint8_t)command[i];
  for(size_t i=0;i<sizeof(arguments);i++)bytes[64+i]=(uint8_t)arguments[i];
  return 1;
}
#endif
