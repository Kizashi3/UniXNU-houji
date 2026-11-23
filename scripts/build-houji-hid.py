#!/usr/bin/env python3
"""Build the in-kernel IOHIDEventService stack and SweetHIDTouch."""
import json
import subprocess
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
recipe = ROOT / "build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json"
record = json.loads(recipe.read_text().strip().rstrip(","))
src_dir = ROOT / "drivers/HoujiHID"
out = ROOT / "build/houji-hid"
out.mkdir(parents=True, exist_ok=True)
names = ["IOHIDEvent.cpp", "IOHIDEventServiceQueue.cpp", "IOHIDEventServiceUserClient.cpp", "SweetHID.cpp", "HoujiNativeTouch.cpp"]
hs = src_dir / "hidsystem"
names += [str(x.relative_to(src_dir)) for x in sorted(hs.glob("*.cpp")) if x.name not in {"IOBSDConsole.cpp"}]
def verify_native_vtable(source, manifest):
    image = source.read_bytes()
    if struct.unpack_from("<IIII", image) != (0xfeedfacf, 0x0100000c, 0, 1):
        raise SystemExit("Native touch requires an arm64 Mach-O object")

    sections = []
    cursor = 32
    for _ in range(struct.unpack_from("<I", image, 16)[0]):
        command, length = struct.unpack_from("<II", image, cursor)
        if command == 2:
            symbol_offset, symbol_count, strings, _ = struct.unpack_from("<IIII", image, cursor + 8)
        if command == 0x19:
            count = struct.unpack_from("<I", image, cursor + 64)[0]
            sections += [cursor + 72 + i * 80 for i in range(count)]
        cursor += length

    symbols = []
    for i in range(symbol_count):
        name_offset, kind, _, _, address = struct.unpack_from("<IBBHQ", image, symbol_offset + i * 16)
        start = strings + name_offset
        end = image.index(b"\0", start)
        symbols.append((image[start:end].decode(), kind, address))

    table = next(address for name, _, address in symbols if name == "__ZTV16HoujiNativeTouch")
    for section in sections:
        start, size = struct.unpack_from("<QQ", image, section + 32)
        if start <= table < start + size:
            break
    else:
        raise SystemExit("Native touch vtable section missing")
    offset, count = struct.unpack_from("<II", image, section + 56)
    slots = {}
    for offset in range(offset, offset + count * 8, 8):
        position, attributes = struct.unpack_from("<II", image, offset)
        external_pointer = attributes >> 24 == 0x0e
        if external_pointer:
            slots[start + position] = symbols[attributes & 0xffffff][0]

    expected = manifest["compiled_slots"]
    got = [slots.get(table + 16 + i * 8) for i in range(len(expected))]
    if got != expected or table + 16 + len(expected) * 8 in slots:
        raise SystemExit("Native touch vtable differs from the qualified IOHIDDevice layout")
    undefined = {name for name, kind, _ in symbols if kind == 1 and "11IOHIDDevice" in name}
    if undefined != set(manifest["bindings"]):
        raise SystemExit("Native touch IOHIDDevice imports differ from the qualified bindings")


objects = []
for name in names:
    src = src_dir / name
    obj = out / (src.stem + ".o")
    cmd = []
    args = record["arguments"]
    i = 0
    while i < len(args):
        value = args[i]
        if value == record["file"]:
            cmd.append(str(src))
        elif value == "-o":
            cmd.extend(["-o", str(obj)])
            i += 1
        elif value == "-Xclang" and args[i + 1].startswith("-W"):
            i += 1
        elif not value.startswith("-W"):
            cmd.append(value)
        i += 1
    cmd += ["-I", str(src_dir), "-I", str(hs), "-I", str(hs / "IOKit"), "-I", str(hs / "IOKit" / "hidsystem"), "-I", str(hs / "IOHIDFamilyHeaders"), "-Wno-error", "-Wno-unused-parameter", "-Wno-sign-conversion",
            "-Wno-unused-function", "-Wno-deprecated-volatile", "-Wno-missing-field-initializers"]
    if name == "HoujiNativeTouch.cpp":
        cmd += ["-fno-c++-static-destructors"]
    result = subprocess.run(cmd, cwd=record["directory"], capture_output=True, text=True)
    (out / (src.stem + ".log")).write_text(result.stdout + result.stderr)
    if result.returncode:
        sys.stderr.write(result.stdout + result.stderr)
        sys.exit(1)
    if name == "HoujiNativeTouch.cpp":
        verify_native_vtable(obj, json.loads((src_dir / "abi-audit.json").read_text()))
        llvm = Path(subprocess.check_output(["brew", "--prefix", "llvm"], text=True).strip()) / "bin"
        late = out / "HoujiNativeTouch.late.o"
        subprocess.run([llvm / "llvm-objcopy", "--remove-section=__DATA,__mod_init_func",
                        "--globalize-symbol=__GLOBAL__sub_I_HoujiNativeTouch.cpp", obj, late], check=True)
        bindings = out / "iohiddevice-bindings.o"
        subprocess.run(["xcrun", "clang", "-target", "arm64-apple-ios17.0", "-c",
                        src_dir / "iohiddevice-bindings.S", "-o", bindings], check=True)
        objects.append(str(bindings))
        obj = late
    objects.append(str(obj))
archive = out / "libHoujiHID.a"
archive.unlink(missing_ok=True)
subprocess.run(["xcrun", "ar", "rcs", str(archive), *objects], check=True)
print("built", archive)
