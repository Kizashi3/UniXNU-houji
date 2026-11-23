/* Real host-ring state machine with a separate fake GPU consumer. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "GpuHostRing.h"
struct model {
 uint32_t reg[7],ring[HHR_WORDS],scratch[2],sqe,rptr,wptr;
 unsigned events,fail,prepared,aperture,checkpoint,kicks,stops,peek,snapshots;
 unsigned busy,fence,never,fault,wrong,sqe_bad,readback_bad,stop_bad,published;
 unsigned gmu_reads,gmu_busy_polls,gmu_busy_forever,gmu_read_fail,post_calls,post_fail;
};
static unsigned cases;
static int event(struct model*m){return ++m->events==m->fail;}
static int guard(void*c){return event(c);}
static int prepare(void*c){struct model*m=c;if(event(m))return 1;m->prepared++;return 0;}
static int aperture(void*c){struct model*m=c;assert(m->prepared);if(event(m))return 1;m->aperture++;return 0;}
static unsigned index_of(uint32_t a){const uint32_t x[]={0x3d02000,0x3d02004,0x3d02008,0x3d02010,0x3d02014,0x3d02a60,0x3d02a64};for(unsigned i=0;i<7;i++)if(x[i]==a)return i;return 7;}
static int read32(void*c,uint32_t a,uint32_t*v){struct model*m=c;if(event(m))return 1;
 unsigned i=index_of(a);if(i<7){*v=m->reg[i]^m->readback_bad;return 0;}
 if(a==0x3d02020)*v=m->sqe^m->sqe_bad;
 else if(a==0x3d02018){if(m->wptr && !m->never && m->busy++>1){
   if(m->wptr==15 || m->wptr==20){unsigned off=m->wptr-5,slot=(m->wptr-15)/5;
    assert(m->ring[off]==0x703d8003 && m->ring[off+1]==HHR_SCRATCH+slot*4 && !m->ring[off+2] && m->ring[off+4]==0x70928000);
    m->scratch[slot]=m->ring[off+3]^m->wrong;}
   m->rptr=m->wptr;}*v=m->rptr;}
 else if(a==0x3d0201c)*v=m->wptr;
 else if(a==0x3d00840)*v=m->rptr==m->wptr?1:2;
 else if(a==0x3d00804)*v=m->fault && m->sqe?1:0;
 else if(a==0x3d02084)*v=0;
 else if(a==0x3d8ec30){m->gmu_reads++;if(m->gmu_read_fail)return 1;*v=(m->gmu_busy_forever || m->gmu_reads<=m->gmu_busy_polls)?0x71c00004:0x71400004;}
 else if(a==0x3d8ec4c){*v=m->fence?1:0;if(m->fence)m->fence--;}
 else {assert(0);return 1;}return 0;
}
static int write32(void*c,uint32_t a,uint32_t v){struct model*m=c;if(event(m))return 1;unsigned i=index_of(a);
 if(i<7){assert(m->aperture && !m->sqe);m->reg[i]=v;}
 else if(a==0x3d02020){assert(v==1 && m->checkpoint && m->published==10);m->sqe=v;}
 else {assert(a==0x3d0201c && m->sqe && m->checkpoint && v==m->published);m->wptr=v;m->kicks++;m->busy=0;}
 return 0;
}
static int publish(void*c,unsigned off,const uint32_t*w,unsigned n){struct model*m=c;if(event(m))return 1;assert(off==m->published && off+n<=20);if(!off){const uint32_t init[]={0x70970001,0x8000000,0x70c80007,0x94b,3,0x20000000,2,HHR_RECORD,0,0x80000000};assert(n==10 && !memcmp(init,w,sizeof init));}else assert(m->rptr==off && n==5);memcpy(m->ring+off,w,n*4);m->published+=n;return 0;}
static int peek(void*c,unsigned i,uint32_t*v){struct model*m=c;if(event(m))return 1;assert(i<2 && m->rptr==15+5*i);m->peek++;*v=m->scratch[i];return 0;}
static int delay(void*c,unsigned u){assert(u==10 || u==100);return event(c);}
static int checkpoint(void*c){struct model*m=c;if(event(m))return 1;assert(!m->sqe && m->published==10);m->checkpoint++;return 0;}
static void snapshot(void*c,unsigned s){struct model*m=c;assert(s<5);m->snapshots|=1u<<s;}
static int stop(void*c,uint32_t w){struct model*m=c;m->stops++;if(event(m) || m->stop_bad)return 1;m->sqe=3;return m->rptr!=w || m->fault;}
static int engine_probe(void*c){struct model*m=c;assert(m->sqe==1 && !m->wptr && m->checkpoint);return event(m);}
static int after_init(void*c,struct hhr_result*r){struct model*m=c;assert(r->phase==4 && r->init_idle && r->rptr==10 && r->wptr==10 && m->scratch[0]==0 && m->scratch[1]==0);m->post_calls++;return m->post_fail?1:event(m);}
static struct hhr_io ops(struct model*m){return (struct hhr_io){m,guard,prepare,aperture,read32,write32,publish,peek,delay,checkpoint,snapshot,stop,engine_probe,NULL};}
int main(void){struct model m={0};struct hhr_result r={0};struct hhr_io io=ops(&m);
 assert(!hhr_run(&io,&r));unsigned events=m.events;assert(r.phase==8 && r.writebacks==2 && r.init_idle && r.kicks==3 && r.stopped && m.scratch[0]==0xc0ffee00 && m.scratch[1]==0xc0ffee01 && m.peek==2 && m.snapshots==31);cases++;
 assert(hhr_run(&io,&r)==HHR_GUARD);cases++;
 for(unsigned i=1;i<=events;i++){m=(struct model){.fail=i};r=(struct hhr_result){0};io=ops(&m);assert(hhr_run(&io,&r));assert(r.phase!=8);if(!m.checkpoint)assert(!m.sqe && !m.kicks);cases++;}
 for(unsigned k=0;k<8;k++){m=(struct model){0};r=(struct hhr_result){0};io=ops(&m);
  if(k==0)m.never=1;if(k==1)m.fault=1;if(k==2)m.wrong=1;if(k==3)m.sqe_bad=2;if(k==4)m.readback_bad=1;if(k==5)m.stop_bad=1;if(k==6)m.fence=200;if(k==7)m.fence=2;
  unsigned code=hhr_run(&io,&r);assert((k==7)==!code);if(k==7)assert(r.fence_retries==2 && r.writebacks==2);if(k==0 || k==1 || k==5)assert(!r.stopped);if(k==2)assert(code==HHR_WRITEBACK && !r.writebacks);cases++;}
 assert(hhr_pkt7(0x17,1)==0x70970001 && hhr_pkt7(0x48,7)==0x70c80007 && hhr_pkt7(0x3d,3)==0x703d8003 && hhr_pkt7(0x12,0)==0x70928000);cases++;
 // Completion is bounded even when RPTR and RBBM already report idle: GMU
 // busy is normal progress, but it must clear before completion is published.
 m=(struct model){.sqe=1,.gmu_busy_polls=3};r=(struct hhr_result){0};io=ops(&m);
 assert(hhr_idle(&io,&r)==HHR_OK && r.polls==4 && m.gmu_reads==4 && r.busy_valid && r.busy==0x71400004);cases++;
 m=(struct model){.sqe=1,.gmu_busy_forever=1};r=(struct hhr_result){0};io=ops(&m);
 assert(hhr_idle(&io,&r)==HHR_TIMEOUT && r.polls==HHR_POLLS && m.gmu_reads==HHR_POLLS && r.busy_valid && (r.busy&0x800000));cases++;
 m=(struct model){.sqe=1,.gmu_read_fail=1};r=(struct hhr_result){.busy=0x800000,.busy_valid=1};io=ops(&m);
 assert(hhr_idle(&io,&r)==HHR_IO && r.polls==1 && m.gmu_reads==1 && !r.busy_valid);cases++;
 m=(struct model){.sqe=1,.fault=1,.gmu_busy_forever=1};r=(struct hhr_result){0};io=ops(&m);
 assert(hhr_idle(&io,&r)==HHR_FAULT && r.polls==1 && !m.gmu_reads);cases++;
 for(unsigned fail=0;fail<2;fail++) {
  m=(struct model){.post_fail=fail};r=(struct hhr_result){0};io=ops(&m);io.post_init=after_init;
  unsigned code=hhr_run(&io,&r);
  if(!fail)assert(!code && r.post_init_attempted && r.post_init_complete && r.writebacks==2);
  else assert(code==HHR_POST_INIT && r.post_init_attempted && !r.post_init_complete && !r.writebacks && r.kicks==1 && m.stops==1 && m.post_calls==1);
  cases++;
 }
 printf("PASS: %u host ring cases; independent GPU consumer, real fixed packets,3submits,2writebacks, every callback failure, bounded fence/idle timeout, halt proof and no premature FS\n",cases);
}
