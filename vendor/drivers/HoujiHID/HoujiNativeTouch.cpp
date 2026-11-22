#include "HoujiNativeTouch.h"
#include "OriginalHidDeviceABI.h"

#include <IOKit/IOBufferMemoryDescriptor.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOWorkLoop.h>
#include <libkern/c++/OSString.h>
#include <libkern/c++/OSSymbol.h>
#include <libkern/c++/OSMetaClass.h>

extern "C" void houji_native_touch_register_class();

namespace {

constexpr uint8_t kReportID = 3;
constexpr unsigned kContactBytes = 6;
constexpr unsigned kReportBytes = 2 + kContactBytes * kHoujiTouchContacts;

// Touch Screen application; each Finger reports Tip Switch, Confidence,
// Contact Identifier and 16-bit X/Y. The report ends with Contact Count.
#define HOUJI_FINGER_DESC                                                       \
    0x09, 0x22, 0xa1, 0x02, 0x09, 0x42, 0x15, 0x00, 0x25, 0x01, 0x75, 0x01,      \
    0x95, 0x01, 0x81, 0x02, 0x09, 0x47, 0x81, 0x02, 0x75, 0x06, 0x95, 0x01,      \
    0x81, 0x03, 0x09, 0x51, 0x75, 0x08, 0x95, 0x01, 0x15, 0x00, 0x26, 0xff,      \
    0x00, 0x81, 0x02, 0x05, 0x01, 0x09, 0x30, 0x15, 0x00, 0x26, 0xff, 0x7f,      \
    0x75, 0x10, 0x95, 0x01, 0x81, 0x02, 0x09, 0x31, 0x81, 0x02, 0x05, 0x0d, 0xc0,

constexpr uint8_t kTouchDescriptor[] = {
    0x05, 0x0d, 0x09, 0x04, 0xa1, 0x01, 0x85, kReportID,
    HOUJI_FINGER_DESC HOUJI_FINGER_DESC HOUJI_FINGER_DESC HOUJI_FINGER_DESC HOUJI_FINGER_DESC
    HOUJI_FINGER_DESC HOUJI_FINGER_DESC HOUJI_FINGER_DESC HOUJI_FINGER_DESC HOUJI_FINGER_DESC
    0x09, 0x54, 0x15, 0x00, 0x25, kHoujiTouchContacts, 0x75, 0x08, 0x95, 0x01, 0x81, 0x02, 0xc0,
};
#undef HOUJI_FINGER_DESC

uint16_t normalize(uint16_t raw, unsigned max)
{
    return (raw < max ? raw : max) * 32767u / max;
}

void writeContact(uint8_t *field, HoujiTouchContact contact, bool down)
{
    const uint16_t x = normalize(contact.x, 1199);
    const uint16_t y = normalize(contact.y, 2669);
    field[0] = down ? 3 : 2;
    field[1] = contact.identifier;
    field[2] = x;
    field[3] = x >> 8;
    field[4] = y;
    field[5] = y >> 8;
}

} // namespace

class HoujiNativeTouch : public IOHIDDevice {
    OSDeclareDefaultStructors(HoujiNativeTouch)

public:
    bool start(IOService *provider) override;
    void free() override;
    IOWorkLoop *getWorkLoop() const override;
    OSString *newTransportString() const override;
    OSString *newProductString() const override;
    IOReturn newReportDescriptor(IOMemoryDescriptor **) const override;
    void submitFrame(const HoujiTouchContact *contacts, unsigned count);

private:
    IOWorkLoop *loop = nullptr;
    HoujiTouchContact previous[kHoujiTouchContacts] = {};
    unsigned previousCount = 0;
    unsigned reportCount = 0;
};

OSDefineMetaClassAndStructors(HoujiNativeTouch, IOHIDDevice)

bool HoujiNativeTouch::start(IOService *provider)
{
    loop = IOWorkLoop::workLoop();
    return loop && setProperty("Built-In", true) &&
        setProperty("DisplayIntegrated", true) &&
        setProperty("DigitizerCollectionDispatch", true) &&
        setProperty("HIDDefaultBehavior", true) && IOHIDDevice::start(provider);
}

void HoujiNativeTouch::free()
{
    // The base frees its work loop reference and report sources before ours.
    IOWorkLoop *owned = loop;
    IOHIDDevice::free();
    OSSafeReleaseNULL(owned);
}

IOWorkLoop *HoujiNativeTouch::getWorkLoop() const { return loop; }

OSString *HoujiNativeTouch::newTransportString() const { return OSString::withCString("SPI"); }

OSString *HoujiNativeTouch::newProductString() const { return OSString::withCString("Houji Touchscreen"); }

IOReturn HoujiNativeTouch::newReportDescriptor(IOMemoryDescriptor **out) const
{
    if (!out) {
        return kIOReturnBadArgument;
    }
    *out = IOBufferMemoryDescriptor::withBytes(kTouchDescriptor, sizeof(kTouchDescriptor), kIODirectionNone);
    return *out ? kIOReturnSuccess : kIOReturnNoMemory;
}

void HoujiNativeTouch::submitFrame(const HoujiTouchContact *contacts, unsigned count)
{
    if (count > kHoujiTouchContacts || (count == 0 && previousCount == 0)) {
        return;
    }
    uint8_t report[kReportBytes] = {kReportID};
    unsigned slot = 0;
    unsigned active = 0;
    for (unsigned i = 0; i < count; ++i) {
        active |= 1u << (contacts[i].identifier & 0x0f);
        writeContact(report + 1 + kContactBytes * slot++, contacts[i], true);
    }
    for (unsigned i = 0; i < previousCount && slot < kHoujiTouchContacts; ++i) {
        if (!(active & (1u << (previous[i].identifier & 0x0f)))) {
            writeContact(report + 1 + kContactBytes * slot++, previous[i], false);
        }
    }
    report[kReportBytes - 1] = slot;
    IOBufferMemoryDescriptor *buffer = IOBufferMemoryDescriptor::withBytes(report, sizeof(report), kIODirectionNone);
    IOReturn status = buffer ? handleReport(buffer, 0, 0) : kIOReturnNoMemory;
    OSSafeReleaseNULL(buffer);
    if (++reportCount <= 8 || (status != kIOReturnSuccess && reportCount % 100 == 0)) {
        IOLog("HOUJI-NATIVEHID: report=%u active=%u slots=%u status=0x%x\n",
            reportCount, count, slot, status);
    }
    if (status == kIOReturnSuccess) {
        for (unsigned i = 0; i < count; ++i) {
            previous[i] = contacts[i];
        }
        previousCount = count;
    }
}

static HoujiNativeTouch *touchDevice;

extern "C" int houji_native_touch_start(IOService *provider)
{
    if (!provider) {
        return kIOReturnBadArgument;
    }
    if (touchDevice) {
        return kIOReturnSuccess;
    }
    const OSSymbol *deviceName = OSSymbol::withCString("IOHIDDevice");
    const OSMetaClass *base = deviceName ? OSMetaClass::getMetaClassWithName(deviceName) : nullptr;
    OSSafeReleaseNULL(deviceName);
    if (base != &IOHIDDevice::gMetaClass) {
        IOLog("HOUJI-NATIVEHID: original IOHIDDevice not loaded\n");
        return kIOReturnNotReady;
    }
    void *registration = OSMetaClass::preModLoad("com.apple.kernel");
    if (!registration) {
        return kIOReturnNoResources;
    }
    houji_native_touch_register_class();
    const OSReturn registered = OSMetaClass::postModLoad(registration);
    IOLog("HOUJI-NATIVEHID: metaclass registration status=0x%x\n", registered);
    if (registered != kOSReturnSuccess) {
        return registered;
    }
    auto device = OSTypeAlloc(HoujiNativeTouch);
    if (!device) {
        return kIOReturnNoMemory;
    }
    if (!device->init() || !device->attach(provider)) {
        device->release();
        return kIOReturnUnsupported;
    }
    if (!device->start(provider)) {
        device->detach(provider);
        device->release();
        return kIOReturnNotReady;
    }
    touchDevice = device;
    IOLog("HOUJI-NATIVEHID: IOHIDDevice started\n");
    return kIOReturnSuccess;
}

extern "C" void houji_native_touch_report(const uint8_t *frame, unsigned size)
{
    if (!touchDevice) {
        return;
    }
    HoujiTouchContact contacts[kHoujiTouchContacts] = {};
    unsigned count = 0;
    if (decodeHoujiTouchReport(frame, size, contacts, count)) {
        touchDevice->submitFrame(contacts, count);
    }
}

extern "C" void houji_native_touch_release()
{
    if (touchDevice) {
        touchDevice->submitFrame(nullptr, 0);
    }
}
