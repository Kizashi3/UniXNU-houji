"""Reserve a boot-FDT resource report; never capabilities or an IRQ grant."""
import struct
from ios16_platform import read_nodes

PROPERTY = 'giulia-gpu-gunyah'
REPORT_BYTES = 256
MAGIC = int.from_bytes(b'GGR1', 'little')


def placeholder():
    return struct.pack('<4I', MAGIC, 1, REPORT_BYTES, 1) + bytes(REPORT_BYTES - 16)


def check_request(blob, mode=None, kernel=None):
    nodes = read_nodes(blob)
    found = [(p, props[PROPERTY]) for p, props in nodes.items() if PROPERTY in props]
    if mode not in (1, 2, 3):
        if found:
            raise ValueError('Gunyah resource request requires an enabled GPU')
        return None
    if found != [('/device-tree/chosen', placeholder())]:
        raise ValueError('GPU requires one pristine chosen Gunyah resource request')
    if nodes['/device-tree'].get('physical-model') != b'OnePlus Ace 5\0':
        raise ValueError('Gunyah handoff requires the Ace 5 GUI identity')
    if kernel is not None and b'GIULIA GPU: boot Gunyah resources' not in kernel:
        raise ValueError('GPU kernel lacks the Gunyah boot-resource consumer')
    return {'version': 1, 'report_bytes': REPORT_BYTES, 'source': 'current-boot-fdt',
            'irq_lease': False, 'runtime_capabilities_verified': False,
            'hypervisor_verified': False, 'hardware_verified': False}


def add_request(blob):
    nodes = read_nodes(blob)
    if len(blob) > 16 * 1024**2 or nodes.get('/device-tree', {}).get('physical-model') != b'OnePlus Ace 5\0':
        raise ValueError('Invalid Gunyah handoff ADT size or board')
    if any(PROPERTY in p for p in nodes.values()) or '/device-tree/chosen' not in nodes:
        raise ValueError('Gunyah request already exists or chosen is absent')
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
                name = blob[at:at + length - 1].decode('ascii')
            at += (length + 3) & ~3
        path = parent + '/' + name
        if path == '/device-tree/chosen':
            found = (start, properties, at)
        for _ in range(children):
            at = walk(at, path)
        return at

    walk(0, '')
    if found is None or found[1] == 0xffffffff:
        raise ValueError('Invalid chosen node')
    start, properties, end = found
    record = struct.pack('<32sI', PROPERTY.encode(), REPORT_BYTES) + placeholder()
    result = bytearray(blob[:end] + record + blob[end:])
    struct.pack_into('<I', result, start, properties + 1)
    result = bytes(result)
    check_request(result, 1)
    actual = read_nodes(result)
    del actual['/device-tree/chosen'][PROPERTY]
    if actual != nodes:
        raise ValueError('Gunyah request changed unrelated ADT data')
    return result
