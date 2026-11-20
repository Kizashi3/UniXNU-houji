#!/usr/bin/env python3
"""Overlay the vendored NativeHidInput driver into the build tree."""
import os, shutil
from pathlib import Path
dev = Path(os.environ.get("DEVICE_DIR", "/tmp/houji-ci"))
tree = Path(".") / "out/houji/tree"
dst = tree / "drivers" / "NativeHidInput"
dst.mkdir(parents=True, exist_ok=True)
for name in ("NativeHidInput.cpp", "OriginalHidDeviceABI.h"):
    shutil.copyfile(dev / "vendor/drivers/NativeHidInput" / name, dst / name)
print("overlaid", dst, sorted(x.name for x in dst.iterdir()))
