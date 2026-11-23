// SPDX-License-Identifier: BSD-2-Clause-Patent
// PMIC GLINK publisher. It never issues charger SET requests. Missing/stale
// readings withdraw the source instead of manufacturing an empty battery.
#include <IOKit/IOLib.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IOTimerEventSource.h>
#include <IOKit/IOInterruptEventSource.h>
#include <IOKit/pwr_mgt/IOPMPowerSource.h>
#include <libkern/c++/OSDictionary.h>
#include <libkern/c++/OSNumber.h>
#include <libkern/c++/OSSymbol.h>
#include <libkern/c++/OSBoolean.h>
#include <kern/clock.h>
#include "HoujiAdsp.h"
#include "HoujiBattmgr.h"
extern "C" {volatile int32_t houji_battery_stats[16];}
namespace {
uint64_t nowMs() {uint64_t ns=0;absolutetime_to_nanoseconds(mach_absolute_time(),&ns);return ns/1000000;}
constexpr unsigned kRing=16,kMessage=64;
}
class HoujiBatterySource:public IOPMPowerSource {
    OSDeclareDefaultStructors(HoujiBatterySource)
    void number(const char *key,int32_t value) {
        const OSSymbol *s=OSSymbol::withCString(key);OSNumber *n=OSNumber::withNumber((uint64_t)(uint32_t)value,32);
        if(s && n)setPSProperty(s,n);if(n)n->release();if(s)s->release();
    }
    void erase(const char *key) {
        if((properties && properties->getObject(key)) || getProperty(key)) {
            if(properties)properties->removeObject(key);removeProperty(key);settingsChangedSinceUpdate=true;
        }
    }
    void optional(const HoujiBattmgr &b,unsigned field,const char *key,int divisor) {
        if(b.valid&(1u<<field))number(key,b.value[field]/divisor);else erase(key);
    }
public:
    void apply(const HoujiBattmgr &b) {
        setBatteryInstalled(b.value[HoujiBmPresent]!=0);
        setExternalConnected(b.value[HoujiBmUsbOnline]!=0);
        setIsCharging(b.value[HoujiBmStatus]==1);
        setCurrentCapacity((unsigned)(b.value[HoujiBmCapacity]/100));setMaxCapacity(100);
        const OSSymbol *full=OSSymbol::withCString("FullyCharged");
        if(full){setPSProperty(full,b.value[HoujiBmStatus]==4?kOSBooleanTrue:kOSBooleanFalse);full->release();}
        optional(b,HoujiBmVoltage,"Voltage",1000);optional(b,HoujiBmTemperature,"Temperature",1);
        optional(b,HoujiBmCycles,"CycleCount",1);optional(b,HoujiBmCharge,"AppleRawCurrentCapacity",1000);
        optional(b,HoujiBmFull,"AppleRawMaxCapacity",1000);optional(b,HoujiBmFull,"NominalChargeCapacity",1000);
        optional(b,HoujiBmDesign,"DesignCapacity",1000);
        // No guessed current polarity, time remaining, battery health or adapter wattage.
        erase("Amperage");erase("InstantAmperage");erase("TimeRemaining");erase("ErrorCondition");
        updateStatus();
    }
    void invalidate() {
        const char *keys[]={"CurrentCapacity","MaxCapacity","Voltage","Temperature","CycleCount",
          "AppleRawCurrentCapacity","AppleRawMaxCapacity","NominalChargeCapacity","DesignCapacity",
          "ExternalConnected","ExternalChargeCapable","IsCharging","FullyCharged"};
        for(const char *key:keys)erase(key);
        OSSymbol *error=const_cast<OSSymbol *>(OSSymbol::withCString("Unavailable"));
        if(error){setErrorCondition(error);error->release();}updateStatus();
    }
};
OSDefineMetaClassAndStructors(HoujiBatterySource,IOPMPowerSource)

class HoujiBatteryManager:public OSObject {
    OSDeclareDefaultStructors(HoujiBatteryManager)
    IOWorkLoop *loop=nullptr;
    IOTimerEventSource *timer=nullptr;
    IOInterruptEventSource *inbox=nullptr;
    IOSimpleLock *lock=nullptr;
    HoujiAdspChannel *channel=nullptr;
    HoujiBatterySource *source=nullptr;
    HoujiBattmgr bm={};
    struct Packet {unsigned generation,length;uint8_t data[kMessage];};
    Packet ring[kRing];unsigned head=0,count=0,generation=0,handledGeneration=0;
    bool up=false,wasUp=false,faulted=false;
    unsigned disabled=0;
    uint64_t deadline=0,nextRefresh=0;
    static void state(void *ctx,int online) {
        auto self=static_cast<HoujiBatteryManager *>(ctx);
        IOSimpleLockLock(self->lock);self->up=online!=0;++self->generation;
        self->head=self->count=0;IOSimpleLockUnlock(self->lock);
        self->inbox->interruptOccurred(nullptr,nullptr,0);
    }
    static void receive(void *ctx,const uint8_t *data,uint32_t length) {
        auto self=static_cast<HoujiBatteryManager *>(ctx);
        IOSimpleLockLock(self->lock);
        if(self->up && length<=kMessage && self->count<kRing) {
            auto &packet=self->ring[(self->head+self->count)%kRing];
            packet.generation=self->generation;packet.length=length;memcpy(packet.data,data,length);++self->count;
        }else houji_battery_stats[10]++;
        IOSimpleLockUnlock(self->lock);self->inbox->interruptOccurred(nullptr,nullptr,0);
    }
    void withdraw() {
        if(!source)return;source->invalidate();
        if(source->terminate(kIOServiceRequired)){source->release();source=nullptr;}
        houji_battery_stats[0]=wasUp?3:2;
    }
    void publish(uint64_t now) {
        if(!houji_battmgr_fresh(&bm,now) || !wasUp || faulted){withdraw();return;}
        if(!source) {
            auto next=new HoujiBatterySource;
            if(!next)return;
            if(!next->init()){next->release();return;}
            IOService *platform=IOService::getPlatform();
            if(!platform || !next->attach(platform)){next->release();return;}
            if(!next->start(platform)){next->detach(platform);next->release();return;}
            next->apply(bm);next->registerService();source=next;
        }else source->apply(bm);
        houji_battery_stats[0]=4;houji_battery_stats[1]=bm.value[HoujiBmCapacity];
        houji_battery_stats[2]=bm.value[HoujiBmStatus];houji_battery_stats[3]=bm.value[HoujiBmUsbOnline];
        houji_battery_stats[4]=bm.valid;
    }
    void pump(uint64_t now) {
        if(!wasUp || faulted || bm.awaiting)return;
        while(bm.active && bm.cursor<HoujiBmFields && (disabled&(1u<<bm.cursor)))
            if(!houji_battmgr_skip_optional(&bm,now))break;
        if(!bm.active){publish(now);nextRefresh=now+5000;return;}
        uint8_t request[HOUJI_BM_REQUEST_BYTES];uint32_t size=houji_battmgr_request(&bm,request);
        if(!size)return;
        if(houji_adsp_send(channel,request,size)) {
            // Refused send and stale channel are not a successful sample.
            ++houji_battery_stats[11];faulted=true;houji_battmgr_disconnect(&bm);withdraw();return;
        }
        deadline=now+2000;
    }
    void service() {
        const uint64_t now=nowMs();unsigned gen;bool online;
        IOSimpleLockLock(lock);gen=generation;online=up;IOSimpleLockUnlock(lock);
        if(gen!=handledGeneration) {
            handledGeneration=gen;wasUp=online;faulted=false;disabled=0;
            houji_battmgr_disconnect(&bm);withdraw();
            if(online) {
                uint8_t subscribe[28];houji_battmgr_subscribe(subscribe);
                if(houji_adsp_send(channel,subscribe,sizeof(subscribe)))++houji_battery_stats[11];
                houji_battmgr_begin(&bm);pump(now);
            }
        }
        for(unsigned i=0;i<kRing;i++) {
            Packet packet={};bool have=false;
            IOSimpleLockLock(lock);
            if(count){packet=ring[head];head=(head+1)%kRing;--count;have=true;}
            IOSimpleLockUnlock(lock);if(!have)break;
            if(packet.generation!=handledGeneration || !wasUp || faulted)continue;
            int result=houji_battmgr_receive(&bm,packet.data,packet.length,now);
            if(result==HoujiBmNotification && !bm.active)houji_battmgr_begin(&bm);
            if(result){publish(now);pump(now);}
        }
        if(wasUp && !faulted && bm.awaiting && now>=deadline) {
            unsigned field=bm.cursor;houji_battmgr_timeout(&bm,now);
            if(HOUJI_BM_REQUIRED&(1u<<field)) {
                // No transaction ID: a late essential reply cannot be matched
                // safely to a new refresh. Require a new transport generation.
                faulted=true;houji_battmgr_disconnect(&bm);withdraw();
            }else {disabled|=1u<<field;pump(now);}
        }
        if(wasUp && !faulted && !bm.active && now>=nextRefresh){houji_battmgr_begin(&bm);pump(now);}
        publish(now);
        houji_battery_stats[5]=bm.responses;houji_battery_stats[6]=bm.errors;
        houji_battery_stats[7]=bm.timeouts;houji_battery_stats[8]=bm.cycles;
        houji_battery_stats[9]=bm.ignored;houji_battery_stats[12]=disabled;
        houji_battery_stats[13]=faulted;houji_battery_stats[14]=handledGeneration;
        timer->setTimeoutMS(1000);
    }
    static void input(OSObject *owner,IOInterruptEventSource *,int) {
        static_cast<HoujiBatteryManager *>(owner)->service();
    }
    static void tick(OSObject *owner,IOTimerEventSource *) {
        static_cast<HoujiBatteryManager *>(owner)->service();
    }
public:
    bool init() override {return OSObject::init();}
    bool activate() {
        lock=IOSimpleLockAlloc();loop=IOWorkLoop::workLoop();
        if(!lock || !loop)return false;
        inbox=IOInterruptEventSource::interruptEventSource(this,input);
        timer=IOTimerEventSource::timerEventSource(this,tick);
        if(!inbox || !timer || loop->addEventSource(inbox)!=kIOReturnSuccess ||
           loop->addEventSource(timer)!=kIOReturnSuccess)return false;
        inbox->enable();houji_battmgr_init(&bm);
        static const HoujiAdspClient client={state,receive};
        channel=houji_adsp_channel("PMIC_RTR_ADSP_APPS",256,8,0,&client,this);
        if(!channel)return false;
        houji_battery_stats[0]=2;timer->setTimeoutMS(1000);return true;
    }
};
OSDefineMetaClassAndStructors(HoujiBatteryManager,OSObject)
extern "C" void houji_battery_start(void) {
    static HoujiBatteryManager *manager=nullptr;if(manager)return;
    manager=new HoujiBatteryManager;
    // Retain once initialized: callbacks registered with transport outlive the
    // startup function. Failure is bounded and reported; no source is published.
    if(!manager || !manager->init() || !manager->activate())houji_battery_stats[0]=-1;
}
