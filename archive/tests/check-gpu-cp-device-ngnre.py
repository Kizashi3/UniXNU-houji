#!/usr/bin/env python3
"""Exercise the shared fixed CP-page audit under address/undefined sanitizers."""
from pathlib import Path
import subprocess
import tempfile

p = Path(__file__).resolve().parents[1]
policy = p / 'native/gpu/uefi/HoujiCpDeviceNgNrePolicy.h'
firmware = p.parent / 'uefi-houji/Mu_Basecore/UefiCpuPkg/Library/ArmMmuLib/HoujiCpDeviceNgNrePolicy.h'
assert policy.read_bytes() == firmware.read_bytes(), 'Firmware/policy source drift'
with tempfile.TemporaryDirectory(prefix='houji-cp-ngnre-') as directory:
    executable = Path(directory) / 'check'
    subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O1', '-g',
                    '-fsanitize=address,undefined', str(Path(__file__).with_suffix('.c')),
                    '-o', str(executable)], check=True)
    subprocess.run([str(executable)], check=True)
