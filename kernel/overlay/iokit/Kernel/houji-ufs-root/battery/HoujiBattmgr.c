/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#include "HoujiBattmgr.h"

static const struct {uint32_t opcode, property;} fields[HoujiBmFields] = {
    {0x30,4}, {0x30,2}, {0x30,0}, {0x32,0}, {0x30,7}, {0x30,13},
    {0x30,9}, {0x30,15}, {0x30,18}, {0x30,17}, {0x30,16}
};
static void put(uint8_t *p,uint32_t v){for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(v>>(8*i));}
static uint32_t get(const uint8_t *p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static void header(uint8_t *p,uint32_t op){put(p,HOUJI_BM_OWNER);put(p+4,1);put(p+8,op);}

void houji_battmgr_init(HoujiBattmgr *b){
    for(size_t i=0;i<sizeof(*b);i++)((uint8_t *)b)[i]=0;
}
void houji_battmgr_disconnect(HoujiBattmgr *b){
    b->valid=b->pending_valid=0;b->sampled_ms=0;b->active=b->awaiting=0;
}
int houji_battmgr_begin(HoujiBattmgr *b){
    if(b->active)return 0;
    b->pending_valid=0;b->pending_first_ms=0;b->cursor=0;b->active=1;b->awaiting=0;
    for(unsigned i=0;i<HoujiBmFields;i++)b->pending[i]=0;
    return 1;
}
uint32_t houji_battmgr_request(HoujiBattmgr *b,uint8_t out[24]){
    if(!b->active||b->awaiting||b->cursor>=HoujiBmFields||!out)return 0;
    header(out,fields[b->cursor].opcode);put(out+12,0);put(out+16,fields[b->cursor].property);put(out+20,0);
    b->awaiting=1;return 24;
}
uint32_t houji_battmgr_subscribe(uint8_t out[28]){
    /* MiCode battery_chg_notify_enable uses MSG_TYPE_NOTIFY and a zeroed
     * payload. This differs from the older sheng request-type subscription. */
    header(out,4);put(out+4,2);put(out+12,0);put(out+16,0);put(out+20,0);put(out+24,0);return 28;
}
static int advance(HoujiBattmgr *b,uint64_t now){
    b->awaiting=0;
    if(++b->cursor<HoujiBmFields)return HoujiBmAnswer;
    b->active=0;b->cycles++;
    b->valid=b->pending_valid;
    for(unsigned i=0;i<HoujiBmFields;i++)b->value[i]=b->pending[i];
    /* Optional properties may time out after the essential replies arrived.
     * Finishing that work must not make those older readings appear fresh. */
    b->sampled_ms=b->pending_first_ms;
    if(now<b->sampled_ms)b->valid=0;
    return HoujiBmCycleDone;
}
static int valid(unsigned field,int32_t v){
    switch(field){
    case HoujiBmCapacity:return v>=0&&v<=10000;
    case HoujiBmPresent:case HoujiBmUsbOnline:return v==0||v==1;
    case HoujiBmStatus:return v>=1&&v<=4; /* UNKNOWN does not establish power state. */
    case HoujiBmVoltage:return v>0&&v<=6000000;
    case HoujiBmTemperature:return v>=-4000&&v<=12500;
    case HoujiBmCurrent:return v>=-20000000&&v<=20000000;
    case HoujiBmCharge:return v>=0&&v<=20000000;
    case HoujiBmFull:case HoujiBmDesign:return v>0&&v<=20000000;
    case HoujiBmCycles:return v>=0&&v<=10000;
    default:return 0;
    }
}
int houji_battmgr_receive(HoujiBattmgr *b,const uint8_t *p,uint32_t n,uint64_t now){
    if(!p||n<12||get(p)!=HOUJI_BM_OWNER){b->ignored++;return 0;}
    uint32_t type=get(p+4),op=get(p+8);
    if(n==16&&type==2&&op==7){
        uint32_t event=get(p+12);
        if(event==0x30||event==0x32||event==0x80){b->notifications++;return HoujiBmNotification;}
    }
    if(n!=24||type!=1||!b->active||!b->awaiting||b->cursor>=HoujiBmFields||
       op!=fields[b->cursor].opcode||get(p+12)!=fields[b->cursor].property){b->ignored++;return 0;}
    b->responses++;
    /* Preserve Linux's signed raw current. The publisher must establish this
     * board's charge/discharge polarity before presenting an amperage value. */
    int32_t v=(int32_t)get(p+16);
    if(!get(p+20)&&valid(b->cursor,v)){
        if((HOUJI_BM_REQUIRED&(1u<<b->cursor))&&!(b->pending_valid&HOUJI_BM_REQUIRED))
            b->pending_first_ms=now;
        b->pending[b->cursor]=v;b->pending_valid|=1u<<b->cursor;
    }else{
        b->errors++;
        if(HOUJI_BM_REQUIRED&(1u<<b->cursor))b->valid=0;
    }
    return advance(b,now);
}
int houji_battmgr_timeout(HoujiBattmgr *b,uint64_t now){
    if(!b->active||!b->awaiting||b->cursor>=HoujiBmFields)return 0;
    b->timeouts++;
    if(HOUJI_BM_REQUIRED&(1u<<b->cursor))b->valid=0;
    return advance(b,now);
}
int houji_battmgr_skip_optional(HoujiBattmgr *b,uint64_t now){
    if(!b->active || b->awaiting || b->cursor>=HoujiBmFields ||
       (HOUJI_BM_REQUIRED&(1u<<b->cursor)))return 0;
    return advance(b,now);
}
int houji_battmgr_fresh(const HoujiBattmgr *b,uint64_t now){
    return (b->valid&HOUJI_BM_REQUIRED)==HOUJI_BM_REQUIRED&&now>=b->sampled_ms&&now-b->sampled_ms<=HOUJI_BM_FRESH_MS;
}
