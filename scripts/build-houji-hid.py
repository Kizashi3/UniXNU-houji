#!/usr/bin/env python3
"""Build the in-kernel IOHIDEventService stack and SweetHIDTouch."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
recipe = ROOT / "build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json"
record = json.loads(recipe.read_text().strip().rstrip(","))
src_dir = ROOT / "drivers/HoujiHID"
out = ROOT / "build/houji-hid"
out.mkdir(parents=True, exist_ok=True)
names = ["IOHIDEvent.cpp", "IOHIDEventServiceQueue.cpp", "IOHIDEventServiceUserClient.cpp", "SweetHID.cpp"]
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
    cmd += ["-I", str(src_dir), "-Wno-error", "-Wno-unused-parameter", "-Wno-sign-conversion",
            "-Wno-unused-function", "-Wno-deprecated-volatile", "-Wno-missing-field-initializers"]
    result = subprocess.run(cmd, cwd=record["directory"], capture_output=True, text=True)
    (out / (src.stem + ".log")).write_text(result.stdout + result.stderr)
    if result.returncode:
        sys.stderr.write(result.stdout + result.stderr)
        sys.exit(1)
    objects.append(str(obj))
archive = out / "libHoujiHID.a"
archive.unlink(missing_ok=True)
subprocess.run(["xcrun", "ar", "rcs", str(archive), *objects], check=True)
print("built", archive)
