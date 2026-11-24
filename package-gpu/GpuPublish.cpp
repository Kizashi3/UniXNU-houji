// SPDX-License-Identifier: BSD-2-Clause-Patent
// NX769J Adreno 750 user-space surface (nx769j-gpu=11), after GpuCommand.cpp left the CP running on ring 0:
//
//   1. UniXNU NativeAdrenoPublish: a NativeAdrenoGpuPublished service whose connections (AGXDeviceUserClient) each get a
//      NativeAdrenoUserClient core with its own GPU address space on the one ring; it carries NativeAdrenoABI.h version 2,
//      the ABI Turnip's Darwin backend and the Metal plugin are built against (scripts/build-nx769j-metal.sh).
//   2. The accelerator iOS 16's Metal discovery looks for: IOServiceMatching("IOAcceleratorES"), then MetalPluginName ->
//      /System/Library/Extensions/<name>.bundle and MetalPluginClassName. Apple's IOGPUFamily (which owns IOAcceleratorES)
//      is not in this kernelcache, so the class is defined here, empty, as ios-fuxi and data-a-live do on iOS 16. The
//      subclass is named AGXAccelerator, the class name Apple's sandbox profiles accept, as UniXNU's and data-a-live's are.
//      Its opens (type 0x4147, Turnip's default) are NativeAdrenoPublish's connections.
//
// Device facts for Turnip (NativeAdrenoAbiDeviceInfo): chip 0x43051401, GMEM 3 MiB at 16 MiB, UCHE trap base, UBWC 4.0 with
// highest bank bit 16, swizzle levels 2 and 3, eight-channel macrotiles (a6xx_calc_ubwc_config, a740 family, Linux v6.16).
#include <IOKit/IOLib.h>
#include <IOKit/IOService.h>
#include <IOKit/IOUserClient.h>
#include <IOKit/IOPlatformExpert.h>
#include <pexpert/pexpert.h>
#include <stdarg.h>

#include "NativeAdrenoABI.h"
#include "NativeAdrenoGpuContext.h"
#include "NativeAdrenoRing.h"
#include "NativeAdrenoSubmit.h"
#include "NativeAdrenoTimer.h"
#include "NativeAdrenoVm.h"
#include "GpuBridge.h"

extern "C" IOReturn native_adreno_publish(NativeAdrenoVm *vm, NativeAdrenoSubmit *submit, NativeAdrenoRing *ring,
    const NativeAdrenoRingClock *clock, const NativeAdrenoTimer *timer, const NativeAdrenoAbiDeviceInfo *info,
    uint32_t input_bits, uint32_t output_bits);
extern "C" IOReturn native_adreno_new_user_client(IOService *, task_t, void *, UInt32, OSDictionary *, IOUserClient **,
    unsigned);
extern "C" uint32_t native_adreno_publish_stats(uint32_t *closed);

// Apple's base of every GPU accelerator, as iOS 16's Metal discovery matches it. Empty: Metal only reads its properties
// and opens it; the opens are served by the subclass.
class IOAcceleratorES : public IOService {
	OSDeclareDefaultStructors(IOAcceleratorES);
};
OSDefineMetaClassAndStructors(IOAcceleratorES, IOService);

class AGXAccelerator : public IOAcceleratorES {
	OSDeclareDefaultStructors(AGXAccelerator);
public:
	IOReturn newUserClient(task_t owningTask, void *securityID, UInt32 type, OSDictionary *properties,
	    IOUserClient **handler) APPLE_KEXT_OVERRIDE;
};
OSDefineMetaClassAndStructors(AGXAccelerator, IOAcceleratorES);

IOReturn
AGXAccelerator::newUserClient(task_t owningTask, void *securityID, UInt32 type, OSDictionary *properties,
    IOUserClient **handler)
{
	return native_adreno_new_user_client(this, owningTask, securityID, type, properties, handler, 0);
}

namespace nx769j_gpu {
namespace {
void say(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
void say(const char *fmt, ...)
{
	char text[168];
	va_list ap;
	va_start(ap, fmt);
	vsnprintf(text, sizeof(text), fmt, ap);
	va_end(ap);
	report(text);
}

NativeAdrenoSubmit gSubmit;
NativeAdrenoTimer gTimer;
NativeAdrenoRingClock gClock;
NativeAdrenoAbiDeviceInfo gInfo = {0x43051401u, 3u << 20, 0x1000000ull, 0x1fffffffff000ull, GpuClientVaStart, 0, 16, 6, 1, 4,
                                   NativeAdrenoDeviceClientIova, 0};

int timerRead(void *, uint32_t reg, uint32_t *value) { return gpuRead32(nullptr, reg, value); }
const NativeAdrenoTimeIo gTimerIo{nullptr, timerRead};
} // namespace

bool
publish()
{
	progress(0xc0);
	NativeAdrenoVm *vm = NativeAdrenoGpuContextVm();
	NativeAdrenoRing *ring = commandRing();
	if (!vm || !ring) {
		say("publish: no GPU VM or ring");
		return false;
	}
	const IOReturn attached = gSubmit.attach(vm, ring);
	const IOReturn timer = gTimer.attach(&gTimerIo, NativeAdrenoTimeCp);
	const unsigned ias = NativeAdrenoGpuContextInputBits();
	gInfo.va_size = ias > 32 ? (1ull << ias) - GpuClientVaStart : 0;
	gClock = commandClock();
	progress(0xc1);
	const IOReturn published = attached ? attached :
	    native_adreno_publish(vm, &gSubmit, ring, &gClock, timer ? nullptr : &gTimer, &gInfo, ias, 40);
	say("publish: submit %x timer %x ias %u va %llx -> %x", unsigned(attached), unsigned(timer), ias,
	    (unsigned long long)gInfo.va_size, unsigned(published));
	if (published) {
		return false;
	}
	progress(0xc2);
	AGXAccelerator *accelerator = new AGXAccelerator;
	if (!accelerator || !accelerator->init()) {
		say("accelerator: allocation failed");
		return false;
	}
	// The keys Metal's _MTLRegisterDevices reads; the bundle reaches /System/Library/Extensions through the GPU addon
	// mount. NativeSandboxGrantProcess (zzw-native-adreno-sandbox-grant) lets every Metal client open it.
	accelerator->setProperty("MetalPluginName", "NativeAdrenoMetal");
	accelerator->setProperty("MetalPluginClassName", "NativeAdrenoMetalDevice");
	accelerator->setProperty("NativeSandboxGrantProcess", "*");
	if (!accelerator->attach(IOService::getPlatform())) {
		accelerator->release();
		say("accelerator: attach failed");
		return false;
	}
	accelerator->registerService();
	say("accelerator: IOAcceleratorES/AGXAccelerator registered, MetalPluginName NativeAdrenoMetal");
	return true;
}

void
publishReport()
{
	uint32_t closed = 0;
	const uint32_t opened = native_adreno_publish_stats(&closed);
	char text[96];
	snprintf(text, sizeof(text), "clients opened %u closed %u", opened, closed);
	printf("NX769J GPU %s\n", text);
}
} // namespace nx769j_gpu
