// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "GpuDmaProbe.h"
#include "GpuCachePublish.h"
struct model {
  struct hgt_owned owned;void *zero;uint64_t zero_pa,image[9],fields[9],far;
  uint32_t tcm[HGA_TCM_WORDS],saved_tcm[HGA_TCM_WORDS],controls[9],saved_controls[9];
  uint32_t device_data[1024],actlr,prr_low,prr_high,smr,s2cr,sctlr,fsr,fsynr,reset;
  unsigned reads,writes,delays,publishes,checkpoints,cpu_calls;
  unsigned fail_read,fail_write,apply_failed,fail_publish,fail_checkpoint,fail_cpu;
  unsigned injected,mode,foreign,timeout_sync;
};
static unsigned ti(uint32_t a) {
  for(unsigned i=0;i<HGA_TCM_WORDS;i++)if(hga_tcm_address(i)==a)return i;
  assert(0);return 0;
}
static int rd(void *c,uint32_t a,uint64_t *v,unsigned wide) {
  struct model *m=c;if(++m->reads==m->fail_read){m->injected=1;return 1;}
  int f=hgp_field_index(a);
  if(f>=0) {assert(wide==(f==5 || f==6));*v=f==0?m->sctlr:m->fields[f];return 0;}
  if(a==HGP_CB(0x60)){assert(wide);*v=m->far;return 0;}assert(!wide);
  if(hga_tcm_address_valid(a)){*v=m->tcm[ti(a)];return 0;}
  for(unsigned i=0;i<9;i++)if(hgd_control_address(i)==a){*v=m->controls[i];return 0;}
  switch(a) {
    case 0x3da0020:*v=0x4c017e18;return 0;
    case 0x3da0024:*v=0x40000016;return 0;
    case 0x3da0028:*v=0x5511;return 0;
    case 0x3da0048:*v=0;return 0;
    case HGP_CB(0x4):*v=m->actlr;return 0;
    case 0x3da6008:*v=m->prr_low;return 0;
    case 0x3da600c:*v=m->prr_high;return 0;
    case HGP_CB(0x58):*v=m->fsr;return 0;
    case HGP_CB(0x68):*v=m->fsynr;return 0;
    case HGP_CB(0x7f4):*v=m->timeout_sync;return 0;
    case 0x3d7e000:*v=m->reset;return 0;
    default:break;
  }
  if(a>=0x3da0800 && a<0x3da0860 && !(a&3)) {
    *v=a==0x3da0800?m->smr:((m->foreign && a==0x3da0804)?0x80000006:0);return 0;
  }
  if(a>=0x3da0c00 && a<0x3da0c60 && !(a&3)){*v=a==0x3da0c00?m->s2cr:0x20000;return 0;}
  if(a>=0x3dc0000 && a<=0x3dd5000 && !(a&4095)){*v=0x3fdde71e;return 0;}
  assert(0);return 1;
}
static int read32(void *c,uint32_t a,uint32_t *v) {uint64_t t=0;int s=rd(c,a,&t,0);*v=(uint32_t)t;return s;}
static int read64(void *c,uint32_t a,uint64_t *v) {return rd(c,a,v,1);}
static void execute(struct model *m) {
  assert(m->sctlr==0x27 && m->smr==0x80000005u && m->s2cr==HGP_CONTEXT_BANK && m->actlr==0x32b);
  assert(m->prr_low==(uint32_t)m->zero_pa && m->prr_high==(m->zero_pa>>32) && m->publishes==2);
  for(unsigned i=0;i<HGA_CODE_WORDS;i++)assert(m->tcm[i]==hga_code[i]);
  uint32_t *mail=&m->tcm[HGA_CODE_WORDS];mail[0]=0xa7500001;
  if(m->mode==7)return;
  mail[1]=m->device_data[0];mail[2]=m->device_data[1];mail[4]=m->device_data[2];
  m->device_data[2]=0xa750cafe;mail[3]=m->device_data[2];mail[5]=0;
  m->fsr=0x402;m->far=0x60002000;m->fsynr=0;
  if(m->mode==1)m->fsr=0x400;
  if(m->mode==2)m->far=0x60003000;
  if(m->mode==3)m->fsynr=16;
  if(m->mode==4)m->fsr=0x408;
  if(m->mode==5)mail[1]^=1;
  mail[0]=m->mode==8?0xa750dead:0xa7500003;
  if(m->mode==8){mail[6]=0x8200;mail[7]=0x60002000;}
}
static int write32(void *c,uint32_t a,uint32_t value) {
  struct model *m=c;unsigned failed=++m->writes==m->fail_write;
  if(m->injected)assert(a==0x3d7e000 && value==1);
  if(failed && !m->apply_failed){m->injected=1;return 1;}
  if(a==0x3d7e000) {
    assert(value<=1);
    if(value==0){assert(m->reset==1);m->reset=0;execute(m);}
    else if(m->mode!=9 || m->reset!=0)m->reset=1;
    if(failed)m->injected=1;return failed;
  }
  assert(m->reset==1);
  if(hga_tcm_address_valid(a)){m->tcm[ti(a)]=value;goto done;}
  for(unsigned i=0;i<9;i++)if(hgd_control_address(i)==a){m->controls[i]=i==8?value&0x7f:value;goto done;}
  switch(a) {
    case 0x3da6008:assert(!m->sctlr && !m->smr && (value==0 || value==(uint32_t)m->zero_pa));m->prr_low=value;break;
    case 0x3da600c:assert(!m->sctlr && !m->smr && (value==0 || value==(m->zero_pa>>32)));m->prr_high=value;break;
    case HGP_CB(0x4):assert(!m->sctlr && !m->smr && (value==3 || value==0x32b));m->actlr=value;break;
    case HGP_CB(0):
      assert(value==0 || value==0x1027);
      if(value){assert(m->actlr==0x32b && m->publishes==2 && !m->smr);m->sctlr=value&~0x1000u;}
      else {assert(!m->smr && m->s2cr==0x20000);m->sctlr=0;}break;
    case 0x3da0c00:assert(!m->smr && (value==HGP_CONTEXT_BANK || value==0x20000));m->s2cr=value;break;
    case 0x3da0800:
      assert(value==0 || (value==0x80000005u && m->sctlr==0x27 && m->s2cr==HGP_CONTEXT_BANK));m->smr=value;break;
    case HGP_CB(0x618):assert(!value && !m->sctlr && !m->smr);break;
    case HGP_CB(0x7f0):assert(value==0xffffffffu && !m->sctlr && !m->smr);break;
    case HGP_CB(0x58):
      assert(value==2 && m->fsr==0x402 && m->far==0x60002000 && !m->sctlr && !m->smr && m->s2cr==0x20000);
      m->fsr&=~value;break;
    default:assert(0);
  }
done:if(failed)m->injected=1;return failed;
}
static int write64(void *c,uint32_t a,uint64_t v) {(void)c;(void)a;(void)v;assert(0);return 1;}
static GPP_U64 gmu_read(void *c,GPP_U32 a,GPP_U32 *v){return read32(c,a,v);}
static GPP_U64 gmu_write(void *c,GPP_U32 a,GPP_U32 v){return write32(c,a,v);}
static int power_guard(void *c){struct model *m=c;return m->reset!=1;}
static int delay(void *c,unsigned us){struct model *m=c;assert(us==10);m->delays++;return 0;}
static GPP_U64 gmu_delay(void*c,unsigned us){return delay(c,us);}
static int publish(void *c,const struct hgt_owned *o,uint64_t pa,void *cpu) {
  struct model *m=c;assert(o==&m->owned && pa==m->zero_pa && cpu==m->zero);
  assert(!m->sctlr && !m->smr && m->reset==1);
  if(++m->publishes==m->fail_publish)return 1;
  memcpy(m->device_data,o->data,4096);return 0;
}
static int invalidate(void *c,uintptr_t at) {
  struct model *m=c;assert(!m->sctlr && !m->smr && m->reset==1 && !m->prr_low && !m->prr_high);
  uintptr_t start=(uintptr_t)m->owned.data;assert(at>=start && at-start<4096 && !(at&63));
  if(m->mode!=6)memcpy((void *)at,(char *)m->device_data+(at-start),64);return 0;
}
static int clean(void*c,uintptr_t at){struct model*m=c;uintptr_t start=(uintptr_t)m->owned.data;assert(at>=start&&at-start<4096&&!(at&63));memcpy((char*)m->device_data+(at-start),(void*)at,64);return 0;}
static int barrier(void*c){(void)c;return 0;}
static int cpu_finish(void*c,const struct hgt_owned*o,struct hga_cpu_result*r) {
  struct model*m=c;m->cpu_calls++;if(m->fail_cpu)return 1;
  struct hga_cpu_io io={c,64,invalidate,clean,barrier};return hga_cpu_finish(&io,o,r);
}
static int checkpoint(void*c,unsigned stage) {
  struct model*m=c;assert(stage==++m->checkpoints && stage<=2 && !m->sctlr && !m->smr && m->reset==1);
  if(m->mode==10 && stage==1)m->foreign=1;
  if(m->mode==11 && stage==2)m->foreign=1;
  if(m->fail_checkpoint==stage){m->injected=1;return 1;}return 0;
}
static void init(struct model *m) {
  memset(m,0,sizeof(*m));assert(!posix_memalign(&m->owned.tables,4096,12288));
  assert(!posix_memalign(&m->owned.data,4096,4096));assert(!posix_memalign(&m->zero,4096,4096));
  memset(m->zero,0,4096);memset(m->owned.data,0,4096);
  ((uint32_t *)m->owned.data)[0]=0x7504cafe;((uint32_t *)m->owned.data)[1]=0x86500071;
  m->owned.table_physical=0x89999000;m->owned.data_physical=0x88888000;m->zero_pa=UINT64_C(0x812340000);
  m->owned.config=(ArmSmmu4KConfig){32,36,m->owned.table_physical,1};
  m->owned.range=(ArmSmmu4KRange){0x60000000,m->owned.data_physical,4096,3,1,3};
  assert(!ArmSmmu4KBuild(&m->owned.config,&m->owned.range,1,m->owned.tables,3,&m->owned.built));
  const uint64_t image[]={0,1,0x1f300,0x38071,0x80802020,(UINT64_C(0x750)<<48)|m->owned.table_physical,UINT64_C(0x750)<<48,0xff44,0};
  memcpy(m->image,image,sizeof(image));memcpy(m->fields,image,sizeof(image));m->reset=1;m->actlr=3;m->s2cr=0x20000;m->fsr=0x400;
  for(unsigned i=0;i<HGA_TCM_WORDS;i++)m->saved_tcm[i]=m->tcm[i]=hga_tcm_address(i)^0x87654321;
  for(unsigned i=0;i<9;i++)m->saved_controls[i]=m->controls[i]=0x12340000+i;
  m->controls[7]=m->saved_controls[7]=0xffffffffu;m->controls[8]=m->saved_controls[8]=0x7f;
}
static void destroy(struct model*m){free(m->owned.tables);free(m->owned.data);free(m->zero);}
static unsigned run(struct model*m,struct hga_result*r) {
  const struct hga_io io={{m,read32,read64,write32,write64,delay,power_guard,0},
    {m,gmu_read,gmu_write,gmu_delay,0},m,publish,cpu_finish,checkpoint};
  return hga_probe(&io,&m->owned,m->image,m->zero_pa,m->zero,r);
}
int main(void) {
  struct model m;struct hga_result r;unsigned cases=0;init(&m);
  assert(!run(&m,&r) && r.complete && !r.must_retain && r.positive && r.negative &&
    r.cpu.verified && r.cpu.restored && r.cpu.observed==0xa750cafe);
  assert(r.detached && r.platform_retired && r.restored==HGA_TCM_WORDS && r.control_restored==0x7f);
  assert(!m.sctlr && !m.smr && m.s2cr==0x20000 && m.actlr==3 && !m.prr_low && !m.prr_high && m.fsr==0x400);
  assert(!memcmp(m.tcm,m.saved_tcm,sizeof(m.tcm)) && !memcmp(m.controls,m.saved_controls,sizeof(m.controls)));
  assert(!m.device_data[2] && !((uint32_t*)m.owned.data)[2]);
  unsigned reads=m.reads,writes=m.writes;destroy(&m);cases++;
  for(unsigned i=1;i<=reads;i++) {
    init(&m);m.fail_read=i;assert(run(&m,&r) && r.must_retain && !r.complete);
    assert(m.reads<5000 && m.delays<3000);destroy(&m);cases++;
  }
  for(unsigned i=1;i<=writes;i++)for(unsigned applied=0;applied<=1;applied++) {
    init(&m);m.fail_write=i;m.apply_failed=applied;
    assert(run(&m,&r) && r.must_retain && !r.complete);destroy(&m);cases++;
  }
  for(unsigned mode=1;mode<=11;mode++) {
    init(&m);m.mode=mode;unsigned code=run(&m,&r);
    if(mode==8)assert(!code && r.complete && r.negative && r.mailbox[0]==0xa750dead);
    else assert(code && r.must_retain && !r.complete);
    if(mode==10 || mode==11)assert(m.foreign);
    assert(m.delays<3000);destroy(&m);cases++;
  }
  for(unsigned i=1;i<=2;i++) {
    init(&m);m.fail_publish=i;assert(run(&m,&r) && r.must_retain);destroy(&m);cases++;
    init(&m);m.fail_checkpoint=i;assert(run(&m,&r) && r.must_retain);destroy(&m);cases++;
  }
  init(&m);m.fail_cpu=1;assert(run(&m,&r) && r.must_retain);destroy(&m);cases++;
  init(&m);m.timeout_sync=1;assert(run(&m,&r) && r.must_retain && m.delays<3000);destroy(&m);cases++;
  printf("PASS: %u cases; real DMA policy, every read/write failure before/after side effect, bounded polling, exact SID5 lease, negative fault ownership, stale CPU cache refusal and full successful retirement\n",cases);
}
