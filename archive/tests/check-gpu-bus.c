// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "GpuBusProbe.h"
struct mock {
  GPP_U32 regs[HGB_REGS];
  GPP_U32 smr[24],s2cr[24],banks[22];
  unsigned reads,writes,smmu_reads,fail_read,fail_write,stuck,delays;
  unsigned action,action_calls;
};
static unsigned index_of(GPP_U32 a) {
  unsigned i;for(i=0;i<HGB_REGS;i++)if(hgb_address(i)==a)return i;
  assert(0);return 0;
}
static GPP_U64 rd(void *v,GPP_U32 a,GPP_U32 *out) {
  struct mock *m=v;unsigned i;
  if(++m->reads==m->fail_read)return 1;
  if(hgb_survey_address(a)) {
    assert(m->regs[HGB_RESET]==1 && (m->regs[HGB_CFG]&0x80000003u)==1 &&
      (m->regs[HGB_MEM]&0x80000003u)==1 && (m->regs[HGB_VOTE]&0x80000001u)==1);
    if(a>=0x3dc0000)*out=m->banks[(a-0x3dc0000)/4096];
    else if(a>=0x3da0c00)*out=m->s2cr[(a-0x3da0c00)/4];
    else *out=m->smr[(a-0x3da0800)/4];
    m->smmu_reads++;return 0;
  }
  i=index_of(a);
  if(i>=HGB_ID0) {
    assert(m->regs[HGB_RESET]==1);
    assert((m->regs[HGB_CFG]&0x80000003u)==1);
    assert((m->regs[HGB_MEM]&0x80000003u)==1);
    assert((m->regs[HGB_VOTE]&0x80000001u)==1);
    m->smmu_reads++;
  }
  *out=m->regs[i];return 0;
}
static GPP_U64 wr(void *v,GPP_U32 a,GPP_U32 value) {
  struct mock *m=v;unsigned i=index_of(a);
  GPP_U32 mask=i==HGB_VOTE?1:2;
  assert(i==HGB_CFG || i==HGB_MEM || i==HGB_VOTE);
  assert(!((value^m->regs[i])&~mask));
  if(++m->writes==m->fail_write)return 1;
  m->regs[i]=value;
  // HALT is status, not writable state. HWCG clocks may halt while idle.
  if(i==HGB_VOTE) {
    if(value&1)m->regs[i]&=~0x80000000u;
    else m->regs[i]|=0x80000000u;
  } else {
    if(value&2)m->regs[i]|=0x80000000u;
    else m->regs[i]&=~0x80000000u;
  }
  if(m->stuck==i+1)m->regs[i]|=0x80000000u;
  return 0;
}
static GPP_U64 delay(void *v,unsigned us) {
  struct mock *m=v;assert(us==1);m->delays++;return 0;
}
static unsigned action(void *v,const struct hgb_result *r) {
  struct mock *m=v;assert(!r->code && r->streams_seen==24 && r->banks_seen==22);
  m->action_calls++;return m->action;
}
static struct mock initial(void) {
  struct mock m;memset(&m,0,sizeof(m));
  m.regs[HGB_CFG]=m.regs[HGB_MEM]=0x80000003u;
  m.regs[HGB_DVM]=1;m.regs[HGB_CX]=0xf822f800;
  m.regs[HGB_HW]=0x80000202;m.regs[HGB_AHB]=0;
  m.regs[HGB_RESET]=1;m.regs[HGB_VOTE]=0x80000000;
  m.regs[HGB_ID0]=0x4c017e18;m.regs[HGB_ID1]=0x40000016;
  m.regs[HGB_ID2]=0x5511;m.regs[HGB_CR0]=0x2f0406;
  for(unsigned i=0;i<24;i++)m.s2cr[i]=0x20000;
  return m;
}
static struct gpp_report report(void) {
  struct gpp_report p;gpp_report_init(&p);
  p.phase=GPP_PHASE_CLOCKS;p.code=GPP_ERR_INITIAL;p.resource=GPP_GMU_CLK;
  p.attempted=p.confirmed=0x1002;p.flags=GPP_ACD_CONSUMED;
  gpp_report_seal(&p);return p;
}
static unsigned run(struct mock *m,struct gpp_report *p,struct hgb_result *r) {
  const struct hgb_io io={m,rd,wr,delay,action};return hgb_probe(&io,p,r);
}
int main(void) {
  struct mock m=initial(),base;struct hgb_result r;
  struct gpp_report p=report(),bad;
  unsigned i,successful_reads,cases=0;
  assert(run(&m,&p,&r)==HGB_OK);cases++;
  assert(r.attempted==7 && r.restored==7 && m.writes==6 && m.smmu_reads==77);
  assert(r.streams_seen==24 && r.banks_seen==22 && !r.active_banks && !r.active_streams);
  assert(m.action_calls==1);
  base=initial();assert(!memcmp(m.regs,base.regs,sizeof(m.regs)));
  successful_reads=m.reads;
  // Every actual successful-path read may fail, including cleanup reads.
  for(i=1;i<=successful_reads;i++) {
    m=initial();m.fail_read=i;
    assert(run(&m,&p,&r)!=HGB_OK);
    assert(m.reads<1100 && m.writes<=6);cases++;
  }
  for(i=1;i<=6;i++) {
    m=initial();m.fail_write=i;assert(run(&m,&p,&r)!=HGB_OK);
    assert(m.reads<1100 && m.writes<=6);cases++;
  }
  for(i=0;i<8;i++) {
    m=initial();
    if(i==HGB_CFG || i==HGB_MEM || i==HGB_DVM)m.regs[i]&=~1u;
    else if(i==HGB_CX)m.regs[i]|=1;
    else if(i==HGB_HW)m.regs[i]&=~0x80000000u;
    else if(i==HGB_AHB)m.regs[i]|=0x80000000u;
    else if(i==HGB_RESET)m.regs[i]=0;
    else m.regs[i]|=1;
    assert(run(&m,&p,&r)==HGB_GUARD && !m.writes && !m.smmu_reads);cases++;
  }
  for(i=0;i<3;i++) {
    m=initial();m.stuck=(i==0?HGB_CFG:i==1?HGB_MEM:HGB_VOTE)+1;
    assert(run(&m,&p,&r)==HGB_TIMEOUT);
    assert(m.delays==999 && !m.smmu_reads && r.restored==r.attempted);cases++;
  }
  for(i=0;i<3;i++) {
    m=initial();m.regs[HGB_ID0+i]^=1;
    assert(run(&m,&p,&r)==HGB_GEOMETRY && !r.streams_seen && !r.banks_seen);
    assert(r.restored==7);cases++;
  }
  for(i=0;i<24;i++) {
    m=initial();m.smr[i]=0x80000005;
    assert(run(&m,&p,&r)==HGB_BUSY && r.active_streams==1 && r.restored==7);cases++;
    m=initial();m.s2cr[i]=0;
    assert(run(&m,&p,&r)==HGB_BUSY && r.nonfault_routes==1 && r.restored==7);cases++;
  }
  for(i=0;i<22;i++) {
    m=initial();m.banks[i]=1;
    assert(run(&m,&p,&r)==HGB_BUSY && r.active_banks==1 && r.restored==7);cases++;
  }
  m=initial();m.regs[HGB_FWINIT]=1;
  assert(run(&m,&p,&r)==HGB_BUSY && r.restored==7);cases++;
  m=initial();m.action=HGB_ACTION;
  assert(run(&m,&p,&r)==HGB_ACTION && r.restored==7 && m.action_calls==1);cases++;
  m=initial();m.action=HGB_RETAIN;
  assert(run(&m,&p,&r)==HGB_RETAIN && !r.restored && m.action_calls==1);cases++;
  m=initial();m.action=99;
  assert(run(&m,&p,&r)==HGB_RETAIN && !r.restored);cases++;
  // A valid CRC alone does not authorize the transaction.
  for(i=0;i<6;i++) {
    m=initial();bad=p;
    if(i==0)bad.confirmed=0;
    if(i==1)bad.attempted|=1u<<GPP_GMU_RATE;
    if(i==2)bad.phase=GPP_PHASE_DONE;
    if(i==3)bad.flags|=GPP_QMP_UNCERTAIN;
    if(i==4)bad.flags|=GPP_PROTOCOL_UNCERTAIN;
    if(i==5)bad.flags&=~GPP_ACD_CONSUMED;
    gpp_report_seal(&bad);
    assert(run(&m,&bad,&r)==HGB_OWNER && !m.reads && !m.writes);cases++;
  }
  for(i=0;i<sizeof(p);i++) {
    bad=p;((unsigned char *)&bad)[i]^=1;m=initial();
    assert(run(&m,&bad,&r)==HGB_OWNER && !m.reads && !m.writes);cases++;
  }
  printf("PASS: %u actual held-reset bus-policy cases; clock-only writes, gated SMMU reads, bounded polls, reverse restoration and failure injection\n",cases);
  return 0;
}
