/*
 * HOUJI-FB: minimal IOMobileFramebuffer service, written for this port.
 *
 * Registers a service whose class name is IOMobileFramebuffer so the iOS
 * IOMobileFramebuffer.framework can find it, implements the user-client
 * selectors CoreAnimation uses, and drives a software vsync timer. The first
 * phase only proves the service path: swaps are parsed and logged, and the
 * presentation step is added once the surface bridge exists.
 */
#include <IOKit/IOService.h>
#include <IOKit/IOUserClient.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/IOTimerEventSource.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOKitKeys.h>
#include <pexpert/pexpert.h>
#include <kern/clock.h>
#include <mach/mach_time.h>
#include <kern/task.h>

#define HOUJI_FB_LOG(fmt, ...) IOLog("HOUJI-FB: " fmt "\n", ##__VA_ARGS__)

/* User-client selectors observed from the framework's call sites. */
enum {
	kSelGetLayerDefaultSurface = 3,
	kSelSwapBegin              = 4,
	kSelSwapEnd                = 5,
	kSelSwapWait               = 6,
	kSelGetID                  = 7,
	kSelGetDisplaySize         = 8,
	kSelIsMainDisplay          = 18,
	kSelGetDotPitch            = 28,
	kSelEnableNotifications    = 72,
};

class IOMobileFramebuffer : public IOService {
	OSDeclareDefaultStructors(IOMobileFramebuffer);
public:
	virtual IOReturn getDisplaySize(uint32_t *w, uint32_t *h) = 0;
};

OSDefineMetaClassAndStructors(IOMobileFramebuffer, IOService);

bool
IOMobileFramebuffer::init(OSDictionary *dict)
{
	return IOService::init(dict);
}

class HoujiFramebuffer;

class HoujiFramebufferClient : public IOUserClient {
	OSDeclareDefaultStructors(HoujiFramebufferClient);
public:
	HoujiFramebuffer *fOwner = nullptr;
	task_t            fTask = TASK_NULL;
	mach_port_t       fPort = MACH_PORT_NULL;

	bool initWithTask(task_t owningTask, void *securityID, UInt32 type) override;
	bool start(IOService *provider) override;
	IOReturn clientClose(void) override;
	IOReturn registerNotificationPort(mach_port_t port, UInt32 type, io_user_reference_t refCon) override;
	IOReturn externalMethod(uint32_t selector, IOExternalMethodArguments *args,
	    IOExternalMethodDispatch *dispatch, OSObject *target, void *reference) override;
};

class HoujiFramebuffer : public IOMobileFramebuffer {
	OSDeclareDefaultStructors(HoujiFramebuffer);
public:
	IOService        *fProvider = nullptr;
	IOWorkLoop       *fWorkLoop = nullptr;
	IOTimerEventSource *fVsync = nullptr;
	uint64_t          fPeriod = 0;
	uint64_t          fVsyncCount = 0;
	uint32_t          fWidth = 0;
	uint32_t          fHeight = 0;
	uint32_t          fRowBytes = 0;
	uint64_t          fBase = 0;
	uint32_t          fSwapCount = 0;

	bool start(IOService *provider) override;
	void stop(IOService *provider) override;
	IOReturn getDisplaySize(uint32_t *w, uint32_t *h) override;
	void vsyncFired(OSObject *owner, IOTimerEventSource *sender);
	IOReturn newUserClient(task_t owningTask, void *securityID, UInt32 type,
	    OSDictionary *properties, IOUserClient **handler) override;
};

OSDefineMetaClassAndStructors(HoujiFramebuffer, IOMobileFramebuffer);

bool
HoujiFramebuffer::start(IOService *provider)
{
	PE_Video video;

	if (!IOMobileFramebuffer::start(provider)) {
		return false;
	}
	fProvider = provider;
	PE_current_console(&video);
	fBase = video.v_baseAddr;
	fWidth = (uint32_t)video.v_width;
	fHeight = (uint32_t)video.v_height;
	fRowBytes = (uint32_t)video.v_rowBytes;
	HOUJI_FB_LOG("boot framebuffer %ux%u stride %u at %#llx", fWidth, fHeight, fRowBytes, fBase);
	if (fWidth == 0 || fHeight == 0 || fRowBytes < fWidth * 4) {
		HOUJI_FB_LOG("no usable boot framebuffer");
		return false;
	}

	setProperty(kIOUserClientClassKey, "HoujiFramebufferClient");
	setProperty("IOMFBDisplayRefresh", true);
	uint32_t hz = 60;
	PE_parse_boot_argn("houji_fb_hz", &hz, sizeof(hz));
	if (hz != 120) {
		hz = 60;
	}
	nanoseconds_to_absolutetime(NSEC_PER_SEC / hz, &fPeriod);

	fWorkLoop = IOWorkLoop::workLoop();
	fVsync = IOTimerEventSource::timerEventSource(this, OSMemberFunctionCast(
	    IOTimerEventSource::Action, this, &HoujiFramebuffer::vsyncFired));
	if (fWorkLoop == nullptr || fVsync == nullptr ||
	    fWorkLoop->addEventSource(fVsync) != kIOReturnSuccess) {
		HOUJI_FB_LOG("work loop setup failed");
		return false;
	}
	fVsync->wakeAtTime(mach_absolute_time() + fPeriod);
	registerService();
	HOUJI_FB_LOG("registered %ux%u, vsync %u Hz", fWidth, fHeight, hz);
	return true;
}

void
HoujiFramebuffer::stop(IOService *provider)
{
	if (fVsync != nullptr) {
		fVsync->cancelTimeout();
	}
	IOMobileFramebuffer::stop(provider);
}

IOReturn
HoujiFramebuffer::getDisplaySize(uint32_t *w, uint32_t *h)
{
	*w = fWidth;
	*h = fHeight;
	return kIOReturnSuccess;
}

void
HoujiFramebuffer::vsyncFired(OSObject *owner, IOTimerEventSource *sender)
{
	fVsyncCount++;
	if ((fVsyncCount % 600) == 0) {
		HOUJI_FB_LOG("vsync %llu swaps %u", fVsyncCount, fSwapCount);
	}
	sender->wakeAtTime(mach_absolute_time() + fPeriod);
}

IOReturn
HoujiFramebuffer::newUserClient(task_t owningTask, void *securityID, UInt32 type,
    OSDictionary *properties, IOUserClient **handler)
{
	HoujiFramebufferClient *client = new HoujiFramebufferClient;
	if (client == nullptr) {
		return kIOReturnNoMemory;
	}
	if (!client->initWithTask(owningTask, securityID, type) ||
	    !client->attach(this) || !client->start(this)) {
		client->detach(this);
		client->release();
		return kIOReturnError;
	}
	client->fOwner = this;
	*handler = client;
	HOUJI_FB_LOG("user client opened type %u", type);
	return kIOReturnSuccess;
}

OSDefineMetaClassAndStructors(HoujiFramebufferClient, IOUserClient);

bool
HoujiFramebufferClient::initWithTask(task_t owningTask, void *securityID, UInt32 type)
{
	if (!IOUserClient::initWithTask(owningTask, securityID, type)) {
		return false;
	}
	fTask = owningTask;
	return true;
}

bool
HoujiFramebufferClient::start(IOService *provider)
{
	return IOUserClient::start(provider);
}

IOReturn
HoujiFramebufferClient::clientClose(void)
{
	terminate();
	return kIOReturnSuccess;
}

IOReturn
HoujiFramebufferClient::registerNotificationPort(mach_port_t port, UInt32 type, io_user_reference_t refCon)
{
	fPort = port;
	HOUJI_FB_LOG("notification port type %u", type);
	return kIOReturnSuccess;
}

IOReturn
HoujiFramebufferClient::externalMethod(uint32_t selector, IOExternalMethodArguments *args,
    IOExternalMethodDispatch *dispatch, OSObject *target, void *reference)
{
	uint64_t out0 = 0, out1 = 0, out2 = 0, out3 = 0;
	uint32_t count = 0;

	switch (selector) {
	case kSelGetDisplaySize:
		out0 = fOwner->fWidth;
		out1 = fOwner->fHeight;
		count = 2;
		break;
	case kSelIsMainDisplay:
		out0 = 1;
		count = 1;
		break;
	case kSelGetDotPitch:
		out0 = 0x10000;   /* 1.0 in 16.16, not measured */
		count = 1;
		break;
	case kSelGetID:
		out0 = 1;
		count = 1;
		break;
	case kSelSwapBegin:
		fOwner->fSwapCount++;
		HOUJI_FB_LOG("swap begin #%u", fOwner->fSwapCount);
		break;
	case kSelSwapEnd:
		HOUJI_FB_LOG("swap end #%u len %llu", fOwner->fSwapCount,
		    (unsigned long long)args->structureInputSize);
		break;
	case kSelSwapWait:
		break;
	case kSelEnableNotifications:
		HOUJI_FB_LOG("notifications %llu", (unsigned long long)
		    (args->scalarInputCount > 0 ? args->scalarInput[0] : 0));
		break;
	case kSelGetLayerDefaultSurface:
		/* Phase 2 returns a real surface port here. */
		HOUJI_FB_LOG("default surface request (not bridged yet)");
		return kIOReturnUnsupported;
	default:
		HOUJI_FB_LOG("selector %u accepted", selector);
		break;
	}
	if (args->scalarOutputCount >= 1) args->scalarOutput[0] = out0;
	if (args->scalarOutputCount >= 2) args->scalarOutput[1] = out1;
	if (args->scalarOutputCount >= 3) args->scalarOutput[2] = out2;
	if (args->scalarOutputCount >= 4) args->scalarOutput[3] = out3;
	(void)count;
	return kIOReturnSuccess;
}

/*
 * Publish the display-subsystem nub. The iOS IOMobileFramebuffer.framework
 * counts /arm-io children with device_type display-subsystem and reads
 * canvas-width/canvas-height from the service's provider.
 */
class HoujiDisplayNub : public IOPlatformDevice {
	OSDeclareDefaultStructors(HoujiDisplayNub);
public:
	bool init(OSDictionary *dict) override {
		if (!IOPlatformDevice::init(dict)) return false;
		setProperty("compatible", "houji,display");
		setProperty("device_type", "display-subsystem");
		setProperty("canvas-width", 1200, 32);
		setProperty("canvas-height", 2670, 32);
		return true;
	}
};
OSDefineMetaClassAndStructors(HoujiDisplayNub, IOPlatformDevice);

extern "C" void
houji_fb_bootstrap(void)
{
	static int done;
	if (done) return;
	done = 1;
	IOService *platform = IOPlatformExpert::getPlatform();
	if (platform == nullptr) {
		HOUJI_FB_LOG("no platform expert");
		return;
	}
	HoujiDisplayNub *nub = new HoujiDisplayNub;
	if (nub == nullptr || !nub->init()) {
		HOUJI_FB_LOG("nub alloc failed");
		return;
	}
	if (!nub->attachToParent(platform, gIODTPlane)) {
		HOUJI_FB_LOG("nub attach failed");
		nub->release();
		return;
	}
	nub->registerService();
	HOUJI_FB_LOG("display nub published");
}
