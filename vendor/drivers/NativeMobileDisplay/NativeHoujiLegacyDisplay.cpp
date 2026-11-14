// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "OriginalHoujiLegacyABI.h"
#include "HoujiLegacyQueue.h"
#include "HoujiLegacyPixels.h"
#include "HoujiLegacyRequest.h"
#include <IOKit/IOLib.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/IOTimerEventSource.h>
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

class NativeHoujiLegacyDisplay : public IOMobileFramebufferLegacy {
    OSDeclareDefaultStructors(NativeHoujiLegacyDisplay)
    IOMemoryMap *scanout = nullptr;
    IOTimerEventSource *timer = nullptr;
    uint64_t period = 0;
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t rowBytes = 0;
    bool copying = false;
    unsigned presented = 0;

    static void vsyncFired(OSObject *owner, IOTimerEventSource *)
    {
        auto display = static_cast<NativeHoujiLegacyDisplay *>(owner);
        const void *head = nullptr;
        __builtin_memcpy(&head, reinterpret_cast<unsigned char *>(display) + 4992, sizeof(head));
        if (head != nullptr)
            houji_legacy_vsync_notify(display, mach_absolute_time(), mach_continuous_time(), display->period);
        display->kickSwapQueue();
        if (display->timer != nullptr)
            display->timer->wakeAtTime(mach_absolute_time() + display->period);
    }

public:
    IOReturn newUserClient(task_t task, void *security, UInt32 type,
        IOUserClient **client) override
    {
        houji_legacy_bootstrap_checkpoint();
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
        timer->wakeAtTime(mach_absolute_time() + period);
        IOLog("HOUJI-LEGACY: stage=hardware mapped=%ux%u refresh=60 writes=0\n", width, height);
        return true;
    }

    void getDisplayDimensions(uint32_t *outWidth, uint32_t *outHeight) override
    {
        if (outWidth != nullptr)
            *outWidth = width;
        if (outHeight != nullptr)
            *outHeight = height;
    }

    bool getRefreshAttributes(uint64_t *values, bool) override
    {
        if (values == nullptr || !period)
            return false;
        const uint64_t refresh[6] = {(1ULL << 32) / 60, period, (1ULL << 32) / 60, period, 0, 0};
        __builtin_memcpy(values, refresh, sizeof(refresh));
        return true;
    }

    // 20H392 UC thunk 0x4c00c04 -> wrapper 0x4bfec14 -> slot 212.
    // One scalar query, one scalar output (32-bit local widened by wrapper),
    // and a 64-byte structure output. Semantics are not yet qualified.
    IOReturn queryBackendCapability(uint32_t query, uint32_t *count, void *output) override
    {
        if (count == nullptr || output == nullptr)
            return kIOReturnBadArgument;
        *count = 0;
        static unsigned reports;
        if (reports++ < 8)
            IOLog("HOUJI-LEGACY: stage=backend-query slot=212 query=%u rc=unsupported\n", query);
        return kIOReturnUnsupported;
    }

    IOReturn collectCompletionReports(uint32_t, void *, uint32_t *count, uint32_t) override
    {
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
        return enabled == 1 && synchronous == 1 && scanout != nullptr &&
            HoujiLegacy20H392::fullFrameRequest(request, width, height);
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
            OSObject *surfaces[4] = {};
            __builtin_memcpy(surfaces, static_cast<unsigned char *>(request) + 2040, sizeof(surfaces));
            OSObject *surface = surfaces[0];
            if (surface != nullptr && !surfaces[1] && !surfaces[2] && !surfaces[3] &&
                surface->metaCast("IOSurface") && houji_legacy_surface_format(surface) == 0x42475241U &&
                houji_legacy_surface_planes(surface) == 0 &&
                houji_legacy_surface_width(surface) >= width && houji_legacy_surface_height(surface) >= height) {
                surface->retain();
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
                    const bool copied = bounds && HoujiLegacy20H392::copyBgra(
                        reinterpret_cast<volatile void *>(scanout->getVirtualAddress()),
                        scanout->getLength(), rowBytes,
                        reinterpret_cast<const void *>(mapping->getVirtualAddress()),
                        allocation, offset, stride, width, height);
                    if (copied) {
                        __asm__ volatile("dsb sy" ::: "memory");
                        if (HoujiLegacy20H392::activatePendingSwap(this, request)) {
                            IOMobileFramebufferLegacy::completeCurrentSwap();
                            ++presented;
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
OSDefineMetaClassAndStructors(NativeHoujiLegacyDisplay, IOMobileFramebufferLegacy)

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
            IOLog("HOUJI-LEGACY: stage=published name=%s old-service-skipped=1\n",
                display->getName());
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
