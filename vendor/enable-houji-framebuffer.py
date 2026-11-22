"""Overlay the HoujiFramebuffer driver and the in-kernel HID stack."""
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

hid_src = DEVICE / "vendor" / "drivers" / "HoujiHID"
hid_dst = TREE / "iokit" / "Kernel" / "arm" / "hid"
if hid_src.is_dir():
    shutil.copytree(hid_src, hid_dst, dirs_exist_ok=True)
    files_conf = TREE / "iokit" / "conf" / "files.arm64"
    if files_conf.is_file():
        text = files_conf.read_text()
        for line in (
            "iokit/Kernel/arm/hid/SweetHID.cpp optional iokitcpp",
            "iokit/Kernel/arm/hid/IOHIDEvent.cpp optional iokitcpp",
            "iokit/Kernel/arm/hid/IOHIDEventServiceQueue.cpp optional iokitcpp",
            "iokit/Kernel/arm/hid/IOHIDEventServiceUserClient.cpp optional iokitcpp",
        ):
            if line.split()[0] not in text:
                text += line + "\n"
        files_conf.write_text(text)
        print("iokit/conf/files.arm64: HoujiHID sources added")
    kct = TREE / "iokit" / "KernelConfigTables.cpp"
    if kct.is_file():
        text = kct.read_text()
        if "SweetHIDTouch" not in text:
            needle = '    ")";'
            idx = text.rfind(needle)
            head = text[:idx]
            close = '    "   }"'
            j = head.rfind(close)
            if idx < 0 or j < 0:
                raise SystemExit("KernelConfigTables tail not found")
            head = head[:j] + '    "   },"' + head[j + len(close):]
            entry = (
                '    "   {"\n'
                '    "     \'IOClass\'         = SweetHIDTouch;"\n'
                '    "     \'IOProviderClass\' = IOResources;"\n'
                '    "     \'IOMatchCategory\' = SweetHIDTouch;"\n'
                '    "   }"\n'
            )
            text = head + entry + text[idx:]
            kct.write_text(text)
            print("KernelConfigTables: SweetHIDTouch entry added")
    print("HoujiHID compiled into iokit")

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
