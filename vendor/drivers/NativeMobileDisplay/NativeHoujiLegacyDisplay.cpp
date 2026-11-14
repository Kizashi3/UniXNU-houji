// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "OriginalHoujiLegacyABI.h"
#include <IOKit/IOLib.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <libkern/c++/OSKext.h>
#include <libkern/c++/OSMetaClass.h>
#include <libkern/c++/OSSymbol.h>
#include <pexpert/pexpert.h>

extern "C" void houji_legacy_initialize_class(void);
static const char *houjiProbeStage = "not-inspected";

class NativeHoujiLegacyDisplay : public IOMobileFramebufferLegacy {
    OSDeclareDefaultStructors(NativeHoujiLegacyDisplay)
public:
#define HOUJI_LEGACY_LEAF(slot) \
    void opaque##slot() override { __builtin_trap(); }
    HOUJI_LEGACY_LEAF(211)
    HOUJI_LEGACY_LEAF(212)
    HOUJI_LEGACY_LEAF(242)
    HOUJI_LEGACY_LEAF(243)
    HOUJI_LEGACY_LEAF(292)
    HOUJI_LEGACY_LEAF(293)
    HOUJI_LEGACY_LEAF(321)
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
    const OSMetaClass *framebuffer = houjiFindClass("IOMobileFramebuffer");
    const OSMetaClass *client = houjiFindClass("IOMobileFramebufferUserClient");
    IOLog("HOUJI-LEGACY: stage=preflight family-loaded=%d base=%p fb=%p client=%p\n",
        OSKext::isKextWithIdentifierLoaded(family), base, framebuffer, client);
    houjiCheckGop();
    if ((framebuffer != nullptr && !houjiClassOwnedBy(framebuffer, family)) ||
        (client != nullptr && !houjiClassOwnedBy(client, family))) {
        houjiProbeStage = "duplicate-original-class-name";
        IOLog("HOUJI-LEGACY: stage=blocked duplicate-original-class-name old-service-retained\n");
        return;
    }
    if (base == nullptr || !houjiClassOwnedBy(base, family) ||
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
        meta->getSuperClass() == base && meta->getClassSize() == 0x1660;
    houjiProbeStage = valid ? "registered-not-published" : "registration-failed";
    IOLog("HOUJI-LEGACY: stage=register valid=%d rc=%#x size=%u allocated=0 published=0\n",
        valid, result, meta == nullptr ? 0U : meta->getClassSize());
}

static unsigned houjiEarlyProbeCalls;
static unsigned houjiLateProbeCalls;

extern "C" void native_legacy_display_probe(void) { ++houjiEarlyProbeCalls; }
extern "C" void native_legacy_display_late_probe(void) { ++houjiLateProbeCalls; }

extern "C" void
houji_legacy_bootstrap_checkpoint(void)
{
    uint32_t enabled = 0;
    PE_parse_boot_argn("houji-legacy-display", &enabled, sizeof(enabled));
    IOLog("HOUJI-LEGACY: checkpoint enabled=%u early=%u late=%u stage=%s\n",
        enabled, houjiEarlyProbeCalls, houjiLateProbeCalls, houjiProbeStage);
    houjiLegacyProbe();
}
