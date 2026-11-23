// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "../kernel/overlay/iokit/Kernel/houji-ufs-root/battery/HoujiBattmgr.h"
static uint32_t get(const uint8_t *p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static void put(uint8_t *p,uint32_t v){for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(v>>(8*i));}
static void reply(uint8_t out[24],const uint8_t request[24],int32_t v,uint32_t error){
 memcpy(out,request,12);put(out+12,get(request+16));put(out+16,(uint32_t)v);put(out+20,error);
}
static const int32_t readings[HoujiBmFields]={8700,1,1,1,4218000,3330,643000,3500000,4067000,4610000,597};
static void cycle(HoujiBattmgr *b,int fail,uint64_t now){
 assert(houji_battmgr_begin(b));assert(!houji_battmgr_begin(b));
 for(unsigned i=0;i<HoujiBmFields;i++){
  uint8_t q[24],a[24];assert(houji_battmgr_request(b,q)==24);assert(!houji_battmgr_request(b,q));
  assert(get(q)==HOUJI_BM_OWNER && get(q+4)==1 && (get(q+8)==0x30||get(q+8)==0x32));
  assert(get(q+12)==0 && get(q+20)==0); // No current limit or other value is written.
  reply(a,q,readings[i],(int)i==fail);
  int result=houji_battmgr_receive(b,a,24,now);
  assert(result==(i+1==HoujiBmFields?HoujiBmCycleDone:HoujiBmAnswer));
  if(i+1<HoujiBmFields && b->cycles==0)assert(!houji_battmgr_fresh(b,now));
 }
 assert(!b->active&&!b->awaiting);
}
int main(void){
 HoujiBattmgr b;houji_battmgr_init(&b);assert(!houji_battmgr_fresh(&b,0));
 cycle(&b,-1,1000);assert(houji_battmgr_fresh(&b,1000));
 assert(b.value[HoujiBmCapacity]==8700 && b.value[HoujiBmCurrent]==643000 && b.value[HoujiBmTemperature]==3330);
 assert(houji_battmgr_fresh(&b,16000));assert(!houji_battmgr_fresh(&b,16001));assert(!houji_battmgr_fresh(&b,999));
 cycle(&b,HoujiBmVoltage,2000);assert(houji_battmgr_fresh(&b,2000));assert(!(b.valid&(1u<<HoujiBmVoltage)));
 for(int i=0;i<4;i++){cycle(&b,i,3000+i);assert(!houji_battmgr_fresh(&b,3000+i));}
 cycle(&b,-1,4000);assert(houji_battmgr_fresh(&b,4000));
 assert(houji_battmgr_begin(&b));uint8_t q[24],a[24];assert(houji_battmgr_request(&b,q)==24);
 reply(a,q,10001,0);assert(houji_battmgr_receive(&b,a,24,4100)==HoujiBmAnswer);assert(!houji_battmgr_fresh(&b,4100));
 houji_battmgr_disconnect(&b);assert(!b.valid&&!b.active&&!houji_battmgr_fresh(&b,4100));
 assert(houji_battmgr_begin(&b));assert(houji_battmgr_request(&b,q)==24);reply(a,q,0,0);
 for(unsigned n=0;n<24;n++)assert(!houji_battmgr_receive(&b,a,n,5000));
 put(a,HOUJI_BM_OWNER+1);assert(!houji_battmgr_receive(&b,a,24,5000));
 reply(a,q,0,0);put(a+4,2);assert(!houji_battmgr_receive(&b,a,24,5000));
 reply(a,q,0,0);put(a+12,13);assert(!houji_battmgr_receive(&b,a,24,5000));
 assert(b.cursor==0&&b.awaiting);
 reply(a,q,0,0);assert(houji_battmgr_receive(&b,a,24,5000)==HoujiBmAnswer); // Actual 0% is valid, not an absent reading.
 assert(b.pending_valid&(1u<<HoujiBmCapacity));assert(!houji_battmgr_fresh(&b,5000));
 assert(houji_battmgr_request(&b,q)==24);assert(houji_battmgr_timeout(&b,5100)==HoujiBmAnswer);assert(b.timeouts==1);
 reply(a,q,1,0);assert(!houji_battmgr_receive(&b,a,24,5200)); // Late timed-out answer never advances another field.
 houji_battmgr_disconnect(&b);
 cycle(&b,-1,6000);assert(houji_battmgr_begin(&b));assert(houji_battmgr_request(&b,q)==24);
 assert(houji_battmgr_timeout(&b,6100)==HoujiBmAnswer);assert(!houji_battmgr_fresh(&b,6100)); // Missing essential reading invalidates prior state.
 uint8_t note[16]={0};put(note,HOUJI_BM_OWNER);put(note+4,2);put(note+8,7);put(note+12,0x30);
 assert(houji_battmgr_receive(&b,note,16,6200)==HoujiBmNotification);put(note+4,1);assert(!houji_battmgr_receive(&b,note,16,6200));
 uint8_t subscribe[28];assert(houji_battmgr_subscribe(subscribe)==28);
 assert(get(subscribe)==HOUJI_BM_OWNER && get(subscribe+4)==2 && get(subscribe+8)==4);
 for(unsigned i=12;i<28;i+=4)assert(!get(subscribe+i)); // Stock notify message, no thresholds/settings.
 houji_battmgr_disconnect(&b);assert(houji_battmgr_begin(&b));
 for(unsigned i=0;i<HoujiBmFields;i++){
  assert(houji_battmgr_request(&b,q)==24);
  if(i<4){reply(a,q,readings[i],0);houji_battmgr_receive(&b,a,24,10000+i);}
  else houji_battmgr_timeout(&b,10000+(i-3)*3000);
 }
 assert(!b.active&&b.sampled_ms==10000);
 assert(!houji_battmgr_fresh(&b,31000)); // Optional timeouts do not renew older essential readings.
 houji_battmgr_disconnect(&b);assert(houji_battmgr_begin(&b));
 assert(!houji_battmgr_skip_optional(&b,32000)); // Essential properties cannot be skipped.
 for(unsigned i=0;i<4;i++){
  assert(houji_battmgr_request(&b,q)==24);reply(a,q,readings[i],0);
  assert(houji_battmgr_receive(&b,a,24,32000)==HoujiBmAnswer);
 }
 uint32_t timeouts=b.timeouts;
 while(b.active)assert(houji_battmgr_skip_optional(&b,32001));
 assert(b.timeouts==timeouts && b.valid==HOUJI_BM_REQUIRED && houji_battmgr_fresh(&b,32001));
 puts("PASS: actual PMIC codec, complete/fresh samples, malformed replies, error/timeout/link loss, units and no charger SET; no device");
}
