#!/usr/bin/env python3
"""Real CLANGPDB-target high IOVA regression; no device, SMC or ARM execution."""
from pathlib import Path
import re,subprocess
p=Path(__file__).resolve().parents[1]
# Use the current complete mirrored application include tree used by UEFI.
base=['docker','exec','-i','unixnu-houji-build','clang','-target','aarch64-unknown-windows-msvc','-fms-extensions','-ffreestanding','-I','/work/uefi-houji/Platforms/Xiaomi/houjiPkg/Application/HoujiStorageProbe','-S','-emit-llvm','-x','c','-o','-','-']
source='#define GG_HOST_TEST 1\n#include "GpuSecureContext.h"\nuint64_t secure_iova(void){return HSE_IOVA;}\n'
r=subprocess.run(base,input=source,text=True,capture_output=True,check=True)
assert re.search(r'define[^\n]*@secure_iova\([^}]+ret i64 4026531840',r.stdout),r.stdout[-6000:]
bad='enum { BAD=0xf0000000u }; unsigned long long secure_iova(void){return BAD;}\n'
r=subprocess.run(base,input=bad,text=True,capture_output=True,check=True)
assert re.search(r'ret i64 -268435456',r.stdout),r.stdout
print('PASS: real Windows ARM64 UEFI target preserves F0000000 as zero-extended64bit IOVA; original enum fixture reproduces bad sign extension')
