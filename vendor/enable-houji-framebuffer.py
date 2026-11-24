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

hid_src = DEVICE / "vendor" / "drivers" / "HoujiHID"
if hid_src.is_dir():
    shutil.copytree(hid_src, TREE / "drivers" / "HoujiHID", dirs_exist_ok=True)
    hid_builder = DEVICE / "scripts" / "build-houji-hid.py"
    if hid_builder.is_file():
        shutil.copyfile(hid_builder, TREE / "scripts" / "build-houji-hid.py")
        (TREE / "scripts" / "build-houji-hid.py").chmod(0o755)
    print("HoujiHID overlay copied")

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

if "build-houji-hid.py" not in text:
    match = re.search(r"archives = \[\n", text)
    if match:
        text = text[:match.end()] + '  "build-houji-hid.py",\n' + text[match.end():]
        board.write_text(text)
        print("board.toml: HoujiHID archive added")

anchor = '  KERNEL_EXTRA_ARCHIVES="$KERNEL_EXTRA_ARCHIVES ${XNU_EXTRA_LD_ARCHIVES:-}"\n'
insert = anchor + (
    '  if [ -n "${XNU_EXTRA_LD_ARCHIVES:-}" ]; then\n'
    '    KERNEL_ARCHIVE_DEPENDENCIES="$KERNEL_ARCHIVE_DEPENDENCIES $ROOT/build/houji-gpu/libHoujiGpu.a"\n'
    '  fi\n'
    '  KERNEL_EXTRA_ARCHIVES="$KERNEL_EXTRA_ARCHIVES -Wl,-force_load,$ROOT/build/houji-framebuffer/libHoujiFramebuffer.a"\n'
    '  KERNEL_ARCHIVE_DEPENDENCIES="$KERNEL_ARCHIVE_DEPENDENCIES $ROOT/build/houji-framebuffer/libHoujiFramebuffer.a"\n'
    '  KERNEL_EXTRA_ARCHIVES="$KERNEL_EXTRA_ARCHIVES -Wl,-force_load,$ROOT/build/houji-hid/libHoujiHID.a"\n'
    '  KERNEL_ARCHIVE_DEPENDENCIES="$KERNEL_ARCHIVE_DEPENDENCIES $ROOT/build/houji-hid/libHoujiHID.a"\n')
for script in (DEVICE.parent / "unixnu" / "scripts" / "build-xnu-4k-baseline.sh",
               TREE / "scripts" / "build-xnu-4k-baseline.sh"):
    if not script.is_file():
        continue
    t = script.read_text()
    if "libHoujiFramebuffer.a" in t and "libHoujiHID.a" in t and "libHoujiGpu.a" in t:
        print(script, ": framebuffer and GPU archives already linked")
        continue
    if anchor not in t:
        raise SystemExit("archive anchor missing in %s" % script)
    script.write_text(t.replace(anchor, insert, 1))
    print(script, ": framebuffer archive linked")
