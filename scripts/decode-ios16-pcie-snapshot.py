"""Decode the opt-in, failure-only PCIe register snapshot (not a handoff)."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import struct
from ios16_pcie_diagnostic import decode_trace, render_trace

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('log', type=Path)
p.add_argument('--out', type=Path, required=True)
a = p.parse_args()
root = Path(__file__).resolve().parents[1]
header = root / 'uefi-overlay/Platforms/OnePlus/giuliaPkg/Drivers/GiuliaInitrdDxe/WifiPcieSnapshot.h'
registers = re.findall(r'\{GW_(GCC|PARF|PHY),(0x[0-9a-f]+|0)\}', header.read_text())
assert len(registers) == 39
bases = {'GCC': 0x100000, 'PARF': 0x1c00000, 'PHY': 0x1c06000}
data = a.log.read_bytes()
snapshots = []
for version, token in dict.fromkeys(re.findall(rb'\bgiulia_pcid([12])=([^\s\x00]+)', data)):
    raw = base64.b64decode(token, validate=True)
    if version == b'2':
        snapshots.append(decode_trace(raw))
        continue
    if len(raw) != 168:
        raise ValueError('Snapshot is truncated or has an unsupported size')
    words = struct.unpack('<42I', raw)
    if words[0] != 0x31535047 or words[1] != 13 or not words[2]:
        raise ValueError('Not a version-1 link-failure snapshot')
    snapshots.append({'stage': words[1], 'error': words[2], 'registers': [
        {'region': region, 'offset': hex(int(offset, 0)),
         'address': hex(bases[region] + int(offset, 0)), 'value': hex(value)}
        for (region, offset), value in zip(registers, words[3:])]})
if not snapshots:
    p.error('No snapshot captured; do not infer register values')
result = {'source_sha256': hashlib.sha256(data).hexdigest(),
          'layout_sha256': hashlib.sha256(header.read_bytes()).hexdigest(),
          'scope': 'UEFI link failure before cleanup; not endpoint enumeration',
          'snapshots': snapshots}
with a.out.open('x') as f:
    json.dump(result, f, indent=2)
    f.write('\n')
print(json.dumps(result, indent=2))
traces = [r for r in snapshots if r.get('format') == 2]
if traces:
    a.out.with_suffix('.txt').write_text('\n'.join(render_trace(r) for r in traces), encoding='utf-8')
