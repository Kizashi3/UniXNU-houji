"""Cross-check the ADT against the built-in platform/CPU personalities we ship."""
import re
import struct


def read_nodes(blob):
    nodes = {}
    def walk(at, parent, depth=0):
        if depth > 64 or at + 8 > len(blob):
            raise ValueError('Invalid ADT node')
        count, children = struct.unpack_from('<II', blob, at)
        at += 8
        props = {}
        for _ in range(count):
            if at + 36 > len(blob):
                raise ValueError('Truncated ADT property')
            key, length = struct.unpack_from('<32sI', blob, at)
            at += 36
            if b'\0' not in key or length > len(blob) - at:
                raise ValueError('Invalid ADT property')
            key = key.split(b'\0', 1)[0].decode('ascii')
            if key in props:
                raise ValueError('Duplicate ADT property')
            props[key] = blob[at:at+length]
            at += (length + 3) & ~3
        name = props.get('name', b'')
        if not name.endswith(b'\0') or b'\0' in name[:-1]:
            raise ValueError('Invalid ADT node name')
        path = parent + '/' + name[:-1].decode('ascii')
        if path in nodes:
            raise ValueError('Duplicate ADT node')
        nodes[path] = props
        for _ in range(children):
            at = walk(at, path, depth+1)
        return at
    if walk(0, '') != len(blob):
        raise ValueError('Invalid ADT length')
    return nodes


def personality(kernel, driver, provider):
    # Read the actual serialized built-in personality, not an unrelated log
    # string containing the same compatible name. Reject ambiguity or drift.
    pattern = (rb"\{\s*'IOClass'\s*=\s*" + driver.encode() + rb";\s*"
               rb"'IOProviderClass'\s*=\s*" + provider.encode() + rb";\s*"
               rb"'IONameMatch'\s*=\s*'([^'\x00]{1,64})';")
    matches = re.findall(pattern, kernel)
    if len(matches) != 1:
        raise ValueError(f'Expected one built-in {driver} personality, found {len(matches)}')
    return matches[0]


def compatible(props):
    value = props.get('compatible', b'')
    if not value.endswith(b'\0') or b'\0\0' in value:
        raise ValueError('Invalid compatible string list')
    return value[:-1].split(b'\0')


def check_platform(adt, kernel):
    nodes = read_nodes(adt)
    root = nodes['/device-tree']
    cpus = [props for path, props in nodes.items() if path.startswith('/device-tree/cpus/')]
    if len(cpus) != 1:
        raise ValueError('This kernel supports one boot CPU')
    platform = personality(kernel, 'SweetPlatformExpert', 'IOPlatformExpertDevice')
    cpu = personality(kernel, 'SweetCPU', 'IOPlatformDevice')
    if platform not in compatible(root):
        raise ValueError(f'ADT does not match built-in platform driver: {platform.decode()}')
    if cpu not in compatible(cpus[0]):
        raise ValueError(f'ADT does not match built-in CPU driver: {cpu.decode()}')
    ids=compatible(root)
    native=ids[0]==b'oneplus,giulia' and root.get('model')==b'OnePlus Ace 5\0'
    gui=(ids[:2]==[b'D22AP',b'iPhone10,3'] and root.get('model')==b'iPhone10,3\0'
         and root.get('physical-model')==b'OnePlus Ace 5\0')
    if (not (native or gui) or b'oneplus,giulia' not in ids or b'qcom,sm8650' not in ids):
        raise ValueError('ADT lost the actual Ace 5 device identity')
    if gui:
        for name in [b'IOMobileFramebufferUserClient',b'IOCoreSurfaceRoot',b'SWEET HID: touch registered']:
            if name not in kernel:raise ValueError('GUI ADT requires compiled service: '+name.decode())
        if '/device-tree/arm-io/disp0' not in nodes or '/device-tree/product' not in nodes:
            raise ValueError('GUI ADT lacks its display/product nodes')
    result={'platform_class': 'SweetPlatformExpert', 'platform_match': platform.decode(),
            'cpu_class': 'SweetCPU', 'cpu_match': cpu.decode(),
            'legacy_platform_alias': platform == b'xiaomi,sweet'}
    if gui:result['gui']=True
    return result
