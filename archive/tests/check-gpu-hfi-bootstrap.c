// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "GpuHfiBootstrap.h"
#include "vendor/Ace5Gmu/giulia_gpu_hfi.h"
struct model {
 uint32_t memory[GGH_BYTES/4];struct ggh_io queues;
 unsigned healthy,send,receive,doorbell,delay,barriers,fail_kind,fail_at,mode,pending,resource_calls;
 uint32_t last_header,start_header;
};
static int fail(struct model*m,unsigned kind,unsigned count){return m->fail_kind==kind && count==m->fail_at;}
static void barrier(void*c){((struct model*)c)->barriers++;}
static int healthy(void*c){struct model*m=c;return !fail(m,1,++m->healthy);}
static int send(void*c,const uint32_t*p,unsigned n){
 struct model*m=c;if(fail(m,2,++m->send))return 1;
 if((m->mode>=12 && m->mode<=17) && m->send>=10) {
  assert(n==11 && p[0]==((m->send+1)<<20 | 0x10b14) && p[1]==((m->send-1)<<20 | 0xb14));
  assert(p[2]==0x61000000+(m->send-10)*4096 && p[8]==p[2]);
  return ggh_send(&m->queues,p,n);
 }
 const unsigned ids[]={15,3,11,11,14,12,11,11,10},sizes[]={19,160,4,4,2,3,4,4,1};
 assert(m->send<=9 && (p[0]&255)==ids[m->send-1] && n==sizes[m->send-1]);
 assert(p[0]==((m->send+1)<<20 | n<<8 | ids[m->send-1]));
 if(m->send==1){assert(p[1]==0 && p[2]==1 && p[3]==2 && p[4]==3);assert(p[10]==231000);}
 if(m->send==2){assert(p[1]==10 && p[2]==1 && p[3]==3);assert(p[6]==0x50030 && p[24]==0x50004 && p[25]==0x50000 && p[26]==0x50068);}
 if(m->send==3)assert(p[1]==1 && p[2]==1 && !p[3]);
 if(m->send==4)assert(p[1]==16 && p[2]==1 && !p[3]);
 if(m->send==5)assert(!p[1]);if(m->send==6)assert(p[1]==121 && !p[2]);
 if(m->send==7)assert(p[1]==2 && !p[2] && !p[3]);
 if(m->send==8)assert(p[1]==29 && p[2]==1 && !p[3]);
 return ggh_send(&m->queues,p,n);
}
static int receive(void*c,unsigned queue,uint32_t*p,unsigned*n){struct model*m=c;if(fail(m,3,++m->receive))return 3;return ggh_receive(&m->queues,queue,p,255,n);}
static int doorbell(void*c){
 struct model*m=c;if(fail(m,4,++m->doorbell))return 1;
 volatile uint32_t*h,*ring;unsigned rd,wr;assert(!ggh_queue(&m->queues,0,&h,&ring,&rd,&wr) && rd!=wr);
 m->last_header=ring[rd];if((m->last_header&255)==10)m->start_header=m->last_header;unsigned n=(m->last_header>>8)&255;assert(((n+3)&~3u)==((wr-rd)&1023));h[10]=wr;m->pending=1;return 0;
}
static int delay(void*c,unsigned us){
 struct model*m=c;assert(us==10);if(fail(m,5,++m->delay))return 1;
 if(!m->pending || m->mode==1)return 0;m->pending=0;
 unsigned q=m->mode==10?2:1;uint32_t*h=m->memory+6+12*q,*ring=m->memory+GGH_RING_OFFSET/4+1024*q;
 unsigned at=h[11],id=m->last_header&255,n=4;
 uint32_t reply[13]={0x10000 | 4<<8 | id,m->last_header,id==12?1:0,0};
 if(m->mode==2)reply[1]^=1;
 if(m->mode==3)reply[0]^=1;
 if(m->mode==4)reply[3]=1;
 if(m->mode==5)reply[2]=99;
 if(m->mode==6 || (m->mode==11 && (id==15 || id==3 || id==14 || id==10))){n=3;reply[0]=(reply[0]&~0xff00u)|(n<<8);}
 if(m->mode==7){n=13;reply[0]=(13<<8)|20;reply[1]=0x1007;reply[2]=0x37d000;}
 if(m->mode==8)reply[0]&=~0x10000u;
 if(m->mode==9)reply[0]=(12<<8)|20; // Malformed/incomplete wire length.
 if(m->mode==10){reply[0]=(4<<8)|100;m->pending=1;}
 if(m->mode>=12 && m->mode<=17 && m->send>=9) {
  uint32_t resource[]={0x00900b14,1,0,0,0x33f,2,0,2,0,4096,0};
  if(m->send>=10){resource[0]+=(m->send-9)<<20;resource[7]=m->send-7;}
  if(m->mode==16 && m->send==10)resource[5]=resource[7]=14;
  if(m->mode==17)resource[7]=m->send;
  n=11;memcpy(reply,resource,sizeof(resource));
  if(m->mode==16 && m->send==11){n=3;reply[0]=0x1030a;reply[1]=m->start_header;reply[2]=0;}
 }
 for(unsigned i=0;i<((n+3)&~3u);i++)ring[(at+i)&1023]=i<n?reply[i]:0xfafafafa;
 h[11]=(at+((n+3)&~3u))&1023;return 0;
}
static void init(struct model*m){memset(m,0,sizeof(*m));assert(!ggh_init(m->memory,sizeof(m->memory),GGH_IOVA));m->queues=(struct ggh_io){m->memory,sizeof(m->memory),GGH_IOVA,m,barrier};}
static int resource(void*c,const uint32_t*request,unsigned n,uint32_t*response){
 struct model*m=c;m->resource_calls++;assert(n==11);
 if(m->mode<16 && request[7]!=2)return 1;
 assert(m->send>=9);
 if(m->mode==13)return -1;if(m->mode==14)return 1;
 memcpy(response,request,44);response[2]=response[8]=0x61000000+(m->send-9)*4096;response[6]=request[7];
 if(m->mode==15)response[4]^=1;return 0;
}
static unsigned run(struct model*m,struct hhb_result*r){const struct hhb_io io={m,healthy,send,receive,doorbell,delay,m->mode>=12?resource:0};return hhb_run(&io,r);}
int main(void){
 struct model*m=malloc(sizeof(*m));struct hhb_result*r=malloc(sizeof(*r));assert(m && r);unsigned cases=0;
 init(m);assert(run(m,r)==HHB_OK && r->completed==9 && r->stage==9 && m->send==9 && r->record[5].value==1);cases++;
 unsigned counts[]={0,m->healthy,m->send,m->receive,m->doorbell,m->delay};
 for(unsigned kind=1;kind<=5;kind++)for(unsigned at=1;at<=counts[kind];at++) {
  init(m);m->fail_kind=kind;m->fail_at=at;assert(run(m,r)!=HHB_OK && r->completed<9);cases++;
 }
 const unsigned expected[]={HHB_OK,HHB_TIMEOUT,HHB_PROTOCOL,HHB_PROTOCOL,HHB_REJECTED,HHB_REJECTED,HHB_PROTOCOL,HHB_RESOURCE,HHB_PROTOCOL,HHB_PROTOCOL,HHB_PROTOCOL};
 for(unsigned mode=1;mode<=10;mode++) {
  init(m);m->mode=mode;assert(run(m,r)==expected[mode]);
  if(mode==6)assert(m->send==3 && r->completed==2 && !r->record[0].status_present);
  else assert(m->send==1 && !r->completed);
  if(mode==7)assert(r->resource_request && r->resource_words==13 && !r->record[0].ack);
  cases++;
 }
 init(m);m->mode=11;assert(run(m,r)==HHB_OK && r->completed==9 && !r->record[0].status_present && r->record[2].status_present && !r->record[8].status_present);cases++;
 for(unsigned mode=12;mode<=15;mode++) {
  init(m);m->mode=mode;unsigned code=run(m,r);
  assert(code==(mode==13?HHB_IO:mode==15?HHB_PROTOCOL:HHB_RESOURCE));
  assert(r->completed==8 && m->resource_calls==(mode==12?2u:1u) && r->resource_acks==(mode==12));
  if(mode==12)assert(m->send==10 && r->resource_count==2 && r->resources[0].sent && !r->resources[1].sent);
  else assert(m->send==9 && r->resource_count==1 && !r->resources[0].sent);
  cases++;
 }
 init(m);m->mode=16;assert(run(m,r)==HHB_OK && r->completed==9 && r->resource_acks==2 && r->resource_count==2 && m->send==11);cases++;
 init(m);m->mode=17;assert(run(m,r)==HHB_PROTOCOL && r->completed==8 && r->resource_acks==HSC_MAX_RESOURCES && r->resource_count==HSC_MAX_RESOURCES && m->send==9+HSC_MAX_RESOURCES);cases++;
 init(m);const struct hhb_io missing={0};assert(hhb_run(&missing,r)==HHB_ARGUMENT && !m->send);cases++;
 printf("PASS: %u HFI bootstrap cases; actual 17-queue rings, wire table shapes, nine ordered requests, matched full ACKs, every transport/health failure, malformed/rejected/debug/timeout and first allocation stop without ACK\n",cases);
 free(m);free(r);
}
