"""Overlay our own HoujiFramebuffer driver into the XNU tree.

Installs iokit/Kernel/arm/HoujiFramebuffer.cpp, adds the build entry and the
built-in personality that matches the display nub we publish at runtime.
"""
import os
import pathlib
import shutil

DEVICE = pathlib.Path(os.environ["DEVICE_DIR"])
TREE = DEVICE.parent / "unixnu" / "out" / "houji" / "tree"
SRC = DEVICE / "vendor" / "drivers" / "HoujiFramebuffer"

arm = TREE / "iokit" / "Kernel" / "arm"
arm.mkdir(parents=True, exist_ok=True)
shutil.copyfile(SRC / "HoujiFramebuffer.cpp", arm / "HoujiFramebuffer.cpp")

conf = TREE / "iokit" / "conf" / "files"
text = conf.read_text()
entry = "iokit/Kernel/arm/HoujiFramebuffer.cpp                     optional iokitcpp\n"
if "HoujiFramebuffer.cpp" not in text:
    text = entry + text
conf.write_text(text)

tables = TREE / "iokit" / "KernelConfigTables.cpp"
t = tables.read_text()
marker = 'const char * gIOKernelConfigTables =\n    "("\n'
personality = (
    '    "   {"\n'
    '    "     \'IOClass\'         = HoujiFramebuffer;"\n'
    '    "     \'IOProviderClass\' = IOPlatformDevice;"\n'
    '    "     \'IONameMatch\'     = \'houji,display\';"\n'
    '    "   },"\n'
)
if "HoujiFramebuffer" not in t:
    if marker not in t:
        raise SystemExit("KernelConfigTables marker missing")
    t = t.replace(marker, marker + personality)
    tables.write_text(t)
print("houji framebuffer overlaid")
