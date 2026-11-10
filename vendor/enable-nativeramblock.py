#!/usr/bin/env python3
"""Overlay the vendored NativeRamBlock driver into the build tree.

`unixnu build kernel` re-assembles out/houji/tree, so the driver must be copied from
the device repository each run. Binding generation and the writable-Data link are
added in later steps; this only makes the driver source available to build-arm-driver.py.
"""
import os
import shutil
from pathlib import Path

dev = Path(os.environ.get('DEVICE_DIR', '/tmp/houji-ci'))
tree = Path('.') / 'out/houji/tree'

dst = tree / 'drivers' / 'NativeRamBlock'
shutil.rmtree(dst, ignore_errors=True)
shutil.copytree(dev / 'vendor' / 'drivers' / 'NativeRamBlock', dst)
print('overlaid', dst, 'cpp', (dst / 'NativeRamBlock.cpp').is_file())