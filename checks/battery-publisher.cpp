// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "publisher-under-test.cpp"
static uint32_t get(const uint8_t *p){return p[0]|uint32_t(p[1])<<8|uint32_t(p[2])<<16|uint32_t(p[3])<<24;}
static void put(uint8_t *p,uint32_t v){memcpy(p,&v,4);}
static int32_t values[]={8700,1,1,1,4218000,3330,643000,3500000,4067000,4610000,597};
static void answer(HoujiBatteryManager &manager,int32_t value,uint32_t error=0) {
    assert(!sent.empty());auto request=sent.back();assert(request.size()==24);uint8_t reply[24]={};
    memcpy(reply,request.data(),12);put(reply+12,get(request.data()+16));put(reply+16,(uint32_t)value);put(reply+20,error);
    connection.client.receive(connection.context,reply,24);manager.service();
}
static void complete(HoujiBatteryManager &m) {while(m.bm.active){unsigned cursor=m.bm.cursor;assert(cursor<HoujiBmFields);answer(m,values[cursor]);}}
static void link(HoujiBatteryManager &m,bool up) {connection.client.state(connection.context,up);m.service();}
static uint64_t property(HoujiBatterySource *s,const char *k){return static_cast<OSNumber *>(s->registry.at(k))->value;}
int main() {
    HoujiBatteryManager m;assert(m.init() && m.activate());assert(!m.source);link(m,true);
    assert(sent.size()==2 && sent[0].size()==28 && sent[1].size()==24);
    for(unsigned i=0;i<4;i++){assert(!m.source);answer(m,values[i]);}
    complete(m);assert(m.source && m.source->registered);assert(property(m.source,"CurrentCapacity")==87);
    assert(property(m.source,"Temperature")==3330 && property(m.source,"Voltage")==4218);
    assert(!m.source->registry.count("Amperage") && !m.source->registry.count("TimeRemaining"));
    unsigned updates=m.source->updates;m.service();clockMs+=1000;m.service();assert(m.source->updates==updates);
    auto old=m.source;link(m,false);assert(!m.source && old->inactive && !old->registry.count("CurrentCapacity"));
    // A queued message from an old generation is discarded even when state
    // events coalesce before the work loop gets a chance to run.
    auto responsesBefore=m.bm.responses;
    connection.client.state(connection.context,1);uint8_t junk[24]={};connection.client.receive(connection.context,junk,24);
    connection.client.state(connection.context,0);connection.client.state(connection.context,1);m.service();
    assert(!m.count && m.bm.responses==responsesBefore && m.bm.cursor==0);complete(m);assert(m.source);
    clockMs+=5001;m.service();for(unsigned i=0;i<4;i++)answer(m,values[i]);
    assert(m.bm.cursor==HoujiBmVoltage);clockMs+=2001;m.service();assert(m.disabled&(1u<<HoujiBmVoltage));
    complete(m);assert(m.source && !m.source->registry.count("Voltage"));
    clockMs+=5001;m.service();for(unsigned i=0;i<4;i++)answer(m,values[i]);
    assert(m.bm.cursor==HoujiBmTemperature);complete(m);assert(m.source && !m.source->registry.count("Voltage"));
    // Essential timeout fails closed until transport reconnects; it never
    // repeatedly reissues the same property into an ambiguous old generation.
    clockMs+=5001;m.service();clockMs+=2001;m.service();assert(m.faulted && !m.source);
    auto requests=sent.size();clockMs+=100000;m.service();assert(sent.size()==requests);
    link(m,false);link(m,true);complete(m);assert(m.source && !m.faulted);
    clockMs+=16000;m.service();assert(!m.source); // Refresh does not renew an old sample.
    complete(m);assert(m.source);
    // Lost messages never overflow the inbox or produce an invented value.
    for(unsigned i=0;i<32;i++)connection.client.receive(connection.context,junk,24);
    assert(m.count==kRing && houji_battery_stats[10]>=16);m.service();assert(!m.count);
    link(m,false);refuseSend=true;link(m,true);assert(m.faulted && !m.source);
    puts("PASS: actual battery publisher freshness, retirement, generation changes, optional skips, timeouts, units, inbox bounds and send failure; API fixture only");
}
