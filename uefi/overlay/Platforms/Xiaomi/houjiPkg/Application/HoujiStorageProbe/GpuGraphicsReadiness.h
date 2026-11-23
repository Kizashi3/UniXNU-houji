/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Read-only A750 security-state observations, not a graphics-readiness gate.
 * OnePlus453d8875 gen7_reg.h:618/623/624 names these dword registers;
 * adreno_gen7.c:1325-1326 reads TSB_STATUS during error reporting.
 * Linux21a7f44/Mesa85fda3b3 a6xx.xml gives TRUST_CNTL no bit/access schema.
 * Consequently no raw value here is decoded as nonsecure or ZAP success.
 */
#ifndef HOUJI_GPU_GRAPHICS_READINESS_H
#define HOUJI_GPU_GRAPHICS_READINESS_H
#include <stdint.h>
enum {HGR_OK,HGR_ARGUMENT,HGR_REUSED,HGR_OWNER,HGR_READ};
enum {HGR_PRE_APERTURE,HGR_POST_APERTURE,HGR_POST_CP_IDLE,
 HGR_POST_AUTH,HGR_POST_MODE_IDLE,HGR_STAGES};
enum {HGR_TRUST_CNTL,HGR_TSB_STATUS_LO,HGR_TSB_STATUS_HI,HGR_REGS};
struct hgr_io {
 void *cookie;
 int (*owned)(void *,unsigned);
 int (*read)(void *,uint32_t,uint32_t *);
};
struct hgr_result {
 unsigned started,stage,code,phase,guards,reads,attempted,valid;
 int owner_code,read_code;
 uint32_t raw[HGR_REGS];
};
static inline uint32_t hgr_address(unsigned reg) {
 static const uint32_t a[]={0x03d3d000,0x03d3f000,0x03d3f004};
 return reg<HGR_REGS?a[reg]:0;
}
static inline unsigned hgr_capture(const struct hgr_io *io,unsigned stage,struct hgr_result *r) {
 if(!r)return HGR_ARGUMENT;
 if(r->started)return HGR_REUSED;
 *r=(struct hgr_result){.started=1,.stage=stage};
 if(stage>=HGR_STAGES || !io || !io->owned || !io->read)return r->code=HGR_ARGUMENT;
 for(unsigned i=0;i<HGR_REGS;i++) {
  r->phase=1;r->guards++;r->owner_code=io->owned(io->cookie,stage);
  if(r->owner_code)return r->code=HGR_OWNER;
  uint32_t v=0;r->phase=2;r->attempted|=1u<<i;r->reads++;
  r->read_code=io->read(io->cookie,hgr_address(i),&v);
  if(r->read_code)return r->code=HGR_READ;
  r->raw[i]=v;r->valid|=1u<<i;
 }
 r->phase=3;r->guards++;r->owner_code=io->owned(io->cookie,stage);
 if(r->owner_code)return r->code=HGR_OWNER;
 r->phase=4;return r->code=HGR_OK;
}
#endif
