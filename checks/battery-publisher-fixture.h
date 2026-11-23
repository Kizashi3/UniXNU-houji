// SPDX-License-Identifier: BSD-2-Clause-Patent
// Minimal service/event API for testing the actual publisher's message and
// freshness logic. Does not emulate IOKit, hardware, or powerd behavior.
#pragma once
#include <cstdint>
#include <cstring>
#include <map>
#include <mutex>
#include <string>
#include <vector>
#include <cassert>
#include <cstdio>
#include "HoujiAdsp.h"
struct OSObject {virtual ~OSObject()=default;virtual bool isEqualTo(const OSObject *other) const{return this==other;}void release() const {}void retain() const {}protected:virtual bool init(){return true;}};
struct OSSymbol:OSObject {std::string text;static OSSymbol *withCString(const char *s){auto r=new OSSymbol;r->text=s;return r;}};
struct OSNumber:OSObject {uint64_t value;bool isEqualTo(const OSObject *o) const override {auto n=dynamic_cast<const OSNumber *>(o);return n && n->value==value;}static OSNumber *withNumber(uint64_t n,unsigned){auto r=new OSNumber;r->value=n;return r;}};
struct OSBoolean:OSObject {bool value;explicit OSBoolean(bool v):value(v){}};
static OSBoolean yes(true),no(false);static OSBoolean *kOSBooleanTrue=&yes,*kOSBooleanFalse=&no;
struct OSDictionary:OSObject {std::map<std::string,OSObject *> values;OSObject *getObject(const char *k){auto i=values.find(k);return i==values.end()?nullptr:i->second;}void removeObject(const char *k){values.erase(k);}};
struct IOService:OSObject {
    bool init() override {return OSObject::init();}
    bool registered=false,inactive=false;std::map<std::string,OSObject *> registry;
    static IOService *getPlatform(){static IOService p;return &p;}
    bool attach(IOService *){return true;}bool start(IOService *){return true;}void detach(IOService *){}
    void registerService(){registered=true;}bool terminate(unsigned){inactive=true;registered=false;return true;}
    void removeProperty(const char *key){registry.erase(key);}
    OSObject *getProperty(const char *key){auto i=registry.find(key);return i==registry.end()?nullptr:i->second;}
};
struct IOPMPowerSource:IOService {
    OSDictionary storage;OSDictionary *properties=&storage;bool settingsChangedSinceUpdate=false;unsigned updates=0;
    void setPSProperty(const OSSymbol *s,OSObject *v){auto old=properties->getObject(s->text.c_str());if(!old || !v->isEqualTo(old))settingsChangedSinceUpdate=true;properties->values[s->text]=v;}
    void flag(const char *k,bool v){auto s=OSSymbol::withCString(k);setPSProperty(s,v?kOSBooleanTrue:kOSBooleanFalse);}
    void number(const char *k,unsigned v){auto s=OSSymbol::withCString(k);setPSProperty(s,OSNumber::withNumber(v,32));}
    void setBatteryInstalled(bool v){flag("BatteryInstalled",v);}void setExternalConnected(bool v){flag("ExternalConnected",v);}
    void setIsCharging(bool v){flag("IsCharging",v);}void setCurrentCapacity(unsigned v){number("CurrentCapacity",v);}
    void setMaxCapacity(unsigned v){number("MaxCapacity",v);}void setErrorCondition(OSSymbol *v){setPSProperty(OSSymbol::withCString("ErrorCondition"),v);}
    void updateStatus(){if(settingsChangedSinceUpdate){++updates;registry=properties->values;settingsChangedSinceUpdate=false;}}
};
struct IOInterruptEventSource:OSObject {
    using Action=void(*)(OSObject *,IOInterruptEventSource *,int);
    static IOInterruptEventSource *interruptEventSource(OSObject *,Action){return new IOInterruptEventSource;}
    void interruptOccurred(void *,void *,int){}void enable(){}
};
struct IOTimerEventSource:OSObject {
    using Action=void(*)(OSObject *,IOTimerEventSource *);
    static IOTimerEventSource *timerEventSource(OSObject *,Action){return new IOTimerEventSource;}
    void setTimeoutMS(unsigned){}
};
struct IOWorkLoop:OSObject {static IOWorkLoop *workLoop(){return new IOWorkLoop;}int addEventSource(OSObject *){return 0;}};
using IOSimpleLock=std::mutex;
static IOSimpleLock *IOSimpleLockAlloc(){return new IOSimpleLock;}
static void IOSimpleLockLock(IOSimpleLock *m){m->lock();}static void IOSimpleLockUnlock(IOSimpleLock *m){m->unlock();}
constexpr int kIOReturnSuccess=0;constexpr unsigned kIOServiceRequired=1;
static uint64_t clockMs=100;
static uint64_t mach_absolute_time(){return clockMs*1000000;}
static void absolutetime_to_nanoseconds(uint64_t ticks,uint64_t *ns){*ns=ticks;}
#define OSDeclareDefaultStructors(x)
#define OSDefineMetaClassAndStructors(x,y)
struct HoujiAdspChannel {HoujiAdspClient client;void *context;};
static HoujiAdspChannel connection;
static std::vector<std::vector<uint8_t>> sent;
static bool refuseSend=false;
extern "C" HoujiAdspChannel *houji_adsp_channel(const char *name,uint32_t size,uint32_t count,int initiator,const HoujiAdspClient *client,void *context) {
    assert(!strcmp(name,"PMIC_RTR_ADSP_APPS") && size==256 && count==8 && !initiator);
    connection={*client,context};return &connection;
}
extern "C" int houji_adsp_send(HoujiAdspChannel *,const void *data,uint32_t bytes) {
    if(refuseSend)return -1;const auto p=static_cast<const uint8_t *>(data);sent.emplace_back(p,p+bytes);return 0;
}
