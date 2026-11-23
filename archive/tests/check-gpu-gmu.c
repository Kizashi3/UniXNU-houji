// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "GpuGmuProbe.h"
struct model {
  GPP_U32 tcm[HGD_TOTAL_WORDS],controls[HGD_CONTROL_WORDS],reset;
  unsigned reads,writes,fail_read,fail_write,timeout,fault,stuck_reset,delays;
  unsigned apply_failed_write;
  unsigned checkpoints,fail_checkpoint,change_reset_stage;
  unsigned cxo_off,hub_off;
  unsigned bad_ao_mask;
};
static unsigned tcm_index(GPP_U32 a) {
  for(unsigned i=0;i<HGD_TOTAL_WORDS;i++)if(hgd_tcm_address(i)==a)return i;
  assert(0);return 0;
}
static GPP_U64 rd(void *v,GPP_U32 a,GPP_U32 *out) {
  struct model *m=v;if(++m->reads==m->fail_read)return 1;
  if(hgd_tcm_address_valid(a)) {*out=m->tcm[tcm_index(a)];return 0;}
  for(unsigned i=0;i<HGD_CONTROL_WORDS;i++)if(hgd_control_address(i)==a) {
    *out=m->controls[i];return 0;
  }
  switch(a) {
    case 0x171004:case 0x171010:case 0x171018:case 0x3d97000:*out=1;break;
    case 0x3d99108:*out=0xf822f800;break;
    case 0x3d99168:*out=0x80000202;break;
    case 0x3d9911c:*out=0;break;
    case 0x3d9913c:*out=0x2001;break;
    case 0x3d99144:*out=m->cxo_off?0x80000000u:1;break;
    case 0x3d993e8:*out=m->hub_off?0x80000000u:1;break;
    case 0x3d993ec:*out=0;break;
    case 0x3d993f0:*out=0x505;break;
    case 0x3d7e000:*out=m->reset;break;
    case 0x3d7e070:case 0x3da0048:*out=0;break;
    case 0x3d7e340:*out=3;break;
    default:assert(0);
  }
  return 0;
}
static GPP_U64 wr(void *v,GPP_U32 a,GPP_U32 value) {
  struct model *m=v;unsigned failed=++m->writes==m->fail_write;
  if(failed && !m->apply_failed_write)return 1;
  for(unsigned i=0;i<HGD_CONTROL_WORDS;i++)if(hgd_control_address(i)==a) {
    assert(m->reset==1);m->controls[i]=i==8?value&(m->bad_ao_mask?0x7eu:0x7fu):value;return failed;
  }
  if(a==0x3d7e000) {
    assert(value<=1);
    if(value==1 && m->stuck_reset && m->reset==0)return 0;
    m->reset=value;
    if(!value && !m->timeout) {
      // Execution itself is separately tested against actual CM3 instructions.
      m->tcm[HGD_CODE_WORDS]=m->fault?0xa750dead:0xa7500002;
      m->tcm[HGD_CODE_WORDS+1]=0x750c0de0;m->tcm[HGD_CODE_WORDS+2]=128;
    }
    return failed;
  }
  assert(hgd_tcm_address_valid(a) && m->reset==1);
  m->tcm[tcm_index(a)]=value;return failed;
}
static GPP_U64 delay(void *v,unsigned us) {
  struct model *m=v;assert(us==10);m->delays++;return 0;
}
static GPP_U64 checkpoint(void *v,unsigned stage) {
  static const unsigned order[]={1,2,6,3,7,8};
  struct model *m=v;assert(m->checkpoints<sizeof(order)/sizeof(order[0]));
  assert(stage==order[m->checkpoints++]);
  assert(m->reset==(stage==7 || stage==8 ? 0u : 1u));
  if(stage==m->fail_checkpoint)return 1;
  if(stage==m->change_reset_stage)m->reset=0;
  return 0;
}
static struct model initial(void) {
  struct model m;memset(&m,0,sizeof(m));m.reset=1;
  for(unsigned i=0;i<HGD_TOTAL_WORDS;i++)m.tcm[i]=0x87543210^hgd_tcm_address(i);
  for(unsigned i=0;i<HGD_CONTROL_WORDS;i++)m.controls[i]=0x12340000+i;
  m.tcm[0]=0xffffffff;return m;
}
static struct hgb_result bus(void) {
  struct hgb_result b;memset(&b,0,sizeof(b));
  b.valid=0x7fff;b.attempted=7;b.streams_seen=24;b.banks_seen=22;
  b.values[HGB_ID0]=0x4c017e18;b.values[HGB_ID1]=0x40000016;
  b.values[HGB_ID2]=0x5511;b.values[HGB_RESET]=1;b.values[HGB_GXPOWER]=3;
  for(unsigned i=0;i<24;i++)b.s2cr[i]=0x20000;
  return b;
}
static struct gpp_report power(void) {
  struct gpp_report p;gpp_report_init(&p);p.phase=GPP_PHASE_CLOCKS;
  p.code=GPP_ERR_INITIAL;p.resource=GPP_GMU_CLK;p.attempted=p.confirmed=0x1002;
  p.flags=GPP_ACD_CONSUMED;gpp_report_seal(&p);return p;
}
static unsigned run(struct model *m,const struct gpp_report *p,const struct hgb_result *b,struct hgd_result *r) {
  const struct hgd_io io={m,rd,wr,delay,checkpoint};return hgd_probe(&io,p,b,r);
}
int main(void) {
  struct model m=initial(),base=initial();struct gpp_report p=power();
  struct hgb_result b=bus(),bad;struct hgd_result r;
  unsigned i,read_count,write_count,cases=0;
  assert(run(&m,&p,&b,&r)==HGD_OK);cases++;
  assert(r.backup_words==HGD_TOTAL_WORDS && r.restored_words==HGD_TOTAL_WORDS &&
    r.reset_held && r.release_attempted && !r.retained && m.reset==1);
  assert(!memcmp(m.tcm,base.tcm,sizeof(m.tcm)));
  assert(!memcmp(m.controls,base.controls,7*sizeof(GPP_U32)));
  assert(m.controls[7]==0xffffffffu && m.controls[8]==0x7fu);
  assert(r.control_backup==9 && r.control_attempted==0x1ff && r.control_restored==0x7f);
  assert(m.checkpoints==6);
  read_count=m.reads;write_count=m.writes;
  for(i=1;i<=read_count;i++) {
    m=initial();m.fail_read=i;assert(run(&m,&p,&b,&r)!=HGD_OK);
    assert(m.reads<1500 && m.writes<=write_count);cases++;
  }
  for(i=1;i<=write_count;i++) {
    m=initial();m.fail_write=i;assert(run(&m,&p,&b,&r)!=HGD_OK);
    assert(m.reads<1500 && m.writes<=write_count);cases++;
    m=initial();m.fail_write=i;m.apply_failed_write=1;
    assert(run(&m,&p,&b,&r)!=HGD_OK && r.reset_held && m.reset==1);
    // Cleanup write failures must still remain failures, even when hardware
    // took the value. Earlier uncertain writes must be fully restored.
    if(i<=HGD_CODE_WORDS+HGD_MAIL_WORDS+HGD_CONTROL_WORDS+1) {
      assert(!memcmp(m.tcm,base.tcm,sizeof(m.tcm)));
      assert(!memcmp(m.controls,base.controls,7*sizeof(GPP_U32)));
    }
    cases++;
  }
  m=initial();m.timeout=1;assert(run(&m,&p,&b,&r)==HGD_TIMEOUT && m.reset==1 && r.reset_held);
  assert(!memcmp(m.tcm,base.tcm,sizeof(m.tcm)) && m.delays==999);cases++;
  m=initial();m.fault=1;assert(run(&m,&p,&b,&r)==HGD_FAULT && r.reset_held);
  assert(!memcmp(m.tcm,base.tcm,sizeof(m.tcm)));cases++;
  m=initial();m.stuck_reset=1;assert(run(&m,&p,&b,&r)==HGD_RESET);
  assert(r.retained && !r.reset_held && !r.restored_words && m.delays==999);cases++;
  const unsigned stages[]={1,2,6,3,7,8};
  for(i=0;i<sizeof(stages)/sizeof(stages[0]);i++) {
    unsigned stage=stages[i];m=initial();m.fail_checkpoint=stage;
    assert(run(&m,&p,&b,&r)==HGD_IO && r.reset_held);
    assert(r.release_attempted==(stage==7 || stage==8));
    assert(!memcmp(m.tcm,base.tcm,sizeof(m.tcm)));cases++;
    assert(!memcmp(m.controls,base.controls,7*sizeof(GPP_U32)));
    if(stage!=7 && stage!=8) {
      m=initial();m.change_reset_stage=stage;
      assert(run(&m,&p,&b,&r)==HGD_GUARD && r.retained && !r.reset_held && !r.release_attempted);cases++;
    }
  }
  m=initial();m.cxo_off=1;
  assert(run(&m,&p,&b,&r)==HGD_GUARD && !m.writes && !r.backup_words);cases++;
  m=initial();m.hub_off=1;
  assert(run(&m,&p,&b,&r)==HGD_GUARD && !m.writes && !r.backup_words);cases++;
  m=initial();m.bad_ao_mask=1;
  assert(run(&m,&p,&b,&r)==HGD_VERIFY && !r.release_attempted && r.reset_held);
  assert(r.verify_address==0x3d8ec18 && r.verify_mask==0x7f && r.verify_value==0x7e);
  assert(!memcmp(m.tcm,base.tcm,sizeof(m.tcm)) && r.control_restored==0x7f);cases++;
  for(i=0;i<9;i++) {
    m=initial();bad=b;
    if(i==0)bad.streams_seen--;
    if(i==1)bad.banks_seen--;
    if(i==2)bad.restored=7;
    if(i==3)bad.values[HGB_GXPOWER]=0;
    if(i==4)bad.values[HGB_FWINIT]=1;
    if(i==5)bad.smr[23]=0x80000005;
    if(i==6)bad.s2cr[0]=0;
    if(i==7)bad.sctlr[21]=1;
    if(i==8)bad.values[HGB_ID0]^=1;
    assert(run(&m,&p,&bad,&r)==HGD_ARGUMENT && !m.reads && !m.writes);cases++;
  }
  printf("PASS: %u actual CM3 policy cases; internal TCM, vendor controls restored, IRQs retained masked, six checkpoints, every read/write fault, retained resources on reset failure\n",cases);
}
