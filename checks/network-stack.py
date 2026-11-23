#!/usr/bin/env python3
"""Check the actual service's failure/privilege/lifetime boundaries, not IOKit."""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
implementation = (ROOT / 'kernel/overlay/iokit/Kernel/arm/HoujiNetworkStack.cpp').read_text()
implementation = re.sub(r'^#include .+\n', '', implementation, flags=re.M)
fixture = r'''
#include <cassert>
#include <cstring>
#include <cstdint>
#include <cstdio>
using IOReturn=int;
using task_t=void *;
using UInt32=uint32_t;
constexpr int kIOReturnSuccess=0,kIOReturnUnsupported=1;
constexpr auto kIOUserClientClassKey="IOUserClientClass";
constexpr auto kIOClientPrivilegeAdministrator="administrator";
#define APPLE_KEXT_OVERRIDE override
#define OSDeclareDefaultStructors(type) public: type()=default;
#define OSDefineMetaClassAndStructors(type,parent)
#define OSDynamicCast(type,value) dynamic_cast<type *>(value)
#define IOLog(...) ((void)0)
#define NO_KEXTD 1
struct OSObject { virtual ~OSObject()=default; };
static bool startOK=true,propertyOK=true,privileged=true,initOK=true;
static unsigned published=0,terminations=0,initialized=0,propertyWrites=0;
struct IOService : OSObject {
 bool inactive=false;
 virtual bool start(IOService *) {return startOK;}
 bool setProperty(const char *key,const char *value) {
  assert(!strcmp(key,kIOUserClientClassKey));assert(!strcmp(value,"IONetworkStackUserClient"));
  ++propertyWrites;return propertyOK;
 }
 void setName(const char *name) {assert(!strcmp(name,"IONetworkStack"));}
 void registerService() {++published;}
 bool isInactive() {return inactive;}
 void terminate() {inactive=true;++terminations;}
 static IOService *getServiceRoot() {static IOService root;return &root;}
 unsigned getBusyState() {return 7;}
};
struct IOUserClient : IOService {
 virtual bool initWithTask(task_t,void *,UInt32) {++initialized;return initOK;}
 static IOReturn clientHasPrivilege(task_t task,const char *privilege) {
  assert(task && !strcmp(privilege,kIOClientPrivilegeAdministrator));return privileged?0:1;
 }
 virtual IOReturn clientClose() {return 99;}
 virtual IOReturn setProperties(OSObject *) {return 99;}
};
static void proc_selfname(char *,size_t) {}
'''
tests = r'''
int main() {
 IOService resources;
 IONetworkStack stack;
 startOK=false;assert(!stack.start(&resources));assert(published==0 && propertyWrites==0);
 startOK=true;propertyOK=false;assert(!stack.start(&resources));assert(published==0);
 propertyOK=true;assert(stack.start(&resources));assert(published==1);
 IONetworkStackUserClient client;
 auto task=reinterpret_cast<void *>(1);
 privileged=false;assert(!client.initWithTask(task,nullptr,0));assert(initialized==0);
 privileged=true;assert(!client.initWithTask(task,nullptr,1));assert(initialized==0);
 initOK=false;assert(!client.initWithTask(task,nullptr,0));
 initOK=true;assert(client.initWithTask(task,nullptr,0));
 assert(!client.start(&resources));
 startOK=false;assert(!client.start(&stack));
 startOK=true;assert(client.start(&stack));
 OSObject arbitraryRequest;
 assert(client.setProperties(nullptr)==kIOReturnUnsupported);
 assert(client.setProperties(&arbitraryRequest)==kIOReturnUnsupported);
 assert(published==1 && !stack.inactive);
 assert(client.clientClose()==kIOReturnSuccess && client.isInactive());
 assert(client.clientClose()==kIOReturnSuccess && terminations==1 && !stack.inactive);
 char snapshot[512];unsigned n=houji_network_stack_snapshot(snapshot,sizeof snapshot);
 assert(n==strlen(snapshot) && strstr(snapshot,"registered=1 opened=1 denied-type=1 denied-privilege=1 naming-requests=2 registry-busy=7 kextd-required=0"));
 for(unsigned capacity=1;capacity<sizeof snapshot;++capacity) {
  memset(snapshot,0xa5,sizeof snapshot);n=houji_network_stack_snapshot(snapshot,capacity);
  assert(n<capacity && !snapshot[n] && (unsigned char)snapshot[capacity]==0xa5);
 }
}
'''
# Verify this service is actually included and matched in the public XNU patch.
patch = (ROOT / 'kernel/patches/local.patch').read_text()
assert '+iokit/Kernel/arm/HoujiNetworkStack.cpp' in patch
assert "'IOClass'         = IONetworkStack;" in patch
assert "'IOMatchCategory' = IONetworkStack;" in patch
with tempfile.TemporaryDirectory(prefix='houji-network-stack-') as directory:
    source, binary = Path(directory) / 'check.cpp', Path(directory) / 'check'
    source.write_text(fixture + implementation + tests)
    subprocess.run(['clang++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-DARM64_BOARD_CONFIG_SWEET=1', '-fsanitize=address,undefined', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print('PASS: actual InterfaceNamer service privilege/failure boundaries, naming rejection and client close lifetime; no kernel or network emulation')
