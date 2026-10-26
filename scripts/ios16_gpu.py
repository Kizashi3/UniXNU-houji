"""Ace 5 GPU input qualification. This module never accesses hardware.

The DTS reader deliberately accepts only decoded, numeric dtc output; source
DTS with macros, labels or includes must first be compiled and decoded by dtc.
"""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CHIP_ID = 0x43051401
COMPATIBLE = 'qcom,adreno-gpu-gen7-9-1'
FIRMWARE = ('gmu_gen70900.bin', 'gen70900_sqe.fw',
            'gen70900_aqe.fw', 'gen70900_zap.mbn')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def block(text, name):
    matches = list(re.finditer(r'(?m)^\s*' + re.escape(name) + r'\s*\{', text))
    if len(matches) != 1:
        raise ValueError('Expected exactly one node: ' + name)
    start = matches[0].end()
    depth = 1
    for end in range(start, len(text)):
        depth += (text[end] == '{') - (text[end] == '}')
        if not depth:
            return text[start:end]
    raise ValueError('Unterminated node: ' + name)


def property_value(node, name):
    # Drop child nodes, so a child property cannot impersonate its parent.
    while '{' in node:
        node, count = re.subn(r'[^;{}]*\{[^{}]*\};', '', node)
        if not count:
            raise ValueError('Malformed decoded DTS')
    values = re.findall(r'(?m)^\s*' + re.escape(name) + r'\s*=\s*([^;]+);', node)
    if len(values) != 1:
        raise ValueError('Expected exactly one property: ' + name)
    return values[0].strip()


def cells(node, name):
    value = property_value(node, name)
    if not re.fullmatch(r'<\s*(?:(?:0x[0-9a-fA-F]+|[0-9]+)\s*)+>', value):
        raise ValueError('Expected decoded numeric cells: ' + name)
    result = [int(x, 0) for x in value[1:-1].split()]
    if any(x > 0xffffffff for x in result):
        raise ValueError('Cell exceeds 32 bits: ' + name)
    return result


def strings(node, name):
    value = property_value(node, name)
    if not re.fullmatch(r'"[^"\\]*"(?:\s*,\s*"[^"\\]*")*', value):
        raise ValueError('Expected string list: ' + name)
    return re.findall(r'"([^"\\]*)"', value)


def windows(node):
    names, reg = strings(node, 'reg-names'), cells(node, 'reg')
    if len(reg) != 2 * len(names) or len(set(names)) != len(names):
        raise ValueError('Register name/window mismatch')
    result = {}
    for i, name in enumerate(names):
        base, size = reg[2*i:2*i+2]
        if not size or base + size > 0x100000000:
            raise ValueError('Invalid register window')
        result[name] = {'base': base, 'size': size}
    return result


def board_from_dts(data):
    text = data.decode('utf-8')
    gpu = block(text, 'qcom,kgsl-3d0@3d00000')
    gmu = block(text, 'qcom,gmu@3d69000')
    smmu = block(text, 'kgsl-smmu@3da0000')
    iommu = block(text, 'qcom,kgsl-iommu@3da0000')
    cx = block(text, 'qcom,gdsc@3d99108')
    cx_hw = block(text, 'syscon@3d99168')
    if cells(cx, 'hw-ctrl-addr') != cells(cx_hw, 'phandle'):
        raise ValueError('CX domain hardware-status reference mismatch')
    if cells(gpu, 'qcom,chipid') != [CHIP_ID] or COMPATIBLE not in strings(gpu, 'compatible'):
        raise ValueError('Not the qualified Ace 5 Adreno 750 v2 GPU')
    if strings(gpu, 'status') not in (['ok'], ['okay']):
        raise ValueError('GPU is disabled')
    phandle = cells(smmu, 'phandle')
    if len(phandle) != 1 or not phandle[0] or cells(smmu, '#iommu-cells') != [2]:
        raise ValueError('Unexpected GPU SMMU specifier')
    routes = {}
    for name, node in [('user', block(iommu, 'gfx3d_user')),
                       ('lpac', block(iommu, 'gfx3d_lpac')),
                       ('secure', block(iommu, 'gfx3d_secure')), ('gmu', gmu)]:
        route = cells(node, 'iommus')
        if len(route) != 3 or route[0] != phandle[0] or route[2] != 0:
            raise ValueError('Invalid GPU SMMU route: ' + name)
        routes[name] = route[1]
    if routes != {'user': 0, 'lpac': 1, 'secure': 2, 'gmu': 5}:
        raise ValueError('Unqualified stream IDs')
    return {
        'chip_id': CHIP_ID, 'gpu_id': 750, 'compatible': COMPATIBLE,
        'model': strings(gpu, 'qcom,gpu-model')[0],
        'gpu_windows': windows(gpu), 'gmu_windows': windows(gmu),
        'smmu_windows': windows(smmu), 'stream_ids': routes,
        'gpu_interrupts': cells(gpu, 'interrupts'),
        'gmu_interrupts': cells(gmu, 'interrupts'),
        'gmu_frequency_table': cells(gmu, 'qcom,gmu-freq-table'),
        'gpu_clock_names': strings(gpu, 'clock-names'),
        'gmu_clock_names': strings(gmu, 'clock-names'),
        'smmu_actlr': cells(smmu, 'qcom,actlr'),
        'gpucc_reg': cells(block(text, 'clock-controller@3d90000'), 'reg'),
        'cx_gdsc_reg': cells(cx, 'reg'),
        'cx_hw_control_reg': cells(cx_hw, 'reg'),
    }


def verify_inputs(dts, source_dir, firmware_dir, pin_path=None):
    pins = json.loads((pin_path or ROOT/'hardware/sm8650-gpu.json').read_text())
    data = dts.read_bytes()
    if digest(data) != pins['dts_sha256']:
        raise ValueError('Captured device tree hash mismatch')
    board = board_from_dts(data)
    if board != pins['board']:
        raise ValueError('Board contract mismatch')
    for source in pins['vendor_sources']:
        data = (source_dir/source['file']).read_bytes()
        if digest(data) != source['sha256']:
            raise ValueError('Vendor source hash mismatch: ' + source['file'])
    gpulist = (source_dir/'adreno-gpulist.h').read_text()
    core = block(gpulist.replace(' = {', ' {'),
                 'static const struct adreno_gen7_core adreno_gpu_core_gen7_9_1')
    for name in FIRMWARE:
        if '"' + name + '"' not in core:
            raise ValueError('Vendor GPU profile does not name ' + name)
    if '.gmem_size = 3 * SZ_1M' not in core or 'adreno_gen7_9_0_hwsched_gpudev' not in core:
        raise ValueError('Vendor GMEM/scheduler contract changed')
    assets = []
    for entry in pins['firmware']:
        path = firmware_dir/entry['name']
        if path.is_symlink():
            raise ValueError('Firmware symlinks are not accepted')
        data = path.read_bytes()
        if len(data) != entry['size'] or digest(data) != entry['sha256']:
            raise ValueError('Firmware hash/size mismatch: ' + entry['name'])
        assets.append(entry)
    return {'schema': 1, 'board': board, 'firmware': assets,
            'inputs_verified': True, 'hardware_initialized': False,
            'metal_available': False, 'remaining': pins['remaining']}
