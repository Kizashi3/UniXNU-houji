// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include "GpuStockGmu.h"
struct model {
 struct hfm_result mem;void *allocs[HFM_MAX+1];unsigned nalloc;
 uint32_t *regs,pdc[2];unsigned reads,writes,barriers,fail_read,fail_write,apply_failed,mode,publishes,checkpoints,delays,lost,bootstraps,stops;struct hgf_result *result;
};
static int alloc(void*c,unsigned n,uint64_t*pa,void**cpu){struct model*m=c;assert(m->nalloc<HFM_MAX+1);assert(!posix_memalign(cpu,4096,n*4096));*pa=0x80000000+0x800000*m->nalloc;m->allocs[m->nalloc++]=*cpu;return 0;}
static int validate(void*c,uint64_t pa,void*cpu,unsigned n,unsigned nc){(void)c;assert(pa && cpu && n && nc<=1);return 0;}
static int publish(void*c,const struct hfm_allocation*a){(void)c;assert(a->cpu && a->physical);return 0;}
static int release(void*c,uint64_t pa,void*cpu,unsigned n){(void)c;(void)pa;(void)cpu;(void)n;assert(0);return 1;}
static uint32_t*reg(struct model*m,uint32_t a){assert(a>=0x3d00000 && a<0x3e00000 && !(a&3));return m->regs+(a-0x3d00000)/4;}
static int rd(void*c,uint32_t a,uint32_t*v){
 struct model*m=c;if(++m->reads==m->fail_read)return 1;
 if(a==0x171004 || a==0x171010 || a==0x171018){if(m->mode==12 && !*reg(m,0x3d7e000) && a==0x171004){m->lost=1;*v=0;}else *v=1;return 0;}
 assert(!m->lost);
 if(a==0xb284520 || a==0xb284500){*v=m->pdc[a==0xb284500];return 0;}
 *v=*reg(m,a);if(a==0x3d7e200 && m->mode!=8)(*reg(m,a))++;return 0;
}
static int rd64(void*c,uint32_t a,uint64_t*v){uint32_t lo,hi;if(rd(c,a,&lo) || rd(c,a+4,&hi))return 1;*v=lo|((uint64_t)hi<<32);return 0;}
static void reply(struct model*m){
 volatile uint32_t*p=m->mem.memory[5].cpu,*cmd=p+6,*ring=p+GGH_RING_OFFSET/4;
 uint32_t head=ring[0];assert(cmd[11]==4 && head==((1u<<20)|(3u<<8)|12) && ring[1]==125 && !ring[2]);cmd[10]=4;
 if(m->mode==3)return;
 volatile uint32_t*h=p+6+12,*to=ring+1024;to[0]=(1u<<20)|(1u<<16)|(4u<<8)|12;to[1]=head;to[2]=1;to[3]=0;
 if(m->mode==4)to[1]^=1;if(m->mode==5)to[2]=0;if(m->mode==6)to[3]=1;if(m->mode==7)to[0]&=~(1u<<16);
 h[11]=4;
}
static int wr(void*c,uint32_t a,uint32_t v){
 struct model*m=c;unsigned failed=++m->writes==m->fail_write;
 if(failed && !m->apply_failed)return 1;
 if(a==0xb284520 || a==0xb284500)m->pdc[a==0xb284500]=v;
 else {
  *reg(m,a)=v;
  if(a==HGP_CB(0x10))*reg(m,a)|=0x60;
  if(a==HGP_CB(0))*reg(m,a)&=~0x1000u;
  if(a==0x3d8ec18)*reg(m,a)&=0x7f;
  if(a==0x3d7e000 && !v){assert(m->checkpoints==2 && m->publishes==2);if(m->mode!=1)*reg(m,0x3d7e070)=0x100;}
  if(a==0x3d7e618 && v && m->mode!=2)*reg(m,0x3d7e600)=1;
  if(a==0x3d7e650)reply(m);
 }
 return failed;
}
static int wr64(void*c,uint32_t a,uint64_t v){if(wr(c,a,(uint32_t)v) || wr(c,a+4,(uint32_t)(v>>32)))return 1;return 0;}
static int barrier(void*c){struct model*m=c;m->barriers++;return 0;}
static int delay(void*c,unsigned us){struct model*m=c;assert(us==10);m->delays++;return 0;}
static int pre(void*c){struct model*m=c;return *reg(m,0x3d7e000)==1 && !(m->mode==9 && m->checkpoints==1);}
static int pub(void*c){struct model*m=c;m->publishes++;return m->mode==10;}
static int cp(void*c,unsigned stage){struct model*m=c;assert(stage==++m->checkpoints && stage<=2 && *reg(m,0x3d7e000)==1);return m->mode==11;}
static void init(struct model*m,const uint8_t*fw){
 memset(m,0,sizeof(*m));m->regs=calloc(0x100000/4,4);assert(m->regs);
 const struct hfm_io io={m,alloc,validate,publish,release};assert(!hfm_prepare(&io,fw,HFM_FW_BYTES,&m->mem));
 *reg(m,0x3d7e000)=1;*reg(m,HGP_CB(4))=3;*reg(m,0x3d97000)=1;*reg(m,0x3d99168)=0x80000000;
 for(unsigned i=0;i<24;i++)*reg(m,0x3da0c00+4*i)=0x20000;
}
static void destroy(struct model*m){for(unsigned i=0;i<m->nalloc;i++)free(m->allocs[i]);free(m->regs);}
static unsigned bootstrap(void*c,struct hhb_result*r){struct model*m=c;m->bootstraps++;assert(*reg(m,0x3d7e000)==0 && *reg(m,0x3d7e600)==1 && m->mem.retained==HFM_ALL);r->stage=9;return r->code=m->mode==13?HHB_RESOURCE:HHB_OK;}
static int stopped(void*c){struct model*m=c;m->stops++;assert(m->result->release_attempted && m->result->reset_held && *reg(m,0x3d7e000)==1 && m->mem.retained==HFM_ALL);return m->mode==15;}
static unsigned run(struct model*m,const uint8_t*fw,struct hgf_result*r){
 m->result=r;
 const struct hgf_io io={{m,rd,rd64,wr,wr64,delay,0,0},m,rd,wr,barrier,delay,pre,pub,cp,m->mode>=13?bootstrap:0,stopped};
 return hgf_run(&io,&m->mem,fw,HFM_FW_BYTES,0x8ffff000,r);
}
int main(int argc,char**argv){
 assert(argc==2);FILE*f=fopen(argv[1],"rb");assert(f);uint8_t*fw=malloc(HFM_FW_BYTES);assert(fread(fw,1,HFM_FW_BYTES,f)==HFM_FW_BYTES);fclose(f);
 struct hgf_result*r=malloc(sizeof(*r));struct model m;unsigned cases=0;
 init(&m,fw);assert(!run(&m,fw,r));assert(r->phase==10 && r->fw_ready && r->hfi_ready && r->query_ack && r->query_value==1 && !r->query_status && r->reset_held && r->retained);
 assert(r->tcm_loaded_words==135 && r->tcm_backup_words==8192 && m.mem.retained==HFM_ALL && !m.mem.released);
 assert(m.stops==1);unsigned writes=m.writes,reads=m.reads;destroy(&m);cases++;
 for(unsigned mode=1;mode<=12;mode++){
  init(&m,fw);m.mode=mode;assert(run(&m,fw,r) && r->retained && !m.mem.released);if(r->release_attempted){assert(r->reset_held==(mode!=12));assert(m.stops==(mode!=12));}else assert(!m.stops);destroy(&m);cases++;
 }
 for(unsigned mode=13;mode<=14;mode++){
  init(&m,fw);m.mode=mode;assert((run(&m,fw,r)!=0)==(mode==13));
  assert(m.bootstraps==1 && r->reset_held && r->retained && !m.mem.released && r->bootstrap.stage==9);
  if(mode==13)assert(r->failed_phase==10 && r->bootstrap.code==HHB_RESOURCE);
  destroy(&m);cases++;
 }
 init(&m,fw);m.mode=15;assert(run(&m,fw,r)==HGF_IO && r->reset_held && m.stops==1);destroy(&m);cases++;
 for(unsigned n=1;n<=writes;n++)for(unsigned applied=0;applied<2;applied++){
  init(&m,fw);m.fail_write=n;m.apply_failed=applied;assert(run(&m,fw,r) && r->retained && !m.mem.released);destroy(&m);cases++;
 }
 for(unsigned n=1;n<=reads;n++){
  // Every critical control/context/HFI read plus both ends of TCM backup.
  if(n>20 && n<8180)continue;
  init(&m,fw);m.fail_read=n;assert(run(&m,fw,r) && r->retained && !m.mem.released);destroy(&m);cases++;
 }
 free(r);free(fw);printf("PASS: %u stock GMU cases; actual pinned firmware planner/layout and HFI queues, ready/ACK sequence, each write before/after side effect, critical read failures, timeouts/incorrect replies, all resources retained until reset\n",cases);
}
