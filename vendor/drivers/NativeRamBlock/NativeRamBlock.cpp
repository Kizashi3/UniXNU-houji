#include <IOKit/IOLib.h>
#include <IOKit/IORegistryEntry.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/storage/IOBlockStorageDevice.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSDictionary.h>
#include <machine/machine_routines.h>

#define super IOBlockStorageDevice

class NativeRamBlock : public IOBlockStorageDevice {
    OSDeclareDefaultStructors(NativeRamBlock)

    uint8_t *memory = nullptr;
    uint64_t capacity = 0;
    IOLock *gate = nullptr;
    bool online = false;

public:
    bool start(IOService *provider) override;
    void stop(IOService *provider) override;
    void free() override;

    IOReturn doEjectMedia() override { return kIOReturnUnsupported; }
    IOReturn doFormatMedia(UInt64) override { return kIOReturnUnsupported; }
    UInt32 doGetFormatCapacities(UInt64 *, UInt32) const override { return 0; }
    char *getVendorString() override { return const_cast<char *>("UniXNU"); }
    char *getProductString() override { return const_cast<char *>("Volatile RAM block"); }
    char *getRevisionString() override { return const_cast<char *>("1.0"); }
    char *getAdditionalDeviceInfoString() override { return const_cast<char *>("ram-backed Data volume"); }
    IOReturn reportBlockSize(UInt64 *value) override { *value = 512; return kIOReturnSuccess; }
    IOReturn reportEjectability(bool *value) override { *value = false; return kIOReturnSuccess; }
    IOReturn reportMaxValidBlock(UInt64 *value) override { *value = capacity ? capacity - 1 : 0; return kIOReturnSuccess; }
    IOReturn reportMediaState(bool *present, bool *changed) override {
        if (present) *present = online;
        if (changed) *changed = false;
        return kIOReturnSuccess;
    }
    IOReturn reportRemovability(bool *value) override { *value = false; return kIOReturnSuccess; }
    IOReturn reportWriteProtection(bool *value) override { *value = false; return kIOReturnSuccess; }
    IOReturn doSynchronizeCache() override { return kIOReturnSuccess; }
    IOReturn doSynchronize(UInt64, UInt64, IOOptionBits) override { return kIOReturnSuccess; }
    IOReturn getWriteCacheState(bool *value) override { *value = false; return kIOReturnSuccess; }
    IOReturn setWriteCacheState(bool) override { return kIOReturnUnsupported; }
    IOReturn doAsyncReadWrite(IOMemoryDescriptor *buffer, UInt64 block, UInt64 nblks,
                              IOStorageAttributes *attributes, IOStorageCompletion *completion) override;
};

OSDefineMetaClassAndStructors(NativeRamBlock, IOBlockStorageDevice)

bool NativeRamBlock::start(IOService *provider)
{
    if (!IOBlockStorageDevice::start(provider)) return false;

    IORegistryEntry *map = IORegistryEntry::fromPath("/chosen/memory-map", gIODTPlane);
    if (!map) { IOLog("NativeRamBlock: no /chosen/memory-map\n"); return false; }
    OSData *window = OSDynamicCast(OSData, map->getProperty("houji-data"));
    map->release();
    if (!window || window->getLength() < 16) { IOLog("NativeRamBlock: no houji-data window\n"); return false; }
    const uint64_t *fields = reinterpret_cast<const uint64_t *>(window->getBytesNoCopy());
    uint64_t physical = fields[0], bytes = fields[1];
    if (!physical || !bytes || bytes < 512) { IOLog("NativeRamBlock: bad window\n"); return false; }

    memory = reinterpret_cast<uint8_t *>(ml_static_ptovirt(physical));
    gate = IOLockAlloc();
    if (!memory || !gate) { IOLog("NativeRamBlock: map/lock failed\n"); return false; }
    capacity = bytes / 512;
    online = true;
    IOLog("NativeRamBlock: online phys=0x%llx bytes=%llu blocks=%llu\n",
          (unsigned long long)physical, (unsigned long long)bytes, (unsigned long long)capacity);
    registerService();
    return true;
}

void NativeRamBlock::stop(IOService *provider)
{
    if (gate) IOLockLock(gate);
    online = false;
    if (gate) IOLockUnlock(gate);
    IOBlockStorageDevice::stop(provider);
}

void NativeRamBlock::free()
{
    if (gate) { IOLockFree(gate); gate = nullptr; }
    memory = nullptr;
    super::free();
}

IOReturn NativeRamBlock::doAsyncReadWrite(IOMemoryDescriptor *buffer, UInt64 block, UInt64 nblks,
    IOStorageAttributes *, IOStorageCompletion *completion)
{
    if (!buffer || !completion || !completion->action || !nblks || block >= capacity ||
        nblks > capacity - block || buffer->getLength() < nblks * 512 ||
        (buffer->getDirection() != kIODirectionIn && buffer->getDirection() != kIODirectionOut))
        return kIOReturnBadArgument;
    if (!gate) return kIOReturnNotReady;

    const uint64_t bytes = nblks * 512;
    const uint64_t offset = block * 512;
    IOLockLock(gate);
    if (!online) { IOLockUnlock(gate); return kIOReturnNotReady; }
    UInt64 done;
    if (buffer->getDirection() == kIODirectionIn)
        done = buffer->writeBytes(0, memory + offset, bytes);
    else
        done = buffer->readBytes(0, memory + offset, bytes);
    IOLockUnlock(gate);

    IOReturn status = (done == bytes) ? kIOReturnSuccess : kIOReturnIOError;
    completion->action(completion->target, completion->parameter, status, done);
    return kIOReturnSuccess;
}