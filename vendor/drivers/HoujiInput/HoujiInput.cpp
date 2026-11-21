/* HoujiInput - publish an IOHIDEventService so iOS has an input source at all.

Base line: the r591 kernel (04db0a97). This file subclasses Apple's prelinked
IOHIDEventService using the verbatim tag headers under vendor/hid-abi, so the
event path is Apple's real machinery and its user client
(IOHIDEventServiceUserClient, also prelinked) is what backboardd already knows
how to open. Nothing here re-implements IOHIDEvent or shadows an Apple class
name - that is the mistake the other line made.

Stages, all inert without their boot argument:
  houji-in=<mode>
    1  send a Consumer volume-up/down key pair on a timer. This is plumbing
       proof only: it shows the service, its user client and the event queue
       reach the UI (the volume HUD is the observable). It is NOT touch and it
       is NOT a real button.
    2  reserved for the real source: pmk8550 PON status over SPMI
       (arbiter cnfg 0x0c42d000 / core 0x0c400000, PON device 0x1300).
*/

#include <IOKit/IOService.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOTimerEventSource.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/device_root.h>
#include <pexpert/pexpert.h>
#include <kern/clock.h>
#include <libkern/OSAtomic.h>

#define KERNEL_PRIVATE 1
#include <IOKit/hid/IOHIDEventService.h>

#define HOJI_LOG(fmt, ...) IOLog("HOUJI-IN: " fmt "\n", ##__VA_ARGS__)

enum {
    kHoujiInOff        = 0,
    kHoujiInSynthKeys  = 1,
    kHoujiInSpmiKeys   = 2,
};

/* HID usages used by the synthetic stage. Page 0x0C is Consumer, 0xE9 volume
 * up and 0xEA volume down; the value is the press (1) / release (0) edge. */
enum {
    kHoujiPageConsumer = 0x0C,
    kHoujiUsageVolUp   = 0xE9,
    kHoujiUsageVolDown = 0xEA,
    kHoujiPageGen      = 0x01,
    kHoujiUsageKeyboard = 0x06,
};

class HoujiInput : public IOHIDEventService
{
    OSDeclareDefaultStructors(HoujiInput)

public:
    bool init(OSDictionary * table) override;
    bool start(IOService * provider) override;
    void stop(IOService * provider) override;

    /* Accept every client: the classes under backboardd are matched by the
     * service's primary usage, and refusing an open is what made an earlier
     * attempt look alive while nothing ever received an event. */
    bool handleOpen(IOService * client, IOOptionBits options, void * argument) override;

protected:
    UInt32 getPrimaryUsagePage() override { return kHoujiPageGen; }
    UInt32 getPrimaryUsage() override { return kHoujiUsageKeyboard; }

private:
    static void tickAction(OSObject * target, IOTimerEventSource * timer);
    void tick(IOTimerEventSource * timer);

    IOWorkLoop * fLoop = nullptr;
    IOTimerEventSource * fTimer = nullptr;
    uint32_t fMode = kHoujiInOff;
    uint32_t fPeriodMs = 5000;
    uint32_t fTicks = 0;
    uint32_t fOpens = 0;
    bool fVolumeUp = false;
};

OSDefineMetaClassAndStructors(HoujiInput, IOHIDEventService)

bool HoujiInput::init(OSDictionary * table)
{
    if (!IOHIDEventService::init(table))
        return false;

    uint32_t mode = 0;
    if (PE_parse_boot_argn("houji-in", &mode, sizeof(mode)))
        fMode = mode;
    HOJI_LOG("init mode=%u (0=off 1=synthetic consumer keys 2=spmi pons)", fMode);
    return true;
}

bool HoujiInput::start(IOService * provider)
{
    if (!IOHIDEventService::start(provider)) {
        HOJI_LOG("super start failed");
        return false;
    }

    /* These four properties are what the event driver and WindowServer read.
     * Built-In and DisplayIntegrated mark it as the panel's own digitizer-class
     * device; without them backboardd's digitizer match silently skips us. */
    OSNumber * page = OSNumber::withNumber(kHoujiPageGen, 32);
    OSNumber * usage = OSNumber::withNumber(kHoujiUsageKeyboard, 32);
    setProperty("Built-In", kOSBooleanTrue);
    setProperty("DisplayIntegrated", kOSBooleanTrue);
    if (page != nullptr && usage != nullptr) {
        setProperty("PrimaryUsagePage", page);
        setProperty("PrimaryUsage", usage);
    }
    /* setProperty retains; drop our own creation references. */
    if (page != nullptr) page->release();
    if (usage != nullptr) usage->release();
    registerService();

    if (fMode == kHoujiInOff) {
        HOJI_LOG("started, timer off (no houji-in argument)");
        return true;
    }

    fLoop = IOWorkLoop::workLoop();
    fTimer = IOTimerEventSource::timerEventSource(this,
              OSMemberFunctionCast(IOTimerEventSource::Action, this, &HoujiInput::tickAction));
    if (fLoop == nullptr || fTimer == nullptr ||
        fLoop->addEventSource(fTimer) != kIOReturnSuccess) {
        HOJI_LOG("work loop setup failed");
        if (fTimer != nullptr) fTimer->release();
        if (fLoop != nullptr) fLoop->release();
        fTimer = nullptr;
        fLoop = nullptr;
        return true;
    }
    fTimer->wakeAfter(fPeriodMs * 1000ULL * 1000ULL);
    HOJI_LOG("started mode=%u period=%ums", fMode, fPeriodMs);
    return true;
}

void HoujiInput::stop(IOService * provider)
{
    if (fTimer != nullptr && fLoop != nullptr)
        fLoop->removeEventSource(fTimer);
    if (fTimer != nullptr) fTimer->release();
    if (fLoop != nullptr) fLoop->release();
    fTimer = nullptr;
    fLoop = nullptr;
    IOHIDEventService::stop(provider);
}

bool HoujiInput::handleOpen(IOService * client, IOOptionBits options, void * argument)
{
    fOpens++;
    HOJI_LOG("open #%u accepted", fOpens);
    return IOHIDEventService::handleOpen(client, options, argument);
}

void HoujiInput::tickAction(OSObject * target, IOTimerEventSource * timer)
{
    HoujiInput * self = OSDynamicCast(HoujiInput, target);
    if (self != nullptr)
        self->tick(timer);
}

void HoujiInput::tick(IOTimerEventSource * timer)
{
    fTicks++;

    if (fMode == kHoujiInSynthKeys) {
        AbsoluteTime stamp;
        clock_get_uptime(&stamp);
        fVolumeUp = !fVolumeUp;
        /* press then release, as a real HID report pair; value 1 = down, 0 = up */
        dispatchKeyboardEvent(stamp, kHoujiPageConsumer,
                              fVolumeUp ? kHoujiUsageVolUp : kHoujiUsageVolDown, 1);
        clock_get_uptime(&stamp);
        dispatchKeyboardEvent(stamp, kHoujiPageConsumer,
                              fVolumeUp ? kHoujiUsageVolUp : kHoujiUsageVolDown, 0);
        HOJI_LOG("synthetic consumer key %s tick=%u opens=%u",
                 fVolumeUp ? "vol-up" : "vol-down", fTicks, fOpens);
    }

    timer->wakeAfter(fPeriodMs * 1000ULL * 1000ULL);
}
