"""Explicit, fixed-size ADT request for pre-EBS GPU power preparation."""
import struct

from ios16_platform import read_nodes


PROPERTY = 'giulia-gpu-power'
MAGIC = int.from_bytes(b'GPP1', 'little')
VERSION = 1
REPORT_BYTES = 256


def placeholder():
    # The loader accepts only this exact request, in addition to the exact
    # giulia_gpu=3 boot token. Its result replaces these reserved bytes in RAM.
    return struct.pack('<4I', MAGIC, VERSION, REPORT_BYTES, 1) + bytes(REPORT_BYTES - 16)


def check_request(blob, mode=None, kernel=None):
    nodes = read_nodes(blob)
    locations = [(path, props[PROPERTY]) for path, props in nodes.items() if PROPERTY in props]
    if mode != 3:
        if locations:
            raise ValueError('GPU power ADT request requires explicit GPU mode 3')
        return None
    if locations != [('/device-tree/chosen', placeholder())]:
        raise ValueError('GPU mode 3 requires one exact, unused chosen GPU power request')
    if nodes['/device-tree'].get('physical-model') != b'OnePlus Ace 5\0':
        raise ValueError('GPU power request requires the Ace 5 GUI identity')
    if kernel is not None and b'GIULIA GPU: UEFI power handoff' not in kernel:
        raise ValueError('GPU mode 3 requires the compiled power handoff consumer')
    return {'version': VERSION, 'report_bytes': REPORT_BYTES,
            'stage': 'requested-before-exit-boot-services',
            'resources_retained_until_reset': True, 'hardware_verified': False,
            'provider_waits_preemptible': False,
            'gmu_execution': False, 'acceleration': False}


def add_request(blob):
    nodes = read_nodes(blob)
    if len(blob) > 16 * 1024**2:
        raise ValueError('GPU ADT exceeds the loader limit')
    if nodes.get('/device-tree', {}).get('physical-model') != b'OnePlus Ace 5\0':
        raise ValueError('GPU power request requires the Ace 5 GUI identity')
    if any(PROPERTY in props for props in nodes.values()):
        raise ValueError('Refusing to overwrite an existing GPU power request or result')
    if '/device-tree/chosen' not in nodes:
        raise ValueError('GPU power request requires chosen')
    found = None

    def walk(at, parent):
        nonlocal found
        start = at
        properties, children = struct.unpack_from('<II', blob, at)
        at += 8
        name = None
        for _ in range(properties):
            key, length = struct.unpack_from('<32sI', blob, at)
            at += 36
            if key.split(b'\0', 1)[0] == b'name':
                name = blob[at:at + length][:-1].decode('ascii')
            at += (length + 3) & ~3
        path = parent + '/' + name
        if path == '/device-tree/chosen':
            found = (start, properties, at)
        for _ in range(children):
            at = walk(at, path)
        return at

    walk(0, '')  # read_nodes already validated every bound, name and duplicate.
    if found is None:
        raise ValueError('Chosen node not found')
    start, properties, end = found
    if properties == 0xffffffff:
        raise ValueError('Chosen property count overflow')
    record = struct.pack('<32sI', PROPERTY.encode(), REPORT_BYTES) + placeholder()
    out = bytearray(blob[:end] + record + blob[end:])
    struct.pack_into('<I', out, start, properties + 1)
    result = bytes(out)
    check_request(result, 3)
    actual = read_nodes(result)
    del actual['/device-tree/chosen'][PROPERTY]
    if actual != nodes:
        raise ValueError('GPU request changed unrelated ADT data')
    return result
