/*
 * HOUJI-FB: minimal IOMobileFramebuffer service, written for this port.
 *
 * The service class is literally named IOMobileFramebuffer: IOService falls
 * back to the metaclass name when a service has no IOName, so both class
 * matching (IOProviderClass) and name matching (IONameMatch) find it.
 *
 * Phase 1 proves the service path: the user client answers the framework's
 * selectors, swaps are parsed and logged, and a 60 Hz timer drives vsync.
 * Presentation (swap -> boot framebuffer copy) is added with the surface
 * bridge in phase 2.
 */
#include <IOKit/IOService.h>
#include <IOKit/IOUserClient.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/IOTimerEventSource.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOKitKeys.h>
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <pexpert/pexpert.h>
#include <kern/clock.h>
#include <mach/mach_time.h>
#include <kern/task.h>
#include <libkern/c++/OSKext.h>

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

class IOMobileFramebuffer;

class HoujiFramebufferClient : public IOUserClient {
	OSDeclareDefaultStructors(HoujiFramebufferClient);
public:
	IOMobileFramebuffer *fOwner = nullptr;
	task_t            fTask = TASK_NULL;
	mach_port_t       fPort = MACH_PORT_NULL;

	bool initWithTask(task_t owningTask, void *securityID, UInt32 type) override;
	bool start(IOService *provider) override;
	IOReturn clientClose(void) override;
	IOReturn registerNotificationPort(mach_port_t port, UInt32 type, io_user_reference_t refCon) override;
	IOReturn externalMethod(uint32_t selector, IOExternalMethodArguments *args,
	    IOExternalMethodDispatch *dispatch, OSObject *target, void *reference) override;
};

class IOMobileFramebuffer : public IOService {
	OSDeclareDefaultStructors(IOMobileFramebuffer);
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
	void vsyncFired(OSObject *owner, IOTimerEventSource *sender);
	bool matchPropertyTable(OSDictionary *table, SInt32 *score) override;
	IOReturn newUserClient(task_t owningTask, void *securityID, UInt32 type,
	    OSDictionary *properties, IOUserClient **handler) override;
};

OSDefineMetaClassAndStructors(IOMobileFramebuffer, IOService);
OSDefineMetaClassAndStructors(HoujiFramebufferClient, IOUserClient);

bool
IOMobileFramebuffer::start(IOService *provider)
{
	PE_Video video;

	if (!IOService::start(provider)) {
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
	setProperty("compatible", "houji,display");
	uint32_t hz = 60;
	PE_parse_boot_argn("houji_fb_hz", &hz, sizeof(hz));
	if (hz != 120) {
		hz = 60;
	}
	nanoseconds_to_absolutetime(NSEC_PER_SEC / hz, &fPeriod);

	fWorkLoop = IOWorkLoop::workLoop();
	fVsync = IOTimerEventSource::timerEventSource(this, OSMemberFunctionCast(
	    IOTimerEventSource::Action, this, &IOMobileFramebuffer::vsyncFired));
	if (fWorkLoop == nullptr || fVsync == nullptr ||
	    fWorkLoop->addEventSource(fVsync) != kIOReturnSuccess) {
		HOUJI_FB_LOG("work loop setup failed");
		return false;
	}
	fVsync->wakeAtTime(mach_absolute_time() + fPeriod);
	HOUJI_FB_LOG("started %ux%u, vsync %u Hz", fWidth, fHeight, hz);
	return true;
}

bool
IOMobileFramebuffer::matchPropertyTable(OSDictionary *table, SInt32 *score)
{
	static unsigned seen;
	bool r = IOService::matchPropertyTable(table, score);

	if (seen < 32) {
		seen++;
		OSString *pc = OSDynamicCast(OSString, table ? table->getObject(kIOProviderClassKey) : nullptr);
		OSString *nm = OSDynamicCast(OSString, table ? table->getObject(kIONameMatchKey) : nullptr);
		HOUJI_FB_LOG("match: provider=%s name=%s -> %d",
		    pc ? pc->getCStringNoCopy() : "?",
		    nm ? nm->getCStringNoCopy() : "?", (int)r);
	}
	return r;
}

void
IOMobileFramebuffer::stop(IOService *provider)
{
	if (fVsync != nullptr) {
		fVsync->cancelTimeout();
	}
	IOService::stop(provider);
}

void
IOMobileFramebuffer::vsyncFired(OSObject *owner, IOTimerEventSource *sender)
{
	fVsyncCount++;
	if ((fVsyncCount % 600) == 0) {
		HOUJI_FB_LOG("vsync %llu swaps %u", fVsyncCount, fSwapCount);
	}
	sender->wakeAtTime(mach_absolute_time() + fPeriod);
}

IOReturn
IOMobileFramebuffer::newUserClient(task_t owningTask, void *securityID, UInt32 type,
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
	uint64_t out0 = 0, out1 = 0;

	switch (selector) {
	case kSelGetDisplaySize:
		out0 = fOwner->fWidth;
		out1 = fOwner->fHeight;
		break;
	case kSelIsMainDisplay:
		out0 = 1;
		break;
	case kSelGetDotPitch:
		out0 = 0x10000;   /* 1.0 in 16.16, not measured */
		break;
	case kSelGetID:
		out0 = 1;
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
	return kIOReturnSuccess;
}

/*
 * Publish the display-subsystem nub under the platform expert and attach the
 * framebuffer service to it. Nothing matches it automatically: this kernel
 * has no personalities, so the service is started by hand.
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

	IOService *platform = IOService::getPlatform();
	if (platform == nullptr) {
		HOUJI_FB_LOG("no platform expert");
		return;
	}
	HoujiDisplayNub *nub = new HoujiDisplayNub;
	if (nub == nullptr || !nub->init(nullptr) ||
	    !nub->attachToParent(platform, gIODTPlane)) {
		HOUJI_FB_LOG("nub alloc/attach failed");
		if (nub != nullptr) nub->release();
		return;
	}
	nub->registerService();
	HOUJI_FB_LOG("display nub published");

	IOMobileFramebuffer *fb = new IOMobileFramebuffer;
	if (fb == nullptr || !fb->init(nullptr) || !fb->attach(nub) || !fb->start(nub)) {
		HOUJI_FB_LOG("framebuffer service start failed");
		if (fb != nullptr) fb->release();
		return;
	}
	fb->registerService();
	{
		OSDictionary *m = OSDictionary::withCapacity(1);
		if (m != nullptr) {
			OSString *s = OSString::withCString("IOMobileFramebuffer");
			unsigned n = 0;
			if (s != nullptr) {
				m->setObject(kIOProviderClassKey, s);
				auto it = IOService::getMatchingServices(m);
				if (it) {
					while (it->getNextObject() != nullptr) {
						n++;
					}
				}
				s->release();
			}
			m->release();
			HOUJI_FB_LOG("self-match class=%u", n);
		}
		m = OSDictionary::withCapacity(1);
		if (m != nullptr) {
			OSString *s = OSString::withCString("IOMobileFramebuffer");
			unsigned n = 0;
			if (s != nullptr) {
				m->setObject(kIONameMatchKey, s);
				auto it = IOService::getMatchingServices(m);
				if (it) {
					while (it->getNextObject() != nullptr) {
						n++;
					}
				}
				s->release();
			}
			m->release();
			HOUJI_FB_LOG("self-match name=%u", n);
		}
	}
	{
		bool loaded = OSKext::isKextWithIdentifierLoaded("com.apple.iokit.IOHIDFamily");
		int rc = 0;
		if (!loaded) {
			rc = (int)OSKext::loadKextWithIdentifier("com.apple.iokit.IOHIDFamily");
		}
		HOUJI_FB_LOG("IOHIDFamily loaded=%d rc=%d now=%d", loaded, rc,
		    OSKext::isKextWithIdentifierLoaded("com.apple.iokit.IOHIDFamily"));
	}
	{
		OSDictionary *m = OSDictionary::withCapacity(1);
		if (m != nullptr) {
			OSString *s = OSString::withCString("IOHIDSystem");
			unsigned n = 0;
			if (s != nullptr) {
				m->setObject(kIOProviderClassKey, s);
				auto it = IOService::getMatchingServices(m);
				if (it) {
					while (it->getNextObject() != nullptr) {
						n++;
					}
				}
				s->release();
			}
			m->release();
			HOUJI_FB_LOG("IOHIDSystem services=%u", n);
		}
	}
	HOUJI_FB_LOG("IOMobileFramebuffer registered: %s", fb->getName());
}
