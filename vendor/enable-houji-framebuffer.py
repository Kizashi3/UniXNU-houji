"""Overlay our own HoujiFramebuffer driver and link it into the kernel.

The device build compiles drivers as archives (build-arm-driver.py) and links
them with force_load, so the driver lives under tree/drivers and is wired
through board.toml and the kernel build script.
"""
import os
import pathlib
import re
import shutil

DEVICE = pathlib.Path(os.environ["DEVICE_DIR"])
TREE = DEVICE.parent / "unixnu" / "out" / "houji" / "tree"
SRC = DEVICE / "vendor" / "drivers" / "HoujiFramebuffer"

dst = TREE / "drivers" / "HoujiFramebuffer"
dst.mkdir(parents=True, exist_ok=True)
shutil.copyfile(SRC / "HoujiFramebuffer.cpp", dst / "HoujiFramebuffer.cpp")

for script in (DEVICE / "scripts" / "build-arm-driver.py", TREE / "scripts" / "build-arm-driver.py"):
    if not script.is_file():
        continue
    text = script.read_text()
    if "'HoujiFramebuffer'" not in text:
        text = text.replace("'NativeRamBlock', ", "'NativeRamBlock', 'HoujiFramebuffer', ", 1)
        text = text.replace("'NativeUfs':'native-ufs',", "'NativeUfs':'native-ufs', 'HoujiFramebuffer':'houji-framebuffer',", 1)
        script.write_text(text)
        print(script, ": HoujiFramebuffer added")

board = DEVICE / "board.toml"
text = board.read_text()
if "build-arm-driver.py HoujiFramebuffer" not in text:
    match = re.search(r"archives = \[\n", text)
    if not match:
        raise SystemExit("board.toml has no archives array")
    text = text[:match.end()] + '  "build-arm-driver.py HoujiFramebuffer",\n' + text[match.end():]
    board.write_text(text)
    print("board.toml: HoujiFramebuffer archive added")

conf = DEVICE / "configs" / "houji_defconfig"
text = conf.read_text()
if "CONFIG_XNU_EXTRA_LD_ARCHIVES" in text:
    text = re.sub(r"CONFIG_XNU_EXTRA_LD_ARCHIVES=.*", 'CONFIG_XNU_EXTRA_LD_ARCHIVES=""', text)
    conf.write_text(text)
    print("defconfig: extra archives cleared")

anchor = '  KERNEL_EXTRA_ARCHIVES="$KERNEL_EXTRA_ARCHIVES ${XNU_EXTRA_LD_ARCHIVES:-}"\n'
insert = anchor + (
    '  KERNEL_EXTRA_ARCHIVES="$KERNEL_EXTRA_ARCHIVES -Wl,-force_load,$ROOT/build/houji-framebuffer/libHoujiFramebuffer.a"\n'
    '  KERNEL_ARCHIVE_DEPENDENCIES="$KERNEL_ARCHIVE_DEPENDENCIES $ROOT/build/houji-framebuffer/libHoujiFramebuffer.a"\n')
for script in (DEVICE.parent / "unixnu" / "scripts" / "build-xnu-4k-baseline.sh",
               TREE / "scripts" / "build-xnu-4k-baseline.sh"):
    if not script.is_file():
        continue
    t = script.read_text()
    if "libHoujiFramebuffer.a" in t:
        print(script, ": framebuffer archive already linked")
        continue
    if anchor not in t:
        raise SystemExit("archive anchor missing in %s" % script)
    script.write_text(t.replace(anchor, insert, 1))
    print(script, ": framebuffer archive linked")
