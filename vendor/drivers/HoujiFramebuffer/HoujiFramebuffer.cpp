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
#include <IOKit/IOMemoryDescriptor.h>

extern "C" struct proc *current_proc(void);
extern "C" int proc_getpid(struct proc *);
extern "C" void houji_legacy_bootstrap_checkpoint(void) __attribute__((weak_import));

#define HOUJI_FB_LOG(fmt, ...) IOLog("HOUJI-FB: " fmt "\n", ##__VA_ARGS__)

static unsigned houjiCountServices(const char *cls);

/*
 * HOUJI-DUMP: the display-mode contract lives entirely in structured buffers
 * whose layouts only the Apple driver knows. Dumping what the caller hands us
 * (input buffer, and the output buffer as the caller pre-filled it) is the only
 * way to learn those layouts instead of guessing at them.
 */
static void
houjiDumpHex(const char *tag, const void *data, uint64_t len)
{
	static const char hexd[] = "0123456789abcdef";
	static unsigned houjiDumpCount;
	const unsigned char *bytes = (const unsigned char *)data;
	char line[3 * 32 + 1];

	if (data == nullptr || len == 0)
		return;
	if (houjiDumpCount >= 40)
		return;

	for (uint64_t off = 0; off < len && off < 256; off += 32) {
		uint64_t n = (len - off < 32) ? (len - off) : 32;

		houjiDumpCount++;
		for (uint64_t i = 0; i < n; i++) {
			line[i * 3] = hexd[bytes[off + i] >> 4];
			line[i * 3 + 1] = hexd[bytes[off + i] & 15];
			line[i * 3 + 2] = ' ';
		}
		line[n * 3] = 0;
		HOUJI_FB_LOG("dump %s +%llu: %s", tag, (unsigned long long)off, line);
	}
}

static void
houjiDumpCall(IOExternalMethodArguments *args)
{
	const void *in = args->structureInput;
	uint64_t inLen = args->structureInputSize;
	IOMemoryMap *inMap = nullptr;
	void *out = args->structureOutput;
	uint64_t outLen = args->structureOutputSize;
	IOMemoryMap *outMap = nullptr;

	if (in == nullptr && args->structureInputDescriptor != nullptr) {
		inMap = args->structureInputDescriptor->map();
		if (inMap != nullptr) {
			in = (const void *)inMap->getAddress();
			inLen = args->structureInputDescriptor->getLength();
		}
	}
	if (out == nullptr && args->structureOutputDescriptor != nullptr) {
		outMap = args->structureOutputDescriptor->map();
		if (outMap != nullptr) {
			out = (void *)outMap->getAddress();
			outLen = args->structureOutputDescriptor->getLength();
		}
	}
	houjiDumpHex("in", in, inLen);
	houjiDumpHex("out", out, outLen);
	if (inMap != nullptr)
		inMap->release();
	if (outMap != nullptr)
		outMap->release();
}

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
	IOMemoryMap      *fMap = nullptr;
	volatile uint32_t *fPixels = nullptr;
	bool              fBootUi = false;
	uint64_t          fBootUiStart = 0;

	bool start(IOService *provider) override;
	void stop(IOService *provider) override;
	void vsyncFired(OSObject *owner, IOTimerEventSource *sender);
	void drawBootUi(uint32_t permille);
	bool matchPropertyTable(OSDictionary *table, SInt32 *score) override;
	IOReturn newUserClient(task_t owningTask, void *securityID, UInt32 type,
	    OSDictionary *properties, IOUserClient **handler) override;
};

OSDefineMetaClassAndStructors(IOMobileFramebuffer, IOService);
OSDefineMetaClassAndStructors(IOMobileFramebufferUserClient, IOUserClient);

static const unsigned char houjiAppleMask[2048] = {
0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,128,0,0,0,0,0,0,0,0,0,0,0,0,0,0,31,128,0,0,0,0,0,0,0,0,0,0,0,0,0,0,255,128,0,0,0,0,0,0,0,0,0,0,0,0,0,3,255,128,0,0,0,0,0,0,0,0,0,0,0,0,0,15,255,128,0,0,0,0,0,0,0,0,0,0,0,0,0,31,255,0,0,0,0,0,0,0,0,0,0,0,0,0,0,127,255,0,0,0,0,0,0,0,0,0,0,0,0,0,0,255,255,0,0,0,0,0,0,0,0,0,0,0,0,0,1,255,255,0,0,0,0,0,0,0,0,0,0,0,0,0,3,255,255,0,0,0,0,0,0,0,0,0,0,0,0,0,7,255,254,0,0,0,0,0,0,0,0,0,0,0,0,0,15,255,254,0,0,0,0,0,0,0,0,0,0,0,0,0,15,255,254,0,0,0,0,0,0,0,0,0,0,0,0,0,31,255,252,0,0,0,0,0,0,0,0,0,0,0,0,0,63,255,252,0,0,0,0,0,0,0,0,0,0,0,0,0,63,255,248,0,0,0,0,0,0,0,0,0,0,0,0,0,63,255,240,0,0,0,0,0,0,0,0,0,0,0,0,0,127,255,240,0,0,0,0,0,0,0,0,0,0,0,0,0,127,255,224,0,0,0,0,0,0,0,0,0,0,0,0,0,255,255,192,0,0,0,0,0,0,0,0,0,0,0,0,0,255,255,128,0,0,0,0,0,0,0,0,0,0,0,0,0,255,255,0,0,0,0,0,0,0,0,0,0,0,0,0,0,255,254,0,0,0,0,0,0,0,0,0,0,0,0,0,0,255,252,0,0,0,0,0,0,0,0,0,0,0,0,0,0,255,248,0,0,0,0,0,0,0,0,0,0,0,0,0,1,255,224,0,0,0,0,0,0,0,0,0,0,0,0,0,1,255,128,0,0,0,0,0,0,0,0,0,0,0,0,0,1,254,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,240,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,7,240,0,0,0,0,0,0,0,0,1,255,192,0,0,0,255,255,0,0,0,0,0,0,0,0,31,255,252,0,0,7,255,255,224,0,0,0,0,0,0,0,127,255,255,0,0,63,255,255,248,0,0,0,0,0,0,1,255,255,255,224,0,255,255,255,252,0,0,0,0,0,0,7,255,255,255,252,15,255,255,255,255,0,0,0,0,0,0,15,255,255,255,255,255,255,255,255,255,128,0,0,0,0,0,31,255,255,255,255,255,255,255,255,255,192,0,0,0,0,0,63,255,255,255,255,255,255,255,255,255,224,0,0,0,0,0,127,255,255,255,255,255,255,255,255,255,240,0,0,0,0,0,255,255,255,255,255,255,255,255,255,255,248,0,0,0,0,1,255,255,255,255,255,255,255,255,255,255,252,0,0,0,0,3,255,255,255,255,255,255,255,255,255,255,252,0,0,0,0,7,255,255,255,255,255,255,255,255,255,255,248,0,0,0,0,15,255,255,255,255,255,255,255,255,255,255,240,0,0,0,0,15,255,255,255,255,255,255,255,255,255,255,192,0,0,0,0,31,255,255,255,255,255,255,255,255,255,255,128,0,0,0,0,31,255,255,255,255,255,255,255,255,255,255,0,0,0,0,0,63,255,255,255,255,255,255,255,255,255,254,0,0,0,0,0,63,255,255,255,255,255,255,255,255,255,252,0,0,0,0,0,127,255,255,255,255,255,255,255,255,255,252,0,0,0,0,0,127,255,255,255,255,255,255,255,255,255,248,0,0,0,0,0,255,255,255,255,255,255,255,255,255,255,240,0,0,0,0,0,255,255,255,255,255,255,255,255,255,255,240,0,0,0,0,0,255,255,255,255,255,255,255,255,255,255,224,0,0,0,0,1,255,255,255,255,255,255,255,255,255,255,224,0,0,0,0,1,255,255,255,255,255,255,255,255,255,255,224,0,0,0,0,1,255,255,255,255,255,255,255,255,255,255,192,0,0,0,0,1,255,255,255,255,255,255,255,255,255,255,192,0,0,0,0,1,255,255,255,255,255,255,255,255,255,255,192,0,0,0,0,3,255,255,255,255,255,255,255,255,255,255,192,0,0,0,0,3,255,255,255,255,255,255,255,255,255,255,192,0,0,0,0,3,255,255,255,255,255,255,255,255,255,255,192,0,0,0,0,3,255,255,255,255,255,255,255,255,255,255,192,0,0,0,0,3,255,255,255,255,255,255,255,255,255,255,192,0,0,0,0,3,255,255,255,255,255,255,255,255,255,255,192,0,0,0,0,3,255,255,255,255,255,255,255,255,255,255,192,0,0,0,0,3,255,255,255,255,255,255,255,255,255,255,192,0,0,0,0,3,255,255,255,255,255,255,255,255,255,255,192,0,0,0,0,3,255,255,255,255,255,255,255,255,255,255,192,0,0,0,0,3,255,255,255,255,255,255,255,255,255,255,224,0,0,0,0,3,255,255,255,255,255,255,255,255,255,255,224,0,0,0,0,3,255,255,255,255,255,255,255,255,255,255,224,0,0,0,0,1,255,255,255,255,255,255,255,255,255,255,240,0,0,0,0,1,255,255,255,255,255,255,255,255,255,255,240,0,0,0,0,1,255,255,255,255,255,255,255,255,255,255,248,0,0,0,0,1,255,255,255,255,255,255,255,255,255,255,248,0,0,0,0,1,255,255,255,255,255,255,255,255,255,255,252,0,0,0,0,0,255,255,255,255,255,255,255,255,255,255,252,0,0,0,0,0,255,255,255,255,255,255,255,255,255,255,254,0,0,0,0,0,255,255,255,255,255,255,255,255,255,255,255,0,0,0,0,0,255,255,255,255,255,255,255,255,255,255,255,128,0,0,0,0,127,255,255,255,255,255,255,255,255,255,255,192,0,0,0,0,127,255,255,255,255,255,255,255,255,255,255,224,0,0,0,0,127,255,255,255,255,255,255,255,255,255,255,240,0,0,0,0,127,255,255,255,255,255,255,255,255,255,255,248,0,0,0,0,63,255,255,255,255,255,255,255,255,255,255,254,0,0,0,0,63,255,255,255,255,255,255,255,255,255,255,255,0,0,0,0,31,255,255,255,255,255,255,255,255,255,255,255,192,0,0,0,31,255,255,255,255,255,255,255,255,255,255,255,192,0,0,0,31,255,255,255,255,255,255,255,255,255,255,255,128,0,0,0,15,255,255,255,255,255,255,255,255,255,255,255,128,0,0,0,15,255,255,255,255,255,255,255,255,255,255,255,0,0,0,0,7,255,255,255,255,255,255,255,255,255,255,255,0,0,0,0,7,255,255,255,255,255,255,255,255,255,255,255,0,0,0,0,3,255,255,255,255,255,255,255,255,255,255,254,0,0,0,0,3,255,255,255,255,255,255,255,255,255,255,254,0,0,0,0,1,255,255,255,255,255,255,255,255,255,255,252,0,0,0,0,1,255,255,255,255,255,255,255,255,255,255,252,0,0,0,0,0,255,255,255,255,255,255,255,255,255,255,248,0,0,0,0,0,255,255,255,255,255,255,255,255,255,255,248,0,0,0,0,0,127,255,255,255,255,255,255,255,255,255,240,0,0,0,0,0,63,255,255,255,255,255,255,255,255,255,224,0,0,0,0,0,63,255,255,255,255,255,255,255,255,255,224,0,0,0,0,0,31,255,255,255,255,255,255,255,255,255,192,0,0,0,0,0,15,255,255,255,255,255,255,255,255,255,128,0,0,0,0,0,15,255,255,255,255,255,255,255,255,255,128,0,0,0,0,0,7,255,255,255,255,255,255,255,255,255,0,0,0,0,0,0,3,255,255,255,255,255,255,255,255,254,0,0,0,0,0,0,1,255,255,255,255,255,255,255,255,252,0,0,0,0,0,0,1,255,255,255,255,255,255,255,255,252,0,0,0,0,0,0,0,255,255,255,255,255,255,255,255,248,0,0,0,0,0,0,0,127,255,255,255,255,255,255,255,240,0,0,0,0,0,0,0,63,255,255,255,255,255,255,255,224,0,0,0,0,0,0,0,31,255,255,255,255,255,255,255,192,0,0,0,0,0,0,0,15,255,255,255,255,255,255,255,128,0,0,0,0,0,0,0,7,255,255,254,7,255,255,255,0,0,0,0,0,0,0,0,1,255,255,224,0,63,255,252,0,0,0,0,0,0,0,0,0,255,255,0,0,15,255,248,0,0,0,0,0,0,0,0,0,63,248,0,0,1,255,224,0,0,0,0,0,0,0,0,0,7,224,0,0,0,31,128,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
};

/* 128x128 apple mask, bit set = ink; drawn scaled into the boot mark. */
static inline bool
houjiApplePixel(double x, double y)
{
	int mx = (int)((x + 1.0) * 63.5);
	int my = (int)((y + 1.0) * 63.5);
	if (mx < 0 || mx > 127 || my < 0 || my > 127) {
		return false;
	}
	unsigned bit = (unsigned)(my * 128 + mx);
	return ((houjiAppleMask[bit >> 3] >> (7 - (bit & 7))) & 1) != 0;
}

void
IOMobileFramebuffer::drawBootUi(uint32_t permille)
{
	volatile uint32_t *dst = fPixels;
	uint32_t w = fWidth, h = fHeight, stride = fRowBytes;
	if (dst == nullptr || w == 0 || h == 0 || stride < w * 4) {
		return;
	}
	const uint32_t black = 0xff000000U, white = 0xffffffffU;
	for (uint32_t y = 0; y < h; y++) {
		volatile uint32_t *row = dst + (uint64_t)y * (stride / 4);
		for (uint32_t x = 0; x < w; x++) {
			row[x] = black;
		}
	}
	uint32_t side = h / 4;
	if (side > w / 3) side = w / 3;
	uint32_t cx = w / 2, cy = (uint32_t)(h * 0.42);
	for (uint32_t y = 0; y < side; y++) {
		for (uint32_t x = 0; x < side; x++) {
			double nx = (2.0 * x / (double)side) - 1.0;
			double ny = (2.0 * y / (double)side) - 1.0;
			if (houjiApplePixel(nx, ny)) {
				uint32_t px = cx - side / 2 + x, py = cy - side / 2 + y;
				if (px < w && py < h) {
					dst[(uint64_t)py * (stride / 4) + px] = white;
				}
			}
		}
	}
	(void)permille;
}

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
	setProperty("compatible", "houji,display");
	uint32_t hz = 60;
	PE_parse_boot_argn("houji_fb_hz", &hz, sizeof(hz));
	if (hz != 120) {
		hz = 60;
	}
	nanoseconds_to_absolutetime(NSEC_PER_SEC / hz, &fPeriod);
	uint64_t interval = (1ULL << 32) / hz;
	uint64_t machInterval = fPeriod;
	uint64_t refresh[6] = { interval, machInterval, interval, machInterval, 0, 0 };
	OSData *refreshData = OSData::withBytes(refresh, sizeof(refresh));
	if (refreshData == nullptr || !setProperty("IOMFBDisplayRefresh", refreshData)) {
		if (refreshData != nullptr) refreshData->release();
		HOUJI_FB_LOG("refresh property setup failed");
		return false;
	}
	refreshData->release();
	HOUJI_FB_LOG("refresh property 60Hz interval=%llu", (unsigned long long)interval);
	{
		uint32_t bootui = 0;
		PE_parse_boot_argn("houji-bootui", &bootui, sizeof(bootui));
		uint64_t bytes = (uint64_t)fRowBytes * fHeight;
		IOMemoryDescriptor *mem = IOMemoryDescriptor::withPhysicalAddress(
		    (IOPhysicalAddress)fBase, (IOByteCount)bytes, kIODirectionOut);
		if (mem != nullptr) {
			fMap = mem->map();
			mem->release();
			if (fMap != nullptr) {
				fPixels = (volatile uint32_t *)fMap->getVirtualAddress();
			}
		}
		if (bootui != 0 && fPixels != nullptr) {
			fBootUi = true;
			fBootUiStart = fVsyncCount;
			drawBootUi(0);
			HOUJI_FB_LOG("boot ui on, %llu bytes mapped", (unsigned long long)bytes);
		} else {
			HOUJI_FB_LOG("boot ui off (arg=%u pixels=%p)", bootui, fPixels);
		}
	}

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
	fBootUi = false;
	if (fMap != nullptr) {
		fMap->release();
		fMap = nullptr;
		fPixels = nullptr;
	}
	IOService::stop(provider);
}

void
IOMobileFramebuffer::vsyncFired(OSObject *owner, IOTimerEventSource *sender)
{
	fVsyncCount++;
	if ((fVsyncCount % 600) == 0) {
		HOUJI_FB_LOG("vsync %llu swaps %u", fVsyncCount, fSwapCount);
		if (houji_legacy_bootstrap_checkpoint != nullptr)
			houji_legacy_bootstrap_checkpoint();
		if (fVsyncCount <= 3600) {
			HOUJI_FB_LOG("services fb=%u hid=%u surf=%u res=%u",
			    houjiCountServices("IOMobileFramebuffer"),
			    houjiCountServices("IOHIDSystem"),
			    houjiCountServices("IOSurfaceRoot"),
			    houjiCountServices("IOResources"));
		}
	}
	if (fBootUi && (fVsyncCount % 60) == 0) {
		uint64_t ticks = fVsyncCount - fBootUiStart;
		uint32_t permille = (uint32_t)(ticks * 1000 / (90ULL * 60ULL));
		if (permille > 950) permille = 950;
		drawBootUi(permille);
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
	fBootUi = false;
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
		houjiDumpCall(args);
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
	if (houji_legacy_bootstrap_checkpoint != nullptr)
		houji_legacy_bootstrap_checkpoint();

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
