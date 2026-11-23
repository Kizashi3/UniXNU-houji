// SPDX-License-Identifier: BSD-2-Clause-Patent
// Actual candidate + actual gpp/hgb/hcw policies, hardware callbacks only mocked.
#include <assert.h>
#include <stdio.h>
#include <string.h>
#ifdef HPH_TEST_FIRMWARE_TYPES
#include <stdint.h>
typedef uint32_t UINT32;
typedef uint64_t UINT64;
#define GPP_FIRMWARE_TYPES 1
#endif
#include "GpuPowerOnlyHandoff.h"
struct mock {
 uint32_t regs[HGB_REGS],smr[24],s2cr[24],banks[22],clock[HCW_REGS],hfi;
 unsigned reads,writes,delays,owners,hubs,queries;
 unsigned fail_read,fail_write,fail_owner,fail_delay,fail_hub,fail_query,stuck;
 unsigned mutate_after_hub,unstable_clock,post_hub_reads,late_owner;
 uint32_t addresses[3],written[3];
};
static unsigned cases;
static int reg_index(uint32_t a) {
 for(unsigned i=0;i<HGB_REGS;i++)if(a==hgb_address(i))return (int)i;
 return -1;
}
static int clock_index(uint32_t a) {
 for(unsigned i=0;i<HCW_REGS;i++)if(a==hcw_address(i))return (int)i;
 return -1;
}
static int owner(void *cookie) {
 struct mock *m=cookie;
 return ++m->owners==m->fail_owner || (m->late_owner && m->hubs && m->post_hub_reads>=m->late_owner);
}
static GPP_U64 read32(void *cookie,GPP_U32 a,GPP_U32 *v) {
 struct mock *m=cookie;assert(v && hph_read_allowed(a));
 if(++m->reads==m->fail_read)return UINT64_C(0x8000000000000007);
 if(m->hubs)m->post_hub_reads++;
 int index=reg_index(a);
 if(index>=0) {*v=m->regs[index];return 0;}
 if(a==0x3d7e600) {*v=m->hfi;return 0;}
 index=clock_index(a);
 if(index>=0) {
  *v=m->clock[index];
  if(m->unstable_clock && index==HCW_GMU_CFG && m->queries)*v^=0x100;
  return 0;
 }
 assert((m->regs[HGB_CFG]&0x80000003u)==1 &&
  (m->regs[HGB_MEM]&0x80000003u)==1 && (m->regs[HGB_VOTE]&0x80000001u)==1);
 if(a>=0x3dc0000)*v=m->banks[(a-0x3dc0000)/4096];
 else if(a>=0x3da0c00)*v=m->s2cr[(a-0x3da0c00)/4];
 else *v=m->smr[(a-0x3da0800)/4];
 return 0;
}
static GPP_U64 write32(void *cookie,GPP_U32 a,GPP_U32 v) {
 struct mock *m=cookie;int field=hph_field(a),reg=reg_index(a);
 assert(field>=0 && reg>=0 && m->writes<3);
 unsigned bit=field==2?1u:2u;
 assert(!((v^m->regs[reg])&~(bit|0x80000000u)));
 assert((v&bit)==(field==2?1u:0u));
 m->addresses[m->writes]=a;m->written[m->writes]=v;
 if(++m->writes==m->fail_write) {
  // A failed firmware store may still have changed the hardware.
  m->regs[reg]=v;return UINT64_C(0x8000000000000007);
 }
 m->regs[reg]=v;
 if(field==2)m->regs[reg]&=~0x80000000u;
 else m->regs[reg]&=~0x80000000u;
 if(m->stuck==m->writes)m->regs[reg]|=0x80000000u;
 return 0;
}
static GPP_U64 delay_us(void *cookie,unsigned us) {
 struct mock *m=cookie;assert(us==1);return ++m->delays==m->fail_delay?1:0;
}
static GPP_U64 hub(void *cookie,const struct gpp_report *p,const struct hgb_result *b) {
 struct mock *m=cookie;
 assert(!m->hubs++ && hgb_owned(p) && b->streams_seen==24 && b->banks_seen==22 &&
  b->attempted==7 && !b->restored && m->regs[HGB_RESET]==1);
 assert(!m->clock[HCW_HUB_AON] && !m->clock[HCW_HUB_CMD] && !m->clock[HCW_HUB_CFG]);
 m->clock[HCW_HUB_CFG]=0x505;
 if(m->mutate_after_hub==1)m->smr[11]=0x80000005;
 if(m->mutate_after_hub==2)m->s2cr[11]=0;
 if(m->mutate_after_hub==3)m->banks[11]=1;
 if(m->mutate_after_hub==4)m->hfi=1;
 if(m->mutate_after_hub==5)m->regs[HGB_RESET]=0;
 return m->fail_hub?UINT64_C(0x8000000000000007):0;
}
static GPP_U64 configured(void *cookie,unsigned which,uint32_t *v) {
 struct mock *m=cookie;assert(which==m->queries && which<2 && v);m->queries++;
 *v=which?200000000u:777u; // Unavailable GMU value must never become a rate claim.
 return !which || m->fail_query==which+1?UINT64_C(0x8000000000000013):0;
}
static struct mock initial(void) {
 struct mock m={0};
 m.regs[HGB_CFG]=m.regs[HGB_MEM]=0x80000003u;m.regs[HGB_DVM]=1;
 m.regs[HGB_CX]=0xf822f800;m.regs[HGB_HW]=0x80000202;m.regs[HGB_AHB]=0;
 m.regs[HGB_RESET]=1;m.regs[HGB_VOTE]=0x80000000;
 m.regs[HGB_ID0]=0x4c017e18;m.regs[HGB_ID1]=0x40000016;m.regs[HGB_ID2]=0x5511;
 m.regs[HGB_CR0]=0x2f0406;m.regs[HGB_GXPOWER]=3;
 for(unsigned i=0;i<24;i++)m.s2cr[i]=0x20000;
 m.clock[HCW_GMU_BRANCH]=0x2001;m.clock[HCW_PLL1_MODE]=0x100;m.clock[HCW_PLL1_USER]=1;
 return m;
}
// Obtain the exact native partial using the real gpp_prepare, not invented fields.
struct prep_mock {uint32_t values[GPP_REGISTER_COUNT];};
static GPP_U64 resolve(void *c) {(void)c;return 0;}
static GPP_U64 acd(void *c) {(void)c;return 0;}
static GPP_U64 resource(void *c,unsigned id,unsigned op,uint32_t requested,uint32_t *actual) {
 struct prep_mock *m=c;
 assert(id==GPP_CX && op==GPP_ENABLE && requested==1 && actual);
 m->values[GPP_REG_CX]=0;m->values[GPP_REG_CX_HW]=0x80000000u;return 0;
}
static GPP_U64 prep_read(void *c,unsigned reg,uint32_t *v) {
 struct prep_mock *m=c;assert(reg<GPP_REGISTER_COUNT);*v=m->values[reg];return 0;
}
static GPP_U64 prep_delay(void *c,unsigned us) {(void)c;(void)us;assert(0);return 1;}
static struct gpp_report power(void) {
 struct prep_mock m={0};m.values[GPP_REG_CFG]=1;m.values[GPP_REG_CX]=1;
 m.values[GPP_REG_GMU]=0x2001;
 struct gpp_report p;gpp_report_init(&p);
 const struct gpp_io io={&m,resolve,acd,resource,prep_read,prep_delay};
 assert(gpp_prepare(&io,&p)==GPP_ERR_INITIAL);
 // Actual GpuPower.c Prepare adds the native provider/QMP diagnostics after
 // gpp_prepare returns; qpt_close has closed/released an acknowledged channel.
 p.flags|=GPP_PROVIDER_UNBOUNDED;p.valid_reads|=0xc000;
 p.values[14]=0x20000;p.values[15]=0x2c;gpp_report_seal(&p);
 assert(hph_power_qualified(&p,HPH_PREPARE_STATUS));return p;
}
static unsigned run(struct mock *m,const struct gpp_report *p,struct hph_record *r) {
 const struct hph_io io={m,read32,write32,delay_us,hub,configured,owner};
 return hph_run(&io,p,HPH_PREPARE_STATUS,r);
}
static void failed(struct mock *m,const struct gpp_report *p,struct hph_record *r) {
 assert(run(m,p,r)!=HPH_OK && !r->complete && r->retained && hph_record_valid(r));
 assert(m->writes<=3);cases++;
}
int main(void) {
 struct gpp_report p=power(),bad;struct hph_record good={0},r;
 struct mock m=initial();assert(run(&m,&p,&good)==HPH_OK);cases++;
 const struct mock running=m;
 assert(hph_record_valid(&good) && good.complete && good.retained && good.action_seen && good.action_complete);
 assert(good.bus_code==HGB_RETAIN && good.original_valid==7 && good.final_valid==7 && good.attempted==7);
 assert(good.original[0]==0x80000003u && good.original[1]==0x80000003u && good.original[2]==0x80000000u);
 assert(good.final[0]==1 && good.final[1]==1 && good.final[2]==1 && m.writes==3 && m.hubs==1 && m.queries==2);
 assert(good.clock.configured_valid==2 && good.clock.configured_hz[0]==0 &&
  good.clock.configured_status_hi[0]==0x80000000u && good.clock.configured_status_lo[0]==0x13);
 assert(good.clock.source[0]==0 && good.clock.derived_valid==1 && good.clock.derived_lo[0]==19200000);
 assert(!good.clock.derived_hi[0] && !(good.clock.derived_valid&2));
 assert(hph_recheck(&good,&good.after,&good.clock)==HPH_OK);cases++;
 unsigned reads=m.reads,owners=m.owners;
 assert(hph_run(NULL,NULL,0,&good)==HPH_REUSED && m.reads==reads);cases++;
 // Every actual successful-path MMIO and ownership call can fail, without a rollback store.
 for(unsigned i=1;i<=reads;i++) {m=initial();m.fail_read=i;r=(struct hph_record){0};failed(&m,&p,&r);}
 for(unsigned i=1;i<=owners;i++) {m=initial();m.fail_owner=i;r=(struct hph_record){0};failed(&m,&p,&r);}
 for(unsigned i=1;i<=3;i++) {
  m=initial();m.fail_write=i;r=(struct hph_record){0};failed(&m,&p,&r);
  assert(r.code==HPH_WRITE && m.writes==i && !(r.final_valid&(1u<<(i-1))));
 }
 for(unsigned i=1;i<=3;i++) {
  m=initial();m.stuck=i;r=(struct hph_record){0};failed(&m,&p,&r);
  assert(r.first_bus_code==HGB_TIMEOUT && m.writes==i && m.delays==999);
  m=initial();m.stuck=i;m.fail_delay=1;r=(struct hph_record){0};failed(&m,&p,&r);
  assert(r.code==HPH_DELAY && m.writes==i && m.delays==1);
 }
 m=initial();m.fail_hub=1;r=(struct hph_record){0};failed(&m,&p,&r);
 assert(r.code==HPH_HUB && r.hub_attempted && r.hub_status_hi==0x80000000u && !m.queries);
 m=initial();m.unstable_clock=1;r=(struct hph_record){0};failed(&m,&p,&r);assert(r.code==HPH_CLOCK);
 // Software NotStarted is a valid observation, never zero-Hz or a fake configured value.
 m=initial();m.fail_query=2;r=(struct hph_record){0};assert(!run(&m,&p,&r) && hph_record_valid(&r));
 assert(!r.clock.configured_valid && !r.clock.configured_hz[0] && !r.clock.configured_hz[1]);cases++;
 for(unsigned i=1;i<=5;i++) {
  m=initial();m.mutate_after_hub=i;r=(struct hph_record){0};failed(&m,&p,&r);
 }
 for(unsigned i=0;i<24;i++) {
  m=initial();m.smr[i]=0x80000005;r=(struct hph_record){0};failed(&m,&p,&r);
  assert(r.first_bus_code==HGB_BUSY && m.writes==3 && !m.hubs);
  m=initial();m.s2cr[i]=0;r=(struct hph_record){0};failed(&m,&p,&r);
 }
 for(unsigned i=0;i<22;i++) {m=initial();m.banks[i]=1;r=(struct hph_record){0};failed(&m,&p,&r);}
 for(unsigned i=0;i<3;i++) {
  m=initial();
  m.clock[i==0?HCW_HUB_AON:i==1?HCW_HUB_CMD:HCW_HUB_CFG]=1;
  r=(struct hph_record){0};failed(&m,&p,&r);assert(!m.hubs && r.hub_before_valid==(1u<<(i+1))-1u);
 }
 // Exact native partial, raw return status, reserved fields and inner CRC all matter.
 for(unsigned i=0;i<29;i++) {
  bad=p;
  switch(i) {
   case 0:bad.code=GPP_OK;break;case 1:bad.phase=GPP_PHASE_DONE;break;
   case 2:bad.resource=GPP_CX;break;case 3:bad.operation=GPP_OP_READ;break;
   case 4:bad.attempted|=1;break;case 5:bad.confirmed=0;break;
   case 6:bad.flags|=GPP_READY;break;case 7:bad.flags&=~GPP_ACD_CONSUMED;break;
   case 8:bad.flags&=~GPP_CFG_INHERITED;break;case 9:bad.retained=0;break;
   case 10:bad.valid_reads&=~8u;break;case 11:bad.values[GPP_REG_GMU]&=~1u;break;
   case 12:bad.firmware_status=1;break;case 13:bad.last_firmware_status=1;break;
   case 14:bad.protocol_status=1;break;case 15:bad.failure_phase=0;break;
   case 16:bad.failure_operation=0;break;case 17:bad.failure_resource=0;break;
   case 18:bad.observed^=1;break;case 19:bad.reserved[0]=1;break;
   case 20:bad.valid_reads&=~0x4000u;break;case 21:bad.values[14]|=1;break;
   case 22:bad.values[14]|=0x100;break;case 23:bad.values[14]|=0x10000;break;
   case 24:bad.values[15]=0x400;break;case 25:bad.values[15]|=1;break;
   case 26:bad.flags&=~GPP_PROVIDER_UNBOUNDED;break;
   case 27:bad.flags&=~GPP_OBSERVED_VALID;break;case 28:bad.valid_reads|=0x10;break;
  }
  gpp_report_seal(&bad);m=initial();r=(struct hph_record){0};
  assert(run(&m,&bad,&r)==HPH_POWER && !m.reads && !m.writes && !m.hubs && hph_record_valid(&r));cases++;
 }
 {const struct hph_io io={&m,read32,write32,delay_us,hub,configured,owner};
  r=(struct hph_record){0};assert(hph_run(&io,&p,0,&r)==HPH_POWER && hph_record_valid(&r));cases++;}
 // CRC and semantic checks, including CRC-valid forged completion.
 for(unsigned i=0;i<HPH_RECORD_BYTES;i++) {
  r=good;((unsigned char *)&r)[i]^=1;assert(!hph_record_valid(&r));cases++;
 }
 for(unsigned i=0;i<16;i++) {
  r=good;
  switch(i) {
   case 0:r.version=2;break;case 1:r.bytes-=4;break;case 2:r.retained=0;break;
   case 3:r.action_complete=0;break;case 4:r.bus_code=HGB_OK;break;case 5:r.attempted=3;break;
   case 6:r.final_valid=3;break;case 7:r.hub_before_valid=3;break;case 8:r.hub_before[1]=1;break;
   case 9:r.clock.configured_valid|=1;break;case 10:r.clock.configured_hz[0]=777;break;
   case 11:r.reserved[0]=1;break;
   case 12:r.original[0]^=0x100;break;case 13:r.clock.valid[0]|=0x80000000u;break;
   case 14:r.clock.derived_valid=3;break;case 15:r.clock.derived_lo[0]=625000000;break;
  }
  hph_seal(&r);assert(!hph_record_valid(&r));cases++;
 }
 // XNU gets no authority from the old snapshot: all fresh routes/banks and raw clocks are checked.
 for(unsigned i=0;i<24;i++) {
  struct hph_cold fresh=good.after;fresh.smr[i]=0x80000000;
  assert(hph_recheck(&good,&fresh,&good.clock)==HPH_COLD);cases++;
  fresh=good.after;fresh.s2cr[i]=0;assert(hph_recheck(&good,&fresh,&good.clock)==HPH_COLD);cases++;
 }
 for(unsigned i=0;i<22;i++) {
  struct hph_cold fresh=good.after;fresh.sctlr[i]|=1;
  assert(hph_recheck(&good,&fresh,&good.clock)==HPH_COLD);cases++;
 }
 const unsigned programming[]={HCW_GMU_CMD,HCW_GMU_CFG,HCW_GMU_BRANCH,HCW_HUB_CMD,HCW_HUB_CFG,
  HCW_HUB_AON,HCW_HUB_CX,HCW_AHB_DIV,HCW_PLL1_MODE,HCW_PLL1_OPMODE,HCW_PLL1_L,HCW_PLL1_ALPHA,HCW_PLL1_USER};
 for(unsigned i=0;i<sizeof(programming)/sizeof(programming[0]);i++) {
  struct hph_clock fresh=good.clock;unsigned reg=programming[i];fresh.raw[0][reg]^=0x20000000;
  fresh.raw[1][reg]^=0x20000000;
  assert(hph_recheck(&good,&good.after,&fresh)!=HPH_OK);cases++;
 }
 {struct hph_clock fresh=good.clock;fresh.raw[0][HCW_PLL1_STATUS]^=1;fresh.raw[1][HCW_PLL1_STATUS]^=2;
  assert(!hph_recheck(&good,&good.after,&fresh));cases++;}
 {unsigned char wire[HPH_RECORD_BYTES+1];memcpy(wire+1,&good,sizeof(good));
  assert(hph_decode(wire+1,HPH_RECORD_BYTES,&r) && !memcmp(&r,&good,sizeof(r)));cases++;
  assert(hph_decode(&good,sizeof(good),&good));cases++;
  assert(!hph_decode(wire+1,HPH_RECORD_BYTES-1,&r) && !r.magic);cases++;
  wire[1]^=1;assert(!hph_decode(wire+1,HPH_RECORD_BYTES,&r) && !r.magic);cases++;
 }
 {m=initial();m.clock[HCW_GMU_CFG]=0x100;r=(struct hph_record){0};
  assert(!run(&m,&p,&r) && hph_record_valid(&r) && r.clock.valid[0]==0xfffff &&
   r.clock.valid[1]==0xfffff && r.clock.source[0]==1 && !r.clock.derived_valid);cases++;
  struct hph_clock fresh=r.clock;fresh.raw[0][HCW_PLL0_L]^=1;fresh.raw[1][HCW_PLL0_L]^=1;
  assert(hph_recheck(&r,&r.after,&fresh)==HPH_CHANGED);cases++;
  fresh=r.clock;fresh.valid[0]&=~(1u<<HCW_PLL0_STATUS);
  assert(hph_recheck(&r,&r.after,&fresh)==HPH_COLD);cases++;
 }
 // Actual callback boundary cannot be used to write reset/SMMU/TCM/CP or to retry.
 const uint32_t forbidden[]={0x3d7e000,0x3da0800,0x3dc0000,0x3d6d000,0x3d02020,0x3d0201c,0x40600c};
 for(unsigned i=0;i<sizeof(forbidden)/sizeof(forbidden[0]);i++) {
  m=initial();r=(struct hph_record){0};struct hgb_result bus={0};
  const struct hph_io io={&m,read32,write32,delay_us,hub,configured,owner};
  struct hph_context context={&io,&p,&r,&bus,0};
  assert(hph_write(&context,forbidden[i],0) && !m.writes && r.code==HPH_WRITE);
  assert(hph_write(&context,0x171004,1) && !m.writes);cases++;
 }
 // A later lost gate must stop the final survey BEFORE any SMMU read.
 for(unsigned i=0;i<8;i++) {
  m=initial();m.regs[HGB_CFG]=m.regs[HGB_MEM]=m.regs[HGB_VOTE]=1;
  m.regs[i]^=(i==HGB_HW || i==HGB_AHB)?0x80000000u:1u;
  r=(struct hph_record){0};struct hgb_result bus={0};struct hph_cold state={0};
  const struct hph_io io={&m,read32,write32,delay_us,hub,configured,owner};
  struct hph_context context={&io,&p,&r,&bus,0};
  assert(!hph_survey(&context,&state) && m.reads==i+1 && !m.writes);cases++;
 }
 {struct hph_cold fresh;struct hph_clock clock;uint32_t failed_address;
  m=running;m.reads=m.owners=m.writes=m.queries=m.hubs=0;
  const struct hph_ro_io io={&m,read32,owner};
  assert(!hph_observe_ro(&io,&fresh,&clock,&failed_address) && !failed_address &&
   !m.writes && !m.queries && !m.hubs && clock.configured_valid==0 &&
   clock.configured_status_hi[0]==0x80000000u && clock.configured_status_lo[0]==0x13 &&
   !hph_recheck(&good,&fresh,&clock));cases++;
  unsigned ro_reads=m.reads,ro_owners=m.owners;
  for(unsigned i=1;i<=ro_reads;i++) {
   m=running;m.reads=m.owners=m.writes=m.queries=m.hubs=0;m.fail_read=i;
   assert(hph_observe_ro(&io,&fresh,&clock,&failed_address)!=HPH_OK && failed_address &&
    !m.writes && !m.queries && !m.hubs);cases++;
   if(i==1)assert(!fresh.valid);
   if(i==2)assert(fresh.valid==1 && fresh.values[HGB_CFG]==1);
  }
  for(unsigned i=1;i<=ro_owners;i++) {
   m=running;m.reads=m.owners=m.writes=m.queries=m.hubs=0;m.fail_owner=i;
   assert(hph_observe_ro(&io,&fresh,&clock,&failed_address)==HPH_OWNER &&
    !m.writes && !m.queries && !m.hubs);cases++;
  }
 }
 printf("power-only handoff: %u cases PASS; wire bytes=%u; no rollback/CM3/context/firmware/CP calls\n",cases,HPH_RECORD_BYTES);
 return 0;
}
