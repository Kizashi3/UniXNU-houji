// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "GpuSmmuContext.h"
struct model {
  uint64_t fields[9];unsigned reads,writes,fail_read,fail_write,apply_failed;
  unsigned checkpoints,last_stage,foreign,change_stage,timeout,delays,bad_read,change_fields;
};
static int field(uint32_t a) {for(unsigned i=0;i<9;i++)if(hgp_field_address(i)==a)return (int)i;return -1;}
static int read_value(struct model *m,uint32_t a,uint64_t *v,int wide) {
  if(++m->reads==m->fail_read)return 1;
  int n=field(a);if(n>=0) {
    assert(wide==(n==5 || n==6));*v=m->fields[n];
    if(m->bad_read && m->checkpoints==1 && m->writes==11 && n==4){*v^=1;m->bad_read=0;}
    return 0;
  }
  assert(!wide);
  switch(a) {
    case 0x3da0020:*v=0x4c017e18;return 0;
    case 0x3da0024:*v=0x40000016;return 0;
    case 0x3da0028:*v=0x5511;return 0;
    case 0x3da0048:case HGP_CB(0x58):*v=0;return 0;
    case HGP_CB(0x7f4):*v=m->timeout;return 0;
    default:break;
  }
  if(a>=0x3da0800 && a<0x3da0860 && !(a&3)){*v=m->foreign?0x80000005:0;return 0;}
  if(a>=0x3da0c00 && a<0x3da0c60 && !(a&3)){*v=0x20000;return 0;}
  if(a>=0x3dc0000 && a<=0x3dd5000 && !(a&4095)){*v=0x1e;return 0;}
  assert(0);return 1;
}
static int rd32(void *cookie,uint32_t a,uint32_t *v) {uint64_t t=0;int r=read_value(cookie,a,&t,0);*v=(uint32_t)t;return r;}
static int rd64(void *cookie,uint32_t a,uint64_t *v) {return read_value(cookie,a,v,1);}
static int write_value(struct model *m,uint32_t a,uint64_t v,int wide) {
  unsigned failed=++m->writes==m->fail_write;if(failed && !m->apply_failed)return 1;
  int n=field(a);
  if(n>=0) {
    assert(wide==(n==5 || n==6));if(!n)assert(!(v&1));
    // Regression from r73: saved power-on CBAR values are not writeable
    // configurations. The native device raised an external abort here.
    if(n==2)assert(v==0x1f300);
    m->fields[n]=n==3?v|0x60:v;return failed;
  }
  assert(!wide && ((a==HGP_CB(0x618) && v==0) || (a==HGP_CB(0x7f0) && v==0xffffffffu)));return failed;
}
static int wr32(void *c,uint32_t a,uint32_t v) {return write_value(c,a,v,0);}
static int wr64(void *c,uint32_t a,uint64_t v) {return write_value(c,a,v,1);}
static int delay(void *c,unsigned us) {struct model *m=c;assert(us==10);m->delays++;return 0;}
static int guard(void *c) {(void)c;return 0;}
static int checkpoint(void *c,unsigned stage) {struct model *m=c;assert(stage>m->last_stage && stage<=3);assert(stage==3 || stage==m->last_stage+1);m->last_stage=stage;m->checkpoints++;if(stage==m->change_stage)m->foreign=1;if(stage==m->change_fields)m->fields[4]^=2;return 0;}
static struct model initial(void) {struct model m={0};for(unsigned i=0;i<9;i++)m.fields[i]=0x10000+i*0x1000;m.fields[0]=0x3fdde71e;m.fields[3]|=0x60;return m;}
static unsigned run(struct model *m,const struct hgt_owned *o,struct hgp_result *r) {
  const struct hgp_io io={m,rd32,rd64,wr32,wr64,delay,guard,checkpoint};return hgp_disabled_context(&io,o,r);
}
static void retired(const struct model *m) {
  assert(m->fields[0]==0 && m->fields[1]==1 && m->fields[2]==0x1f300);
  assert(m->fields[3]==0x38071 && m->fields[4]==0x80802020);
  assert(!m->fields[5] && !m->fields[6] && m->fields[7]==0xff44 && !m->fields[8]);
}
static unsigned visitor(void *cookie,const struct hgp_io *io,const struct hgt_owned *o,const uint64_t *image) {
  unsigned mode=*(unsigned *)cookie;struct model *m=io->cookie;
  assert(m->checkpoints==2 && !image[0] && image[5]==m->fields[5] && o->tables);
  if(mode==1)return HGP_IO;
  if(mode==2)m->foreign=1;
  if(mode==3)m->fields[4]^=2;
  return 0;
}
int main(void) {
  uint64_t *tables=calloc(3,4096);uint32_t *data=calloc(1,4096);assert(tables && data);
  struct hgt_owned owned={0};owned.tables=tables;owned.data=data;owned.table_physical=0x89999000;owned.data_physical=0x88888000;
  owned.config=(ArmSmmu4KConfig){32,36,owned.table_physical,1};
  owned.range=(ArmSmmu4KRange){0x60000000,owned.data_physical,4096,3,1,3};
  assert(!ArmSmmu4KBuild(&owned.config,&owned.range,1,tables,3,&owned.built));
  struct model m=initial();struct hgp_result r;unsigned cases=0;
  assert(run(&m,&owned,&r)==HGP_OK && r.safe_to_release && r.attempted==0x1ff && r.retired==0x1ff);
  retired(&m);assert(m.checkpoints==3);cases++;
  assert(r.configured[0]==0 && r.configured[3]==0x38071 && r.configured[4]==0x80802020);
  unsigned reads=m.reads,writes=m.writes;
  for(unsigned i=1;i<=reads;i++) {
    m=initial();m.fail_read=i;assert(run(&m,&owned,&r)!=HGP_OK);assert(m.reads<1500);cases++;
  }
  for(unsigned i=1;i<=writes;i++)for(unsigned applied=0;applied<2;applied++) {
    m=initial();m.fail_write=i;m.apply_failed=applied;assert(run(&m,&owned,&r)!=HGP_OK);
    if(r.safe_to_release)retired(&m);cases++;
  }
  m=initial();m.change_stage=1;assert(run(&m,&owned,&r)==HGP_GUARD && !m.writes && r.safe_to_release);cases++;
  m=initial();m.change_stage=2;assert(run(&m,&owned,&r)==HGP_GUARD && !r.safe_to_release);cases++;
  m=initial();m.change_fields=2;assert(run(&m,&owned,&r)==HGP_GUARD && !r.safe_to_release);cases++;
  m=initial();m.change_stage=3;assert(run(&m,&owned,&r)==HGP_GUARD && !r.safe_to_release);cases++;
  m=initial();m.change_fields=3;assert(run(&m,&owned,&r)==HGP_GUARD && !r.safe_to_release);cases++;
  m=initial();m.timeout=1;assert(run(&m,&owned,&r)==HGP_TIMEOUT && !r.safe_to_release && r.polls==200 && m.delays==198);cases++;
  m=initial();m.bad_read=1;assert(run(&m,&owned,&r)==HGP_VERIFY && r.safe_to_release);cases++;
  retired(&m);
  for(unsigned mode=0;mode<=3;mode++) {
    m=initial();const struct hgp_io io={&m,rd32,rd64,wr32,wr64,delay,guard,checkpoint};
    unsigned code=hgp_disabled_context_visit(&io,&owned,&r,visitor,&mode);
    if(!mode){assert(!code && r.safe_to_release);retired(&m);}
    else assert(code && !r.safe_to_release && !r.retired && m.checkpoints==2);
    cases++;
  }
  free(tables);free(data);
  printf("PASS: %u actual disabled selected-bank native4K context cases; known disabled retirement with zero TTBRs, no replay of uninitialized CBAR, 64-bit I/O, every failure, no M=1/stream/global/fault-clear writes\n",cases);
}
