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
#include <libkern/c++/OSData.h>

extern "C" struct proc *current_proc(void);
extern "C" int proc_getpid(struct proc *);

#define HOUJI_FB_LOG(fmt, ...) IOLog("HOUJI-FB: " fmt "\n", ##__VA_ARGS__)

static unsigned houjiCountServices(const char *cls);

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

class IOMobileFramebufferUserClient : public IOUserClient {
	OSDeclareDefaultStructors(IOMobileFramebufferUserClient);
public:
	IOMobileFramebuffer *fOwner = nullptr;
	task_t            fTask = TASK_NULL;
	mach_port_t       fPort = MACH_PORT_NULL;
	uint32_t          fMethodLogCount = 0;

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
OSDefineMetaClassAndStructors(IOMobileFramebufferUserClient, IOUserClient);

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

	setProperty(kIOUserClientClassKey, "IOMobileFramebufferUserClient");
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
		if (fVsyncCount <= 3600) {
			HOUJI_FB_LOG("services fb=%u hid=%u surf=%u res=%u",
			    houjiCountServices("IOMobileFramebuffer"),
			    houjiCountServices("IOHIDSystem"),
			    houjiCountServices("IOSurfaceRoot"),
			    houjiCountServices("IOResources"));
		}
	}
	sender->wakeAtTime(mach_absolute_time() + fPeriod);
}

IOReturn
IOMobileFramebuffer::newUserClient(task_t owningTask, void *securityID, UInt32 type,
    OSDictionary *properties, IOUserClient **handler)
{
	IOMobileFramebufferUserClient *client = new IOMobileFramebufferUserClient;
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
	HOUJI_FB_LOG("user client opened pid %d type %u", proc_getpid(current_proc()), type);
	return kIOReturnSuccess;
}

bool
IOMobileFramebufferUserClient::initWithTask(task_t owningTask, void *securityID, UInt32 type)
{
	if (!IOUserClient::initWithTask(owningTask, securityID, type)) {
		return false;
	}
	fTask = owningTask;
	return true;
}

bool
IOMobileFramebufferUserClient::start(IOService *provider)
{
	return IOUserClient::start(provider);
}

IOReturn
IOMobileFramebufferUserClient::clientClose(void)
{
	HOUJI_FB_LOG("user client closed pid %d swaps %u",
	    proc_getpid(current_proc()), fOwner ? fOwner->fSwapCount : 0);
	terminate();
	return kIOReturnSuccess;
}

IOReturn
IOMobileFramebufferUserClient::registerNotificationPort(mach_port_t port, UInt32 type, io_user_reference_t refCon)
{
	fPort = port;
	HOUJI_FB_LOG("notification port type %u", type);
	return kIOReturnSuccess;
}

IOReturn
IOMobileFramebufferUserClient::externalMethod(uint32_t selector, IOExternalMethodArguments *args,
    IOExternalMethodDispatch *dispatch, OSObject *target, void *reference)
{
	uint64_t out0 = 0, out1 = 0;
	uint32_t outputCount = 0;
	bool logMethod = fMethodLogCount < 96;
	if (logMethod) {
		fMethodLogCount++;
		HOUJI_FB_LOG("method pid=%d selector=%u in=%u out=%u structIn=%llu structOut=%llu values=%llu,%llu",
		    proc_getpid(current_proc()), selector, args->scalarInputCount,
		    args->scalarOutputCount, (unsigned long long)args->structureInputSize,
		    (unsigned long long)args->structureOutputSize,
		    (unsigned long long)(args->scalarInputCount > 0 ? args->scalarInput[0] : 0),
		    (unsigned long long)(args->scalarInputCount > 1 ? args->scalarInput[1] : 0));
	}

	switch (selector) {
	case kSelGetDisplaySize:
		out0 = fOwner->fWidth;
		out1 = fOwner->fHeight;
		outputCount = 2;
		break;
	case kSelIsMainDisplay:
		out0 = 1;
		outputCount = 1;
		break;
	case kSelGetDotPitch:
		out0 = 0x10000;   /* 1.0 in 16.16, not measured */
		outputCount = 1;
		break;
	case kSelGetID:
		out0 = 1;
		outputCount = 1;
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
	case 57:
	case 74:
	case 79:
	case 84:
		HOUJI_FB_LOG("known-unimplemented selector=%u", selector);
		return kIOReturnUnsupported;
	case kSelGetLayerDefaultSurface:
		/* Phase 2 returns a real surface port here. */
		HOUJI_FB_LOG("default surface request (not bridged yet)");
		if (logMethod) HOUJI_FB_LOG("method result selector=%u rc=%#x", selector, kIOReturnUnsupported);
		return kIOReturnUnsupported;
	default:
		if (logMethod) HOUJI_FB_LOG("selector %u accepted", selector);
		break;
	}
	if (outputCount != 0) {
		if (args->scalarOutput == nullptr || args->scalarOutputCount < outputCount) {
			HOUJI_FB_LOG("method selector=%u needs %u scalar outputs", selector, outputCount);
			return kIOReturnBadArgument;
		}
		args->scalarOutput[0] = out0;
		if (outputCount == 2) args->scalarOutput[1] = out1;
		args->scalarOutputCount = outputCount;
	} else {
		if (args->scalarOutputCount >= 1) args->scalarOutput[0] = out0;
		if (args->scalarOutputCount >= 2) args->scalarOutput[1] = out1;
	}
	if (logMethod) {
		HOUJI_FB_LOG("method result selector=%u rc=0 count=%u values=%llu,%llu",
		    selector, args->scalarOutputCount,
		    (unsigned long long)out0, (unsigned long long)out1);
	}
	return kIOReturnSuccess;
}

static unsigned
houjiCountServices(const char *cls)
{
	unsigned n = 0;
	OSDictionary *m = OSDictionary::withCapacity(1);

	if (m == nullptr) {
		return 0;
	}
	OSString *s = OSString::withCString(cls);
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
	return n;
}

class HoujiDisplayNub : public IOPlatformDevice {
	OSDeclareDefaultStructors(HoujiDisplayNub);
public:
	bool init(OSDictionary *dict) override {
		if (!IOPlatformDevice::init(dict)) return false;
		static char compatible[] = "houji,display";
		static char deviceType[] = "display-subsystem";
		PE_Video video = {};
		if (PE_current_console(&video) != 0 || video.v_width == 0 || video.v_height == 0) {
			return false;
		}
		uint32_t width = (uint32_t)video.v_width;
		uint32_t height = (uint32_t)video.v_height;
		setName("display0");
		return setProperty("compatible", compatible, sizeof(compatible)) &&
		       setProperty("device_type", deviceType, sizeof(deviceType)) &&
		       setProperty("canvas-width", &width, sizeof(width)) &&
		       setProperty("canvas-height", &height, sizeof(height));
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
	IOService *provider = platform;
	IORegistryEntry *armIO = IORegistryEntry::fromPath("/arm-io", gIODTPlane);
	if (armIO) {
		HoujiDisplayNub *nub = new HoujiDisplayNub;
		if (nub != nullptr) {
			if (!nub->init(nullptr)) {
				nub->release();
			} else if (!nub->attach(platform)) {
				nub->release();
			} else if (!nub->attachToParent(armIO, gIODTPlane)) {
				nub->detach(platform);
				nub->release();
			} else {
				OSData *type = OSDynamicCast(OSData, nub->getProperty("device_type"));
				OSData *compatible = OSDynamicCast(OSData, nub->getProperty("compatible"));
				OSData *width = OSDynamicCast(OSData, nub->getProperty("canvas-width"));
				OSData *height = OSDynamicCast(OSData, nub->getProperty("canvas-height"));
				bool valid = type != nullptr &&
				    type->getLength() == sizeof("display-subsystem") &&
				    memcmp(type->getBytesNoCopy(), "display-subsystem", sizeof("display-subsystem")) == 0 &&
				    compatible != nullptr && compatible->getLength() == sizeof("houji,display") &&
				    memcmp(compatible->getBytesNoCopy(), "houji,display", sizeof("houji,display")) == 0 &&
				    width != nullptr && width->getLength() == sizeof(uint32_t) &&
				    height != nullptr && height->getLength() == sizeof(uint32_t) &&
				    nub->getParentEntry(gIODTPlane) == armIO &&
				    nub->getProvider() == platform;
				if (valid && nub->start(platform)) {
					nub->registerService();
					provider = nub;
					char path[256];
					int pathSize = sizeof(path);
					if (nub->getPath(path, &pathSize, gIODTPlane)) {
						HOUJI_FB_LOG("enumeration DT=%s type=OSData canvas=4,4 service-parent=%s",
						    path, nub->getProvider()->getName());
					}
				} else {
					nub->detachFromParent(armIO, gIODTPlane);
					nub->detach(platform);
					nub->release();
				}
			}
		}
	}
	if (armIO != nullptr) armIO->release();
	if (provider == platform) {
		HOUJI_FB_LOG("enumeration precondition failed; retaining platform-provider service");
	}

	IOMobileFramebuffer *fb = new IOMobileFramebuffer;
	if (fb == nullptr || !fb->init(nullptr) || !fb->attach(provider) || !fb->start(provider)) {
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
	{
		int on = 0;
		PE_parse_boot_argn("houji_hid", &on, sizeof(on));
		if (on) {
			IOService *resources = IOService::getResourceService();
			IOService *hid = OSDynamicCast(IOService,
			    OSMetaClass::allocClassWithName("IOHIDSystem"));
			if (resources == nullptr) {
				HOUJI_FB_LOG("no IOResources for IOHIDSystem");
			} else if (hid == nullptr) {
				HOUJI_FB_LOG("IOHIDSystem alloc failed");
			} else if (!hid->init(nullptr) || !hid->attach(resources)) {
				HOUJI_FB_LOG("IOHIDSystem attach failed");
				hid->release();
			} else if (!hid->start(resources)) {
				HOUJI_FB_LOG("IOHIDSystem start failed");
			} else {
				hid->registerService();
				HOUJI_FB_LOG("IOHIDSystem published");
			}
		}
	}
}
