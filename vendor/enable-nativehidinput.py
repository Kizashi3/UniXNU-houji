#!/usr/bin/env python3
"""Overlay the vendored NativeHidInput driver into the build tree."""
import os, shutil
from pathlib import Path
dev = Path(os.environ.get("DEVICE_DIR", "/tmp/houji-ci"))
tree = Path(".") / "out/houji/tree"
dst = tree / "drivers" / "NativeHidInput"
dst.mkdir(parents=True, exist_ok=True)
shutil.copyfile(dev / "vendor/drivers/NativeHidInput/NativeHidInput.cpp", dst / "NativeHidInput.cpp")
print("overlaid", dst / "NativeHidInput.cpp", "bytes", (dst / "NativeHidInput.cpp").stat().st_size)
