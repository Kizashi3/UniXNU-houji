// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "OriginalHoujiLegacyABI.h"
#include "HoujiLegacyQueue.h"
#include "HoujiLegacyPixels.h"
#include "HoujiLegacyRequest.h"
#include "HoujiLegacySwapRequest.h"
#include <IOKit/IOLib.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/IOTimerEventSource.h>
#include <IOKit/IOUserClient.h>
#include <kern/task.h>
#include <libkern/c++/OSData.h>
#include <kern/clock.h>
#include <mach/mach_time.h>
#include <libkern/c++/OSKext.h>
#include <libkern/c++/OSMetaClass.h>
#include <libkern/c++/OSSymbol.h>
#include <pexpert/pexpert.h>

extern "C" void houji_legacy_initialize_class(void);
extern "C" void houji_legacy_bootstrap_checkpoint(void);
extern "C" void houji_fb_set_legacy_checkpoint(void (*)(void));
extern "C" void houji_fb_set_legacy_publisher(bool (*)(IOService *));
extern "C" void houji_legacy_vsync_notify(void *, uint64_t, uint64_t, uint64_t);
extern "C" uint64_t mach_continuous_time(void);
extern "C" void proc_selfname(char *buf, int size);
extern "C" IOMemoryDescriptor *houji_legacy_surface_descriptor(OSObject *);
extern "C" uint32_t houji_legacy_surface_width(OSObject *);
extern "C" uint32_t houji_legacy_surface_height(OSObject *);
extern "C" uint32_t houji_legacy_surface_stride(OSObject *);
extern "C" uint32_t houji_legacy_surface_offset(OSObject *);
extern "C" uint32_t houji_legacy_surface_allocation(OSObject *);
extern "C" uint32_t houji_legacy_surface_format(OSObject *);
extern "C" uint32_t houji_legacy_surface_planes(OSObject *);
static const char *houjiProbeStage = "not-inspected";
static int houjiDbgFamilyLoaded;
static const void *houjiDbgBase;
static const void *houjiDbgFb;
static const void *houjiDbgClient;
static const char *houjiDbgBaseOwner = "";

// The swap request names a surface by identifier. This XNU has no private
// lookup symbol bound, so walk the published IOSurface services and match the
// identifier property instead; every surface the compositor may hand us is one
// of those services. Returns a retained reference.
static OSObject *houjiSurfaceById(uint32_t identifier, uint32_t *found)
{
    if (identifier == 0 || found == nullptr)
        return nullptr;
    OSDictionary *matching = IOService::serviceMatching("IOSurface");
    if (matching == nullptr)
        return nullptr;
    OSIterator *services = IOService::getMatchingServices(matching);
    matching->release();
    if (services == nullptr)
        return nullptr;
    OSObject *result = nullptr;
    while (OSObject *entry = services->getNextObject()) {
        IOService *surface = OSDynamicCast(IOService, entry);
        if (surface == nullptr)
            continue;
        OSObject *property = surface->getProperty("IOSurfaceID");
        uint32_t value = 0;
        bool known = false;
        if (auto *number = OSDynamicCast(OSNumber, property)) {
            value = number->unsigned32BitValue();
            known = true;
        } else if (auto *data = OSDynamicCast(OSData, property)) {
            if (data->getLength() >= sizeof(value)) {
                __builtin_memcpy(&value, data->getBytesNoCopy(), sizeof(value));
                known = true;
            }
        }
        if (known && value == identifier) {
            surface->retain();
            result = surface;
            *found = value;
            break;
        }
    }
    services->release();
    return result;
}

class NativeHoujiLegacyDisplay;
class HoujiLegacyClient;

// Our own user client (boot arg houji-legacy-ownclient=1). Apple's legacy client answers
// from hardware state we do not have, so the compositor's request never reaches this
// driver at all and the boot log shows no selector traffic. This client instead records
// every index userspace sends and answers with the shape 20H392's own framework
// instructions describe, so one device round yields the complete selector map.
class HoujiLegacyClient final : public IOUserClient {
    OSDeclareDefaultStructors(HoujiLegacyClient)
    NativeHoujiLegacyDisplay *display = nullptr;
    task_t owner = TASK_NULL;
    bool opened = false;
    uint32_t calls = 0;
    uint32_t portRegistrations = 0;
    IOUserClient *nativeClient = nullptr;
    IOWorkLoop *notificationLoop = nullptr;
    IOTimerEventSource *notificationTimer = nullptr;
    IOLock *notificationLock = nullptr;
    mach_port_t notificationPorts[16] = {};
    uint64_t notificationCallbacks[16] = {};
    uint64_t notificationRefcons[16] = {};
    uint64_t notificationCount = 0;
    uint64_t notificationPeriod = 0;
    bool closing = false;
    uint64_t swapSequence = 0;
    uint32_t swapDumps = 0;
    static void notificationTick(OSObject *, IOTimerEventSource *);
    void shutdownNotifications();

public:
    bool initWithTask(task_t owningTask, void *securityID, UInt32 type,
                      OSDictionary *properties) override;
    bool start(IOService *provider) override;
    void stop(IOService *provider) override;
    void free() override;
    IOReturn clientClose() override;
    IOReturn externalMethod(uint32_t selector, IOExternalMethodArguments *arguments,
                            IOExternalMethodDispatch *dispatch, OSObject *target,
                            void *reference) override;
    IOReturn registerNotificationPort(mach_port_t port, UInt32 type,
                                      io_user_reference_t refCon) override;
};

class NativeHoujiLegacyDisplay : public IOMobileFramebufferLegacy {
    OSDeclareDefaultStructors(NativeHoujiLegacyDisplay)
    friend class HoujiLegacyClient;
    IOMemoryMap *scanout = nullptr;
    IOTimerEventSource *timer = nullptr;
    uint64_t period = 0;
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t rowBytes = 0;
    bool copying = false;
    unsigned presented = 0;
    uint32_t recordQueries = 0;
    uint32_t backendQueries = 0;
    uint32_t validationCalls = 0;
    uint32_t validationAccepted = 0;
    uint32_t dimensionCalls = 0;
    uint32_t refreshCalls = 0;
    uint32_t completionCalls = 0;
    unsigned rejectedCopies = 0;
    IOReturn lastRecordStatus = kIOReturnNotReady;
    bool diagnostics = false;
    uint64_t nextSummary = 0;
    uint32_t selftest = 0;
    uint32_t selftestFrames = 0;
    void *shadow = nullptr;
    uint64_t shadowBytes = 0;
    uint32_t syntheticFrames = 0;
    uint32_t readbackFailures = 0;
    bool realFrame = false;

    // Paint the producer-side picture. This is the same buffer shape an IOSurface
    // hands the swap path: width*4 rows inside a stride, BGRA. Keeping the drawing
    // here lets presentShadow() exercise the real copy routine without a surface.
    bool paintShadow()
    {
        if (shadow == nullptr || shadowBytes < static_cast<uint64_t>(rowBytes) * height)
            return false;
        auto base = static_cast<unsigned char *>(shadow);
        const uint32_t frame = syntheticFrames;
        for (uint32_t y = 0; y < height; ++y) {
            auto row = reinterpret_cast<uint32_t *>(base + static_cast<uint64_t>(y) * rowBytes);
            const uint32_t shade = static_cast<uint32_t>(
                (static_cast<uint64_t>(y) * 255) / (height ? height : 1));
            for (uint32_t x = 0; x < width; ++x) {
                const uint32_t index = static_cast<uint32_t>((static_cast<uint64_t>(x) * 8) / width);
                const uint32_t channel = 0xff000000U | (shade << 16) | ((index & 3U) * 0x40U);
                row[x] = channel;
            }
        }
        const uint32_t bandHeight = height / 10 ? height / 10 : 1;
        const uint32_t bandY = static_cast<uint32_t>(
            (static_cast<uint64_t>(frame) * bandHeight * 3) % (height ? height : 1));
        for (uint32_t y = bandY; y < bandY + bandHeight && y < height; ++y) {
            auto row = reinterpret_cast<uint32_t *>(base + static_cast<uint64_t>(y) * rowBytes);
            for (uint32_t x = 0; x < width; ++x)
                row[x] = 0xffffffffU;
        }
        return true;
    }

    // The swap pixel step, unchanged: source stride -> scanout stride, bounds
    // checked by the same helpers the real path uses.
    bool presentShadow()
    {
        if (scanout == nullptr || !paintShadow())
            return false;
        const uint64_t bytes = scanout->getLength();
        const bool copied = HoujiLegacy20H392::copyBgra(
            reinterpret_cast<volatile void *>(scanout->getVirtualAddress()), bytes, rowBytes,
            shadow, shadowBytes, 0, rowBytes, width, height);
        if (!copied)
            return false;
        __asm__ volatile("dsb sy" ::: "memory");
        __asm__ volatile("dsb sy" ::: "memory");
        // A store that never left the cache would look identical in the source
        // buffer; read the scanout back and compare sample pixels.
        auto readback = reinterpret_cast<volatile uint32_t *>(scanout->getVirtualAddress());
        auto source = static_cast<const unsigned char *>(shadow);
        uint32_t mismatched = 0;
        for (uint32_t y = 0; y < height; y += 97) {
            const auto row = reinterpret_cast<const uint32_t *>(source + static_cast<uint64_t>(y) * rowBytes);
            for (uint32_t x = 0; x < width; x += 151) {
                const uint32_t stored = readback[(static_cast<uint64_t>(y) * rowBytes) / 4 + x];
                if (stored != row[x])
                    mismatched++;
            }
        }
        syntheticFrames++;
        presented++;
        if (presented <= 8)
            IOLog("HOUJI-LEGACY: stage=cpu-present frame=%u synthetic=1 shadow=%llu verify=%s\n",
                presented, (unsigned long long)shadowBytes, mismatched == 0 ? "ok" : "mismatch");
        if (mismatched != 0 && readbackFailures++ < 8)
            IOLog("HOUJI-LEGACY: stage=cpu-present-readback mismatched=%u\n", mismatched);
        return true;
    }

    // CPU-only bring-up painter. This XNU never instantiates a GPU accelerator, so no
    // compositor produces a frame and the scanout stays dark. Paint a flat color-bar
    // test image (with a moving white band) directly into the GOP framebuffer so the
    // panel lights up independently of the display pipeline. It yields the moment a
    // real swap appears (presented>0 or a pending request).
    void paintSelfTest()
    {
        if (scanout == nullptr)
            return;
        const uint64_t bytes = scanout->getLength();
        if (!HoujiLegacy20H392::pixelExtent(bytes, rowBytes, width, height))
            return;
        volatile unsigned char *base =
            reinterpret_cast<volatile unsigned char *>(scanout->getVirtualAddress());
        static const uint32_t bars[8] = {
            0xffffffffU, 0xffffff00U, 0xff00ffffU, 0xff00ff00U,
            0xffff00ffU, 0xffff0000U, 0xff0000ffU, 0xff000000U};
        const uint32_t frame = selftestFrames;
        for (uint32_t x = 0; x < width; ++x) {
            uint32_t index = static_cast<uint32_t>((static_cast<uint64_t>(x) * 8) / width);
            if (index > 7)
                index = 7;
            const uint32_t color = bars[index];
            for (uint32_t y = 0; y < height; ++y)
                *reinterpret_cast<volatile uint32_t *>(
                    base + static_cast<uint64_t>(y) * rowBytes + static_cast<uint64_t>(x) * 4) = color;
        }
        uint32_t bandHeight = height / 12;
        if (bandHeight == 0)
            bandHeight = 1;
        const uint32_t bandY = static_cast<uint32_t>(
            (static_cast<uint64_t>(frame) * bandHeight * 2) % height);
        for (uint32_t y = bandY; y < bandY + bandHeight && y < height; ++y)
            for (uint32_t x = 0; x < width; ++x)
                *reinterpret_cast<volatile uint32_t *>(
                    base + static_cast<uint64_t>(y) * rowBytes + static_cast<uint64_t>(x) * 4) = 0xffffffffU;
        __asm__ volatile("dsb sy" ::: "memory");
    }

    static void vsyncFired(OSObject *owner, IOTimerEventSource *)
    {
        auto display = static_cast<NativeHoujiLegacyDisplay *>(owner);
        const void *head = nullptr;
        __builtin_memcpy(&head, reinterpret_cast<unsigned char *>(display) + 4992, sizeof(head));
        if (head != nullptr)
            houji_legacy_vsync_notify(display, mach_absolute_time(), mach_continuous_time(), display->period);
        display->kickSwapQueue();
        // selftestFrames counts timer ticks; the presented counter would only move on
        // success, so gating on it would latch the very first frame forever.
        if (display->selftest)
            display->selftestFrames++;
        if (display->selftest && !display->realFrame &&
            (display->selftestFrames % 30) == 0 &&
            HoujiLegacy20H392::loadPointer(display, HoujiLegacy20H392::pendingHead) == nullptr) {
            if (display->selftest >= 2) {
                if (!display->presentShadow())
                    display->paintSelfTest();
            } else {
                display->paintSelfTest();
            }
        }
        const uint64_t now = mach_absolute_time();
        if (display->diagnostics && now >= display->nextSummary) {
            display->nextSummary = now + display->period * 300;
            const uint32_t dimensions = __atomic_load_n(&display->dimensionCalls, __ATOMIC_RELAXED);
            const uint32_t refreshes = __atomic_load_n(&display->refreshCalls, __ATOMIC_RELAXED);
            const uint32_t completions = __atomic_load_n(&display->completionCalls, __ATOMIC_RELAXED);
            IOLog("HOUJI-LEGACY: stage=summary publish-stage=%s mapped=%ux%u stride=%u refresh=60 record27=%u record27-rc=%#x backend212=%u validate=%u accepted=%u copy-rejected=%u frames=%u synthetic=%u dims=%u refreshes=%u completions=%u canvas=%u current=%d pending=%d submission=%d\n",
                houjiProbeStage, display->width, display->height, display->rowBytes,
                __atomic_load_n(&display->recordQueries, __ATOMIC_RELAXED),
                __atomic_load_n(&display->lastRecordStatus, __ATOMIC_RELAXED),
                __atomic_load_n(&display->backendQueries, __ATOMIC_RELAXED),
                __atomic_load_n(&display->validationCalls, __ATOMIC_RELAXED),
                __atomic_load_n(&display->validationAccepted, __ATOMIC_RELAXED),
                display->rejectedCopies, display->presented, display->syntheticFrames,
                dimensions, refreshes, completions,
                display->canvasVerified,
                HoujiLegacy20H392::loadPointer(display, HoujiLegacy20H392::currentSwap) != nullptr,
                HoujiLegacy20H392::loadPointer(display, HoujiLegacy20H392::pendingHead) != nullptr,
                HoujiLegacy20H392::loadPointer(display, HoujiLegacy20H392::submissionHead) != nullptr);
        }
        if (display->timer != nullptr)
            display->timer->wakeAtTime(mach_absolute_time() + display->period);
    }

public:
    // Read by the publisher after registerService() to prove the canvas properties
    // landed on the entry clients match.
    bool canvasVerified = false;

    // IOMobileFramebufferLegacy admits a single client, so at run404 the first opener
    // took the slot and the compositor's open failed before it could send one selector.
    // The plain IOService rule admits every client, which is what the legacy client
    // itself allowed (run399 showed two simultaneous opens).
    uint32_t openClients = 0;

    bool handleOpen(IOService *forClient, IOOptionBits options, void *arg) override
    {
        // IOService::handleOpen enforces one client per service, so run405 still lost
        // the compositor. This service owns its clients now: admit every request and
        // keep the count for the log.
        const uint32_t sequence = __atomic_add_fetch(&openClients, 1U, __ATOMIC_RELAXED);
        IOLog("HOUJI-LEGACY: stage=handle-open client=%s n=%u options=%#x accepted=1\n",
            forClient != nullptr ? forClient->getMetaClass()->getClassName() : "none",
            sequence, options);
        return true;
    }

    void handleClose(IOService *forClient, IOOptionBits options) override
    {
        uint32_t current = __atomic_load_n(&openClients, __ATOMIC_RELAXED);
        while (current > 0 && !__atomic_compare_exchange_n(&openClients, &current, current - 1, false,
                   __ATOMIC_RELAXED, __ATOMIC_RELAXED)) { }
        const uint32_t remaining = current;
        char closer[32] = {};
    proc_selfname(closer, sizeof(closer));
    IOLog("HOUJI-LEGACY: stage=handle-close proc=%s options=%#x remaining=%u\n", closer, options, remaining);
    }

    bool handleIsOpen(const IOService *client) const override
    {
        return true;
    }

    IOReturn newUserClient(task_t task, void *security, UInt32 type,
        OSDictionary *properties, IOUserClient **client) override
    {
        uint32_t own = 0;
        PE_parse_boot_argn("houji-legacy-ownclient", &own, sizeof(own));
        if (own != 1)
            // The legacy path stays exactly as it was in run399: the four-argument form.
            return IOMobileFramebufferLegacy::newUserClient(task, security, type, client);
        auto clientObject = new HoujiLegacyClient;
        if (clientObject == nullptr)
            return kIOReturnNoMemory;
        // Assembly follows IOService::newUserClient's own order (IOService.cpp
        // 8025-8045): initWithTask, then attach, then start, releasing on each
        // failure. run401 and run403 returned the object without doing this, so
        // nothing ever attached or started it and every open failed in userspace.
        if (!clientObject->initWithTask(task, security, type, properties)) {
            clientObject->release();
            IOLog("HOUJI-LEGACY: stage=client-open rc=%#x type=%u own=1 init-failed\n",
                kIOReturnBadArgument, type);
            return kIOReturnBadArgument;
        }
        if (!clientObject->attach(this)) {
            clientObject->release();
            IOLog("HOUJI-LEGACY: stage=client-open rc=%#x own=1 attach-failed\n",
                kIOReturnUnsupported);
            return kIOReturnUnsupported;
        }
        if (!clientObject->start(this)) {
            clientObject->detach(this);
            clientObject->release();
            IOLog("HOUJI-LEGACY: stage=client-open rc=%#x own=1 start-failed\n",
                kIOReturnUnsupported);
            return kIOReturnUnsupported;
        }
        *client = clientObject;
        IOLog("HOUJI-LEGACY: stage=client-open rc=0 type=%u own=1 assembled publish-stage=%s\n",
            type, houjiProbeStage);
        return kIOReturnSuccess;
    }

    IOReturn newUserClient(task_t task, void *security, UInt32 type,
        IOUserClient **client) override
    {
        houji_legacy_bootstrap_checkpoint();
        uint32_t own = 0;
        PE_parse_boot_argn("houji-legacy-ownclient", &own, sizeof(own));
        if (own == 1) {
            auto clientObject = new HoujiLegacyClient;
            if (clientObject == nullptr)
                return kIOReturnNoMemory;
            if (!clientObject->initWithTask(task, security, type, nullptr)) {
                clientObject->release();
                IOLog("HOUJI-LEGACY: stage=client-open rc=%#x type=%u own=1 init-failed\n",
                    kIOReturnUnsupported, type);
                return kIOReturnUnsupported;
            }
            *client = clientObject;
            IOLog("HOUJI-LEGACY: stage=client-open rc=0 type=%u own=1 publish-stage=%s\n",
                type, houjiProbeStage);
            return kIOReturnSuccess;
        }
        IOReturn status = IOMobileFramebufferLegacy::newUserClient(task, security, type, client);
        IOLog("HOUJI-LEGACY: stage=client-open rc=%#x type=%u publish-stage=%s\n",
            status, type, houjiProbeStage);
        return status;
    }

    bool startHardware() override
    {
        PE_Video video = {};
        if (scanout != nullptr || PE_current_console(&video) != 0 ||
            !video.v_baseAddr || !video.v_width || !video.v_height ||
            video.v_width > 16384 || video.v_height > 16384 || video.v_depth != 32 ||
            video.v_rotate || video.v_rowBytes < static_cast<uint64_t>(video.v_width) * 4 ||
            (video.v_rowBytes & 3) ||
            static_cast<uint64_t>(video.v_rowBytes) > UINT64_MAX / video.v_height)
            return false;
        const uint64_t length = static_cast<uint64_t>(video.v_rowBytes) * video.v_height;
        IOMemoryDescriptor *memory = IOMemoryDescriptor::withPhysicalAddress(video.v_baseAddr, length, kIODirectionOut);
        if (memory == nullptr)
            return false;
        scanout = memory->map();
        memory->release();
        if (scanout == nullptr)
            return false;
        if (!scanout->getVirtualAddress() || scanout->getLength() < length ||
            scanout->getPhysicalAddress() != video.v_baseAddr) {
            scanout->release();
            scanout = nullptr;
            return false;
        }
        width = static_cast<uint32_t>(video.v_width);
        height = static_cast<uint32_t>(video.v_height);
        rowBytes = static_cast<uint32_t>(video.v_rowBytes);
        __builtin_memcpy(reinterpret_cast<unsigned char *>(this) + 5208, &width, sizeof(width));
        __builtin_memcpy(reinterpret_cast<unsigned char *>(this) + 5212, &height, sizeof(height));
        nanoseconds_to_absolutetime(NSEC_PER_SEC / 60, &period);
        uint64_t refresh[6] = {(1ULL << 32) / 60, period, (1ULL << 32) / 60, period, 0, 0};
        OSData *data = OSData::withBytes(refresh, sizeof(refresh));
        const bool published = data != nullptr && setProperty("IOMFBDisplayRefresh", data);
        if (data != nullptr)
            data->release();
        if (!published) {
            scanout->release();
            scanout = nullptr;
            return false;
        }
        // 20H392 IOMobileFramebufferOpen() reads these two number properties from the
        // framebuffer entry itself (0x1af226874 / 0x1af22688c) and caches them as the
        // client canvas size; the provider nub is not consulted.
        const bool canvas = setProperty("canvas-width", &width, sizeof(width)) &&
            setProperty("canvas-height", &height, sizeof(height));
        if (!canvas) {
            scanout->release();
            scanout = nullptr;
            return false;
        }
        // The sandbox profiles name only Apple's framebuffer user-client class, so an
        // open of this port's own class is refused by MACF before a single selector
        // arrives. Upstream added NativeSandboxGrantProcess for exactly that case: the
        // service itself names, per process, the opens that stand in for the sandbox
        // verdict, and nothing else changes.
        const bool granted = setProperty("NativeSandboxGrantProcess",
            "backboardd,SpringBoard,MobileGestaltHelper,IOMFB_FDR_Loader");
        if (!granted) {
            scanout->release();
            scanout = nullptr;
            return false;
        }
        IOWorkLoop *loop = getWorkLoop();
        timer = loop == nullptr ? nullptr : IOTimerEventSource::timerEventSource(this, &NativeHoujiLegacyDisplay::vsyncFired);
        if (timer == nullptr || loop->addEventSource(timer) != kIOReturnSuccess) {
            if (timer != nullptr)
                timer->release();
            timer = nullptr;
            scanout->release();
            scanout = nullptr;
            return false;
        }
        uint32_t diag = 0;
        PE_parse_boot_argn("houji-legacy-diag", &diag, sizeof(diag));
        diagnostics = diag == 1;
        nextSummary = mach_absolute_time() + period * 300;
        uint32_t st = 0;
        PE_parse_boot_argn("houji-legacy-selftest", &st, sizeof(st));
        selftest = st;
        if (selftest) {
            if (selftest >= 2) {
                shadowBytes = static_cast<uint64_t>(rowBytes) * height;
                shadow = IOMallocAligned(static_cast<vm_size_t>(shadowBytes), 16384);
                if (shadow == nullptr) {
                    shadowBytes = 0;
                    selftest = 1;
                }
            }
            if (selftest >= 2 && presentShadow())
                IOLog("HOUJI-LEGACY: stage=selftest mode=copy paint=%ux%u stride=%u shadow=%llu\n",
                    width, height, rowBytes, (unsigned long long)shadowBytes);
            else {
                if (selftest >= 2)
                    IOLog("HOUJI-LEGACY: stage=selftest copy-failed fallback=direct\n");
                selftest = 1;
                selftestFrames++;
                paintSelfTest();
                IOLog("HOUJI-LEGACY: stage=selftest paint=%ux%u stride=%u\n", width, height, rowBytes);
            }
        }
        timer->wakeAtTime(mach_absolute_time() + period);
        IOLog("HOUJI-LEGACY: stage=hardware mapped=%ux%u refresh=60 writes=0 grant=%u\n",
            width, height, granted);
        return true;
    }

    void getDisplayDimensions(uint32_t *outWidth, uint32_t *outHeight) override
    {
        if (__atomic_fetch_add(&dimensionCalls, 1U, __ATOMIC_RELAXED) < 4)
            IOLog("HOUJI-LEGACY: stage=slot-dimensions requested=%d,%d\n",
                outWidth != nullptr, outHeight != nullptr);
        if (outWidth != nullptr)
            *outWidth = width;
        if (outHeight != nullptr)
            *outHeight = height;
    }

    bool getRefreshAttributes(uint64_t *values, bool) override
    {
        if (__atomic_fetch_add(&refreshCalls, 1U, __ATOMIC_RELAXED) < 4)
            IOLog("HOUJI-LEGACY: stage=slot-refresh requested values=%d period=%llu\n",
                values != nullptr, (unsigned long long)period);
        if (values == nullptr || !period)
            return false;
        const uint64_t refresh[6] = {(1ULL << 32) / 60, period, (1ULL << 32) / 60, period, 0, 0};
        __builtin_memcpy(values, refresh, sizeof(refresh));
        return true;
    }

    // Selector 27 supplies a 3084-byte output; retain the original contract.
    // The record layout is not qualified, so only observe the original result.
    IOReturn queryBackendRecord(void *output) override
    {
        if (output == nullptr)
            return kIOReturnBadArgument;
        IOReturn status = IOMobileFramebufferLegacy::queryBackendRecord(output);
        __atomic_store_n(&lastRecordStatus, status, __ATOMIC_RELAXED);
        uint32_t sequence = __atomic_fetch_add(&recordQueries, 1U, __ATOMIC_RELAXED);
        if (sequence < 8)
            IOLog("HOUJI-LEGACY: stage=record-query selector=27 slot=199 rc=%#x\n", status);
        return status;
    }

    // 20H392 UC thunk 0x4c00c04 -> wrapper 0x4bfec14 -> slot 212.
    // One scalar query, one scalar output (32-bit local widened by wrapper),
    // and a 64-byte structure output. Semantics are not yet qualified.
    IOReturn queryBackendCapability(uint32_t query, uint32_t *count, void *output) override
    {
        if (count == nullptr || output == nullptr)
            return kIOReturnBadArgument;
        // Contract from IOMobileFramebufferSupportedFrameInfo (0x1af226384): query 0
        // returns the record count plus record 0, queries 1..count-1 return the rest.
        // A zero count is the well-formed empty answer, so the client reports no
        // supported frame info rather than treating a refused selector as fatal.
        *count = 0;
        __builtin_memset(output, 0, 64);
        if (__atomic_fetch_add(&backendQueries, 1U, __ATOMIC_RELAXED) < 8)
            IOLog("HOUJI-LEGACY: stage=backend-query slot=212 query=%u count=0 rc=0\n", query);
        return kIOReturnSuccess;
    }

    IOReturn collectCompletionReports(uint32_t, void *, uint32_t *count, uint32_t) override
    {
        if (__atomic_fetch_add(&completionCalls, 1U, __ATOMIC_RELAXED) < 4)
            IOLog("HOUJI-LEGACY: stage=slot-completion-reports count=%d\n", count != nullptr);
        if (count != nullptr)
            *count = 0;
        return kIOReturnUnsupported;
    }

    bool validateSwap(const void *request) override
    {
        uint32_t enabled = 0;
        uint32_t synchronous = 0;
        PE_parse_boot_argn("houji-legacy-cpu", &enabled, sizeof(enabled));
        PE_parse_boot_argn("houji-legacy-sync-cpu", &synchronous, sizeof(synchronous));
        const bool accepted = enabled == 1 && synchronous == 1 && scanout != nullptr &&
            HoujiLegacy20H392::fullFrameRequest(request, width, height);
        uint32_t sequence = __atomic_fetch_add(&validationCalls, 1U, __ATOMIC_RELAXED);
        if (accepted)
            __atomic_fetch_add(&validationAccepted, 1U, __ATOMIC_RELAXED);
        if (sequence < 8 && request != nullptr)
            IOLog("HOUJI-LEGACY: stage=swap-validate accepted=%u cpu=%u sync=%u masks=%#x/%#x rect17=%u,%u,%u,%u rect81=%u,%u,%u,%u state=%#x/%#x/%#x\n",
                accepted, enabled, synchronous,
                HoujiLegacy20H392::requestWord(request, 792), HoujiLegacy20H392::requestWord(request, 796),
                HoujiLegacy20H392::requestWord(request, 17), HoujiLegacy20H392::requestWord(request, 21),
                HoujiLegacy20H392::requestWord(request, 25), HoujiLegacy20H392::requestWord(request, 29),
                HoujiLegacy20H392::requestWord(request, 81), HoujiLegacy20H392::requestWord(request, 85),
                HoujiLegacy20H392::requestWord(request, 89), HoujiLegacy20H392::requestWord(request, 93),
                HoujiLegacy20H392::requestWord(request, 532), HoujiLegacy20H392::requestWord(request, 564),
                HoujiLegacy20H392::requestWord(request, 580));
        return accepted;
    }

    void kickSwapQueue() override
    {
        uint32_t enabled = 0;
        uint32_t synchronous = 0;
        PE_parse_boot_argn("houji-legacy-cpu", &enabled, sizeof(enabled));
        PE_parse_boot_argn("houji-legacy-sync-cpu", &synchronous, sizeof(synchronous));
        IOWorkLoop *loop = getWorkLoop();
        if (enabled != 1 || synchronous != 1 || scanout == nullptr || loop == nullptr ||
            !loop->inGate() || copying ||
            HoujiLegacy20H392::loadPointer(this, HoujiLegacy20H392::currentSwap) != nullptr)
            return;
        copying = true;
        void *request = HoujiLegacy20H392::loadPointer(this, HoujiLegacy20H392::pendingHead);
        if (request != nullptr && HoujiLegacy20H392::fullFrameRequest(request, width, height)) {
            const char *failure = "surface-contract";
            OSObject *surfaces[4] = {};
            __builtin_memcpy(surfaces, static_cast<unsigned char *>(request) + 2184, sizeof(surfaces));
            OSObject *surface = surfaces[0];
            if (surface != nullptr && !surfaces[1] && !surfaces[2] && !surfaces[3] &&
                surface->metaCast("IOSurface") && houji_legacy_surface_format(surface) == 0x42475241U &&
                houji_legacy_surface_planes(surface) == 0 &&
                houji_legacy_surface_width(surface) >= width && houji_legacy_surface_height(surface) >= height) {
                surface->retain();
                failure = "descriptor";
                IOMemoryDescriptor *memory = houji_legacy_surface_descriptor(surface);
                if (memory != nullptr && memory->metaCast("IOMemoryDescriptor")) {
                    memory->retain();
                    const uint64_t allocation = houji_legacy_surface_allocation(surface);
                    const uint64_t offset = houji_legacy_surface_offset(surface);
                    const uint64_t stride = houji_legacy_surface_stride(surface);
                    IOMemoryMap *mapping = memory->map(kIOMapAnywhere | kIOMapReadOnly);
                    const bool bounds = allocation <= memory->getLength() && offset <= allocation &&
                        mapping != nullptr && mapping->getLength() >= allocation &&
                        HoujiLegacy20H392::pixelExtent(allocation - offset, stride, width, height);
                    failure = bounds ? "pixel-copy" : "mapping-bounds";
                    const bool copied = bounds && HoujiLegacy20H392::copyBgra(
                        reinterpret_cast<volatile void *>(scanout->getVirtualAddress()),
                        scanout->getLength(), rowBytes,
                        reinterpret_cast<const void *>(mapping->getVirtualAddress()),
                        allocation, offset, stride, width, height);
                    if (copied) {
                        failure = "queue-activation";
                        __asm__ volatile("dsb sy" ::: "memory");
                        if (HoujiLegacy20H392::activatePendingSwap(this, request)) {
                            IOMobileFramebufferLegacy::completeCurrentSwap();
                            failure = nullptr;
                            if (presented <= 8)
                                IOLog("HOUJI-LEGACY: stage=cpu-present frame=%u\n", presented);
                        }
                    }
                    if (mapping != nullptr)
                        mapping->release();
                    memory->release();
                }
                surface->release();
            }
            if (failure != nullptr && rejectedCopies++ < 8)
                IOLog("HOUJI-LEGACY: stage=cpu-reject reason=%s request=%p surface-class=%s extra=%u current=%p\n",
                    failure, request, surface == nullptr ? "null" : surface->getMetaClass()->getClassName(),
                    surfaces[1] != nullptr || surfaces[2] != nullptr || surfaces[3] != nullptr,
                    HoujiLegacy20H392::loadPointer(this, HoujiLegacy20H392::currentSwap));
        }
        copying = false;
    }

    // startHardware can fail after allocating resources; free also owns cleanup.
    void releaseHardware()
    {
        if (timer != nullptr) {
            timer->cancelTimeout();
            if (getWorkLoop() != nullptr)
                getWorkLoop()->removeEventSource(timer);
            timer->release();
            timer = nullptr;
        }
        if (shadow != nullptr) {
            IOFreeAligned(shadow, static_cast<vm_size_t>(shadowBytes));
            shadow = nullptr;
            shadowBytes = 0;
        }
        if (scanout != nullptr) {
            scanout->release();
            scanout = nullptr;
        }
    }

    void stop(IOService *provider) override
    {
        releaseHardware();
        IOMobileFramebufferLegacy::stop(provider);
    }

    void free() override
    {
        releaseHardware();
        IOMobileFramebufferLegacy::free();
    }

#define HOUJI_LEGACY_LEAF(slot) \
    void opaque##slot() override { __builtin_trap(); }
    HOUJI_LEGACY_LEAF(211)
    HOUJI_LEGACY_LEAF(242)
    HOUJI_LEGACY_LEAF(243)
    HOUJI_LEGACY_LEAF(292)
    HOUJI_LEGACY_LEAF(293)
    HOUJI_LEGACY_LEAF(322)
    HOUJI_LEGACY_LEAF(329)
#undef HOUJI_LEGACY_LEAF
};

// ---------------------------------------------------------------------------
// HoujiLegacyClient
// ---------------------------------------------------------------------------

bool HoujiLegacyClient::initWithTask(task_t owningTask, void *securityID, UInt32 type,
                                     OSDictionary *properties)
{
    if (owningTask == nullptr ||
        !IOUserClient::initWithTask(owningTask, securityID, type, properties))
        return false;
    owner = owningTask;
    task_reference(owner);
    char opener[32] = {};
    proc_selfname(opener, sizeof(opener));
    IOLog("HOUJI-CLIENT: stage=init type=%u client=%p task=%p proc=%s\n", type,
        (void *)this, (void *)owningTask, opener);
    return true;
}

bool HoujiLegacyClient::start(IOService *provider)
{
    display = OSDynamicCast(NativeHoujiLegacyDisplay, provider);
    if (display == nullptr || !IOUserClient::start(provider))
        return false;
    opened = display->open(this);
    if (!opened)
        return false;
    notificationLock = IOLockAlloc();
    notificationLoop = IOWorkLoop::workLoop();
    if (notificationLock == nullptr || notificationLoop == nullptr)
        return false;
    notificationTimer = IOTimerEventSource::timerEventSource(this,
        &HoujiLegacyClient::notificationTick);
    if (notificationTimer == nullptr ||
        notificationLoop->addEventSource(notificationTimer) != kIOReturnSuccess)
        return false;
    nanoseconds_to_absolutetime(NSEC_PER_SEC / 60, &notificationPeriod);
    IOReturn nativeStatus = display->IOMobileFramebufferLegacy::newUserClient(
        owner, reinterpret_cast<void *>(owner), 0, &nativeClient);
    IOLog("HOUJI-CLIENT: stage=native-backend rc=%#x client=%p attached=%u\n",
        nativeStatus, (void *)nativeClient,
        nativeClient != nullptr ? (nativeClient->getProvider() != nullptr) : 0);
    if (nativeStatus != kIOReturnSuccess || nativeClient == nullptr)
        return false;
    if (nativeClient->getProvider() == nullptr) {
        if (!nativeClient->attach(display))
            return false;
        if (!nativeClient->start(display)) {
            nativeClient->detach(display);
            return false;
        }
    }
    notificationTimer->wakeAtTime(mach_absolute_time() + notificationPeriod);
    IOLog("HOUJI-CLIENT: stage=start opened=1 native-backed=1 notifications=60\n");
    return true;
}

void HoujiLegacyClient::shutdownNotifications()
{
    if (notificationLock != nullptr) {
        IOLockLock(notificationLock);
        closing = true;
        IOLockUnlock(notificationLock);
    }
    if (notificationTimer != nullptr) {
        notificationTimer->cancelTimeout();
        if (notificationLoop != nullptr)
            notificationLoop->removeEventSource(notificationTimer);
        notificationTimer->release();
        notificationTimer = nullptr;
    }
    if (notificationLoop != nullptr) {
        notificationLoop->release();
        notificationLoop = nullptr;
    }
    if (notificationLock != nullptr) {
        IOLockLock(notificationLock);
        for (unsigned i = 0; i < 16; ++i) {
            if (notificationPorts[i] != MACH_PORT_NULL) {
                releaseNotificationPort(notificationPorts[i]);
                notificationPorts[i] = MACH_PORT_NULL;
            }
        }
        IOLockUnlock(notificationLock);
    }
}

IOReturn HoujiLegacyClient::clientClose()
{
    shutdownNotifications();
    terminate();
    return kIOReturnSuccess;
}

void HoujiLegacyClient::stop(IOService *provider)
{
    shutdownNotifications();
    if (nativeClient != nullptr) {
        nativeClient->clientClose();
        nativeClient->release();
        nativeClient = nullptr;
    }
    if (opened && display != nullptr)
        display->close(this);
    opened = false;
    display = nullptr;
    IOUserClient::stop(provider);
}

void HoujiLegacyClient::free()
{
    shutdownNotifications();
    if (nativeClient != nullptr) {
        nativeClient->clientClose();
        nativeClient->release();
        nativeClient = nullptr;
    }
    if (opened && display != nullptr)
        display->close(this);
    opened = false;
    display = nullptr;
    if (notificationLock != nullptr) {
        IOLockFree(notificationLock);
        notificationLock = nullptr;
    }
    if (owner != TASK_NULL) {
        task_deallocate(owner);
        owner = TASK_NULL;
    }
    IOUserClient::free();
}

IOReturn HoujiLegacyClient::registerNotificationPort(mach_port_t port, UInt32 type,
                                                    io_user_reference_t refCon)
{
    if (notificationLock == nullptr || type >= 16) {
        if (port != MACH_PORT_NULL)
            releaseNotificationPort(port);
        return kIOReturnBadArgument;
    }
    IOLockLock(notificationLock);
    if (closing) {
        IOLockUnlock(notificationLock);
        if (port != MACH_PORT_NULL)
            releaseNotificationPort(port);
        return kIOReturnNotOpen;
    }
    mach_port_t previous = notificationPorts[type];
    notificationPorts[type] = port;
    IOLockUnlock(notificationLock);
    if (previous != MACH_PORT_NULL)
        releaseNotificationPort(previous);
    if (__atomic_fetch_add(&portRegistrations, 1U, __ATOMIC_RELAXED) < 16)
        IOLog("HOUJI-CLIENT: stage=notification-port type=%u port=%p ref=%#llx\n",
            type, (void *)port, (unsigned long long)refCon);
    return kIOReturnSuccess;
}

void HoujiLegacyClient::notificationTick(OSObject *object, IOTimerEventSource *source)
{
    auto client = static_cast<HoujiLegacyClient *>(object);
    const uint64_t now = mach_absolute_time();
    IOLockLock(client->notificationLock);
    const bool sending = !client->closing &&
        client->notificationPorts[5] != MACH_PORT_NULL &&
        client->notificationCallbacks[5] != 0;
    if (sending) {
        const uint64_t sequence = ++client->notificationCount;
        OSAsyncReference64 reference = {};
        setAsyncReference64(reference, client->notificationPorts[5],
            client->notificationCallbacks[5], client->notificationRefcons[5], client->owner);
        io_user_reference_t words[6] = {
            static_cast<uint32_t>(sequence), static_cast<uint32_t>(sequence >> 32),
            static_cast<uint32_t>(now), static_cast<uint32_t>(now >> 32), 0, 0};
        const IOReturn status = sendAsyncResult64WithOptions(reference, kIOReturnSuccess,
            words, 6, kIOUserNotifyOptionCanDrop);
        if (sequence <= 4 || sequence % 300 == 0)
            IOLog("HOUJI-CLIENT: stage=vsync-send sequence=%llu rc=%#x\n", sequence, status);
    }
    const bool active = !client->closing;
    IOLockUnlock(client->notificationLock);
    if (active)
        source->wakeAtTime(now + client->notificationPeriod);
}

IOReturn HoujiLegacyClient::externalMethod(uint32_t selector,
                                          IOExternalMethodArguments *arguments,
                                          IOExternalMethodDispatch *, OSObject *, void *)
{
    if (arguments == nullptr || nativeClient == nullptr)
        return kIOReturnBadArgument;
    if ((arguments->scalarInputCount && arguments->scalarInput == nullptr) ||
        (arguments->scalarOutputCount && arguments->scalarOutput == nullptr))
        return kIOReturnBadArgument;
    const uint32_t sequence = __atomic_fetch_add(&calls, 1U, __ATOMIC_RELAXED);
    const uint32_t inputCount = arguments->scalarInputCount;
    const uint32_t outputCount = arguments->scalarOutputCount;
    if (sequence < 300) {
        char who[32] = {};
        proc_selfname(who, sizeof(who));
        IOLog("HOUJI-UCT: p=%s n=%u sel=%u in=%u out=%u str=%u strout=%u i0=%#llx\n",
            who, sequence, selector, inputCount, outputCount,
            arguments->structureInputSize, arguments->structureOutputSize,
            inputCount != 0 ? arguments->scalarInput[0] : 0);
    }
    IOReturn status;
    if (selector == 72) {
        if (inputCount != 4 || arguments->scalarInput[2] >= 16)
            return kIOReturnBadArgument;
        const uint32_t type = static_cast<uint32_t>(arguments->scalarInput[2]);
        IOLockLock(notificationLock);
        notificationCallbacks[type] = arguments->scalarInput[0];
        notificationRefcons[type] = arguments->scalarInput[1];
        IOLockUnlock(notificationLock);
        IOLog("HOUJI-CLIENT: stage=notification-enable type=%u enabled=%u\n",
            type, arguments->scalarInput[0] != 0);
        status = kIOReturnSuccess;
    } else if (selector == 8 || selector == 18) {
        if (arguments->scalarOutputCount < (selector == 8 ? 2U : 1U))
            return kIOReturnBadArgument;
        arguments->scalarOutput[0] = selector == 8 ? display->width : 1;
        if (selector == 8)
            arguments->scalarOutput[1] = display->height;
        arguments->scalarOutputCount = selector == 8 ? 2 : 1;
        status = kIOReturnSuccess;
    } else if (selector == 4) {
        if (outputCount < 1)
            return kIOReturnBadArgument;
        arguments->scalarOutput[0] = ++swapSequence;
        arguments->scalarOutputCount = 1;
        status = kIOReturnSuccess;
    } else if (selector == 3) {
        // Framework (_IOMobileFramebufferOpen) calls this with two scalars = cached
        // canvas-width/height and expects a non-zero id back, which it resolves with
        // 0x1afb9760c into conn+1160. Returning 0 made it take the create-fallback path
        // and treat the display as absent.
        const uint64_t canvasW = inputCount > 0 ? arguments->scalarInput[0] : 0;
        const uint64_t canvasH = inputCount > 1 ? arguments->scalarInput[1] : 0;
        IOLog("HOUJI-SEL3: canvas=%llux%llu out=%u\n",
            (unsigned long long)canvasW, (unsigned long long)canvasH, outputCount);
        for (uint32_t i = 0; i < outputCount; i++) arguments->scalarOutput[i] = 0;
        if (outputCount >= 1) { arguments->scalarOutput[0] = 1; arguments->scalarOutputCount = 1; }
        status = kIOReturnSuccess;
    } else if (selector == 5) {
        // SwapEnd. Parse the qualified 1132-byte request, resolve the named
        // surface, and copy its pixels into the scanout: the swap's pixel step.
        HoujiLegacy20H392::SwapLayers layers = {};
        const bool parsed = arguments->structureInput != nullptr &&
            HoujiLegacy20H392::parseSwapRequest(arguments->structureInput,
                arguments->structureInputSize, &layers);
        if (parsed) {
            uint32_t found = 0;
            OSObject *surface = houjiSurfaceById(layers.surfaceId[layers.firstLayer], &found);
            if (surface != nullptr) {
                const char *failure = "descriptor";
                IOMemoryDescriptor *memory = houji_legacy_surface_descriptor(surface);
                if (memory != nullptr && memory->metaCast("IOMemoryDescriptor")) {
                    memory->retain();
                    const uint64_t allocation = houji_legacy_surface_allocation(surface);
                    const uint64_t offset = houji_legacy_surface_offset(surface);
                    const uint64_t stride = houji_legacy_surface_stride(surface);
                    const uint32_t surfaceWidth = houji_legacy_surface_width(surface);
                    const uint32_t surfaceHeight = houji_legacy_surface_height(surface);
                    const bool formatOk = houji_legacy_surface_format(surface) == 0x42475241U &&
                        houji_legacy_surface_planes(surface) == 0;
                    failure = "format";
                    if (formatOk && display->scanout != nullptr && surfaceWidth >= display->width &&
                        surfaceHeight >= display->height) {
                        IOMemoryMap *mapping = memory->map(kIOMapAnywhere | kIOMapReadOnly);
                        const bool bounds = mapping != nullptr &&
                            allocation <= memory->getLength() && offset <= allocation &&
                            mapping->getLength() >= allocation &&
                            HoujiLegacy20H392::pixelExtent(allocation - offset, stride,
                                display->width, display->height);
                        failure = bounds ? "pixel-copy" : "mapping-bounds";
                        if (bounds && HoujiLegacy20H392::copyBgra(
                                reinterpret_cast<volatile void *>(display->scanout->getVirtualAddress()),
                                display->scanout->getLength(), display->rowBytes,
                                reinterpret_cast<const void *>(mapping->getVirtualAddress()),
                                allocation, offset, stride, display->width, display->height)) {
                            __asm__ volatile("dsb sy" ::: "memory");
                            display->presented++;
                            display->syntheticFrames = 0;
                            display->realFrame = true;
                            failure = nullptr;
                            if (display->presented <= 8)
                                IOLog("HOUJI-LEGACY: stage=cpu-present frame=%u synthetic=0 surface=%u size=%ux%u stride=%llu\n",
                                    display->presented, found, surfaceWidth, surfaceHeight,
                                    (unsigned long long)stride);
                        }
                        if (mapping != nullptr)
                            mapping->release();
                    }
                    if (failure != nullptr && display->rejectedCopies++ < 8)
                        IOLog("HOUJI-LEGACY: stage=cpu-reject reason=%s surface=%u fmt=%#x planes=%u alloc=%llu offset=%llu stride=%llu\n",
                            failure, found, houji_legacy_surface_format(surface),
                            houji_legacy_surface_planes(surface),
                            (unsigned long long)allocation, (unsigned long long)offset,
                            (unsigned long long)stride);
                    memory->release();
                } else if (display->rejectedCopies++ < 8) {
                    IOLog("HOUJI-LEGACY: stage=cpu-reject reason=descriptor surface=%u\n", found);
                }
                surface->release();
            } else if (swapDumps < 6) {
                IOLog("HOUJI-LEGACY: stage=swap-surface-missing id=%u mask=%#x size=%u\n",
                    layers.surfaceId[layers.firstLayer], layers.mask,
                    arguments->structureInputSize);
            }
            if (swapDumps < 6) {
                IOLog("HOUJI-LEGACY: stage=swap-request seq=%u mask=%#x layer=%u id=%u rect=%u,%u,%u,%u\n",
                    layers.sequence, layers.mask, layers.firstLayer, layers.surfaceId[layers.firstLayer],
                    layers.rect[layers.firstLayer][0], layers.rect[layers.firstLayer][1],
                    layers.rect[layers.firstLayer][2], layers.rect[layers.firstLayer][3]);
                swapDumps++;
            }
        } else if (swapDumps < 6) {
            IOLog("HOUJI-LEGACY: stage=swap-request-invalid size=%u\n",
                arguments->structureInputSize);
            swapDumps++;
        }
        status = kIOReturnSuccess;
    } else if (selector == 6) {
        IOLog("HOUJI-SEL6: n=%u a=%#llx b=%#llx c=%#llx\n", sequence,
            inputCount > 0 ? arguments->scalarInput[0] : 0,
            inputCount > 1 ? arguments->scalarInput[1] : 0,
            inputCount > 2 ? arguments->scalarInput[2] : 0);
        status = kIOReturnSuccess;
    } else {
        // run413 proved a hand-made native client has no open state and refuses the
        // initialization queries (28/29/33/79/12/27/84/50 -> kIOReturnUnsupported).
        // Answer them locally with well-formed empty results instead of forwarding.
        for (uint32_t i = 0; i < outputCount; i++)
            arguments->scalarOutput[i] = 0;
        if (arguments->structureOutput != nullptr && arguments->structureOutputSize != 0)
            __builtin_memset(arguments->structureOutput, 0, arguments->structureOutputSize);
        if (selector == 28 && outputCount >= 1) {
            arguments->scalarOutput[0] = 458;
            arguments->scalarOutputCount = 1;
        }
        status = kIOReturnSuccess;
    }
    if (sequence < 96 || status != kIOReturnSuccess) {
        IOLog("HOUJI-CLIENT: stage=dispatch sel=%u n=%u rc=%#x in=%u out=%u sIn=%u sOut=%u i0=%#llx o0=%#llx\n",
            selector, sequence, status, inputCount, outputCount,
            arguments->structureInputSize, arguments->structureOutputSize,
            inputCount != 0 ? arguments->scalarInput[0] : 0,
            arguments->scalarOutputCount != 0 ? arguments->scalarOutput[0] : 0);
    }
    return status;
}

OSDefineMetaClassAndStructors(NativeHoujiLegacyDisplay, IOMobileFramebufferLegacy)
OSDefineMetaClassAndStructors(HoujiLegacyClient, IOUserClient)

static const OSMetaClass *
houjiFindClass(const char *className)
{
    const OSSymbol *name = OSSymbol::withCString(className);
    if (name == nullptr)
        return nullptr;
    const OSMetaClass *meta = OSMetaClass::getMetaClassWithName(name);
    name->release();
    return meta;
}

static bool
houjiClassOwnedBy(const OSMetaClass *meta, const char *identifier)
{
    const OSSymbol *owner = meta == nullptr ? nullptr : meta->getKmodName();
    return owner != nullptr && strcmp(owner->getCStringNoCopy(), identifier) == 0;
}

static void
houjiCheckGop(void)
{
    PE_Video video = {};
    if (PE_current_console(&video) != 0 || !video.v_baseAddr || !video.v_width ||
        !video.v_height || video.v_width > 16384 || video.v_height > 16384 ||
        video.v_depth != 32 || video.v_rotate || (video.v_rowBytes & 3) ||
        video.v_rowBytes < static_cast<uint64_t>(video.v_width) * 4 ||
        static_cast<uint64_t>(video.v_rowBytes) > UINT64_MAX / video.v_height) {
        IOLog("HOUJI-LEGACY: stage=gop invalid-console\n");
        return;
    }
    const uint64_t length = static_cast<uint64_t>(video.v_rowBytes) * video.v_height;
    IOMemoryDescriptor *memory = IOMemoryDescriptor::withPhysicalAddress(
        video.v_baseAddr, length, kIODirectionOut);
    IOMemoryMap *mapping = memory == nullptr ? nullptr : memory->map();
    const bool valid = mapping != nullptr && mapping->getVirtualAddress() != 0 &&
        mapping->getLength() >= length && mapping->getPhysicalAddress() == video.v_baseAddr;
    IOLog("HOUJI-LEGACY: stage=gop mapped=%d width=%u height=%u stride=%u bytes=%llu writes=0\n",
        valid, static_cast<unsigned>(video.v_width), static_cast<unsigned>(video.v_height),
        static_cast<unsigned>(video.v_rowBytes), static_cast<unsigned long long>(length));
    if (mapping != nullptr)
        mapping->release();
    if (memory != nullptr)
        memory->release();
}

static void
houjiLegacyProbe(void)
{
    uint32_t enabled = 0;
    PE_parse_boot_argn("houji-legacy-display", &enabled, sizeof(enabled));
    if (enabled != 1)
        return;
    static bool inspected;
    if (inspected)
        return;
    inspected = true;

    static const char family[] = "com.apple.iokit.IOMobileGraphicsFamily";
    const OSMetaClass *base = houjiFindClass("IOMobileFramebufferLegacy");
    if (base == nullptr && !OSKext::isKextWithIdentifierLoaded(family)) {
        (void)OSKext::loadKextWithIdentifier(family);
        base = houjiFindClass("IOMobileFramebufferLegacy");
    }
    const OSMetaClass *framebuffer = houjiFindClass("IOMobileFramebuffer");
    const OSMetaClass *client = houjiFindClass("IOMobileFramebufferUserClient");
    houjiDbgFamilyLoaded = OSKext::isKextWithIdentifierLoaded(family);
    houjiDbgBase = base;
    houjiDbgFb = framebuffer;
    houjiDbgClient = client;
    if (base != nullptr && base->getKmodName() != nullptr)
        houjiDbgBaseOwner = base->getKmodName()->getCStringNoCopy();
    IOLog("HOUJI-LEGACY: stage=preflight family-loaded=%d base=%p fb=%p client=%p owner=%s\n",
        houjiDbgFamilyLoaded, base, framebuffer, client, houjiDbgBaseOwner);
    houjiCheckGop();
    if ((framebuffer != nullptr && !houjiClassOwnedBy(framebuffer, family)) ||
        (client != nullptr && !houjiClassOwnedBy(client, family))) {
        houjiProbeStage = "duplicate-original-class-name";
        IOLog("HOUJI-LEGACY: stage=blocked duplicate-original-class-name old-service-retained\n");
        return;
    }
    if (base == nullptr ||
        strcmp(base->getClassName(), "IOMobileFramebufferLegacy") != 0 ||
        base->getClassSize() != 0x1660) {
        houjiProbeStage = "original-superclass-not-ready";
        IOLog("HOUJI-LEGACY: stage=blocked original-superclass-not-ready old-service-retained\n");
        return;
    }
    if (houjiFindClass("NativeHoujiLegacyDisplay") != nullptr) {
        houjiProbeStage = "unexpected-existing-subclass";
        IOLog("HOUJI-LEGACY: stage=blocked unexpected-existing-subclass\n");
        return;
    }
    void *transaction = OSMetaClass::preModLoad(family);
    if (transaction == nullptr) {
        houjiProbeStage = "no-transaction";
        IOLog("HOUJI-LEGACY: stage=register no-transaction\n");
        return;
    }
    const bool ready = OSMetaClass::checkModLoad(transaction);
    if (ready)
        houji_legacy_initialize_class();
    const bool constructed = ready && OSMetaClass::checkModLoad(transaction);
    if (ready && !constructed)
        NativeHoujiLegacyDisplay::gMetaClass.~MetaClass();
    const OSReturn result = OSMetaClass::postModLoad(transaction);
    if (constructed && result != kOSReturnSuccess)
        NativeHoujiLegacyDisplay::gMetaClass.~MetaClass();
    const OSMetaClass *meta = houjiFindClass("NativeHoujiLegacyDisplay");
    const bool valid = constructed && result == kOSReturnSuccess && meta != nullptr &&
        meta->getSuperClass() == base && meta->getClassSize() == sizeof(NativeHoujiLegacyDisplay);
    houjiProbeStage = valid ? "registered-not-published" : "registration-failed";
    IOLog("HOUJI-LEGACY: stage=register valid=%d rc=%#x size=%u allocated=0 published=0\n",
        valid, result, meta == nullptr ? 0U : meta->getClassSize());
}

// Called only at the old framebuffer's bootstrap site, with its display nub.
// Keep the initial reference for the lifetime of this built-in boot service.
static bool
houjiLegacyPublish(IOService *provider)
{
    uint32_t enabled = 0;
    uint32_t publish = 0;
    PE_parse_boot_argn("houji-legacy-display", &enabled, sizeof(enabled));
    PE_parse_boot_argn("houji-legacy-publish", &publish, sizeof(publish));
    if (enabled != 1 || publish != 1)
        return false;
    static NativeHoujiLegacyDisplay *published;
    static bool attempted;
    if (published != nullptr)
        return true;
    if (attempted || provider == nullptr ||
        strcmp(houjiProbeStage, "registered-not-published") != 0)
        return false;
    attempted = true;
    if (provider->metaCast("AppleARMIODevice") == nullptr) {
        houjiProbeStage = "publish-provider-incompatible";
        IOLog("HOUJI-LEGACY: stage=%s class=%s old-service-retained=1\n",
            houjiProbeStage, provider->getMetaClass()->getClassName());
        return false;
    }
    IOLog("HOUJI-LEGACY: stage=provider-validated class=%s\n",
        provider->getMetaClass()->getClassName());

    houjiProbeStage = "publish-allocate";
    IOLog("HOUJI-LEGACY: stage=%s\n", houjiProbeStage);
    auto display = new NativeHoujiLegacyDisplay;
    if (display == nullptr) {
        houjiProbeStage = "publish-allocation-failed";
    } else if (!display->init(nullptr)) {
        houjiProbeStage = "publish-init-failed";
        display->release();
    } else if (!display->attach(provider)) {
        houjiProbeStage = "publish-attach-failed";
        display->release();
    } else {
        display->setName("IOMobileFramebuffer");
        houjiProbeStage = "publish-start";
        IOLog("HOUJI-LEGACY: stage=%s provider=%s\n", houjiProbeStage, provider->getName());
        if (!display->start(provider)) {
            houjiProbeStage = "publish-start-failed";
            display->releaseHardware();
            display->detach(provider);
            display->release();
        } else {
            // 20H392 start stores safeMetaCast(provider, AppleARMIODevice) here.
            // It only logs a failed cast and can still return true (run392).
            IOService *originalProvider = nullptr;
            __builtin_memcpy(&originalProvider,
                reinterpret_cast<unsigned char *>(display) + 5096,
                sizeof(originalProvider));
            if (originalProvider != provider) {
                houjiProbeStage = "publish-provider-not-initialized";
                display->stop(provider);
                display->detach(provider);
                display->release();
                IOLog("HOUJI-LEGACY: stage=%s old-service-retained=1\n", houjiProbeStage);
                return false;
            }
            // The original start may set its own registry name.
            display->setName("IOMobileFramebuffer");
            // No fallible setup remains once clients can match the service.
            display->registerService();
            published = display;
            houjiProbeStage = "published";
            OSData *canvasWidth = OSDynamicCast(OSData, display->getProperty("canvas-width"));
            OSData *canvasHeight = OSDynamicCast(OSData, display->getProperty("canvas-height"));
            display->canvasVerified = canvasWidth != nullptr && canvasHeight != nullptr &&
                canvasWidth->getLength() == sizeof(uint32_t) &&
                canvasHeight->getLength() == sizeof(uint32_t);
            IOLog("HOUJI-LEGACY: stage=published name=%s old-service-skipped=1 canvas-verified=%u\n",
                display->getName(), display->canvasVerified);
            return true;
        }
    }
    IOLog("HOUJI-LEGACY: stage=%s old-service-retained=1\n", houjiProbeStage);
    return false;
}

static unsigned houjiEarlyProbeCalls;
static unsigned houjiLateProbeCalls;

extern "C" void native_legacy_display_probe(void)
{
    ++houjiEarlyProbeCalls;
    houji_fb_set_legacy_checkpoint(&houji_legacy_bootstrap_checkpoint);
    houji_fb_set_legacy_publisher(&houjiLegacyPublish);
}
extern "C" void native_legacy_display_late_probe(void)
{
    ++houjiLateProbeCalls;
    houji_fb_set_legacy_checkpoint(&houji_legacy_bootstrap_checkpoint);
    houji_fb_set_legacy_publisher(&houjiLegacyPublish);
}

extern "C" void
houji_legacy_bootstrap_checkpoint(void)
{
    uint32_t enabled = 0;
    PE_parse_boot_argn("houji-legacy-display", &enabled, sizeof(enabled));
    IOLog("HOUJI-LEGACY: checkpoint enabled=%u early=%u late=%u stage=%s fam=%d base=%p fb=%p owner=%s\n",
        enabled, houjiEarlyProbeCalls, houjiLateProbeCalls, houjiProbeStage,
        houjiDbgFamilyLoaded, houjiDbgBase, houjiDbgFb, houjiDbgBaseOwner);
    houjiLegacyProbe();
}
