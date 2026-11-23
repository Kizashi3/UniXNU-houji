#!/usr/bin/env python3
"""Check the actual UEFI command line fits Darwin 22 without losing touch."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / 'uefi/overlay/Platforms/Xiaomi/houjiPkg/Application/HoujiStorageProbe/HoujiStorageProbe.c').read_text()
base = re.search(r'BaseBootArgs = L"([^"]+)";', source).group(1)
capacity = int(re.search(r'CHAR16 BootArgs\[(\d+)\];', source).group(1))
template = re.search(r'UnicodeSPrint\(BootArgs,sizeof\(BootArgs\),L"([^"]+)"', source).group(1)
for mhz in (231, 500, 680, 903):
    candidate = re.sub(r'gpu_max_mhz=\d+', f'gpu_max_mhz={mhz}', base)
    assert candidate != base or mhz == 903
    for touch in (0, 1):
        command = template % (candidate, touch)
        assert len(command.encode('ascii')) + 1 <= min(capacity, 608)
        options = [word.split('=', 1)[0] for word in command.split()]
        assert len(options) == len(set(options)), 'duplicate boot argument'
        assert f'gpu_max_mhz={mhz}' in command.split()
        assert command.endswith(f'houji_touch={touch}')
assert 'StrLen(BaseBootArgs) + StrLen(L" houji_touch=1") >= ARRAY_SIZE(BootArgs)' in source
print('PASS: UEFI GPU ceiling and touch handoff fit the 608-byte Darwin 22 command line')
