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

extern "C" int sweet_hid_start(IOService *provider);
extern "C" void sweet_hid_touch(int finger, int down, int x, int y);
#include <pexpert/pexpert.h>
#include <kern/clock.h>
#include <mach/mach_time.h>
#include <kern/task.h>

#include <kern/thread.h>
extern "C" kern_return_t kernel_thread_start(thread_continue_t continuation,
    void *parameter, thread_t *new_thread);
extern "C" void thread_deallocate(thread_t thread);
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


/* ---- inlined NativeGeniSpi (UniXNU, BSD-2-Clause-Patent) ---- */
// SPDX-License-Identifier: BSD-2-Clause-Patent
// Qualcomm GENI serial-engine SPI master, FIFO (PIO) mode. Register layout and sequences follow the study of the
// Linux spi-geni-qcom / qcom-geni-se drivers (no code copied). No board addresses, clocks or pins here.
#ifndef GENI_SPI_H
#define GENI_SPI_H
#include <stdint.h>
#include <stddef.h>

// Serial-engine registers (offsets from the SE base).
#define GENI_FORCE_DEFAULT_REG 0x20
#define GENI_OUTPUT_CTRL 0x24
#define SE_GENI_CGC_CTRL 0x28
#define SE_GENI_STATUS 0x40
#define GENI_SER_M_CLK_CFG 0x48
#define GENI_IF_DISABLE_RO 0x64
#define GENI_FW_REVISION_RO 0x68
#define SE_GENI_CLK_SEL 0x7c
#define SE_GENI_BYTE_GRAN 0x254
#define SE_GENI_DMA_MODE_EN 0x258
#define SE_GENI_TX_PACKING_CFG0 0x260
#define SE_GENI_TX_PACKING_CFG1 0x264
#define SE_GENI_RX_PACKING_CFG0 0x284
#define SE_GENI_RX_PACKING_CFG1 0x288
#define SE_SPI_CPHA 0x224
#define SE_SPI_LOOPBACK 0x22c
#define SE_SPI_CPOL 0x230
#define SE_SPI_DEMUX_OUTPUT_INV 0x24c
#define SE_SPI_DEMUX_SEL 0x250
#define SE_SPI_TRANS_CFG 0x25c
#define SE_SPI_WORD_LEN 0x268
#define SE_SPI_TX_TRANS_LEN 0x26c
#define SE_SPI_RX_TRANS_LEN 0x270
#define SE_GENI_M_CMD0 0x600
#define SE_GENI_M_CMD_CTRL_REG 0x604
#define SE_GENI_M_IRQ_STATUS 0x610
#define SE_GENI_M_IRQ_EN 0x614
#define SE_GENI_M_IRQ_CLEAR 0x618
#define SE_GENI_S_IRQ_EN 0x644
#define SE_GENI_S_IRQ_CLEAR 0x648
#define SE_DMA_TX_IRQ_CLR 0xc44
#define SE_DMA_RX_IRQ_CLR 0xd44
#define SE_GENI_TX_FIFOn 0x700
#define SE_GENI_RX_FIFOn 0x780
#define SE_GENI_TX_FIFO_STATUS 0x800
#define SE_GENI_RX_FIFO_STATUS 0x804
#define SE_GENI_TX_WATERMARK_REG 0x80c
#define SE_GENI_RX_WATERMARK_REG 0x810
#define SE_GENI_RX_RFR_WATERMARK_REG 0x814
#define SE_IRQ_EN 0xe1c
#define SE_HW_PARAM_0 0xe24
#define SE_DMA_GENERAL_CFG 0xe30
#define SE_GSI_EVENT_EN 0xe18
// Serial-engine DMA registers (qcom-geni-se.c / geni-se.h of the pinned mainline tree).
#define SE_DMA_TX_PTR_L 0xc30
#define SE_DMA_TX_PTR_H 0xc34
#define SE_DMA_TX_ATTR 0xc38
#define SE_DMA_TX_LEN 0xc3c
#define SE_DMA_TX_IRQ_STAT 0xc40
#define SE_DMA_TX_IRQ_EN_SET 0xc4c
#define SE_DMA_TX_LEN_IN 0xc54
#define SE_DMA_TX_FSM_RST 0xc58
#define SE_DMA_RX_PTR_L 0xd30
#define SE_DMA_RX_PTR_H 0xd34
#define SE_DMA_RX_ATTR 0xd38
#define SE_DMA_RX_LEN 0xd3c
#define SE_DMA_RX_IRQ_STAT 0xd40
#define SE_DMA_RX_IRQ_EN_SET 0xd4c
#define SE_DMA_RX_LEN_IN 0xd54
#define SE_DMA_RX_FSM_RST 0xd58
// SE_DMA_{TX,RX}_IRQ_STAT / _EN_SET fields
#define GENI_DMA_DONE (1u<<0)
#define GENI_DMA_EOT (1u<<1)
#define GENI_DMA_AHB_ERR (1u<<2)        // TX_SBE / RX_SBE
#define GENI_DMA_RESET_DONE (1u<<3)
#define GENI_DMA_TX_ATTR_EOT_BUF (1u<<0)
// Wrapper register (offset from the QUP wrapper base).
#define QUPV3_HW_VER_REG 0x4

#define GENI_PROTO_NONE 0
#define GENI_PROTO_SPI 1
#define GENI_PROTO_INVALID 255

#define GENI_M_CMD_TX_ONLY 1
#define GENI_M_CMD_RX_ONLY 2
#define GENI_M_CMD_TX_RX 3              // full duplex: spi-geni-qcom.c issues SPI_TX_ONLY|SPI_RX_ONLY (its SPI_TX_RX=7 is never used)
#define GENI_M_PARAM_FRAGMENTATION (1u<<2)

// Register field values.
#define GENI_FORCE_DEFAULT (1u<<0)
#define GENI_SER_CLK_EN (1u<<0)
#define GENI_CLK_DIV_SHIFT 4
#define GENI_CLK_DIV_MAX 0xfffu
#define GENI_FIFO_IF_DISABLE (1u<<0)
#define GENI_FW_PROTO_SHIFT 8
#define GENI_DMA_MODE_EN (1u<<0)
#define GENI_DEFAULT_CGC_EN 0x7fu
#define GENI_DEFAULT_IO_OUTPUT_CTRL 0x7fu
#define GENI_M_OPCODE_SHIFT 27
#define GENI_M_PARAMS_MASK 0x7ffffffu
#define GENI_M_CMD_CANCEL (1u<<2)
#define GENI_M_CMD_ABORT (1u<<1)
#define GENI_STATUS_M_ACTIVE (1u<<0)
#define GENI_TRANS_LEN_MASK 0xffffffu
#define GENI_WORD_LEN_MIN 4
#define GENI_CS_TOGGLE (1u<<1)
#define GENI_CPHA_BIT (1u<<0)
#define GENI_CPOL_BIT (1u<<2)
#define GENI_LOOPBACK_ENABLE 1u
// SE_IRQ_EN
#define GENI_IRQ_DMA_RX (1u<<0)
#define GENI_IRQ_DMA_TX (1u<<1)
#define GENI_IRQ_M (1u<<2)
#define GENI_IRQ_S (1u<<3)
// SE_DMA_GENERAL_CFG
#define GENI_DMA_RX_CGC_ON (1u<<0)
#define GENI_DMA_TX_CGC_ON (1u<<1)
#define GENI_DMA_AHB_SLV_CGC_ON (1u<<2)
#define GENI_AHB_SEC_SLV_CGC_ON (1u<<3)
// M_IRQ bits
#define GENI_M_CMD_DONE (1u<<0)
#define GENI_M_CMD_OVERRUN (1u<<1)
#define GENI_M_ILLEGAL_CMD (1u<<2)
#define GENI_M_CMD_FAILURE (1u<<3)
#define GENI_M_CMD_CANCEL_DONE (1u<<4)
#define GENI_M_CMD_ABORT_DONE (1u<<5)
#define GENI_M_IO_DATA_DEASSERT (1u<<22)
#define GENI_M_IO_DATA_ASSERT (1u<<23)
#define GENI_M_RX_FIFO_RD_ERR (1u<<24)
#define GENI_M_RX_FIFO_WR_ERR (1u<<25)
#define GENI_M_RX_FIFO_WATERMARK (1u<<26)
#define GENI_M_RX_FIFO_LAST (1u<<27)
#define GENI_M_TX_FIFO_RD_ERR (1u<<28)
#define GENI_M_TX_FIFO_WR_ERR (1u<<29)
#define GENI_M_TX_FIFO_WATERMARK (1u<<30)
#define GENI_M_COMMON_IRQ_EN (0x7eu | GENI_M_IO_DATA_DEASSERT | GENI_M_IO_DATA_ASSERT | GENI_M_RX_FIFO_RD_ERR | \
                              GENI_M_RX_FIFO_WR_ERR | GENI_M_TX_FIFO_RD_ERR | GENI_M_TX_FIFO_WR_ERR)
#define GENI_S_COMMON_IRQ_EN (0x3eu | 0x3e00u | (1u<<24) | (1u<<25))
#define GENI_M_ERRORS (GENI_M_CMD_OVERRUN | GENI_M_ILLEGAL_CMD | GENI_M_CMD_FAILURE | GENI_M_RX_FIFO_RD_ERR | \
                       GENI_M_RX_FIFO_WR_ERR | GENI_M_TX_FIFO_RD_ERR | GENI_M_TX_FIFO_WR_ERR)
// RX_FIFO_STATUS
#define GENI_RX_LAST (1u<<31)
#define GENI_RX_LAST_VALID_SHIFT 28
#define GENI_RX_LAST_VALID_MASK 7u
#define GENI_RX_WC_MASK 0x1ffffffu
// Packing vector fields
#define GENI_PACK_START_SHIFT 5
#define GENI_PACK_DIR_SHIFT 4
#define GENI_PACK_LEN_SHIFT 1
#define GENI_PACK_STOP (1u<<0)
#define GENI_PACK_VECTOR_SHIFT 10
#define GENI_PACK_VECTORS 4

#define GENI_SPI_CPHA 0x01
#define GENI_SPI_CPOL 0x02
#define GENI_SPI_CS_HIGH 0x04
#define GENI_SPI_LSB_FIRST 0x08
#define GENI_SPI_LOOP 0x20

#define GENI_ERR_PARAM (-22)
#define GENI_ERR_PROTO (-71)
#define GENI_ERR_NODEV (-19)
#define GENI_ERR_TIMEOUT (-110)
#define GENI_ERR_IO (-5)
#define GENI_ERR_NOTSUP (-95)

struct geni_io {
    void *ctx;
    uint32_t (*rd)(void *ctx, uint32_t reg);
    void (*wr)(void *ctx, uint32_t reg, uint32_t value);
    void (*delay_us)(void *ctx, unsigned us);
};

struct geni_spi_info {
    uint32_t fw_revision, protocol, if_disable, hw_param0, geni_status;
    uint32_t qup_hw_version;
    unsigned tx_fifo_depth, fifo_width_bits;
    int fifo_disabled;
};

struct geni_dma {
        void *ctx;
        void (*clean)(void *ctx, void *virt, size_t len);        // write back CPU-dirty lines before the engine reads
        void (*clean_inval)(void *ctx, void *virt, size_t len);  // write back and drop before the engine writes
        void (*inval)(void *ctx, void *virt, size_t len);        // drop stale lines after the engine wrote
        uint8_t *tx_virt, *rx_virt;
        uint64_t tx_phys, rx_phys;
        size_t size;
};

struct geni_spi {
    struct geni_io se;                  // serial engine registers
    struct geni_io wrapper;             // QUP wrapper registers (hardware version only)
    struct geni_spi_info info;
    unsigned oversampling, tx_wm;
    unsigned cur_bpw;
    unsigned cur_speed_hz;
    uint32_t last_mode;
    int last_cs;
    unsigned poll_limit;                // iterations of the completion poll before cancel/abort
    int poll_only;                      // 1: switch the engine interrupt outputs off after init (completion polled); 2: leave them on
    uint32_t snap_irq, snap_status, snap_txfs, snap_rxfs;  // registers read just before a timed-out transfer is cancelled
    uint32_t snap_dma_tx, snap_dma_rx, snap_dma_txin, snap_dma_rxin;
    int snap_valid;
    uint32_t last_tx_in, last_rx_in;                  // SE_DMA_{TX,RX}_LEN_IN after the latest DMA transfer: bytes the engine moved
    // SE DMA mode (for engines whose FIFO interface is disabled and that cannot be re-enabled from the host): transfers go
    // through two caller-provided buffers that the serial engine's DMA master can reach at tx_phys/rx_phys. The caller owns
    // the translation (SMMU) and cache policy; the callbacks maintain the CPU caches around each transfer.
    int use_dma;
    struct geni_dma dma;
    int allow_fifo_disabled;            // try FIFO mode even when FIFO_IF_DISABLE is set (the Linux fallback when no GPI channel exists)
};

// Read-only: protocol, FIFO geometry, FIFO-disable flag, version. Safe to run before any register write; only valid when
// the SE clocks are already running (the caller must know that).
int geni_spi_read_info(struct geni_spi *s);
// Select FIFO mode and program the controller defaults. Refuses engines that are not configured for SPI or whose FIFO
// interface is disabled (those need the GPI DMA path, which this driver does not implement).
int geni_spi_init(struct geni_spi *s);
int geni_spi_setup(struct geni_spi *s, unsigned mode, unsigned chip_select);
// Program the serial clock: divider from the SE source clock (sclk_hz) and the requested rate; clk_sel is the source index.
int geni_spi_set_clock(struct geni_spi *s, unsigned speed_hz, unsigned sclk_hz, unsigned clk_sel);
// With use_dma set the transfer runs through the SE DMA engine.
// One full-duplex (rx!=NULL, tx!=NULL), TX-only or RX-only transfer of len bytes (8 bits per word), polled.
int geni_spi_transfer(struct geni_spi *s, const uint8_t *tx, uint8_t *rx, size_t len, int keep_cs);
#endif

// SPDX-License-Identifier: BSD-2-Clause-Patent

static uint32_t rd(struct geni_spi *s, uint32_t reg) { return s->se.rd(s->se.ctx, reg); }
static void wr(struct geni_spi *s, uint32_t reg, uint32_t v) { s->se.wr(s->se.ctx, reg, v); }
static void rmw_set(struct geni_spi *s, uint32_t reg, uint32_t bits) { wr(s, reg, rd(s, reg) | bits); }

static void irq_clear(struct geni_spi *s) {
	HOUJI_FB_LOG("touch v14: step8 gsi_event_en");
	IOSleep(6000);
    wr(s, SE_GSI_EVENT_EN, 0);
    wr(s, SE_GENI_M_IRQ_CLEAR, 0xffffffffu);
    wr(s, SE_GENI_S_IRQ_CLEAR, 0xffffffffu);
    wr(s, SE_DMA_TX_IRQ_CLR, 0xffffffffu);
    wr(s, SE_DMA_RX_IRQ_CLR, 0xffffffffu);
    wr(s, SE_IRQ_EN, 0xffffffffu);
}

// FIFO words hold fifo_width_bits/8 packed bytes at 8 bits per word.
static unsigned bytes_per_word(const struct geni_spi *s) { return s->info.fifo_width_bits / 8; }

int geni_spi_read_info(struct geni_spi *s) {
    if (!s || !s->se.rd || !s->wrapper.rd) return GENI_ERR_PARAM;
    uint32_t fw = rd(s, GENI_FW_REVISION_RO);
    s->info.fw_revision = fw;
    s->info.protocol = (fw >> GENI_FW_PROTO_SHIFT) & 0xff;
    s->info.if_disable = rd(s, GENI_IF_DISABLE_RO);
    s->info.fifo_disabled = (s->info.if_disable & GENI_FIFO_IF_DISABLE) != 0;
    s->info.geni_status = rd(s, SE_GENI_STATUS);
    s->info.hw_param0 = rd(s, SE_HW_PARAM_0);
    s->info.qup_hw_version = s->wrapper.rd(s->wrapper.ctx, QUPV3_HW_VER_REG);
    uint32_t major = s->info.qup_hw_version >> 28, minor = (s->info.qup_hw_version >> 16) & 0xfff;
    uint32_t mask = ((major == 3 && minor >= 10) || major > 3) ? 0xff0000u : 0x3f0000u;
    s->info.tx_fifo_depth = (s->info.hw_param0 & mask) >> 16;
    s->info.fifo_width_bits = (s->info.hw_param0 >> 24) & 0x3f;
    return 0;
}

// Packing for 8-bit words, 4 per FIFO word, MSB first inside each byte; same values the vendor sequence programs.
static void config_packing(struct geni_spi *s, unsigned bpw, unsigned pack_words, int msb_first) {
    uint32_t cfg[GENI_PACK_VECTORS] = {0};
    int idx_start = msb_first ? (int)bpw - 1 : 0, idx = idx_start;
    int idx_delta = msb_first ? -8 : 8;
    unsigned ceil_bpw = (bpw + 7) & ~7u;
    unsigned iter = ceil_bpw * pack_words / 8;
    int temp_bpw = (int)bpw;
    if (iter == 0 || iter > GENI_PACK_VECTORS) return;
    for (unsigned i = 0; i < iter; i++) {
        int len = (temp_bpw < 8 ? temp_bpw : 8) - 1;
        cfg[i] = ((uint32_t)idx << GENI_PACK_START_SHIFT) | ((uint32_t)(msb_first != 0) << GENI_PACK_DIR_SHIFT) |
                 ((uint32_t)len << GENI_PACK_LEN_SHIFT);
        if (temp_bpw <= 8) {
            idx = (int)(i + 1) * 8 + idx_start;
            temp_bpw = (int)bpw;
        } else {
            idx += idx_delta;
            temp_bpw -= 8;
        }
    }
    cfg[iter - 1] |= GENI_PACK_STOP;
    uint32_t cfg0 = cfg[0] | (cfg[1] << GENI_PACK_VECTOR_SHIFT);
    uint32_t cfg1 = cfg[2] | (cfg[3] << GENI_PACK_VECTOR_SHIFT);
    wr(s, SE_GENI_TX_PACKING_CFG0, cfg0);
    wr(s, SE_GENI_TX_PACKING_CFG1, cfg1);
    wr(s, SE_GENI_RX_PACKING_CFG0, cfg0);
    wr(s, SE_GENI_RX_PACKING_CFG1, cfg1);
    if (pack_words || bpw == 32) wr(s, SE_GENI_BYTE_GRAN, bpw / 16);
}

static void set_word_len(struct geni_spi *s, unsigned bpw, int msb_first) {
    unsigned pack = (s->info.fifo_width_bits % bpw) ? 1 : s->info.fifo_width_bits / bpw;
    config_packing(s, bpw, pack, msb_first);
    wr(s, SE_SPI_WORD_LEN, (bpw - GENI_WORD_LEN_MIN) & 0x3ff);
}

int geni_spi_init(struct geni_spi *s) {
    int r = geni_spi_read_info(s);
    if (r) return r;
    if (s->info.protocol != GENI_PROTO_SPI) return GENI_ERR_PROTO;
    if (s->use_dma && (!s->dma.tx_virt || !s->dma.rx_virt || !s->dma.tx_phys || !s->dma.rx_phys || !s->dma.size))
        return GENI_ERR_PARAM;
    if (s->info.fifo_disabled && !s->allow_fifo_disabled && !s->use_dma) return GENI_ERR_NOTSUP;   // GPI DMA path not implemented
    if (s->info.tx_fifo_depth < 4 || s->info.fifo_width_bits != 32) return GENI_ERR_NODEV;
	HOUJI_FB_LOG("touch v14: step1 irq_clear");
	IOSleep(6000);
    // geni_se_init
    irq_clear(s);
	HOUJI_FB_LOG("touch v14: step2 cgc_ctrl");
	IOSleep(6000);
    rmw_set(s, SE_GENI_CGC_CTRL, GENI_DEFAULT_CGC_EN);
	HOUJI_FB_LOG("touch v14: step3 dma_general_cfg");
	IOSleep(6000);
    rmw_set(s, SE_DMA_GENERAL_CFG, GENI_AHB_SEC_SLV_CGC_ON | GENI_DMA_AHB_SLV_CGC_ON | GENI_DMA_TX_CGC_ON | GENI_DMA_RX_CGC_ON);
	HOUJI_FB_LOG("touch v14: step4 output_ctrl");
	IOSleep(6000);
    wr(s, GENI_OUTPUT_CTRL, GENI_DEFAULT_IO_OUTPUT_CTRL);
	HOUJI_FB_LOG("touch v14: step5 force_default");
	IOSleep(6000);
    wr(s, GENI_FORCE_DEFAULT_REG, GENI_FORCE_DEFAULT);
	HOUJI_FB_LOG("touch v14: step6 se_irq_en");
	IOSleep(6000);
    rmw_set(s, SE_IRQ_EN, GENI_IRQ_M | GENI_IRQ_S | GENI_IRQ_DMA_TX | GENI_IRQ_DMA_RX);
	HOUJI_FB_LOG("touch v14: step7 dma_mode_en");
	IOSleep(6000);
    wr(s, SE_GENI_DMA_MODE_EN, rd(s, SE_GENI_DMA_MODE_EN) & ~GENI_DMA_MODE_EN);
    wr(s, SE_GSI_EVENT_EN, 0);
	HOUJI_FB_LOG("touch v14: step9 rx_watermark");
	IOSleep(6000);
    wr(s, SE_GENI_RX_WATERMARK_REG, s->info.tx_fifo_depth - 3);
    wr(s, SE_GENI_RX_RFR_WATERMARK_REG, s->info.tx_fifo_depth - 2);
	HOUJI_FB_LOG("touch v14: step10 m_irq_en");
	IOSleep(6000);
    rmw_set(s, SE_GENI_M_IRQ_EN, GENI_M_COMMON_IRQ_EN);
    rmw_set(s, SE_GENI_S_IRQ_EN, GENI_S_COMMON_IRQ_EN);
    s->tx_wm = 1;
    uint32_t major = s->info.qup_hw_version >> 28, minor = (s->info.qup_hw_version >> 16) & 0xfff;
    s->oversampling = (major == 1 && minor == 0) ? 2 : 1;
    // FIFO mode selection
    irq_clear(s);
    rmw_set(s, SE_GENI_M_IRQ_EN, GENI_M_CMD_DONE | GENI_M_TX_FIFO_WATERMARK | GENI_M_RX_FIFO_WATERMARK | GENI_M_RX_FIFO_LAST);
    wr(s, SE_GENI_DMA_MODE_EN, rd(s, SE_GENI_DMA_MODE_EN) & ~GENI_DMA_MODE_EN);
    wr(s, SE_SPI_LOOPBACK, 0);
    wr(s, SE_SPI_DEMUX_SEL, 0);
    wr(s, SE_SPI_CPHA, 0);
    wr(s, SE_SPI_CPOL, 0);
    wr(s, SE_SPI_DEMUX_OUTPUT_INV, 0);
    wr(s, SE_SPI_TRANS_CFG, rd(s, SE_SPI_TRANS_CFG) & ~GENI_CS_TOGGLE);   // chip select is never driven manually
    s->cur_bpw = 0;
    s->cur_speed_hz = 0;
    s->last_mode = 0;
    s->last_cs = 0;
    if (!s->poll_limit) s->poll_limit = 1000000;
    if (s->use_dma) {
        // geni_se_select_dma_mode: drop the FIFO interrupt sources and switch the engine to its DMA master.
        irq_clear(s);
        wr(s, SE_GENI_M_IRQ_EN, rd(s, SE_GENI_M_IRQ_EN) & ~(GENI_M_CMD_DONE | GENI_M_TX_FIFO_WATERMARK | GENI_M_RX_FIFO_WATERMARK | GENI_M_RX_FIFO_LAST));
        wr(s, SE_GENI_DMA_MODE_EN, rd(s, SE_GENI_DMA_MODE_EN) | GENI_DMA_MODE_EN);
    }
    if (s->poll_only == 1) wr(s, SE_IRQ_EN, 0);     // status registers stay pollable; no unhandled interrupt reaches the GIC
    return 0;
}

int geni_spi_setup(struct geni_spi *s, unsigned mode, unsigned chip_select) {
    if (chip_select > 15) return GENI_ERR_PARAM;
    unsigned changed = s->last_mode ^ mode;
    int cs_changed = ((unsigned)s->last_cs != chip_select);
    s->last_cs = (int)chip_select;
    s->last_mode = mode;
    if (changed & GENI_SPI_LSB_FIRST) s->cur_bpw = 0;
    if (changed & GENI_SPI_LOOP) wr(s, SE_SPI_LOOPBACK, (mode & GENI_SPI_LOOP) ? GENI_LOOPBACK_ENABLE : 0);
    if (cs_changed) wr(s, SE_SPI_DEMUX_SEL, chip_select);
    if (changed & GENI_SPI_CPHA) wr(s, SE_SPI_CPHA, (mode & GENI_SPI_CPHA) ? GENI_CPHA_BIT : 0);
    if (changed & GENI_SPI_CPOL) wr(s, SE_SPI_CPOL, (mode & GENI_SPI_CPOL) ? GENI_CPOL_BIT : 0);
    if ((changed & GENI_SPI_CS_HIGH) || (cs_changed && (mode & GENI_SPI_CS_HIGH)))
        wr(s, SE_SPI_DEMUX_OUTPUT_INV, (mode & GENI_SPI_CS_HIGH) ? (1u << chip_select) : 0);
    return 0;
}

int geni_spi_set_clock(struct geni_spi *s, unsigned speed_hz, unsigned sclk_hz, unsigned clk_sel) {
    if (!speed_hz || !sclk_hz || clk_sel > 7 || !s->oversampling) return GENI_ERR_PARAM;
    unsigned long long denom = (unsigned long long)s->oversampling * speed_hz;
    unsigned long long div = (sclk_hz + denom - 1) / denom;
    if (div == 0 || div > GENI_CLK_DIV_MAX) return GENI_ERR_PARAM;
    wr(s, SE_GENI_CLK_SEL, clk_sel);
    wr(s, GENI_SER_M_CLK_CFG, ((uint32_t)div << GENI_CLK_DIV_SHIFT) | GENI_SER_CLK_EN);
    s->cur_speed_hz = speed_hz;
    return 0;
}

struct xfer {
    const uint8_t *tx;
    uint8_t *rx;
    size_t tx_rem, rx_rem, len;
};

static int handle_tx(struct geni_spi *s, struct xfer *x) {
    unsigned bpw = bytes_per_word(s);
    size_t max = (size_t)(s->info.tx_fifo_depth - s->tx_wm) * bpw;
    if (x->tx_rem < max) max = x->tx_rem;
    const uint8_t *p = x->tx + (x->len - x->tx_rem);
    size_t i = 0;
    while (i < max) {
        uint32_t word = 0;
        size_t n = max - i < bpw ? max - i : bpw;
        for (size_t j = 0; j < n; j++) word |= (uint32_t)p[i++] << (8 * j);
        wr(s, SE_GENI_TX_FIFOn, word);
    }
    x->tx_rem -= max;
    if (!x->tx_rem) {
        wr(s, SE_GENI_TX_WATERMARK_REG, 0);
        return 0;
    }
    return 1;
}

static void handle_rx(struct geni_spi *s, struct xfer *x) {
    unsigned bpw = bytes_per_word(s);
    uint32_t st = rd(s, SE_GENI_RX_FIFO_STATUS);
    size_t bytes = (size_t)(st & GENI_RX_WC_MASK) * bpw;
    if (st & GENI_RX_LAST) {
        unsigned valid = (st >> GENI_RX_LAST_VALID_SHIFT) & GENI_RX_LAST_VALID_MASK;
        if (valid && valid < 4) bytes -= bpw - valid;
    }
    if (!x->rx) {
        for (size_t i = 0; i < (bytes + bpw - 1) / bpw; i++) (void)rd(s, SE_GENI_RX_FIFOn);
        return;
    }
    if (x->rx_rem < bytes) bytes = x->rx_rem;
    uint8_t *p = x->rx + (x->len - x->rx_rem);
    size_t i = 0;
    while (i < bytes) {
        uint32_t word = rd(s, SE_GENI_RX_FIFOn);
        size_t n = bytes - i < bpw ? bytes - i : bpw;
        for (size_t j = 0; j < n; j++) p[i++] = (uint8_t)(word >> (8 * j));
    }
    x->rx_rem -= bytes;
}

static int wait_bit(struct geni_spi *s, uint32_t bit) {
    for (unsigned n = 0; n < s->poll_limit; n++) {
        uint32_t st = rd(s, SE_GENI_M_IRQ_STATUS);
        if (st & bit) {
            wr(s, SE_GENI_M_IRQ_CLEAR, st);
            return 0;
        }
        if (s->se.delay_us) s->se.delay_us(s->se.ctx, 1);
    }
    return GENI_ERR_TIMEOUT;
}

static void recover(struct geni_spi *s) {
    wr(s, SE_GENI_TX_WATERMARK_REG, 0);
    wr(s, SE_GENI_M_CMD_CTRL_REG, GENI_M_CMD_CANCEL);
    if (wait_bit(s, GENI_M_CMD_CANCEL_DONE | GENI_M_CMD_DONE) == 0) return;
    wr(s, SE_GENI_M_CMD_CTRL_REG, GENI_M_CMD_ABORT);
    (void)wait_bit(s, GENI_M_CMD_ABORT_DONE | GENI_M_CMD_DONE);
}

static int transfer_dma(struct geni_spi *s, const uint8_t *tx, uint8_t *rx, size_t len, int keep_cs) {
    struct geni_dma *d = &s->dma;
    if (len > d->size) return GENI_ERR_PARAM;
    uint32_t cmd = 0;
    if (tx) {
        volatile uint8_t *tv = d->tx_virt;   // volatile: the buffer may be an uncached device-type mapping, so no merged stores
        for (size_t i = 0; i < len; i++) tv[i] = tx[i];
        if (d->clean) d->clean(d->ctx, d->tx_virt, len);
        cmd |= GENI_M_CMD_TX_ONLY;
        wr(s, SE_SPI_TX_TRANS_LEN, (uint32_t)len);
    }
    if (rx) {
        volatile uint8_t *rv0 = d->rx_virt;
        for (size_t i = 0; i < len; i++) rv0[i] = 0x5a;   // canary: bytes the engine never wrote stay recognisable
        if (d->clean_inval) d->clean_inval(d->ctx, d->rx_virt, len);
        cmd |= GENI_M_CMD_RX_ONLY;
        wr(s, SE_SPI_RX_TRANS_LEN, (uint32_t)len);
    }
    if (cmd == (GENI_M_CMD_TX_ONLY | GENI_M_CMD_RX_ONLY)) cmd = GENI_M_CMD_TX_RX;
    wr(s, SE_GENI_M_IRQ_CLEAR, 0xffffffffu);
    wr(s, SE_DMA_TX_IRQ_CLR, 0xffffffffu);
    wr(s, SE_DMA_RX_IRQ_CLR, 0xffffffffu);
    wr(s, SE_GENI_M_CMD0, (cmd << GENI_M_OPCODE_SHIFT) | (keep_cs ? GENI_M_PARAM_FRAGMENTATION : 0));
    // geni_se_rx_init_dma / geni_se_tx_init_dma: the LEN write starts each direction.
    if (rx) {
        wr(s, SE_DMA_RX_IRQ_EN_SET, GENI_DMA_DONE | GENI_DMA_EOT | GENI_DMA_AHB_ERR);
        wr(s, SE_DMA_RX_PTR_L, (uint32_t)d->rx_phys);
        wr(s, SE_DMA_RX_PTR_H, (uint32_t)(d->rx_phys >> 32));
        wr(s, SE_DMA_RX_ATTR, 0);
        wr(s, SE_DMA_RX_LEN, (uint32_t)len);
    }
    if (tx) {
        wr(s, SE_DMA_TX_IRQ_EN_SET, GENI_DMA_DONE | GENI_DMA_EOT | GENI_DMA_AHB_ERR);
        wr(s, SE_DMA_TX_PTR_L, (uint32_t)d->tx_phys);
        wr(s, SE_DMA_TX_PTR_H, (uint32_t)(d->tx_phys >> 32));
        wr(s, SE_DMA_TX_ATTR, GENI_DMA_TX_ATTR_EOT_BUF);
        wr(s, SE_DMA_TX_LEN, (uint32_t)len);
    }
    int tx_done = !tx, rx_done = !rx, status = GENI_ERR_TIMEOUT;
    for (unsigned n = 0; n < s->poll_limit; n++) {
        uint32_t ts = tx ? rd(s, SE_DMA_TX_IRQ_STAT) : 0, rs = rx ? rd(s, SE_DMA_RX_IRQ_STAT) : 0;
        uint32_t ms = rd(s, SE_GENI_M_IRQ_STATUS);
        if (ts) wr(s, SE_DMA_TX_IRQ_CLR, ts);
        if (rs) wr(s, SE_DMA_RX_IRQ_CLR, rs);
        if (ms) wr(s, SE_GENI_M_IRQ_CLEAR, ms);
        if ((ts & GENI_DMA_AHB_ERR) || (rs & GENI_DMA_AHB_ERR) || (ms & GENI_M_ERRORS)) { status = GENI_ERR_IO; break; }
        if (ts & GENI_DMA_DONE) tx_done = 1;
        if (rs & GENI_DMA_DONE) rx_done = 1;
        if (tx_done && rx_done) { status = 0; break; }
        if (s->se.delay_us) s->se.delay_us(s->se.ctx, 1);
    }
    s->last_tx_in = tx ? rd(s, SE_DMA_TX_LEN_IN) : 0;
    s->last_rx_in = rx ? rd(s, SE_DMA_RX_LEN_IN) : 0;
    if (status == 0) {
        if (rx) {
            if (d->inval) d->inval(d->ctx, d->rx_virt, len);
            volatile uint8_t *rv = d->rx_virt;
            for (size_t i = 0; i < len; i++) rx[i] = rv[i];
        }
        return 0;
    }
    s->snap_dma_tx = rd(s, SE_DMA_TX_IRQ_STAT);
    s->snap_dma_rx = rd(s, SE_DMA_RX_IRQ_STAT);
    s->snap_dma_txin = rd(s, SE_DMA_TX_LEN_IN);
    s->snap_dma_rxin = rd(s, SE_DMA_RX_LEN_IN);
    s->snap_irq = rd(s, SE_GENI_M_IRQ_STATUS);
    s->snap_status = rd(s, SE_GENI_STATUS);
    s->snap_txfs = rd(s, SE_GENI_TX_FIFO_STATUS);
    s->snap_rxfs = rd(s, SE_GENI_RX_FIFO_STATUS);
    s->snap_valid = 1;
    recover(s);
    wr(s, SE_DMA_TX_FSM_RST, 1);
    wr(s, SE_DMA_RX_FSM_RST, 1);
    return status;
}

int geni_spi_transfer(struct geni_spi *s, const uint8_t *tx, uint8_t *rx, size_t len, int keep_cs) {
    if (!s || !len || len > GENI_TRANS_LEN_MASK || (!tx && !rx) || !s->cur_speed_hz) return GENI_ERR_PARAM;
    if (s->cur_bpw != 8) {
        set_word_len(s, 8, !(s->last_mode & GENI_SPI_LSB_FIRST));
        s->cur_bpw = 8;
    }
    if (s->use_dma) return transfer_dma(s, tx, rx, len, keep_cs);
    struct xfer x = {tx, rx, tx ? len : 0, rx ? len : 0, len};
    uint32_t cmd = 0;
    if (tx) {
        cmd |= GENI_M_CMD_TX_ONLY;
        wr(s, SE_SPI_TX_TRANS_LEN, (uint32_t)len);
    }
    if (rx) {
        cmd |= GENI_M_CMD_RX_ONLY;
        wr(s, SE_SPI_RX_TRANS_LEN, (uint32_t)len);
    }
    if (cmd == (GENI_M_CMD_TX_ONLY | GENI_M_CMD_RX_ONLY)) cmd = GENI_M_CMD_TX_RX;
    wr(s, SE_GENI_M_IRQ_CLEAR, 0xffffffffu);
    wr(s, SE_GENI_M_CMD0, (cmd << GENI_M_OPCODE_SHIFT) | (keep_cs ? GENI_M_PARAM_FRAGMENTATION : 0));
    if (tx && handle_tx(s, &x)) wr(s, SE_GENI_TX_WATERMARK_REG, s->tx_wm);
    int status = GENI_ERR_TIMEOUT;
    for (unsigned n = 0; n < s->poll_limit; n++) {
        uint32_t st = rd(s, SE_GENI_M_IRQ_STATUS);
        if (!st) {
            if (s->se.delay_us) s->se.delay_us(s->se.ctx, 1);
            continue;
        }
        wr(s, SE_GENI_M_IRQ_CLEAR, st);
        if (st & GENI_M_ERRORS) {
            status = GENI_ERR_IO;
            break;
        }
        if (st & (GENI_M_RX_FIFO_WATERMARK | GENI_M_RX_FIFO_LAST)) handle_rx(s, &x);
        if ((st & GENI_M_TX_FIFO_WATERMARK) && tx) handle_tx(s, &x);
        if (st & GENI_M_CMD_DONE) {
            if (rx && x.rx_rem) handle_rx(s, &x);
            status = (x.tx_rem || x.rx_rem) ? GENI_ERR_IO : 0;
            if (x.tx_rem) wr(s, SE_GENI_TX_WATERMARK_REG, 0);
            return status;
        }
    }
    s->snap_dma_tx = rd(s, SE_DMA_TX_IRQ_STAT);
    s->snap_dma_rx = rd(s, SE_DMA_RX_IRQ_STAT);
    s->snap_dma_txin = rd(s, SE_DMA_TX_LEN_IN);
    s->snap_dma_rxin = rd(s, SE_DMA_RX_LEN_IN);
    s->snap_irq = rd(s, SE_GENI_M_IRQ_STATUS);
    s->snap_status = rd(s, SE_GENI_STATUS);
    s->snap_txfs = rd(s, SE_GENI_TX_FIFO_STATUS);
    s->snap_rxfs = rd(s, SE_GENI_RX_FIFO_STATUS);
    s->snap_valid = 1;
    recover(s);
    return status;
}

/* ---- end NativeGeniSpi ---- */

/* HOUJI-TOUCH v7: the branch clock and GENI identity are confirmed (proto SPI,
 * 32-bit FIFO, depth 41).  Bring the serial engine up and send the first read
 * command to the Synaptics part, logging every result. */
#define HOUJI_TOUCH_GCC		0x00100000ULL
#define HOUJI_TOUCH_BRANCH	(HOUJI_TOUCH_GCC + 0x52008)
#define HOUJI_TOUCH_SE		0x00a90000ULL
#define HOUJI_TOUCH_WRAP		0x00ac0000ULL

static uint32_t
houjiGeniRd(void *ctx, uint32_t reg)
{
	return *(volatile uint32_t *)((uint8_t *)ctx + reg);
}

static void
houjiGeniWr(void *ctx, uint32_t reg, uint32_t value)
{
	*(volatile uint32_t *)((uint8_t *)ctx + reg) = value;
}

static void
houjiGeniDelay(void *ctx, unsigned us)
{
	IOSleep(us ? (us + 999) / 1000 : 0);
}

static uint8_t *
houjiTouchMap(uint64_t phys, uint32_t size)
{
	IOMemoryDescriptor *mem = IOMemoryDescriptor::withPhysicalAddress(
	    (IOPhysicalAddress)phys, size, kIODirectionOut);
	if (mem == nullptr) { return nullptr; }
	IOMemoryMap *map = mem->map();
	mem->release();
	if (map == nullptr) { return nullptr; }
	return (uint8_t *)map->getVirtualAddress();
}

static int
houjiTouchWrite32(uint64_t phys, uint32_t value)
{
	IOMemoryDescriptor *mem = IOMemoryDescriptor::withPhysicalAddress(
	    (IOPhysicalAddress)phys, 4, kIODirectionOut);
	if (mem == nullptr) { return 0; }
	IOMemoryMap *map = mem->map();
	mem->release();
	if (map == nullptr) { return 0; }
	*(volatile uint32_t *)map->getVirtualAddress() = value;
	map->release();
	return 1;
}

static uint32_t
houjiTouchRead32(uint64_t phys)
{
	uint32_t value = 0;
	IOMemoryDescriptor *mem = IOMemoryDescriptor::withPhysicalAddress(
	    (IOPhysicalAddress)phys, 4, kIODirectionIn);
	if (mem == nullptr) { return 0; }
	IOMemoryMap *map = mem->map();
	mem->release();
	if (map == nullptr) { return 0; }
	value = *(volatile uint32_t *)map->getVirtualAddress();
	map->release();
	return value;
}

static void houjiTouchProbe(void);

static void
houjiTouchThreadMain(void *arg, wait_result_t wr)
{
	IOSleep(120000);
	HOUJI_FB_LOG("touch v39: deferred probe starting");
	houjiTouchProbe();
	thread_terminate(current_thread());
}

/* v19: the TLMM register aperture that answered the v5 pin reads. */
#define HOUJI_TOUCH_TLMM	0x0f100000ULL
#define HOUJI_TOUCH_RSC_DRV	0x17a20000ULL
#define HOUJI_TOUCH_RSC_TCS	0xd00u
#define HOUJI_TOUCH_CMDB	0x81c60000ULL
#define HOUJI_TOUCH_CMDB_SIZE	0x20000u

struct HoujiRscLayout {
	uint32_t tcs_stride, cmd_stride, irq_status, irq_clear, wait_for_cmpl,
	    control, status, cmd_enable, cmd_msgid, cmd_addr, cmd_data;
};

static HoujiRscLayout
houjiRscLayout(uint32_t id)
{
	if (((id >> 16) & 0xffu) >= 3u) {
		return {672, 24, 0x04, 0x08, 0x20, 0x24, 0x28, 0x2c, 0x34, 0x38, 0x3c};
	}
	return {672, 20, 0x04, 0x08, 0x10, 0x14, 0x18, 0x1c, 0x30, 0x34, 0x38};
}

static uint16_t
houjiRh16(const uint8_t *p)
{
	return (uint16_t)(p[0] | ((uint16_t)p[1] << 8));
}

static uint32_t
houjiRh32(const uint8_t *p)
{
	return (uint32_t)houjiRh16(p) | ((uint32_t)houjiRh16(p + 2) << 16);
}

static int
houjiCmdFind(const uint8_t *db, uint32_t bytes, const char *name, uint32_t *address)
{
	if (bytes < 144 || houjiRh32(db + 4) != 0x0c0330dbu) {
		return -1;
	}
	uint8_t key[8] = {0};
	for (unsigned i = 0; i < 8 && name[i]; i++) {
		key[i] = (uint8_t)name[i];
	}
	for (unsigned s = 0; s < 8; s++) {
		const uint8_t *slave = db + 8 + 16 * s;
		unsigned id = houjiRh16(slave);
		if (!id) {
			break;
		}
		uint32_t entries = 144u + houjiRh16(slave + 2);
		unsigned count = houjiRh16(slave + 6);
		if (entries > bytes || count > (bytes - entries) / 24) {
			return -2;
		}
		for (unsigned e = 0; e < count; e++) {
			const uint8_t *entry = db + entries + 24 * e;
			bool same = true;
			for (unsigned i = 0; i < 8; i++) {
				if (entry[i] != key[i]) {
					same = false;
					break;
				}
			}
			if (!same) {
				continue;
			}
			uint32_t addr = houjiRh32(entry + 16);
			if (!addr) {
				return -2;
			}
			*address = addr;
			HOUJI_FB_LOG("touch v39: cmd-db %s addr=%08x slave=%u", name, addr, id);
			return 0;
		}
	}
	return -3;
}

static int
houjiRpmhVote3(uint8_t *rsc, const HoujiRscLayout &l, uint32_t address, uint32_t mv,
    const char *name)
{
	const unsigned tcs = 1;
	const uint32_t base = HOUJI_TOUCH_RSC_TCS + tcs * l.tcs_stride;
	uint32_t status = *(volatile uint32_t *)(rsc + base + l.status);
	uint32_t enable = *(volatile uint32_t *)(rsc + base + l.cmd_enable);
	uint32_t wait = *(volatile uint32_t *)(rsc + base + l.wait_for_cmpl);
	uint32_t irq = *(volatile uint32_t *)(rsc + HOUJI_TOUCH_RSC_TCS + l.irq_status);
	HOUJI_FB_LOG("touch v39: rpmh %s tcs%u status=%08x enable=%08x wait=%08x irq=%08x",
	    name, tcs, status, enable, wait, irq);
	if (!status || status == 0xffffffffu || enable || wait || (irq & (1u << tcs))) {
		HOUJI_FB_LOG("touch v39: rpmh %s tcs%u not idle", name, tcs);
		return -1;
	}
	volatile uint32_t *control = (volatile uint32_t *)(rsc + base + l.control);
	*control = 0;
	*(volatile uint32_t *)(rsc + HOUJI_TOUCH_RSC_TCS + l.irq_clear) = 1u << tcs;
	static const uint32_t offsets[3] = {0, 8, 4};
	const uint32_t data[3] = {mv, 7u, 1u};
	for (unsigned c = 0; c < 3; c++) {
		uint32_t cmd = base + c * l.cmd_stride;
		*(volatile uint32_t *)(rsc + cmd + l.cmd_msgid) = 8u | (1u << 8) | (1u << 16);
		*(volatile uint32_t *)(rsc + cmd + l.cmd_addr) = address + offsets[c];
		*(volatile uint32_t *)(rsc + cmd + l.cmd_data) = data[c];
	}
	*(volatile uint32_t *)(rsc + base + l.wait_for_cmpl) = 7u;
	*(volatile uint32_t *)(rsc + base + l.cmd_enable) = 7u;
	*control = 1u << 16;
	*control = (1u << 16) | (1u << 24);
	bool done = false;
	uint32_t command[3] = {0, 0, 0};
	for (unsigned ms = 0; ms < 200; ms++) {
		irq = *(volatile uint32_t *)(rsc + HOUJI_TOUCH_RSC_TCS + l.irq_status);
		status = *(volatile uint32_t *)(rsc + base + l.status);
		bool complete = true;
		for (unsigned c = 0; c < 3; c++) {
			command[c] = *(volatile uint32_t *)(rsc + base + c * l.cmd_stride +
			    l.cmd_data + 4);
			if (command[c] == 0xffffffffu ||
			    (command[c] & ((1u << 8) | (1u << 16))) != ((1u << 8) | (1u << 16))) {
				complete = false;
			}
		}
		if (status && status != 0xffffffffu && complete) {
			done = true;
			break;
		}
		IOSleep(1);
	}
	HOUJI_FB_LOG("touch v39: rpmh %s done=%d irq=%08x status=%08x cmd=%08x/%08x/%08x",
	    name, done, irq, status, command[0], command[1], command[2]);
	if (!done) {
		return -2;
	}
	*(volatile uint32_t *)(rsc + HOUJI_TOUCH_RSC_TCS + l.irq_clear) = 1u << tcs;
	*control = 0;
	*(volatile uint32_t *)(rsc + base + l.cmd_enable) = 0;
	*(volatile uint32_t *)(rsc + base + l.wait_for_cmpl) = 0;
	HOUJI_FB_LOG("touch v39: %s tcs%u released wait=%08x", name, tcs,
	    *(volatile uint32_t *)(rsc + base + l.wait_for_cmpl));
	return 0;
}

static int
houjiTouchPowerOn(void)
{
	uint8_t *rsc = houjiTouchMap(HOUJI_TOUCH_RSC_DRV, 0x10000);
	uint8_t *db = houjiTouchMap(HOUJI_TOUCH_CMDB, HOUJI_TOUCH_CMDB_SIZE);
	HOUJI_FB_LOG("touch v39: rpmh maps rsc=%d db=%d", rsc != nullptr, db != nullptr);
	if (rsc == nullptr || db == nullptr) {
		return -1;
	}
	uint32_t id = *(volatile uint32_t *)rsc;
	HoujiRscLayout layout = houjiRscLayout(id);
	HOUJI_FB_LOG("touch v39: rsc id=%08x tcs_stride=%u cmd_stride=%u", id,
	    layout.tcs_stride, layout.cmd_stride);
	uint32_t l9 = 0, l12 = 0;
	int e9 = houjiCmdFind(db, HOUJI_TOUCH_CMDB_SIZE, "ldob9", &l9);
	int e12 = houjiCmdFind(db, HOUJI_TOUCH_CMDB_SIZE, "ldob12", &l12);
	HOUJI_FB_LOG("touch v39: lookup ldob9=%d ldob12=%d", e9, e12);
	if (e9 || e12) {
		return -2;
	}
	IOSleep(6000);
	int r = houjiRpmhVote3(rsc, layout, l9, 3000, "ldob9");
	HOUJI_FB_LOG("touch v39: ldob9 3000mV vote=%d", r);
	IOSleep(6000);
	if (r == 0) {
		r = houjiRpmhVote3(rsc, layout, l12, 1800, "ldob12");
		HOUJI_FB_LOG("touch v39: ldob12 1800mV vote=%d", r);
	}
	IOSleep(6000);
	return r;
}

static void
houjiTouchReset(void)
{
	uint64_t irq = HOUJI_TOUCH_TLMM + 0x1000ULL * 162;
	uint64_t rst = HOUJI_TOUCH_TLMM + 0x1000ULL * 161;
	uint32_t v = houjiTouchRead32(irq);
	HOUJI_FB_LOG("touch v39: gpio162 cfg=%08x io=%08x", v, houjiTouchRead32(irq + 4));
	houjiTouchWrite32(irq, (v & ~0x3ffu) | (3u << 6) | 3u);
	v = houjiTouchRead32(rst);
	houjiTouchWrite32(rst + 4, houjiTouchRead32(rst + 4) & ~2u);
	houjiTouchWrite32(rst, (v & ~0x3ffu) | (3u << 6) | 0x200u);
	HOUJI_FB_LOG("touch v39: reset low cfg=%08x io=%08x", houjiTouchRead32(rst),
	    houjiTouchRead32(rst + 4));
	IOSleep(10);
	houjiTouchWrite32(rst + 4, houjiTouchRead32(rst + 4) | 2u);
	HOUJI_FB_LOG("touch v39: reset high cfg=%08x io=%08x", houjiTouchRead32(rst),
	    houjiTouchRead32(rst + 4));
	IOSleep(250);
}

/* Every write that v15 showed capable of taking the machine down is logged and
 * given a full log-flush interval before it is issued. */
static void
houjiTouchWriteStep(struct geni_spi *s, uint32_t reg, uint32_t value, const char *name)
{
	uint32_t old = rd(s, reg);
	if (old == value) {
		HOUJI_FB_LOG("touch v39: %s already %08x", name, old);
		return;
	}
	HOUJI_FB_LOG("touch v39: %s about to write %08x -> %08x", name, old, value);
	IOSleep(6000);
	wr(s, reg, value);
	HOUJI_FB_LOG("touch v39: %s wrote now=%08x", name, rd(s, reg));
}

static void
houjiTouchPrepare(struct geni_spi *s)
{
	uint32_t v = rd(s, SE_GENI_CGC_CTRL);
	houjiTouchWriteStep(s, SE_GENI_CGC_CTRL, v | GENI_DEFAULT_CGC_EN, "cgc");
	houjiTouchWriteStep(s, GENI_OUTPUT_CTRL, GENI_DEFAULT_IO_OUTPUT_CTRL, "output-ctrl");
	houjiTouchWriteStep(s, SE_IRQ_EN, 0, "irq-en");
	wr(s, SE_GENI_M_IRQ_CLEAR, 0xffffffffu);
	wr(s, SE_GENI_S_IRQ_CLEAR, 0xffffffffu);
	HOUJI_FB_LOG("touch v39: irq cleared m=%08x", rd(s, SE_GENI_M_IRQ_STATUS));
	v = rd(s, SE_GENI_DMA_MODE_EN);
	houjiTouchWriteStep(s, SE_GENI_DMA_MODE_EN, v & ~GENI_DMA_MODE_EN, "dma-mode");
	houjiTouchWriteStep(s, SE_GSI_EVENT_EN, 0, "gsi-event");
	houjiTouchWriteStep(s, SE_SPI_LOOPBACK, 0, "loopback");
	houjiTouchWriteStep(s, SE_SPI_DEMUX_SEL, 0, "demux");
	houjiTouchWriteStep(s, SE_SPI_CPHA, 0, "cpha");
	houjiTouchWriteStep(s, SE_SPI_CPOL, 0, "cpol");
	houjiTouchWriteStep(s, SE_SPI_DEMUX_OUTPUT_INV, 0, "demux-inv");
	v = rd(s, SE_SPI_TRANS_CFG);
	houjiTouchWriteStep(s, SE_SPI_TRANS_CFG, v & ~GENI_CS_TOGGLE, "trans-cfg");
	houjiTouchWriteStep(s, SE_GENI_RX_WATERMARK_REG, s->info.tx_fifo_depth - 3, "rx-wm");
	houjiTouchWriteStep(s, SE_GENI_RX_RFR_WATERMARK_REG, s->info.tx_fifo_depth - 2, "rx-rfr");
	houjiTouchWriteStep(s, SE_GENI_M_IRQ_EN, GENI_M_CMD_DONE | GENI_M_TX_FIFO_WATERMARK |
	    GENI_M_RX_FIFO_WATERMARK | GENI_M_RX_FIFO_LAST, "m-irq-en");
}

static int
houjiTouchSpiStart(struct geni_spi *s)
{
	HOUJI_FB_LOG("touch v39: word-len kept=%08x", rd(s, SE_SPI_WORD_LEN));
	HOUJI_FB_LOG("touch v39: tx-len about to write");
	IOSleep(6000);
	wr(s, SE_SPI_TX_TRANS_LEN, 16);
	HOUJI_FB_LOG("touch v39: tx-len now=%08x", rd(s, SE_SPI_TX_TRANS_LEN));
	HOUJI_FB_LOG("touch v39: irq-clear about to write");
	IOSleep(6000);
	wr(s, SE_GENI_M_IRQ_CLEAR, 0xffffffffu);
	HOUJI_FB_LOG("touch v39: irq now=%08x", rd(s, SE_GENI_M_IRQ_STATUS));
	HOUJI_FB_LOG("touch v39: cmd0 about to write");
	IOSleep(6000);
	wr(s, SE_GENI_M_CMD0, GENI_M_CMD_TX_ONLY << GENI_M_OPCODE_SHIFT);
	HOUJI_FB_LOG("touch v39: cmd0 now=%08x status=%08x", rd(s, SE_GENI_M_CMD0),
	    rd(s, SE_GENI_STATUS));
	for (unsigned i = 0; i < 4; i++) {
		HOUJI_FB_LOG("touch v39: fifo word %u about to write", i);
		IOSleep(6000);
		wr(s, SE_GENI_TX_FIFOn, 0);
		HOUJI_FB_LOG("touch v39: fifo word %u now txfs=%08x", i,
		    rd(s, SE_GENI_TX_FIFO_STATUS));
	}
	for (unsigned n = 0; n < 200; n++) {
		uint32_t st = rd(s, SE_GENI_M_IRQ_STATUS);
		if (st) {
			HOUJI_FB_LOG("touch v39: irq after %u ms = %08x status=%08x txfs=%08x rxfs=%08x",
			    n, st, rd(s, SE_GENI_STATUS), rd(s, SE_GENI_TX_FIFO_STATUS),
			    rd(s, SE_GENI_RX_FIFO_STATUS));
			wr(s, SE_GENI_M_IRQ_CLEAR, st);
			return 0;
		}
		IOSleep(1);
	}
	HOUJI_FB_LOG("touch v39: poll timeout status=%08x irq=%08x txfs=%08x rxfs=%08x",
	    rd(s, SE_GENI_STATUS), rd(s, SE_GENI_M_IRQ_STATUS), rd(s, SE_GENI_TX_FIFO_STATUS),
	    rd(s, SE_GENI_RX_FIFO_STATUS));
	return -1;
}

static void
houjiTouchDump(const char *tag, const uint8_t *buf, unsigned bytes)
{
	for (unsigned i = 0; i < bytes; i += 4) {
		HOUJI_FB_LOG("touch v39: %s[%u]=%02x %02x %02x %02x", tag, i,
		    buf[i], buf[i + 1], buf[i + 2], buf[i + 3]);
	}
}

static void
houjiTouchPinConfig(volatile uint8_t *tlmm, unsigned pin, unsigned mux, unsigned pull,
    unsigned drive, bool output, bool high)
{
	volatile uint32_t *cfg = (volatile uint32_t *)(tlmm + 0x1000ULL * pin);
	volatile uint32_t *io = (volatile uint32_t *)(tlmm + 0x1000ULL * pin + 4);
	if (output) {
		*io = (*io & ~2u) | (high ? 2u : 0u);
	}
	uint32_t v = *cfg;
	v &= ~0x3ffu;
	v |= (mux << 2) | (pull & 3u) | ((drive & 7u) << 6) | (output ? 0x200u : 0u);
	*cfg = v;
}

static void
houjiTouchBitDelay(void)
{
	for (unsigned i = 0; i < 10; i++) {
		__asm__ volatile("nop");
	}
}

static void
houjiTouchBitTransfer(volatile uint8_t *tlmm, const uint8_t *tx, uint8_t *rx, unsigned len)
{
	volatile uint32_t *cs = (volatile uint32_t *)(tlmm + 0x1000ULL * 51 + 4);
	volatile uint32_t *clk = (volatile uint32_t *)(tlmm + 0x1000ULL * 50 + 4);
	volatile uint32_t *mosi = (volatile uint32_t *)(tlmm + 0x1000ULL * 49 + 4);
	volatile uint32_t *miso = (volatile uint32_t *)(tlmm + 0x1000ULL * 48 + 4);
	*cs = *cs & ~2u;
	houjiTouchBitDelay();
	for (unsigned i = 0; i < len; i++) {
		uint8_t out = tx ? tx[i] : 0;
		uint8_t in = 0;
		for (int b = 7; b >= 0; b--) {
			*mosi = (*mosi & ~2u) | (((out >> b) & 1u) ? 2u : 0u);
			houjiTouchBitDelay();
			*clk = *clk | 2u;
			houjiTouchBitDelay();
			in = (uint8_t)(((unsigned)in << 1) | (*miso & 1u));
			*clk = *clk & ~2u;
			houjiTouchBitDelay();
		}
		if (rx) {
			rx[i] = in;
		}
	}
	*cs = *cs | 2u;
	houjiTouchBitDelay();
}

static int
houjiTouchBitFrame(volatile uint8_t *tlmm, uint8_t *buf, unsigned size, const char *tag)
{
	memset(buf, 0xcc, size);
	houjiTouchBitTransfer(tlmm, nullptr, buf, size);
	if (buf[0] != 0xa5) {
		HOUJI_FB_LOG("touch v39: %s no-header first=%02x", tag, buf[0]);
		return -1;
	}
	unsigned len = buf[2] | ((unsigned)buf[3] << 8);
	HOUJI_FB_LOG("touch v39: %s code=%02x len=%u", tag, buf[1], len);
	if (len > 0 && len + 5 <= size) {
		for (unsigned i = 0; i + 3 < len && i < 32; i += 4) {
			HOUJI_FB_LOG("touch v39: %s[%u]=%02x %02x %02x %02x", tag, i,
			    buf[4 + i], buf[5 + i], buf[6 + i], buf[7 + i]);
		}
	}
	return 0;
}

static int
houjiTouchBitBang(void)
{
	uint8_t *tlmm = houjiTouchMap(HOUJI_TOUCH_TLMM, 0x200000);
	HOUJI_FB_LOG("touch v39: bitbang map=%d", tlmm != nullptr);
	if (tlmm == nullptr) {
		return -1;
	}
	houjiTouchPinConfig(tlmm, 48, 0, 1, 3, false, false);
	houjiTouchPinConfig(tlmm, 49, 0, 0, 3, true, false);
	houjiTouchPinConfig(tlmm, 50, 0, 0, 3, true, false);
	houjiTouchPinConfig(tlmm, 51, 0, 0, 3, true, true);
	HOUJI_FB_LOG("touch v39: pins 48=%08x/%08x 49=%08x/%08x 50=%08x/%08x 51=%08x/%08x",
	    houjiTouchRead32(HOUJI_TOUCH_TLMM + 0x30000), houjiTouchRead32(HOUJI_TOUCH_TLMM + 0x30004),
	    houjiTouchRead32(HOUJI_TOUCH_TLMM + 0x31000), houjiTouchRead32(HOUJI_TOUCH_TLMM + 0x31004),
	    houjiTouchRead32(HOUJI_TOUCH_TLMM + 0x32000), houjiTouchRead32(HOUJI_TOUCH_TLMM + 0x32004),
	    houjiTouchRead32(HOUJI_TOUCH_TLMM + 0x33000), houjiTouchRead32(HOUJI_TOUCH_TLMM + 0x33004));
	IOSleep(6000);

	uint8_t frame[2048];
	houjiTouchBitFrame(tlmm, frame, sizeof(frame), "startup");
	IOSleep(100);
	houjiTouchBitFrame(tlmm, frame, sizeof(frame), "startup2");
	IOSleep(100);

	uint8_t disable[4] = {0x06, 0x01, 0x00, 0xc0};
	HOUJI_FB_LOG("touch v39: disable vendor raw report about to send");
	houjiTouchBitTransfer(tlmm, disable, nullptr, sizeof(disable));
	IOSleep(100);
	houjiTouchBitFrame(tlmm, frame, sizeof(frame), "disable-resp");

	uint8_t enable[4] = {0x05, 0x01, 0x00, 0x11};
	HOUJI_FB_LOG("touch v39: enable touch report about to send");
	houjiTouchBitTransfer(tlmm, enable, nullptr, sizeof(enable));
	IOSleep(100);
	houjiTouchBitFrame(tlmm, frame, sizeof(frame), "enable-resp");

	uint8_t getcfg[3] = {0x25, 0x00, 0x00};
	HOUJI_FB_LOG("touch v39: get touch report config about to send");
	houjiTouchBitTransfer(tlmm, getcfg, nullptr, sizeof(getcfg));
	IOSleep(100);
	houjiTouchBitFrame(tlmm, frame, sizeof(frame), "config-resp");
	for (unsigned i = 32; i < 128; i += 4) {
		HOUJI_FB_LOG("touch v39: cfg[%u]=%02x %02x %02x %02x", i,
		    frame[4 + i], frame[5 + i], frame[6 + i], frame[7 + i]);
	}

	unsigned idle = 0, touch = 0;
	unsigned lastFinger = 0, lastX = 0, lastY = 0;
	bool lastDown = false;
	for (unsigned n = 0; n < 3500; n++) {
		memset(frame, 0xcc, sizeof(frame));
		houjiTouchBitTransfer(tlmm, nullptr, frame, sizeof(frame));
		if (frame[0] == 0xa5) {
			unsigned len = frame[2] | ((unsigned)frame[3] << 8);
			if (frame[1] == 0x11) {
				touch++;
				unsigned active = len > 17 ? frame[4 + 17] : 0;
				HOUJI_FB_LOG("touch v39: TOUCH%u len=%u active=%u", touch, len, active);
				if (len >= 27 && active > 0) {
					unsigned finger = frame[4 + 18] & 0x0fu;
					unsigned x = frame[4 + 19] | ((unsigned)frame[4 + 20] << 8);
					unsigned y = frame[4 + 21] | ((unsigned)frame[4 + 22] << 8);
					unsigned sx = x * 1079u / 1199u;
					unsigned sy = y * 2399u / 2669u;
					lastFinger = finger;
					lastX = sx;
					lastY = sy;
					lastDown = true;
					sweet_hid_touch((int)finger, 1, (int)sx, (int)sy);
					HOUJI_FB_LOG("touch v39: HID down f=%u raw=%u,%u scaled=%u,%u",
					    finger, x, y, sx, sy);
				} else if (lastDown) {
					sweet_hid_touch((int)lastFinger, 0, (int)lastX, (int)lastY);
					HOUJI_FB_LOG("touch v39: HID up f=%u", lastFinger);
					lastDown = false;
				}
				for (unsigned i = 0; i + 3 < len && i < 64; i += 4) {
					HOUJI_FB_LOG("touch v39: tdata[%u]=%02x %02x %02x %02x", i,
					    frame[4 + i], frame[5 + i], frame[6 + i], frame[7 + i]);
				}
			} else if (frame[1] != 0x00 && frame[1] != 0xc0) {
				HOUJI_FB_LOG("touch v39: report%u code=%02x len=%u", n, frame[1], len);
			} else if (frame[1] == 0x00) {
				idle++;
				if ((idle % 500) == 0) {
					HOUJI_FB_LOG("touch v39: idle=%u touch=%u", idle, touch);
				}
			}
		}
		IOSleep(50);
	}
	HOUJI_FB_LOG("touch v39: loop done idle=%u touch=%u", idle, touch);
	return 0;
}

static void
houjiTouchProbe(void)
{
	uint32_t on = 0;

	PE_parse_boot_argn("houji-touchprobe", &on, sizeof(on));
	if (on != 1) {
		return;
	}

	HOUJI_FB_LOG("touch v30: bitbang probe start");
	HOUJI_FB_LOG("touch v30: power about to run");
	IOSleep(6000);
	int bbPower = houjiTouchPowerOn();
	HOUJI_FB_LOG("touch v30: power=%d", bbPower);
	HOUJI_FB_LOG("touch v30: reset about to run");
	IOSleep(6000);
	houjiTouchReset();
	IOSleep(6000);
	houjiTouchBitBang();
	HOUJI_FB_LOG("touch v30: done");
	return;

	HOUJI_FB_LOG("touch v30: probe start");
	uint8_t *se = houjiTouchMap(HOUJI_TOUCH_SE, 0x4000);
	uint8_t *wrap = houjiTouchMap(HOUJI_TOUCH_WRAP, 0x1000);
	HOUJI_FB_LOG("touch v30: maps se=%d wrap=%d", se != nullptr, wrap != nullptr);
	if (se == nullptr || wrap == nullptr) {
		return;
	}
	IOSleep(6000);

	struct geni_spi s;
	memset(&s, 0, sizeof(s));
	s.se.ctx = se;
	s.se.rd = houjiGeniRd;
	s.se.wr = houjiGeniWr;
	s.se.delay_us = houjiGeniDelay;
	s.wrapper.ctx = wrap;
	s.wrapper.rd = houjiGeniRd;
	s.wrapper.wr = houjiGeniWr;
	s.poll_only = 1;
	s.poll_limit = 200000;
	s.oversampling = 1;
	s.tx_wm = 1;

	int r = geni_spi_read_info(&s);
	HOUJI_FB_LOG("touch v30: read_info=%d proto=%u depth=%u width=%u fifo_disabled=%d",
	    r, s.info.protocol, s.info.tx_fifo_depth, s.info.fifo_width_bits, s.info.fifo_disabled);
	HOUJI_FB_LOG("touch v30: survey cgc=%08x out=%08x irqen=%08x dma=%08x gsi=%08x",
	    rd(&s, SE_GENI_CGC_CTRL), rd(&s, GENI_OUTPUT_CTRL), rd(&s, SE_IRQ_EN),
	    rd(&s, SE_GENI_DMA_MODE_EN), rd(&s, SE_GSI_EVENT_EN));
	HOUJI_FB_LOG("touch v30: survey loop=%08x demux=%08x cpha=%08x cpol=%08x inv=%08x",
	    rd(&s, SE_SPI_LOOPBACK), rd(&s, SE_SPI_DEMUX_SEL), rd(&s, SE_SPI_CPHA),
	    rd(&s, SE_SPI_CPOL), rd(&s, SE_SPI_DEMUX_OUTPUT_INV));
	HOUJI_FB_LOG("touch v30: survey trans=%08x word=%08x mclk=%08x mcmd=%08x status=%08x",
	    rd(&s, SE_SPI_TRANS_CFG), rd(&s, SE_SPI_WORD_LEN), rd(&s, GENI_SER_M_CLK_CFG),
	    rd(&s, SE_GENI_M_CMD0), rd(&s, SE_GENI_STATUS));
	IOSleep(6000);

	uint64_t rcg = HOUJI_TOUCH_GCC + 0x183c8;
	uint32_t cmd = houjiTouchRead32(rcg);
	HOUJI_FB_LOG("touch v30: rcg cmd=%08x cfg=%08x m=%08x n=%08x d=%08x root_off=%u",
	    cmd, houjiTouchRead32(rcg + 0x4), houjiTouchRead32(rcg + 0x8),
	    houjiTouchRead32(rcg + 0xc), houjiTouchRead32(rcg + 0x10), (cmd >> 31) & 1u);
	HOUJI_FB_LOG("touch v30: rcg programming 19.2MHz TCXO bypass");
	IOSleep(6000);
	houjiTouchWrite32(rcg + 0x8, 0);
	houjiTouchWrite32(rcg + 0xc, 0);
	houjiTouchWrite32(rcg + 0x10, 0);
	houjiTouchWrite32(rcg + 0x4, 0);
	houjiTouchWrite32(rcg, 0x3u);
	cmd = houjiTouchRead32(rcg);
	HOUJI_FB_LOG("touch v30: rcg now cmd=%08x cfg=%08x m=%08x n=%08x d=%08x root_off=%u",
	    cmd, houjiTouchRead32(rcg + 0x4), houjiTouchRead32(rcg + 0x8),
	    houjiTouchRead32(rcg + 0xc), houjiTouchRead32(rcg + 0x10), (cmd >> 31) & 1u);

	uint32_t branch = houjiTouchRead32(HOUJI_TOUCH_BRANCH);
	HOUJI_FB_LOG("touch v30: branch=%08x halt=%08x", branch,
	    houjiTouchRead32(HOUJI_TOUCH_GCC + 0x183bc));
	if ((branch & (1u << 26)) == 0) {
		HOUJI_FB_LOG("touch v30: branch bit26 about to enable");
		IOSleep(6000);
		houjiTouchWrite32(HOUJI_TOUCH_BRANCH, branch | (1u << 26));
		HOUJI_FB_LOG("touch v30: branch now=%08x halt=%08x",
		    houjiTouchRead32(HOUJI_TOUCH_BRANCH), houjiTouchRead32(HOUJI_TOUCH_GCC + 0x183bc));
	}
	IOSleep(6000);

	houjiTouchPrepare(&s);
	HOUJI_FB_LOG("touch v30: se prepared");

	HOUJI_FB_LOG("touch v30: setup about to run");
	IOSleep(6000);
	r = geni_spi_setup(&s, 0, 0);
	HOUJI_FB_LOG("touch v30: setup=%d", r);
	uint32_t clock_select = rd(&s, SE_GENI_CLK_SEL);
	uint32_t clock_config = rd(&s, GENI_SER_M_CLK_CFG);
	HOUJI_FB_LOG("touch v30: clock sel=%08x cfg=%08x", clock_select, clock_config);
	if (clock_config & GENI_SER_CLK_EN) {
		s.cur_speed_hz = 1000000;
		HOUJI_FB_LOG("touch v30: clock kept as bootloader left it");
	} else {
		HOUJI_FB_LOG("touch v30: set_clock about to run");
		IOSleep(6000);
		r = geni_spi_set_clock(&s, 1000000, 19200000, 0);
		HOUJI_FB_LOG("touch v30: set_clock=%d oversampling=%u cfg=%08x", r,
		    s.oversampling, rd(&s, GENI_SER_M_CLK_CFG));
	}

	HOUJI_FB_LOG("touch v30: packing about to program");
	IOSleep(6000);
	set_word_len(&s, 8, true);
	s.cur_bpw = 8;
	HOUJI_FB_LOG("touch v30: packing done word=%08x txpack=%08x rxpack=%08x",
	    rd(&s, SE_SPI_WORD_LEN), rd(&s, SE_GENI_TX_PACKING_CFG0),
	    rd(&s, SE_GENI_RX_PACKING_CFG0));
	HOUJI_FB_LOG("touch v30: spi start about to run");
	r = houjiTouchSpiStart(&s);
	HOUJI_FB_LOG("touch v30: spi start=%d", r);
	if (r != 0) {
		HOUJI_FB_LOG("touch v30: spi start failed, stopping");
		return;
	}

	int power = houjiTouchPowerOn();
	HOUJI_FB_LOG("touch v30: power=%d", power);
	HOUJI_FB_LOG("touch v30: reset about to run");
	IOSleep(6000);
	houjiTouchReset();
	IOSleep(6000);

	uint8_t tx32[32];
	uint8_t rx32[32];
	memset(tx32, 0, sizeof(tx32));
	memset(rx32, 0xcc, sizeof(rx32));
	r = geni_spi_transfer(&s, tx32, rx32, sizeof(rx32), 0);
	HOUJI_FB_LOG("touch v30: read32=%d status=%08x irq=%08x txfs=%08x rxfs=%08x",
	    r, houjiGeniRd(se, SE_GENI_STATUS), houjiGeniRd(se, SE_GENI_M_IRQ_STATUS),
	    houjiGeniRd(se, SE_GENI_TX_FIFO_STATUS), houjiGeniRd(se, SE_GENI_RX_FIFO_STATUS));
	houjiTouchDump("read", rx32, 16);

	uint8_t get_report[4] = {0x0a, 0x00, 0x00, 0x5a};
	memset(rx32, 0xcc, sizeof(rx32));
	int w = geni_spi_transfer(&s, get_report, nullptr, sizeof(get_report), 1);
	int q = geni_spi_transfer(&s, tx32, rx32, sizeof(rx32), 0);
	HOUJI_FB_LOG("touch v30: get_report write=%d read=%d", w, q);
	houjiTouchDump("report", rx32, 16);
	HOUJI_FB_LOG("touch v30: done");
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
	{
		thread_t touchThread = nullptr;
		if (kernel_thread_start((thread_continue_t)houjiTouchThreadMain, nullptr,
		    &touchThread) == KERN_SUCCESS) {
			thread_deallocate(touchThread);
		}
	}
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
