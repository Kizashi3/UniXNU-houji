// SPDX-License-Identifier: APSL-2.0
// IONetworkStack compatibility based on ios-apollo patch 0129, which credits
// HackiOS MiniIONetworkStack. See sources.lock.json for the pinned reference.
//
// configd's InterfaceNamer waits for this service before publishing registry
// quiescence. SystemConfiguration interface enumeration (including Settings'
// About page) waits for that notification. This port has no IONetworkInterface
// drivers to name yet. Expose the service/open contract, refuse naming requests,
// and leave registry quiet/busy decisions to IOKit and configd. No radio, MAC
// address, interface or successful naming result is fabricated here.
#include <IOKit/IOLib.h>
#include <IOKit/IOKitKeys.h>
#include <IOKit/IOService.h>
#include <IOKit/IOUserClient.h>
#include <sys/proc.h>

#if defined(ARM64_BOARD_CONFIG_SWEET)
static unsigned gHoujiNetworkRegistered, gHoujiNetworkOpened, gHoujiNetworkDeniedType, gHoujiNetworkDeniedPrivilege, gHoujiNetworkNamingRequests;
extern "C" unsigned houji_network_stack_snapshot(char *out, unsigned capacity);
extern "C" unsigned houji_network_stack_snapshot(char *out, unsigned capacity) {
    if (!out || !capacity) return 0;
    IOService *root = IOService::getServiceRoot();
    int bytes = snprintf(out, capacity,
        "HOUJI NETWORK SNAPSHOT: registered=%u opened=%u denied-type=%u denied-privilege=%u naming-requests=%u registry-busy=%u kextd-required=%u; service compatibility, no radio\n",
        __atomic_load_n(&gHoujiNetworkRegistered, __ATOMIC_RELAXED), __atomic_load_n(&gHoujiNetworkOpened, __ATOMIC_RELAXED),
        __atomic_load_n(&gHoujiNetworkDeniedType, __ATOMIC_RELAXED), __atomic_load_n(&gHoujiNetworkDeniedPrivilege, __ATOMIC_RELAXED),
        __atomic_load_n(&gHoujiNetworkNamingRequests, __ATOMIC_RELAXED), root ? (unsigned)root->getBusyState() : ~0U,
        (unsigned)!NO_KEXTD);
    return bytes <= 0 ? 0 : (unsigned)bytes < capacity ? (unsigned)bytes : capacity - 1;
}
class IONetworkStack : public IOService {
    OSDeclareDefaultStructors(IONetworkStack);
public:
    bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
};
OSDefineMetaClassAndStructors(IONetworkStack, IOService);

bool IONetworkStack::start(IOService *provider) {
    if (!IOService::start(provider)) return false;
    if (!setProperty(kIOUserClientClassKey, "IONetworkStackUserClient")) return false;
    setName("IONetworkStack");
    registerService();
    __atomic_store_n(&gHoujiNetworkRegistered, 1, __ATOMIC_RELAXED);
    IOLog("HOUJI NETWORK: interface-namer service registered; radio unavailable\n");
    return true;
}

class IONetworkStackUserClient : public IOUserClient {
    OSDeclareDefaultStructors(IONetworkStackUserClient);
public:
    bool initWithTask(task_t owningTask, void *securityID, UInt32 type) APPLE_KEXT_OVERRIDE;
    bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
    IOReturn clientClose(void) APPLE_KEXT_OVERRIDE;
    IOReturn setProperties(OSObject *properties) APPLE_KEXT_OVERRIDE;
};
OSDefineMetaClassAndStructors(IONetworkStackUserClient, IOUserClient);

bool IONetworkStackUserClient::initWithTask(task_t owningTask, void *securityID, UInt32 type) {
    if (type != 0) {
        __atomic_fetch_add(&gHoujiNetworkDeniedType, 1, __ATOMIC_RELAXED);
        return false;
    }
    if (clientHasPrivilege(owningTask, kIOClientPrivilegeAdministrator) != kIOReturnSuccess) {
        __atomic_fetch_add(&gHoujiNetworkDeniedPrivilege, 1, __ATOMIC_RELAXED);
        return false;
    }
    return IOUserClient::initWithTask(owningTask, securityID, type);
}

bool IONetworkStackUserClient::start(IOService *provider) {
    if (!OSDynamicCast(IONetworkStack, provider) || !IOUserClient::start(provider)) return false;
    __atomic_fetch_add(&gHoujiNetworkOpened, 1, __ATOMIC_RELAXED);
    char name[32] = "?";
    proc_selfname(name, sizeof(name));
    IOLog("HOUJI NETWORK: interface-namer client opened by %s; registry busy=%u\n",
          name, (unsigned)IOService::getServiceRoot()->getBusyState());
    return true;
}

IOReturn IONetworkStackUserClient::clientClose(void) {
    if (!isInactive()) terminate();
    return kIOReturnSuccess;
}

IOReturn IONetworkStackUserClient::setProperties(OSObject *properties) {
    (void)properties;
    __atomic_fetch_add(&gHoujiNetworkNamingRequests, 1, __ATOMIC_RELAXED);
    return kIOReturnUnsupported;
}
#endif
