/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Read-only short polling lease, armed only after full same-epoch audits.
 * All page tables are pinned and absent from device-writeable graphs; no CPU
 * graph edit or filesystem operation is permitted while RAW is outstanding.
 */
#ifndef HOUJI_GPU_CP_POLL_H
#define HOUJI_GPU_CP_POLL_H
#include <stdint.h>
enum {HCF_POWER_REGS=7,HCF_REGS=19,HCF_ROOTS=6};
struct hcf_snapshot {uint32_t regs[HCF_REGS];uint64_t roots[HCF_ROOTS];unsigned valid_regs,valid_roots;};
struct hcf_result {unsigned calls,failed,failed_index,reason;struct hcf_snapshot first_fault,last;};
static inline uint32_t hcf_reg(unsigned i){const uint32_t a[]={0x171004,0x171010,0x171018,0x3d97000,0x3d99108,0x3d99168,0x3d9911c,0x3da0048,0x3dc0058,0x3dc2058,0x3dc3058,0x3d7e340,0x3d8ec40,0x3d8ec30,0x3d7e070,0x3d7e600,0x3dc0000,0x3dc2000,0x3dc3000};return i<HCF_REGS?a[i]:0;}
static inline uint32_t hcf_root(unsigned i){const uint32_t a[]={0x3dc0020,0x3dc0028,0x3dc2020,0x3dc2028,0x3dc3020,0x3dc3028};return i<HCF_ROOTS?a[i]:0;}
static inline unsigned hcf_power(const struct hcf_snapshot *s,unsigned *index) {
 const uint32_t mask[]={0x80000003,0x80000003,0x80000001,0x80000001,1,0x80000000,0x80000000};
 const uint32_t wanted[]={1,1,1,1,0,0x80000000,0};
 for(unsigned i=0;i<HCF_POWER_REGS;i++){*index=i;if(!(s->valid_regs&(1u<<i)) || (s->regs[i]&mask[i])!=wanted[i])return 5;}
 return 0;
}
static inline unsigned hcf_check(const struct hcf_snapshot *s,const uint64_t lease[HCF_ROOTS],unsigned *index) {
 if(!s || !lease || !index)return 1;*index=0;
 if(s->valid_regs!=((1u<<HCF_REGS)-1) || s->valid_roots!=((1u<<HCF_ROOTS)-1))return 2;
 if(hcf_power(s,index))return 5;
 for(unsigned i=HCF_POWER_REGS;i<HCF_REGS;i++) {
  *index=i;uint32_t v=s->regs[i];
  if((i==7 && v) || (i>=8 && i<=10 && (v&0xc00001feu)) || (i==11 && (v&3)) || (i==12 && v) ||
   (i==14 && (v&0x1ff)!=0x100) || (i==15 && !(v&1)) || (i>=16 && (v&~0x1000u)!=0x27))return 3;
 }
 for(unsigned i=0;i<HCF_ROOTS;i++){*index=HCF_REGS+i;if(!lease[i] || s->roots[i]!=lease[i])return 4;}
 return 0;
}
#endif
