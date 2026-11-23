// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "GpuDesktopPerfProfile.h"
struct model {unsigned reads,writes,healths,qualifications,sends,receives,doorbells,delays,gx_reads,fail_read,fail_write,fail_health,fail_qualified,apply,mode,requested,ack,cleared;uint32_t header;};
static int healthy(void*c){struct model*m=c;return ++m->healths!=m->fail_health;}
static int qualified(void*c){struct model*m=c;return ++m->qualifications==m->fail_qualified;}
static int send(void*c,const uint32_t*q,unsigned n){struct model*m=c;m->sends++;assert(n==4 && (q[0]&0xfffff)==0x41e && q[1]==1 && q[2]==2 && q[3]==5);m->header=q[0];return m->mode==8;}
static int receive(void*c,unsigned queue,uint32_t*q,unsigned*n){struct model*m=c;assert(queue==1 || queue==2);m->receives++;if(queue==2 || m->mode==9)return 1;
 q[0]=0x0011031e;q[1]=m->header;q[2]=m->mode==10?1:0;*n=3;return 0;}
static int doorbell(void*c){struct model*m=c;m->doorbells++;return 0;}
static int delay(void*c,unsigned us){struct model*m=c;assert(us==10);m->delays++;return 0;}
static int read32(void*c,uint32_t a,uint32_t*v){struct model*m=c;if(++m->reads==m->fail_read)return 1;
 switch(a){
 case 0x3d7e340:*v=m->requested && m->mode!=2?0:3;break;
 case 0x3d7e648:*v=1;if(m->mode==5 || (m->requested && m->mode!=1 && !m->cleared)){*v|=HGX_ACK;m->ack=1;}break;
 case 0x3d7e658:*v=m->mode==6?HGX_SET:0;break;
 case 0x3d8ec40:*v=m->mode==3?1:0;break;
 case 0x3d8ec30:*v=m->mode==4?1u<<23:0;break;
 case 0x3d00840:case 0x3d0084c:case 0x3d02020:assert(m->requested && m->ack && m->cleared && m->mode!=1 && m->mode!=2 && m->mode!=3 && m->mode!=4);m->gx_reads++;*v=a==0x3d02020?3:0;break;
 default:assert(0);return 1;
 }return 0;
}
static int write32(void*c,uint32_t a,uint32_t v){struct model*m=c;unsigned failure=++m->writes==m->fail_write;if(failure && !m->apply)return 1;
 if(a==0x3d7e650){assert(v==HGX_SET && m->sends && m->doorbells && !m->requested);m->requested=1;}
 else {assert(a==0x3d7e644 && v==HGX_ACK && m->ack);if(m->mode!=7)m->cleared=1;}return failure;}
static unsigned run(struct model*m,struct hgx_result*r){struct hgx_io io={{m,healthy,send,receive,doorbell,delay,0},read32,write32,qualified};unsigned seq=21;unsigned code=hup_gx_run(&io,&seq,r);assert(seq==21+(r->vote.record[0].attempted!=0));return code;}
int main(void){struct hgx_result*r=malloc(sizeof(*r));assert(r);struct model m={0};unsigned cases=0;
 assert(!run(&m,r) && r->phase==6 && r->valid==0x7ff && r->gx_ready && r->clear_confirmed && r->acked && r->retained && m.gx_reads==3 && m.writes==2 && r->vote.record[0].ack && !r->vote.record[0].status_present);cases++;
 unsigned reads=m.reads,writes=m.writes,health=m.healths,qual=m.qualifications;
 for(unsigned type=0;type<4;type++)for(unsigned n=1;n<=(type==0?reads:type==1?writes:type==2?health:qual);n++)for(unsigned apply=0;apply<(type==1?2u:1u);apply++){
  memset(&m,0,sizeof(m));m.apply=apply;if(type==0)m.fail_read=n;if(type==1)m.fail_write=n;if(type==2)m.fail_health=n;if(type==3)m.fail_qualified=n;
  assert(run(&m,r) && r->retained);if(type==3)assert(!m.gx_reads);cases++;
 }
 for(unsigned mode=1;mode<=10;mode++) {memset(&m,0,sizeof(m));m.mode=mode;assert(run(&m,r) && r->retained && !m.gx_reads);if(mode==5 || mode==6)assert(!m.sends && !m.writes);if(mode==8 || mode==9 || mode==10)assert(!m.writes);cases++;}
 free(r);printf("PASS: %u fixed DCVS/OOB/GX cases; correct legacy ACK, fresh OOB ownership, exact W1C bit, bounded waits, no GX read under invalid power/fence, every I/O/guard failure and partial side effect retains resources\n",cases);
}
