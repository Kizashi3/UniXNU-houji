/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Read-only capture of platform ACTLR and PRR addresses while all banks are
 * disabled and every stream is invalid/FAULT. Never replay unknown values.
 */
#ifndef HOUJI_GPU_SMMU_PLATFORM_H
#define HOUJI_GPU_SMMU_PLATFORM_H
#include "GpuSmmuContext.h"
struct hgs_result {unsigned code,reads,stable;uint32_t actlr,prr_low,prr_high;};
static inline unsigned hgs_snapshot(const struct hgp_io *io,struct hgs_result *r) {
  struct hgp_result guard={0};uint64_t value=0;uint32_t first[3]={0};
  if(!r)return HGP_ARGUMENT;*r=(struct hgs_result){0};
  if(!io || !io->read32 || !io->power_guard)return r->code=HGP_ARGUMENT;
  static const uint32_t address[]={HGP_CB(0x4),0x3da6008,0x3da600c};
  for(unsigned pass=0;pass<2;pass++) {
    if(!hgp_guard(io,&guard)) {r->code=guard.code;goto done;}
    for(unsigned i=0;i<3;i++) {
      if(!hgp_read(io,&guard,address[i],&value,0)) {r->code=guard.code;goto done;}
      if(!pass)first[i]=(uint32_t)value;
      else if(value!=first[i]) {r->code=HGP_GUARD;goto done;}
    }
  }
  if(!hgp_guard(io,&guard)) {r->code=guard.code;goto done;}
  r->actlr=first[0];r->prr_low=first[1];r->prr_high=first[2];r->stable=1;
done:
  r->reads=guard.reads;return r->code;
}
#endif
