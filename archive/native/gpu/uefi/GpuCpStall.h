/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Fixed direct-read CP stall observations, never a completion/idle waiver.
 * Register names/offsets: OnePlus453d8875 gen7_reg.h:47-52,105-110,120-121,
 * 184-186; Mesa85fda3b3 a6xx.xml:175-186,366-369,553-583.
 * Primary actual-read precedent: Linux21a7f44 a6xx_fault_detect_irq:1825-1843
 * (status/status3 and BR IB1/IB2), OnePlus453d adreno_gen7.c:1218-1285
 * (CP/BV interrupt, fault and protection). CP_STATUS_1 has a named schema but
 * no decoded bits. No indexed debug selectors or register writes are exposed.
 *
 * Capture before reset, under the existing fresh live power/context/fault
 * lease. A stalled engine can be busy: the owner must not require idle here.
 * This file has no print, firmware, filesystem, cache or memory-write callback.
 * Raw IB base/remaining are observations, not an asserted SQE program counter.
 */
#ifndef HOUJI_GPU_CP_STALL_H
#define HOUJI_GPU_CP_STALL_H
#include <stdint.h>
enum {HCS_OK,HCS_ARGUMENT,HCS_REUSED,HCS_OWNER,HCS_READ};
enum {HCS_STATUS,HCS_STATUS3,HCS_INTERRUPT,HCS_FAULT,HCS_PROTECT,HCS_STATUS1,
 HCS_IB1_LO,HCS_IB1_HI,HCS_IB1_REMAIN,HCS_IB2_LO,HCS_IB2_HI,HCS_IB2_REMAIN,
 HCS_BV_FAULT,HCS_BV_PROTECT,HCS_REGS};
struct hcs_io {void *cookie;int (*owned)(void *);int (*read)(void *,uint32_t,uint32_t *);};
struct hcs_result {
 unsigned started,stage,code,guards,reads,attempted,valid;
 int owner_code,read_code;
 uint32_t raw[HCS_REGS];
};
static inline uint32_t hcs_address(unsigned i) {
 static const uint32_t a[]={0x03d00840,0x03d0084c,0x03d0208c,0x03d02084,
  0x03d02090,0x03d02094,0x03d024a0,0x03d024a4,0x03d024a8,0x03d024ac,
  0x03d024b0,0x03d024b4,0x03d02990,0x03d02984};
 return i<HCS_REGS?a[i]:0;
}
static inline const char *hcs_name(unsigned i) {
 static const char *const names[]={"RBBM_STATUS","RBBM_STATUS3","CP_INTERRUPT_STATUS",
  "CP_HW_FAULT","CP_PROTECT_STATUS","CP_STATUS_1","CP_IB1_BASE_LO","CP_IB1_BASE_HI",
  "CP_IB1_REM_SIZE","CP_IB2_BASE_LO","CP_IB2_BASE_HI","CP_IB2_REM_SIZE",
  "CP_BV_HW_FAULT","CP_BV_PROTECT_STATUS"};
 return i<HCS_REGS?names[i]:"invalid";
}
static inline unsigned hcs_capture(const struct hcs_io *io,unsigned stage,struct hcs_result *r) {
 if(!r)return HCS_ARGUMENT;
 if(r->started)return HCS_REUSED;
 *r=(struct hcs_result){.started=1,.stage=stage};
 if(!io || !io->owned || !io->read)return r->code=HCS_ARGUMENT;
 for(unsigned i=0;i<HCS_REGS;i++) {
  r->guards++;r->owner_code=io->owned(io->cookie);
  if(r->owner_code)return r->code=HCS_OWNER;
  uint32_t v=0;r->attempted|=1u<<i;r->reads++;
  r->read_code=io->read(io->cookie,hcs_address(i),&v);
  if(r->read_code)return r->code=HCS_READ;
  r->raw[i]=v;r->valid|=1u<<i;
 }
 r->guards++;r->owner_code=io->owned(io->cookie);
 return r->code=r->owner_code?HCS_OWNER:HCS_OK;
}
#endif
