/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef HOUJI_GPU_DOORBELL_FAULT_POLICY_H
#define HOUJI_GPU_DOORBELL_FAULT_POLICY_H
#include <stdint.h>
struct hdf_request {uint64_t pc,address;uint32_t value;unsigned armed,failed;};
struct hdf_fault {uint64_t pc,address,esr,far,lr;unsigned valid;};
static inline int hdf_expected(const struct hdf_request *r,uint64_t pc,uint64_t x0,
 uint64_t x1,uint64_t esr,uint64_t far,uint32_t instruction) {
 return r && r->armed && !r->failed && r->address==0x3d7e650 && r->value==1 &&
  r->pc==pc && x0==r->address && x1==1 && far==r->address &&
  ((esr>>26)&63)==0x25 && (esr&(1u<<25)) && (esr&0x7ff)==0x50 &&
  instruction==UINT32_C(0xb9000001); // STR w1,[x0], exact external write abort.
}
#endif
