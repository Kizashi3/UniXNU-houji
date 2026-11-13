"""Overlay the houji SweetFramebuffer display stack into the XNU tree.

Sources are vendored under vendor/drivers/HoujiDisplay; this script rewrites
the SWEET build guard, installs the files into iokit/Kernel/arm, adds the
build entries, registers the AppleCLCD and IOCoreSurfaceRoot personalities
and adds the bootstrap that creates the sweet,display nub at runtime.
"""
import os
import pathlib

DEVICE = pathlib.Path(os.environ["DEVICE_DIR"])
TREE = DEVICE.parent / "unixnu" / "out" / "houji" / "tree"
SRC = DEVICE / "vendor" / "drivers" / "HoujiDisplay"
DST = TREE / "iokit" / "Kernel" / "arm"

DST.mkdir(parents=True, exist_ok=True)
for name in ("SweetFramebuffer.cpp", "SweetSurface.cpp", "SweetSurface.h", "HoujiSurfaceAcquire.h",
             "HoujiFrameQueue.h", "HoujiDisplayTiming.h", "HoujiDisplayTiming.inc",
             "HoujiScaleRows.h", "HoujiBacklightProtocol.h", "HoujiBacklight.inc"):
    text = (SRC / name).read_text(errors="surrogateescape")
    text = text.replace("#if defined(SWEET)", "#if 1").replace("#if defined(SWEET) &&", "#if 1 &&")
    (DST / name).write_text(text)

bootstrap = '''
#include <IOKit/IOService.h>
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IOLib.h>
#include <pexpert/pexpert.h>

class HoujiDisplayNub : public IOPlatformDevice {
	OSDeclareDefaultStructors(HoujiDisplayNub);
public:
	bool init(OSDictionary *dict) override {
		if (!IOPlatformDevice::init(dict)) return false;
		setProperty("compatible", "sweet,display");
		setProperty("device_type", "display-subsystem");
		setProperty("name", "disp0");
		return true;
	}
};
OSDefineMetaClassAndStructors(HoujiDisplayNub, IOPlatformDevice);

extern "C" void
houji_display_bootstrap(void)
{
	static int done;
	IOService *platform;

	if (done) {
		return;
	}
	done = 1;
	platform = IOPlatformExpert::getPlatform();
	if (platform == NULL) {
		IOLog("HOUJI-DISP: no platform expert\\n");
		return;
	}
	HoujiDisplayNub *nub = new HoujiDisplayNub;
	if (nub == NULL) {
		IOLog("HOUJI-DISP: no nub\\n");
		return;
	}
	if (!nub->init()) {
		IOLog("HOUJI-DISP: nub init failed\\n");
		nub->release();
		return;
	}
	if (!nub->attachToParent(platform, gIODTPlane)) {
		IOLog("HOUJI-DISP: attach failed\\n");
		nub->release();
		return;
	}
	nub->registerService();
	IOLog("HOUJI-DISP: sweet,display nub published\\n");
}

extern "C" int houji_console_muted = 0;
extern "C" int native_adreno_present_begin_frame(uint32_t) { return 0; }
extern "C" uint32_t native_adreno_present_capture_fence(void) { return 0; }
extern "C" void native_adreno_present_end(void) { }
'''
(DST / "HoujiDisplayBootstrap.cpp").write_text(bootstrap)

conf = TREE / "iokit" / "conf" / "files"
text = conf.read_text()
for entry in ("iokit/Kernel/arm/SweetSurface.cpp                    optional iokitcpp\n",
              "iokit/Kernel/arm/SweetFramebuffer.cpp                optional iokitcpp\n",
              "iokit/Kernel/arm/HoujiDisplayBootstrap.cpp           optional iokitcpp\n"):
    if entry.split()[0] not in text:
        text = entry + text
conf.write_text(text)

tables = TREE / "iokit" / "KernelConfigTables.cpp"
t = tables.read_text()
marker = 'const char * gIOKernelConfigTables =\n    "("\n'
personality = (
    '    "   {"\n'
    '    "     \'IOClass\'         = AppleCLCD;"\n'
    '    "     \'IOProviderClass\' = IOPlatformDevice;"\n'
    '    "     \'IONameMatch\'     = \'sweet,display\';"\n'
    '    "   },"\n'
    '    "   {"\n'
    '    "     \'IOClass\'         = IOCoreSurfaceRoot;"\n'
    '    "     \'IOProviderClass\' = IOResources;"\n'
    '    "     \'IOMatchCategory\' = IOCoreSurfaceRoot;"\n'
    '    "   },"\n'
)
if "AppleCLCD" not in t:
    if marker not in t:
        raise SystemExit("KernelConfigTables marker missing")
    t = t.replace(marker, marker + personality)
    tables.write_text(t)
print("houji display overlaid")
