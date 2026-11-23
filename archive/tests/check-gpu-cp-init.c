/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "uefi/GpuCpInit.h"
static struct hci_result result;static unsigned header,cases,healths,ready_count,apertures,sends,delays,read_count,debug_sent;
static unsigned ack_value,ack_words,header_flip,sender_flip,fail_health,fail_ready,fail_reads;
static int fail_aperture,fail_send,fail_receive,fail_doorbell,fail_delay,no_ack,always_busy,debug_flood;
static int healthy(void*c){(void)c;return ++healths!=fail_health;}
static int ready(void*c){(void)c;return ++ready_count==fail_ready;}
static int aperture(void*c){(void)c;apertures++;return fail_aperture;}
static int send(void*c,const uint32_t*w,unsigned n){(void)c;sends++;const uint32_t expected[]={0x70970001,0x08000000,0x70c80007,0x94b,3,0x20000000,2,0x6303f000,0,0x80000000};assert(n==11 && (w[0]&0xfffff)==0xb83 && !memcmp(w+1,expected,sizeof(expected)));header=w[0];return fail_send;}
static int receive(void*c,unsigned q,uint32_t*w,unsigned*n){(void)c;if(fail_receive)return 2;
 if(q==2 && debug_flood){w[0]=0x123;*n=1;debug_sent++;return 0;}
 if(q==2 || no_ack || !delays || debug_flood)return 1;
 w[0]=((ack_words<<8)|0x10083)^header_flip;w[1]=header^sender_flip;w[2]=ack_value;w[3]=0xdeadbeef;*n=ack_words;return 0;
}
static int doorbell(void*c){(void)c;return fail_doorbell;}
static int delay(void*c,unsigned us){(void)c;assert(us==10);delays++;return fail_delay;}
static int read32(void*c,uint32_t a,uint32_t*v){(void)c;read_count++;if(read_count==fail_reads)return 1;
 if(a==0x3d8ec30)*v=always_busy || result.polls<3?1u<<23:0;
 else if(a==0x3d00840)*v=1;else if(a==0x3d02020 || a==0x3d00804)*v=0;else assert(0);return 0;
}
static void reset(void){memset(&result,0,sizeof(result));header=healths=ready_count=apertures=sends=delays=read_count=debug_sent=0;
 ack_value=header_flip=sender_flip=fail_health=fail_ready=fail_reads=0;ack_words=3;fail_aperture=fail_send=fail_receive=fail_doorbell=fail_delay=no_ack=always_busy=debug_flood=0;}
static unsigned run(void){const struct hci_io io={{0,healthy,send,receive,doorbell,delay,0},ready,aperture,read32};unsigned sequence=22;return hci_run(&io,&result,&sequence);}
int main(void){reset();assert(!run() && result.phase==6 && result.idle && result.raw.record[0].ack && result.polls==3 && sends==1 && apertures==1);unsigned hc=healths;cases++;
 reset();ack_value=1;ack_words=4;assert(!run() && !result.raw.record[0].status_present && result.raw.record[0].reply[3]==0xdeadbeef);cases++;
 for(unsigned i=1;i<=hc;i++){reset();fail_health=i;assert(run() && healths==i && result.phase!=6);cases++;}
 for(unsigned i=1;i<=2;i++){reset();fail_ready=i;assert(run()==HCI_GUARD && !sends);cases++;}
 reset();fail_aperture=1;assert(run()==HCI_APERTURE && !sends && apertures==1);cases++;
 for(unsigned i=0;i<20;i++){reset();header_flip=1u<<i;assert(run()==HCI_EXCHANGE && !result.idle);cases++;}
 for(unsigned i=0;i<32;i++){reset();sender_flip=1u<<i;assert(run()==HCI_EXCHANGE && !result.idle);cases++;}
 for(unsigned i=1;i<=6;i++){reset();fail_reads=i;assert(run()==HCI_IO && read_count==i);cases++;}
 reset();ack_value=0xffffffff;assert(run()==HCI_EXCHANGE && result.raw.code==HHB_REJECTED);cases++;
 reset();fail_send=1;assert(run()==HCI_EXCHANGE && result.raw.code==HHB_IO && !result.raw.record[0].sent);cases++;
 reset();fail_doorbell=1;assert(run()==HCI_EXCHANGE && result.raw.code==HHB_IO);cases++;
 reset();fail_receive=1;assert(run()==HCI_EXCHANGE && result.raw.code==HHB_PROTOCOL);cases++;
 reset();fail_delay=1;assert(run()==HCI_EXCHANGE && result.raw.code==HHB_IO);cases++;
 reset();no_ack=1;assert(run()==HCI_EXCHANGE && result.raw.code==HHB_TIMEOUT && delays==20000 && sends==1);cases++;
 reset();always_busy=1;assert(run()==HCI_TIMEOUT && result.polls==20000 && sends==1 && result.raw.record[0].ack);cases++;
 reset();debug_flood=1;assert(run()==HCI_EXCHANGE && result.raw.code==HHB_PROTOCOL && result.debug_count==33 && result.debug[7].words[0]==0x123);cases++;
 assert(hci_packet(0x17,1)==0x70970001 && hci_packet(0x48,7)==0x70c80007);cases++;
 printf("PASS: %u fixed CP-init sequence, async ACK contract, guard/fault/timeout/debug cases; no NOP/PAS/mode-exit/fence command\n",cases);
}
