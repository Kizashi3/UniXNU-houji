/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef HOUJI_GPU_READ_FAULT_POLICY_H
#define HOUJI_GPU_READ_FAULT_POLICY_H
#include <stdint.h>
struct hrf_request {uint64_t pc,address;unsigned armed,width,failed;};
struct hrf_fault {uint64_t pc,address,esr,far,lr;unsigned width,valid;};
static inline int hrf_address(uint64_t a,unsigned width) {
 if(width==64)return !(a&7) && a>=0x3dc0000 && a<0x3dd6000 &&
  ((a&4095)==0x20 || (a&4095)==0x28 || (a&4095)==0x60);
 return width==32 && !(a&3) && ((a>=0x3d00000 && a<0x3e00000) ||
  a==0x171004 || a==0x171010 || a==0x171018 || a==0x171000a8 || a==0x17100128);
}
static inline int hrf_expected(const struct hrf_request *r,uint64_t pc,uint64_t x0,uint64_t esr,uint64_t far,uint32_t instruction) {
 return r && r->armed && !r->failed && hrf_address(r->address,r->width) &&
  r->pc==pc && x0==r->address && far==r->address && ((esr>>26)&63)==0x25 &&
  (esr&(1u<<25)) && (esr&0x7ff)==0x10 &&
  instruction==(r->width==32?UINT32_C(0xb9400000):UINT32_C(0xf9400000));
}
#endif
