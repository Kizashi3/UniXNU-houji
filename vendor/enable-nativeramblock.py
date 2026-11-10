#!/usr/bin/env python3
"""Overlay the vendored NativeRamBlock driver into the build tree.

The upstream tree already ships a reference drivers/NativeRamBlock; replace only its
NativeRamBlock.cpp with our own self-contained implementation (build-arm-driver.py
compiles that single file). Copying the file in place avoids removing the upstream
directory, which can fail on read-only auxiliary files.
"""
import os
import shutil
from pathlib import Path

dev = Path(os.environ.get('DEVICE_DIR', '/tmp/houji-ci'))
tree = Path('.') / 'out/houji/tree'

dst = tree / 'drivers' / 'NativeRamBlock'
dst.mkdir(parents=True, exist_ok=True)
src = dev / 'vendor' / 'drivers' / 'NativeRamBlock' / 'NativeRamBlock.cpp'
shutil.copyfile(src, dst / 'NativeRamBlock.cpp')
print('overlaid', dst / 'NativeRamBlock.cpp', 'bytes', (dst / 'NativeRamBlock.cpp').stat().st_size)