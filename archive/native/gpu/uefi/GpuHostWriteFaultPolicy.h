/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef HOUJI_GPU_HOST_WRITE_FAULT_POLICY_H
#define HOUJI_GPU_HOST_WRITE_FAULT_POLICY_H
#include <stdint.h>
struct hhw_request {uint64_t pc;unsigned armed,failed,value;};
static inline int hhw_match(const struct hhw_request *r,uint64_t pc,uint64_t x0,uint64_t x1,
 uint64_t esr,uint64_t far,uint32_t instruction) {
 return r && r->armed && !r->failed && (r->value==1 || r->value==3) && pc==r->pc &&
  x0==0x3d02020 && x1==r->value && far==0x3d02020 && ((esr>>26)&63)==0x25 &&
  (esr&(1u<<25)) && (esr&0x7ff)==0x50 && instruction==0xb9000001u;
}
#endif
