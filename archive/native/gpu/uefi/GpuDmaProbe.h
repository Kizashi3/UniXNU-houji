/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Exclusive selected-bank / ASID750 / slot0 SID5 native4K GMU memory diagnostic.
 * Known polling SCTLR profile masks context IRQ and never stalls on a fault.
 * Every failure retains all resources; only CM3 reset is attempted on failure.
 * No arbitrary register replay, GPU commands, stock firmware or HFI.
 */
#ifndef HOUJI_GPU_DMA_PROBE_H
#define HOUJI_GPU_DMA_PROBE_H
#include "GpuGmuProbe.h"
#include "GpuSmmuContext.h"
#include "GpuDmaCode.h"
#include "GpuDmaMemory.h"
enum { HGA_CODE_WORDS=sizeof(hga_code)/4,HGA_MAIL_WORDS=8,HGA_STACK_WORDS=16,
  HGA_TCM_WORDS=HGA_CODE_WORDS+HGA_MAIL_WORDS+HGA_STACK_WORDS };
struct hga_io {
  struct hgp_io smmu;
  struct hgd_io gmu;
  void *cookie;
  int (*publish)(void *,const struct hgt_owned *,uint64_t,void *);
  int (*cpu_finish)(void *,const struct hgt_owned *,struct hga_cpu_result *);
  int (*checkpoint)(void *,unsigned);
};
struct hga_result {
  unsigned code,phase,must_retain,complete,published,positive,negative;
  unsigned backed_up,restored,control_backup,control_attempted,control_restored;
  unsigned enable_attempted,stream_attempted,release_attempted,detached,platform_retired;
  uint32_t saved[HGA_TCM_WORDS],controls[9],mailbox[8],fsr,fsynr;
  uint64_t far;
  struct hgp_result regs;
  struct hgd_result cm3;
  struct hga_cpu_result cpu;
};
static inline uint32_t hga_tcm_address(unsigned i) {
  if(i<HGA_CODE_WORDS)return 0x3d6d000+4*i;
  i-=HGA_CODE_WORDS;if(i<HGA_MAIL_WORDS)return 0x3d71000+4*i;
  i-=HGA_MAIL_WORDS;return i<HGA_STACK_WORDS?0x3d74f40+4*i:0;
}
static inline int hga_tcm_address_valid(uint32_t a) {
  if(a&3)return 0;
  return (a>=0x3d6d000 && a<0x3d6d000+sizeof(hga_code)) ||
    (a>=0x3d71000 && a<0x3d71020) || (a>=0x3d74f40 && a<0x3d74f80);
}
static inline uint32_t hga_control_value(unsigned i) {
  static const uint32_t v[]={1,1,2,0x4052,1,1,1,0xffffffffu,0xffffffffu};
  return i<9?v[i]:0;
}
static inline int hga_set(const struct hga_io *io,struct hga_result *r,uint32_t a,
    uint32_t wanted,uint32_t mask) {
  uint64_t v=0;
  return hgp_write(&io->smmu,&r->regs,a,wanted,0) &&
    hgp_read(&io->smmu,&r->regs,a,&v,0) && (((uint32_t)v^wanted)&mask)==0;
}
/* Called only with CM3 held reset. Snapshot every stream, bank and exact
 * configured root; the selected stream alone may have our exact lease. */
static inline int hga_guard(const struct hga_io *io,struct hga_result *r,
    const uint64_t *image,uint64_t zero,unsigned platform,unsigned enabled,unsigned attached) {
  uint64_t v=0;
  if(io->smmu.power_guard(io->smmu.cookie))return 0;
  const uint32_t a[]={0x3da0020,0x3da0024,0x3da0028,0x3da0048};
  const uint32_t wanted[]={0x4c017e18,0x40000016,0x5511,0};
  for(unsigned i=0;i<4;i++)if(!hgp_read(&io->smmu,&r->regs,a[i],&v,0) || v!=wanted[i])return 0;
  for(unsigned i=0;i<24;i++) {
    if(!hgp_read(&io->smmu,&r->regs,0x3da0800+4*i,&v,0) ||
       v!=(i==0 && attached?0x80000005u:0))return 0;
    if(!hgp_read(&io->smmu,&r->regs,0x3da0c00+4*i,&v,0) ||
       v!=(i==0 && attached?HGP_CONTEXT_BANK:0x20000))return 0;
  }
  for(unsigned i=0;i<22;i++) {
    if(!hgp_read(&io->smmu,&r->regs,0x3dc0000+4096*i,&v,0))return 0;
    if(i==HGP_CONTEXT_BANK) {if(enabled?((v&~UINT64_C(0x1000))!=0x27):v!=0)return 0;}
    else if(v&1)return 0;
  }
  for(unsigned i=1;i<9;i++)
    if(!hgp_read(&io->smmu,&r->regs,hgp_field_address(i),&v,i==5 || i==6) || v!=image[i])return 0;
  const uint32_t pa[]={HGP_CB(0x4),0x3da6008,0x3da600c};
  const uint32_t pv[]={platform?0x32bu:3u,platform?(uint32_t)zero:0,platform?(uint32_t)(zero>>32):0};
  for(unsigned i=0;i<3;i++)if(!hgp_read(&io->smmu,&r->regs,pa[i],&v,0) || v!=pv[i])return 0;
  return 1;
}
static inline int hga_verify_tcm(const struct hga_io *io,struct hga_result *r) {
  uint32_t v=0;
  for(unsigned i=0;i<HGA_CODE_WORDS+HGA_MAIL_WORDS;i++) {
    uint32_t wanted=i<HGA_CODE_WORDS?hga_code[i]:0;
    if(!hgd_read(&io->gmu,&r->cm3,hga_tcm_address(i),&v) || v!=wanted)return 0;
  }
  for(unsigned i=0;i<9;i++) {
    uint32_t mask=i==8?0x7f:0xffffffffu;
    if(!hgd_read(&io->gmu,&r->cm3,hgd_control_address(i),&v) ||
       ((v^hga_control_value(i))&mask))return 0;
  }
  return 1;
}
static inline int hga_zero_valid(const struct hgt_owned *o,uint64_t pa,const void *cpu) {
  if(!o || !cpu || !pa || (pa&4095) || ((uintptr_t)cpu&4095) ||
     pa>=(UINT64_C(1)<<36)-4096 || (uintptr_t)cpu>UINTPTR_MAX-4096 ||
     (pa<o->table_physical+12288 && o->table_physical<pa+4096) ||
     (pa<o->data_physical+4096 && o->data_physical<pa+4096) ||
     ((uintptr_t)cpu<(uintptr_t)o->tables+12288 && (uintptr_t)o->tables<(uintptr_t)cpu+4096) ||
     ((uintptr_t)cpu<(uintptr_t)o->data+4096 && (uintptr_t)o->data<(uintptr_t)cpu+4096))return 0;
  const volatile uint32_t *words=cpu;
  for(unsigned i=0;i<1024;i++)if(words[i])return 0;
  return 1;
}
static inline unsigned hga_probe(const struct hga_io *io,const struct hgt_owned *owned,
    const uint64_t *image,uint64_t zero,void *zero_cpu,struct hga_result *r) {
  uint64_t v=0;uint32_t w=0;
  if(!r)return HGP_ARGUMENT;*r=(struct hga_result){0};r->must_retain=1;
  if(!io || !io->smmu.read32 || !io->smmu.read64 || !io->smmu.write32 ||
     !io->smmu.write64 || !io->smmu.power_guard || !io->smmu.delay ||
     !io->gmu.read || !io->gmu.write || !io->gmu.delay || !io->publish ||
     !io->cpu_finish || !owned || !image || !hga_zero_valid(owned,zero,zero_cpu))return r->code=HGP_ARGUMENT;
#define HGA_REQUIRE(condition,error) do {if(!(condition)){r->code=(error);goto failed;}} while(0)
  r->phase=1;
  HGA_REQUIRE(hga_guard(io,r,image,zero,0,0,0),HGP_GUARD);r->cm3.reset_held=1;
  HGA_REQUIRE(!io->publish(io->cookie,owned,zero,zero_cpu),HGP_IO);r->published++;
  HGA_REQUIRE(hgp_read(&io->smmu,&r->regs,HGP_CB(0x58),&v,0),HGP_IO);
  HGA_REQUIRE(!(v&0xc00001feu),HGP_GUARD);
  for(unsigned i=0;i<HGA_TCM_WORDS;i++) {
    HGA_REQUIRE(hgd_read(&io->gmu,&r->cm3,hga_tcm_address(i),&r->saved[i]),HGP_IO);r->backed_up++;
  }
  for(unsigned i=0;i<9;i++) {
    HGA_REQUIRE(hgd_read(&io->gmu,&r->cm3,hgd_control_address(i),&r->controls[i]),HGP_IO);r->control_backup++;
  }
  r->phase=2;
  for(unsigned i=0;i<HGA_CODE_WORDS+HGA_MAIL_WORDS;i++) {
    uint32_t wanted=i<HGA_CODE_WORDS?hga_code[i]:0;
    HGA_REQUIRE(hgd_write(&io->gmu,&r->cm3,hga_tcm_address(i),wanted) &&
      hgd_read(&io->gmu,&r->cm3,hga_tcm_address(i),&w) && w==wanted,HGP_VERIFY);
  }
  for(unsigned i=0;i<9;i++) {
    r->control_attempted|=1u<<i;
    HGA_REQUIRE(hgd_write(&io->gmu,&r->cm3,hgd_control_address(i),hga_control_value(i)),HGP_IO);
  }
  HGA_REQUIRE(hga_verify_tcm(io,r),HGP_VERIFY);
  r->phase=3;
  HGA_REQUIRE(hga_set(io,r,0x3da6008,(uint32_t)zero,0xffffffffu) &&
    hga_set(io,r,0x3da600c,(uint32_t)(zero>>32),0xffffffffu) &&
    hga_set(io,r,HGP_CB(0x4),0x32b,0xffffffffu) && hgp_sync(&io->smmu,&r->regs),HGP_IO);
  r->phase=4;
  HGA_REQUIRE(!io->checkpoint || !io->checkpoint(io->cookie,1),HGP_IO);
  HGA_REQUIRE(hga_guard(io,r,image,zero,1,0,0) && hga_verify_tcm(io,r) &&
    hga_zero_valid(owned,zero,zero_cpu),HGP_GUARD);
  HGA_REQUIRE(!io->publish(io->cookie,owned,zero,zero_cpu),HGP_IO);r->published++;
  r->phase=5;r->enable_attempted=1;
  // ASIDPNE may read zero, as documented by the native4K component. CFIE=0;
  // CFCFG=0 supplies a non-stalling fault response for the single bad read.
  HGA_REQUIRE(hga_set(io,r,HGP_CB(0),0x1027,~0x1000u),HGP_VERIFY);
  r->phase=6;r->stream_attempted=1;
  // Route is installed while invalid; valid SID5 is the final attach write.
  HGA_REQUIRE(hga_set(io,r,0x3da0c00,HGP_CONTEXT_BANK,0xffffffffu) &&
    hga_set(io,r,0x3da0800,0x80000005u,0xffffffffu),HGP_VERIFY);
  HGA_REQUIRE(hga_guard(io,r,image,zero,1,1,1),HGP_GUARD);
  HGA_REQUIRE(hgp_read(&io->smmu,&r->regs,HGP_CB(0x58),&v,0) && !(v&0xc00001feu),HGP_GUARD);
  r->phase=7;r->release_attempted=1;r->cm3.reset_held=0;
  HGA_REQUIRE(hgd_write(&io->gmu,&r->cm3,0x3d7e000,0),HGP_IO);
  for(unsigned i=0;i<1000;i++) {
    HGA_REQUIRE(hgd_read(&io->gmu,&r->cm3,0x3d71000,&r->mailbox[0]),HGP_IO);
    if(r->mailbox[0]==0xa7500003 || r->mailbox[0]==0xa750dead)break;
    HGA_REQUIRE(i<999,HGP_TIMEOUT);r->cm3.polls++;
    HGA_REQUIRE(!io->gmu.delay(io->gmu.cookie,10),HGP_IO);
  }
  r->phase=8;
  HGA_REQUIRE(hgd_write(&io->gmu,&r->cm3,0x3d7e000,1),HGP_IO);
  for(unsigned i=0;i<1000;i++) {
    HGA_REQUIRE(hgd_read(&io->gmu,&r->cm3,0x3d7e000,&w),HGP_IO);
    if(w==1){r->cm3.reset_held=1;break;}
    HGA_REQUIRE(i<999,HGP_TIMEOUT);r->cm3.polls++;
    HGA_REQUIRE(!io->gmu.delay(io->gmu.cookie,10),HGP_IO);
  }
  r->phase=9;
  for(unsigned i=1;i<8;i++)HGA_REQUIRE(hgd_read(&io->gmu,&r->cm3,0x3d71000+4*i,&r->mailbox[i]),HGP_IO);
  r->positive=r->mailbox[1]==0x7504cafeu && r->mailbox[2]==0x86500071u &&
    r->mailbox[3]==0xa750cafeu && r->mailbox[4]==0;
  HGA_REQUIRE(hgp_read(&io->smmu,&r->regs,HGP_CB(0x58),&v,0),HGP_IO);r->fsr=(uint32_t)v;
  HGA_REQUIRE(hgp_read(&io->smmu,&r->regs,HGP_CB(0x60),&r->far,1),HGP_IO);
  HGA_REQUIRE(hgp_read(&io->smmu,&r->regs,HGP_CB(0x68),&v,0),HGP_IO);r->fsynr=(uint32_t)v;
  r->negative=(r->fsr&0xc00001feu)==2 && r->far==UINT64_C(0x60002000) && !(r->fsynr&16);
  HGA_REQUIRE(r->positive && r->negative && hga_guard(io,r,image,zero,1,1,1),HGP_VERIFY);
  r->phase=10;
  // Invalidate the stream first; never retarget a valid SID. CM3 reset is held.
  HGA_REQUIRE(hga_set(io,r,0x3da0800,0,0xffffffffu) &&
    hga_set(io,r,0x3da0c00,0x20000,0xffffffffu) &&
    hga_set(io,r,HGP_CB(0),0,0xffffffffu) && hgp_sync(&io->smmu,&r->regs),HGP_IO);
  r->detached=1;
  HGA_REQUIRE(hga_guard(io,r,image,zero,1,0,0),HGP_GUARD);
  // Only this exact observed read-translation fault belongs to this test.
  // No global faults or arbitrary FSR contents are cleared.
  HGA_REQUIRE(hgp_write(&io->smmu,&r->regs,HGP_CB(0x58),2,0) &&
    hgp_read(&io->smmu,&r->regs,HGP_CB(0x58),&v,0) && !(v&0xc00001feu),HGP_VERIFY);
  r->phase=11;
  // Restore only the exact known cold ACTLR baseline 3 / PRR zero required
  // above, never an arbitrary captured power-on image like the old CBAR bug.
  HGA_REQUIRE(hga_set(io,r,HGP_CB(0x4),3,0xffffffffu) && hgp_sync(&io->smmu,&r->regs) &&
    hga_set(io,r,0x3da6008,0,0xffffffffu) && hga_set(io,r,0x3da600c,0,0xffffffffu),HGP_IO);
  HGA_REQUIRE(hga_guard(io,r,image,zero,0,0,0),HGP_GUARD);r->platform_retired=1;
  r->phase=12;
  for(unsigned i=0;i<HGA_TCM_WORDS;i++) {
    HGA_REQUIRE(hgd_write(&io->gmu,&r->cm3,hga_tcm_address(i),r->saved[i]) &&
      hgd_read(&io->gmu,&r->cm3,hga_tcm_address(i),&w) && w==r->saved[i],HGP_RESTORE);r->restored++;
  }
  for(unsigned i=7;i>0;i--) {
    unsigned n=i-1;
    HGA_REQUIRE(hgd_write(&io->gmu,&r->cm3,hgd_control_address(n),r->controls[n]) &&
      hgd_read(&io->gmu,&r->cm3,hgd_control_address(n),&w) && w==r->controls[n],HGP_RESTORE);
    r->control_restored|=1u<<n;
  }
  r->phase=13;
  HGA_REQUIRE(!io->cpu_finish(io->cookie,owned,&r->cpu) && r->cpu.verified && r->cpu.restored,HGP_VERIFY);
  HGA_REQUIRE(hga_zero_valid(owned,zero,zero_cpu) && hga_guard(io,r,image,zero,0,0,0),HGP_GUARD);
  r->phase=14;
  HGA_REQUIRE(!io->checkpoint || !io->checkpoint(io->cookie,2),HGP_IO);
  HGA_REQUIRE(hga_guard(io,r,image,zero,0,0,0),HGP_GUARD);
  r->complete=1;r->must_retain=0;return HGP_OK;
failed:
  // A failed release/reset write may already have reached hardware. Do not
  // free, gate clocks, detach an uncertain foreign stream, or overwrite TCM.
  // Only try to hold the known diagnostic master in reset, with bounded polls.
  if(r->release_attempted && !r->cm3.reset_held) {
    (void)hgd_write(&io->gmu,&r->cm3,0x3d7e000,1);
    for(unsigned i=0;i<1000;i++) {
      if(!hgd_read(&io->gmu,&r->cm3,0x3d7e000,&w))break;
      if(w==1){r->cm3.reset_held=1;break;}
      if(i==999 || io->gmu.delay(io->gmu.cookie,10))break;
    }
  }
  return r->code?r->code:(r->code=HGP_IO);
#undef HGA_REQUIRE
}
#endif
