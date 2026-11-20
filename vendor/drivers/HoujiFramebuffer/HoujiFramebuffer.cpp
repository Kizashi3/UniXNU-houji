/*
 * HOUJI-FB: minimal HoujiFramebuffer service, written for this port.
 *
 * The service class is literally named HoujiFramebuffer: IOService falls
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
#include <IOKit/IODeviceMemory.h>

extern "C" struct proc *current_proc(void);
extern "C" int proc_getpid(struct proc *);
static void (*houjiLegacyCheckpoint)(void);
extern "C" void
houji_fb_set_legacy_checkpoint(void (*checkpoint)(void))
{
	houjiLegacyCheckpoint = checkpoint;
}

// Return true only after the replacement has started and registered.
static bool (*houjiLegacyPublisher)(IOService *);
extern "C" void
houji_fb_set_legacy_publisher(bool (*publisher)(IOService *))
{
    houjiLegacyPublisher = publisher;
}

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

class HoujiFramebuffer;

class HoujiFramebufferUserClient : public IOUserClient {
	OSDeclareDefaultStructors(HoujiFramebufferUserClient);
public:
	HoujiFramebuffer *fOwner = nullptr;
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

class HoujiFramebuffer : public IOService {
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

OSDefineMetaClassAndStructors(HoujiFramebuffer, IOService);
OSDefineMetaClassAndStructors(HoujiFramebufferUserClient, IOUserClient);

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
HoujiFramebuffer::drawBootUi(uint32_t permille)
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
HoujiFramebuffer::start(IOService *provider)
{
	setName("IOMobileFramebuffer");
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

	setProperty(kIOUserClientClassKey, "HoujiFramebufferUserClient");
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
	    IOTimerEventSource::Action, this, &HoujiFramebuffer::vsyncFired));
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
HoujiFramebuffer::matchPropertyTable(OSDictionary *table, SInt32 *score)
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
HoujiFramebuffer::stop(IOService *provider)
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
HoujiFramebuffer::vsyncFired(OSObject *owner, IOTimerEventSource *sender)
{
	fVsyncCount++;
	if ((fVsyncCount % 600) == 0) {
		HOUJI_FB_LOG("vsync %llu swaps %u", fVsyncCount, fSwapCount);
		if (houjiLegacyCheckpoint != nullptr)
			houjiLegacyCheckpoint();
		if (fVsyncCount <= 3600) {
			HOUJI_FB_LOG("services fb=%u hid=%u surf=%u res=%u",
			    houjiCountServices("HoujiFramebuffer"),
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
HoujiFramebuffer::newUserClient(task_t owningTask, void *securityID, UInt32 type,
    OSDictionary *properties, IOUserClient **handler)
{
	HoujiFramebufferUserClient *client = new HoujiFramebufferUserClient;
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
HoujiFramebufferUserClient::initWithTask(task_t owningTask, void *securityID, UInt32 type)
{
	if (!IOUserClient::initWithTask(owningTask, securityID, type)) {
		return false;
	}
	fTask = owningTask;
	return true;
}

bool
HoujiFramebufferUserClient::start(IOService *provider)
{
	return IOUserClient::start(provider);
}

IOReturn
HoujiFramebufferUserClient::clientClose(void)
{
	HOUJI_FB_LOG("user client closed pid %d swaps %u",
	    proc_getpid(current_proc()), fOwner ? fOwner->fSwapCount : 0);
	terminate();
	return kIOReturnSuccess;
}

IOReturn
HoujiFramebufferUserClient::registerNotificationPort(mach_port_t port, UInt32 type, io_user_reference_t refCon)
{
	fPort = port;
	HOUJI_FB_LOG("notification port type %u", type);
	return kIOReturnSuccess;
}

IOReturn
HoujiFramebufferUserClient::externalMethod(uint32_t selector, IOExternalMethodArguments *args,
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

/* libaks selectors (AppleKeyStore.framework, iOS 16.7). */
enum {
	kAKSOpen = 0,
	kAKSCreateBag = 2,
	kAKSSaveBag = 3,
	kAKSUnloadBag = 4,
	kAKSSetSystem = 5,
	kAKSLoadBag = 6,
	kAKSGetLockState = 7,
	kAKSUnlockDevice = 9,
	kAKSWrapKey = 10,
	kAKSUnwrapKey = 11,
	kAKSUnlockBag = 12,
	kAKSLockBag = 13,
	kAKSGetSystem = 14,
	kAKSGetDeviceState = 17,
	kAKSAssertHold = 26,
	kAKSAssertDrop = 27,
	kAKSGetExtDeviceState = 35,
	kAKSUnloadSessionBags = 55,
	kAKSAssertConsume = 101,
	kAKSNotifyStateSet = 102,
};

#define HOUJI_AKS_SYSTEM_HANDLE 0
/* bit 2: unlocked since boot; lock bits clear: unlocked */
#define HOUJI_AKS_LOCK_STATE 0x4

class AppleKeyStore final : public IOService {
	OSDeclareDefaultStructors(AppleKeyStore)
public:
	bool start(IOService *provider) override
	{
		if (!IOService::start(provider))
			return false;
		setName("AppleKeyStore");
		setProperty(kIOUserClientClassKey, "AppleKeyStoreUserClient");
		setProperty("KeyOperationsAvailable", true);
		registerService();
		IOLog("HOUJI-AKS: AppleKeyStore registered (unlocked, no passcode)\n");
		return true;
	}
};
OSDefineMetaClassAndStructors(AppleKeyStore, IOService)

class AppleKeyStoreUserClient final : public IOUserClient {
	OSDeclareDefaultStructors(AppleKeyStoreUserClient)
public:
	IOReturn clientClose(void) override
	{
		terminate();
		return kIOReturnSuccess;
	}
	IOReturn externalMethod(uint32_t selector, IOExternalMethodArguments *args,
	    IOExternalMethodDispatch *dispatch, OSObject *target, void *reference) override;
};
OSDefineMetaClassAndStructors(AppleKeyStoreUserClient, IOUserClient)

static IOReturn
houjiAksStructOut(IOExternalMethodArguments *args, const void *buf, uint32_t len)
{
	if (args->structureOutputDescriptor != nullptr) {
		if (len > args->structureOutputDescriptor->getLength()) {
			return kIOReturnNoSpace;
		}
		args->structureOutputDescriptor->writeBytes(0, buf, len);
		args->structureOutputDescriptorSize = len;
		return kIOReturnSuccess;
	}
	if (args->structureOutput == nullptr || len > args->structureOutputSize) {
		return kIOReturnNoSpace;
	}
	memcpy(args->structureOutput, buf, len);
	args->structureOutputSize = len;
	return kIOReturnSuccess;
}

static uint32_t
houjiAksDerPair(uint8_t *p, const char *key, uint8_t value)
{
	uint32_t klen = (uint32_t)strlen(key);
	uint32_t n = 0;

	p[n++] = 0x30;
	p[n++] = (uint8_t)(2 + klen + 3);
	p[n++] = 0x0c;
	p[n++] = (uint8_t)klen;
	memcpy(p + n, key, klen);
	n += klen;
	p[n++] = 0x02;
	p[n++] = 0x01;
	p[n++] = value;
	return n;
}

static IOReturn
houjiAksDeviceState(IOExternalMethodArguments *args)
{
	static const struct {
		const char *key;
		uint8_t value;
	} fields[] = {
		{ "ss", HOUJI_AKS_LOCK_STATE }, { "sls", 0 }, { "sb", 0 }, { "sfa", 0 },
		{ "sgs", 0 }, { "sas", 0 }, { "sgpe", 0 }, { "srcd", 0 },
	};
	uint8_t buf[128];
	uint32_t n = 2;

	for (unsigned int i = 0; i < sizeof(fields) / sizeof(fields[0]); i++) {
		n += houjiAksDerPair(buf + n, fields[i].key, fields[i].value);
	}
	buf[0] = 0x31;
	buf[1] = (uint8_t)(n - 2);
	return houjiAksStructOut(args, buf, n);
}

static uint32_t
houjiAksStructOutSize(IOExternalMethodArguments *args)
{
	return args->structureOutputDescriptor != nullptr ?
	       (uint32_t)args->structureOutputDescriptor->getLength() : args->structureOutputSize;
}

IOReturn
AppleKeyStoreUserClient::externalMethod(uint32_t selector, IOExternalMethodArguments *args,
    __unused IOExternalMethodDispatch *dispatch, __unused OSObject *target, __unused void *reference)
{
	IOReturn ret = kIOReturnSuccess;
	uint32_t inStruct = args->structureInputDescriptor != nullptr ?
	    (uint32_t)args->structureInputDescriptor->getLength() : args->structureInputSize;
	uint32_t outScalars = args->scalarOutputCount;
	uint32_t outStruct = houjiAksStructOutSize(args);

	switch (selector) {
	case kAKSOpen:
	case kAKSUnloadBag:
	case kAKSSetSystem:
	case kAKSUnlockDevice:
	case kAKSUnlockBag:
	case kAKSLockBag:
	case kAKSAssertHold:
	case kAKSAssertDrop:
	case kAKSAssertConsume:
	case kAKSUnloadSessionBags:
	case kAKSNotifyStateSet:
		args->scalarOutputCount = 0;
		break;
	case kAKSGetSystem:
		if (outScalars < 1) {
			ret = kIOReturnBadArgument;
			break;
		}
		args->scalarOutput[0] = HOUJI_AKS_SYSTEM_HANDLE;
		args->scalarOutputCount = 1;
		break;
	case kAKSGetLockState:
		if (outScalars < 1) {
			ret = kIOReturnBadArgument;
			break;
		}
		args->scalarOutput[0] = HOUJI_AKS_LOCK_STATE;
		args->scalarOutputCount = 1;
		break;
	case kAKSGetDeviceState:
	case kAKSGetExtDeviceState:
		args->scalarOutputCount = 0;
		ret = houjiAksDeviceState(args);
		break;
	default:
		ret = kIOReturnUnsupported;
		break;
	}

	IOLog("HOUJI-AKS: sel %u in %u/%u out %u/%u -> 0x%x\n", selector,
	    args->scalarInputCount, inStruct, outScalars, outStruct, ret);
	return ret;
}


extern "C" IOService *native_hid_input_allocate(void);
extern "C" bool native_hid_input_requested(void) { return true; }
extern "C" void native_hid_input_observed(unsigned what, int result)
{
	if (what == 2) {
		IOLog("HOUJI-HID: device start observed result=%d\n", result);
	}
}
extern "C" void native_hid_live_checkpoint(IOService *) {}

static void
houjiHidInputBootstrap(IOService *platform)
{
	int on = 0;
	PE_parse_boot_argn("houji-hid-input", &on, sizeof(on));
	if (on == 0) {
		return;
	}
	IOService *dev = native_hid_input_allocate();
	if (dev == nullptr) {
		IOLog("HOUJI-HID: alloc failed\n");
		return;
	}
	if (!dev->init(platform)) {
		IOLog("HOUJI-HID: init failed\n");
		dev->release();
		return;
	}
	if (!dev->attach(platform)) {
		IOLog("HOUJI-HID: attach failed\n");
		dev->release();
		return;
	}
	if (!dev->start(platform)) {
		IOLog("HOUJI-HID: start failed\n");
		dev->detach(platform);
		dev->release();
		return;
	}
	dev->registerService();
	IOLog("HOUJI-HID: published IOHIDDevice matches=%u\n", houjiCountServices("IOHIDDevice"));
}

static void
houjiKeyEventsBootstrap(IOService *platform)
{
    uint32_t enabled = 0;
    PE_parse_boot_argn("houji-keyevents", &enabled, sizeof(enabled));
    if (enabled != 1)
        return;
    if (houjiCountServices("AppleKeyStore") != 0) {
        IOLog("HOUJI-KEYEVENTS: existing-service-retained\n");
        return;
    }
    auto service = new AppleKeyStore;
    if (service == nullptr) {
        IOLog("HOUJI-KEYEVENTS: allocation-failed\n");
        return;
    }
    if (!service->init(nullptr)) {
        service->release();
        IOLog("HOUJI-KEYEVENTS: init-failed\n");
        return;
    }
    if (!service->attach(platform)) {
        service->release();
        IOLog("HOUJI-KEYEVENTS: attach-failed\n");
        return;
    }
    if (!service->start(platform)) {
        service->detach(platform);
        service->release();
        IOLog("HOUJI-KEYEVENTS: start-failed\n");
        return;
    }
    service->registerService();
    IOLog("HOUJI-KEYEVENTS: published matches=%u notifications-only=1 key-operations=0\n",
        houjiCountServices("AppleKeyStore"));
}

// Use the native provider's actual metaclass when Legacy publication is requested.
// The pinned 20H392 AppleARMIODevice uses IOService init/start/stop/free.
static uint64_t gPanelPhys;
static uint64_t gPanelBytes;

static bool
houjiDisplayProperties(IOService *nub)
{
    static char compatible[] = "houji,display";
    static char deviceType[] = "display-subsystem";
    PE_Video video = {};
    if (PE_current_console(&video) != 0 || video.v_width == 0 || video.v_height == 0)
        return false;
    uint32_t width = 1200; /* panel canvas (reference manifest canvas=[1200,2670]) */
    uint32_t height = 2670;
    gPanelPhys = video.v_baseAddr;
    gPanelBytes = video.v_rowBytes * (uint64_t)video.v_height;
    nub->setName("display0");
    return nub->setProperty("compatible", compatible, sizeof(compatible)) &&
        nub->setProperty("device_type", deviceType, sizeof(deviceType)) &&
        nub->setProperty("canvas-width", &width, sizeof(width)) &&
        nub->setProperty("canvas-height", &height, sizeof(height));
}

class HoujiDisplayNub : public IOPlatformDevice {
    OSDeclareDefaultStructors(HoujiDisplayNub);
public:
    // The original IOMobileFramebufferLegacy startHardware() maps device memory
    // index 0 for scanout; without it the family refuses to start and never
    // allocates its default framebuffer. Publish the panel window here.
    IODeviceMemory *getDeviceMemoryWithIndex(unsigned int index) override
    {
        if (index != 0 || gPanelPhys == 0 || gPanelBytes == 0)
            return IOPlatformDevice::getDeviceMemoryWithIndex(index);
        return IODeviceMemory::withRange(gPanelPhys, gPanelBytes);
    }
};
OSDefineMetaClassAndStructors(HoujiDisplayNub, IOPlatformDevice);

static IOService *
houjiAllocateDisplayNub()
{
    uint32_t enabled = 0, publish = 0;
    PE_parse_boot_argn("houji-legacy-display", &enabled, sizeof(enabled));
    PE_parse_boot_argn("houji-legacy-publish", &publish, sizeof(publish));
    if (enabled == 1 && publish == 1) {
        OSObject *object = OSMetaClass::allocClassWithName("AppleARMIODevice");
        static const char family[] = "com.apple.driver.AppleARMPlatform";
        if (object == nullptr && !OSKext::isKextWithIdentifierLoaded(family)) {
            OSReturn status = OSKext::loadKextWithIdentifier(family);
            HOUJI_FB_LOG("provider family load rc=%#x", status);
            object = OSMetaClass::allocClassWithName("AppleARMIODevice");
        }
        IOService *native = OSDynamicCast(IOService, object);
        if (native != nullptr && native->metaCast("AppleARMIODevice") != nullptr) {
            HOUJI_FB_LOG("provider allocated class=%s size=%u",
                native->getMetaClass()->getClassName(),
                native->getMetaClass()->getClassSize());
            return native;
        }
        if (object != nullptr)
            object->release();
        HOUJI_FB_LOG("native provider unavailable; using generic nub");
    }
    return new HoujiDisplayNub;
}

// SWEET display: the AppleCLCD class compiled into this kernel owns the panel and
// answers IOMobileFramebuffer itself. It is not reachable through a kext
// personality here, so allocate and start it the same way the Legacy service is
// published. Gated by houji-sweet-display=1.
static void
houjiStartSweetDisplay(IOService *nub)
{
    uint32_t enabled = 0;
    PE_parse_boot_argn("houji-sweet-display", &enabled, sizeof(enabled));
    if (enabled != 1 || nub == nullptr) {
        return;
    }
    OSObject *object = OSMetaClass::allocClassWithName("AppleCLCD");
    IOService *display = OSDynamicCast(IOService, object);
    if (display == nullptr) {
        if (object != nullptr) {
            object->release();
        }
        HOUJI_FB_LOG("sweet display unavailable");
        return;
    }
    if (!display->init(nullptr) || !display->attach(nub) || !display->start(nub)) {
        HOUJI_FB_LOG("sweet display start failed");
        if (display->getProvider() != nullptr) {
            display->detach(nub);
        }
        display->release();
        return;
    }
    display->registerService();
    HOUJI_FB_LOG("sweet display published class=%s", display->getMetaClass()->getClassName());
}

// Called by the SWEET framebuffer's vsync timer once the data volume is mounted.
// watchdogd asserts and exits when IOWatchdog is missing, and its launchd job
// panics the kernel after repeated crashes. Registering the service at boot
// disturbs the APFS mount that follows, so it happens here instead.
extern "C" void
houji_start_watchdog_late(void)
{
    static bool started;
    if (started) {
        return;
    }
    started = true;
    OSObject *object = OSMetaClass::allocClassWithName("IOWatchdog");
    IOService *service = OSDynamicCast(IOService, object);
    if (service == nullptr) {
        HOUJI_FB_LOG("watchdog class missing");
        return;
    }
    IOService *platform = IOService::getPlatform();
    if (platform == nullptr || !service->init(nullptr) ||
        !service->attach(platform) || !service->start(platform)) {
        if (service->getProvider() != nullptr) {
            service->detach(platform);
        }
        service->release();
        HOUJI_FB_LOG("watchdog late start failed");
        return;
    }
    service->registerService();
    HOUJI_FB_LOG("watchdog published late");
}

extern "C" void houji_persona_bootstrap(void);

extern "C" void
houji_fb_bootstrap(void)
{
	static int done;
	if (done) return;
	done = 1;
	houji_persona_bootstrap();

	IOService *platform = IOService::getPlatform();
	if (platform == nullptr) {
		HOUJI_FB_LOG("no platform expert");
		return;
	}
	houjiKeyEventsBootstrap(platform);
	houjiHidInputBootstrap(platform);
	IOService *provider = platform;
	IORegistryEntry *armIO = IORegistryEntry::fromPath("/arm-io", gIODTPlane);
	if (armIO) {
		IOService *nub = nullptr;
		{
			uint32_t sweetPick = 0;
			PE_parse_boot_argn("houji-sweet-display", &sweetPick, sizeof(sweetPick));
			if (sweetPick == 1) {
				IORegistryEntry *dent = IORegistryEntry::fromPath("/arm-io/disp0", gIODTPlane);
				IOService *dsvc = dent ? OSDynamicCast(IOService, dent) : nullptr;
				if (dsvc != nullptr) {
					uint32_t cw = 1200, ch = 2670;
					dsvc->setProperty("canvas-width", &cw, sizeof(cw));
					dsvc->setProperty("canvas-height", &ch, sizeof(ch));
					dsvc->setProperty("device_type", (void *)"display-subsystem", sizeof("display-subsystem"));
					provider = dsvc;
					HOUJI_FB_LOG("disp0 DT provider class=%s", dsvc->getMetaClass()->getClassName());
				}
				if (dent != nullptr) dent->release();
			}
			if (provider == platform) nub = houjiAllocateDisplayNub();
		}
		if (nub != nullptr) {
			if (!nub->init(nullptr) || !houjiDisplayProperties(nub)) {
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
	if (provider != platform) {
		houjiStartSweetDisplay(provider);
	}
	if (provider == platform) {
		HOUJI_FB_LOG("enumeration precondition failed; retaining platform-provider service");
	}
	if (houjiLegacyCheckpoint != nullptr)
		houjiLegacyCheckpoint();

	uint32_t houjiSweetOn = 0;
	PE_parse_boot_argn("houji-sweet-display", &houjiSweetOn, sizeof(houjiSweetOn));
	// When the in-kernel Sweet AppleCLCD owns the display, do not publish a second
	// IOMobileFramebuffer service (the legacy/generic HoujiFramebuffer would shadow it).
	const bool legacyPublished = houjiSweetOn == 1 ||
	    (houjiLegacyPublisher != nullptr && houjiLegacyPublisher(provider));
	if (!legacyPublished) {
		HoujiFramebuffer *fb = new HoujiFramebuffer;
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
		HOUJI_FB_LOG("HoujiFramebuffer registered: %s", fb->getName());
	} else {
		HOUJI_FB_LOG("Legacy published; old framebuffer skipped");
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
			{
				static const char *names[] = {
				    "IOHIDSystem", "IOHIDEventService", "IOHIDDevice",
				    "IOHIDInterface", "IOHIDEventDriver", "IOHIDResource"};
				for (unsigned i = 0; i < sizeof(names) / sizeof(names[0]); i++) {
					const OSSymbol *symbol = OSSymbol::withCString(names[i]);
					const OSMetaClass *meta = symbol != nullptr
					    ? OSMetaClass::getMetaClassWithName(symbol) : nullptr;
					if (symbol != nullptr)
						const_cast<OSSymbol *>(symbol)->release();
					HOUJI_FB_LOG("hid class %s %s", names[i],
					    meta != nullptr ? "present" : "missing");
				}
			}
			}
	}
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
