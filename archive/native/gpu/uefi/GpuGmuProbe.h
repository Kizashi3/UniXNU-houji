/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * CM3 ITCM/DTCM-only diagnostic, with exact TCM backup/restore and bounded polls.
 * Nine pinned CM3 startup controls; IRQ masks retained until platform reset.
 * No SMMU, external RAM, RCG, HFI, pending-IRQ clear or GPU command writes.
 */
#ifndef HOUJI_GPU_GMU_PROBE_H
#define HOUJI_GPU_GMU_PROBE_H
#include "GpuBusProbe.h"
#include "GpuGmuCode.h"
enum { HGD_OK,HGD_ARGUMENT,HGD_GUARD,HGD_IO,HGD_VERIFY,HGD_TIMEOUT,
       HGD_FAULT,HGD_RESET,HGD_RESTORE };
enum { HGD_CODE_WORDS=sizeof(hgd_code)/4,HGD_MAIL_WORDS=8,HGD_STACK_WORDS=16,
       HGD_TOTAL_WORDS=HGD_CODE_WORDS+HGD_MAIL_WORDS+HGD_STACK_WORDS,HGD_CONTROL_WORDS=9 };
struct hgd_io {
  void *cookie;
  GPP_U64 (*read)(void *,GPP_U32,GPP_U32 *);
  GPP_U64 (*write)(void *,GPP_U32,GPP_U32);
  GPP_U64 (*delay)(void *,unsigned);
  GPP_U64 (*checkpoint)(void *,unsigned);
};
struct hgd_result {
  unsigned code,reads,writes,polls,backup_words,modified,release_attempted;
  unsigned reset_held,restored_words,retained;
  GPP_U32 last_address,last_value,mailbox[HGD_MAIL_WORDS],gfsr;
  GPP_U32 saved[HGD_TOTAL_WORDS];
  GPP_U32 control_saved[HGD_CONTROL_WORDS];
  unsigned control_backup,control_attempted,control_restored;
  GPP_U32 verify_address,verify_value,verify_expected,verify_mask;
};
// Pinned gen7_gmu_register_config / power_config / irq_disable. The last
// two masks stay disabled until reset: never re-enable a pending unhandled IRQ.
static inline GPP_U32 hgd_control_address(unsigned i) {
  static const GPP_U32 a[]={0x3d7e3c0,0x3d7e3c4,0x3d7e004,0x3d7e0b4,
    0x3d7d03c,0x3d7d000,0x3d7d004,0x3d7e64c,0x3d8ec18};
  return i<HGD_CONTROL_WORDS?a[i]:0;
}
static inline int hgd_control_address_valid(GPP_U32 a) {
  unsigned i;for(i=0;i<HGD_CONTROL_WORDS;i++)if(hgd_control_address(i)==a)return 1;
  return 0;
}
static inline GPP_U32 hgd_tcm_address(unsigned i) {
  if(i<HGD_CODE_WORDS)return 0x3d6d000+4*i;
  i-=HGD_CODE_WORDS;
  if(i<HGD_MAIL_WORDS)return 0x3d71000+4*i;
  i-=HGD_MAIL_WORDS;
  return i<HGD_STACK_WORDS?0x3d74f40+4*i:0;
}
static inline int hgd_tcm_address_valid(GPP_U32 a) {
  if(a&3)return 0;
  return (a>=0x3d6d000 && a<0x3d6d000+sizeof(hgd_code)) ||
    (a>=0x3d71000 && a<0x3d71000+4*HGD_MAIL_WORDS) ||
    (a>=0x3d74f40 && a<0x3d74f40+4*HGD_STACK_WORDS);
}
static inline int hgd_bus_complete(const struct hgb_result *b) {
  unsigned i;
  if(!b || b->code || b->valid!=0x7fff || b->attempted!=7 || b->restored ||
     b->streams_seen!=24 || b->banks_seen!=22 || b->active_streams ||
     b->nonfault_routes || b->active_banks || b->values[HGB_FWINIT] ||
     b->values[HGB_GXPOWER]!=3 || b->values[HGB_GFSR] ||
     b->values[HGB_ID0]!=0x4c017e18 || b->values[HGB_ID1]!=0x40000016 ||
     b->values[HGB_ID2]!=0x5511 || b->values[HGB_RESET]!=1)return 0;
  for(i=0;i<24;i++)if(b->smr[i] || b->s2cr[i]!=0x20000)return 0;
  for(i=0;i<22;i++)if(b->sctlr[i]&1)return 0;
  return 1;
}
static inline int hgd_read(const struct hgd_io *io,struct hgd_result *r,
                          GPP_U32 a,GPP_U32 *out) {
  r->last_address=a;r->reads++;
  if(io->read(io->cookie,a,out)) {if(!r->code)r->code=HGD_IO;return 0;}
  r->last_value=*out;return 1;
}
static inline int hgd_write(const struct hgd_io *io,struct hgd_result *r,
                           GPP_U32 a,GPP_U32 value) {
  r->last_address=a;r->writes++;
  if(io->write(io->cookie,a,value)) {if(!r->code)r->code=HGD_IO;return 0;}
  return 1;
}
static inline int hgd_guard(const struct hgd_io *io,struct hgd_result *r) {
  unsigned i;GPP_U32 value=0;
  static const GPP_U32 guard_address[]={0x171004,0x171010,0x171018,0x3d97000,
    0x3d99108,0x3d99168,0x3d9911c,0x3d9913c,0x3d7e000,0x3d7e070,0x3d7e340,0x3da0048,
    0x3d99144,0x3d993e8,0x3d993ec,0x3d993f0};
  static const GPP_U32 guard_mask[]={0x80000003,0x80000003,0x80000001,0x80000001,
    1,0x80000000,0x80000000,0x80000001,0xffffffff,0xffffffff,0xffffffff,0xffffffff,
    0x80000001,0x80000000,0x80000001,0x71f};
  static const GPP_U32 guard_value[]={1,1,1,1,0,0x80000000,0,1,1,0,3,0,1,0,0,0x505};
  for(i=0;i<sizeof(guard_address)/sizeof(guard_address[0]);i++) {
    if(!hgd_read(io,r,guard_address[i],&value))return 0;
    if((value&guard_mask[i])!=guard_value[i]) {r->code=HGD_GUARD;return 0;}
  }
  return 1;
}
static inline int hgd_checkpoint(const struct hgd_io *io,struct hgd_result *r,unsigned stage) {
  if(io->checkpoint && io->checkpoint(io->cookie,stage)) {r->code=HGD_IO;return 0;}
  // Checkpoint I/O may run firmware events at application TPL. Revalidate
  // every clock/reset prerequisite before touching TCM or releasing CM3.
  if(!hgd_guard(io,r)) {r->reset_held=0;r->retained=1;return 0;}
  return 1;
}
static inline unsigned hgd_probe(const struct hgd_io *io,const struct gpp_report *p,
                                const struct hgb_result *b,struct hgd_result *r) {
  unsigned i;GPP_U32 value=0;int reset_seen=0;
  if(!r)return HGD_ARGUMENT;
  for(i=0;i<sizeof(*r);i++)((unsigned char *)r)[i]=0;
  if(!io || !io->read || !io->write || !io->delay || !hgb_owned(p) ||
     !hgd_bus_complete(b))return r->code=HGD_ARGUMENT;
  if(!hgd_guard(io,r)) {r->retained=1;return r->code;}
  reset_seen=1;
  if(!hgd_checkpoint(io,r,1)) {if(r->retained)return r->code;goto cleanup;}
  // TCM can contain all ones: that is data, not an invalid-register sentinel.
  for(i=0;i<HGD_TOTAL_WORDS;i++) {
    if(!hgd_read(io,r,hgd_tcm_address(i),&r->saved[i]))goto cleanup;
    r->backup_words++;
  }
  if(!hgd_checkpoint(io,r,2)) {if(r->retained)return r->code;goto cleanup;}
  r->modified=1;
  for(i=0;i<HGD_CODE_WORDS+HGD_MAIL_WORDS;i++) {
    GPP_U32 wanted=i<HGD_CODE_WORDS?hgd_code[i]:0;
    if(!hgd_write(io,r,hgd_tcm_address(i),wanted) ||
       !hgd_read(io,r,hgd_tcm_address(i),&value))goto cleanup;
    if(value!=wanted) {r->code=HGD_VERIFY;goto cleanup;}
  }
  if(!hgd_read(io,r,0x3d7e000,&value) || value!=1) {
    if(!r->code)r->code=HGD_RESET;goto cleanup;
  }
  for(i=0;i<HGD_CONTROL_WORDS;i++) {
    if(!hgd_read(io,r,hgd_control_address(i),&r->control_saved[i]))goto cleanup;
    r->control_backup++;
  }
  if(!hgd_checkpoint(io,r,6)) {if(r->retained)return r->code;goto cleanup;}
  for(i=0;i<HGD_CONTROL_WORDS;i++) {
    static const GPP_U32 init[]={1,1,2,0x4052,1,1,1,0xffffffffu,0xffffffffu};
    r->control_attempted|=1u<<i;
    if(!hgd_write(io,r,hgd_control_address(i),init[i]) ||
       !hgd_read(io,r,hgd_control_address(i),&value))goto cleanup;
    // AO interrupt mask implements low bits only. Same-chip pinned terminal
    // reference verifies 0x7f after the vendor's UINT_MAX mask write.
    GPP_U32 mask=i==8?0x7fu:0xffffffffu;
    if((value&mask)!=(init[i]&mask)) {
      r->verify_address=hgd_control_address(i);r->verify_value=value;
      r->verify_expected=init[i];r->verify_mask=mask;
      r->code=HGD_VERIFY;goto cleanup;
    }
  }
  if(!hgd_checkpoint(io,r,3)) {if(r->retained)return r->code;goto cleanup;}
  r->release_attempted=1;
  if(!hgd_write(io,r,0x3d7e000,0))goto cleanup;
  // This exact diagnostic is confined to internal TCM, IRQs masked, no WFI.
  // Saving a host checkpoint while it runs cannot expose external DMA.
  if(io->checkpoint && io->checkpoint(io->cookie,7)) {r->code=HGD_IO;goto cleanup;}
  for(i=0;i<1000;i++) {
    if(!hgd_read(io,r,0x3d71000,&r->mailbox[0]))goto cleanup;
    if(r->mailbox[0]==0xa7500002)break;
    if(r->mailbox[0]==0xa750dead) {r->code=HGD_FAULT;goto cleanup;}
    r->polls++;
    if(i<999 && io->delay(io->cookie,10)) {r->code=HGD_IO;goto cleanup;}
  }
  if(i==1000) {r->code=HGD_TIMEOUT;goto cleanup;}
  for(i=1;i<HGD_MAIL_WORDS;i++)
    if(!hgd_read(io,r,0x3d71000+4*i,&r->mailbox[i]))goto cleanup;
  if(r->mailbox[1]!=0x750c0de0 || r->mailbox[2]!=128)r->code=HGD_VERIFY;
  if(!hgd_read(io,r,0x3da0048,&r->gfsr))goto cleanup;
  if(r->gfsr)r->code=HGD_FAULT;
  if(io->checkpoint && io->checkpoint(io->cookie,8))r->code=HGD_IO;
cleanup:
  // A failed release write might have reached hardware. Always assert reset
  // after an attempted release; never overwrite TCM while CM3 may be running.
  if(r->release_attempted)(void)hgd_write(io,r,0x3d7e000,1);
  if(reset_seen || r->release_attempted) {
    for(i=0;i<1000;i++) {
      if(!hgd_read(io,r,0x3d7e000,&value))break;
      if(value==1) {r->reset_held=1;break;}
      r->polls++;
      if(i<999 && io->delay(io->cookie,10))break;
    }
  }
  if(!r->reset_held) {r->retained=1;return r->code?r->code:(r->code=HGD_RESET);}
  if(r->modified) {
    if(r->backup_words!=HGD_TOTAL_WORDS) {r->retained=1;return r->code=HGD_RESTORE;}
    for(i=0;i<HGD_TOTAL_WORDS;i++) {
      if(hgd_write(io,r,hgd_tcm_address(i),r->saved[i]) &&
         hgd_read(io,r,hgd_tcm_address(i),&value) && value==r->saved[i])r->restored_words++;
    }
    if(r->restored_words!=HGD_TOTAL_WORDS)r->code=HGD_RESTORE;
  }
  for(i=7;i>0;i--) {
    unsigned n=i-1;if(!(r->control_attempted&(1u<<n)))continue;
    if(hgd_write(io,r,hgd_control_address(n),r->control_saved[n]) &&
       hgd_read(io,r,hgd_control_address(n),&value) && value==r->control_saved[n])
      r->control_restored|=1u<<n;
  }
  if(r->control_restored!=(r->control_attempted&0x7fu))r->code=HGD_RESTORE;
  return r->code;
}
#endif
