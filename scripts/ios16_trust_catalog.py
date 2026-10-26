"""Bounded Apple v2 trust-cache container and Mach-O CodeDirectory readers."""
import hashlib
import struct

MAX_BYTES = 16 * 1024**2


def modules(data):
    if not 8 <= len(data) <= MAX_BYTES:
        raise ValueError('Trust catalogue size')
    count, = struct.unpack_from('<I', data)
    if not 1 <= count <= 128 or 4 + 4*count > len(data):
        raise ValueError('Trust catalogue module count')
    offsets = struct.unpack_from('<'+'I'*count, data, 4) + (len(data),)
    result = []
    for start, end in zip(offsets, offsets[1:]):
        if start < 4+4*count or start % 4 or not start+24 <= end <= len(data):
            raise ValueError('Trust module bounds')
        version, = struct.unpack_from('<I', data, start)
        entries, = struct.unpack_from('<I', data, start+20)
        if version != 2 or end-start != 24+24*entries:
            raise ValueError('Trust module version/length')
        hashes = [data[i:i+20] for i in range(start+24, end, 24)]
        if any(a >= b for a, b in zip(hashes, hashes[1:])) or any(
                not 1 <= data[i+20] <= 4 for i in range(start+24, end, 24)):
            raise ValueError('Unsorted or unsupported trust entry')
        result.append({'uuid': data[start+4:start+20].hex(), 'entries': entries,
                       'hashes': hashes})
    return result


def im4p_payload(data, expected_type=b'trst'):
    def tlv(at, limit):
        if at+2 > limit: raise ValueError('Truncated DER')
        tag, length = data[at:at+2]; at += 2
        if length & 128:
            width = length & 127
            if not 1 <= width <= 4 or at+width > limit: raise ValueError('DER length')
            length = int.from_bytes(data[at:at+width], 'big'); at += width
        if at+length > limit: raise ValueError('DER bounds')
        return tag, at, at+length
    tag, at, end = tlv(0, len(data))
    if tag != 48 or end != len(data): raise ValueError('Expected IM4P sequence')
    fields = []
    while at < end:
        tag, begin, at = tlv(at, end)
        fields.append((tag, data[begin:at]))
    if len(fields) < 4 or fields[0] != (22, b'IM4P') or fields[1] != (22, expected_type) or fields[3][0] != 4:
        raise ValueError('Expected IM4P trust cache')
    return fields[3][1]


def code_hashes(binary):
    """Return hashes of embedded CodeDirectories; never invent a missing one."""
    if binary[:4] == bytes.fromhex('cafebabe'):
        n, = struct.unpack_from('>I', binary, 4)
        if n > 16 or 8+20*n > len(binary): raise ValueError('Fat Mach-O header')
        arm = [struct.unpack_from('>IIIII', binary, 8+20*i) for i in range(n)]
        arm = [v for v in arm if v[0] == 0x100000c and v[1] & 0xffffff == 0]
        if len(arm) != 1: raise ValueError('Expected one ARM64 slice')
        _, _, offset, size, _ = arm[0]
        if offset+size > len(binary): raise ValueError('Fat slice bounds')
        binary = binary[offset:offset+size]
    if binary[:4] != bytes.fromhex('cffaedfe'): raise ValueError('Expected ARM64 Mach-O')
    cpu, = struct.unpack_from('<I', binary, 4)
    count, commands_size = struct.unpack_from('<II', binary, 16)
    if cpu != 0x100000c or 32+commands_size > len(binary) or count > 4096:
        raise ValueError('Mach-O commands')
    at = 32; signature = None
    for _ in range(count):
        if at+8 > 32+commands_size: raise ValueError('Truncated load command')
        command, size = struct.unpack_from('<II', binary, at)
        if size < 8 or at+size > 32+commands_size: raise ValueError('Load command size')
        if command == 0x1d:
            if size != 16 or signature is not None: raise ValueError('Code signature command')
            offset, length = struct.unpack_from('<II', binary, at+8)
            if offset+length > len(binary): raise ValueError('Code signature bounds')
            signature = binary[offset:offset+length]
        at += size
    if signature is None or len(signature) < 12: raise ValueError('Missing signature')
    magic, length, count = struct.unpack_from('>III', signature)
    if magic != 0xfade0cc0 or length > len(signature) or 12+8*count > length:
        raise ValueError('Signature superblob')
    result = []
    for i in range(count):
        slot, offset = struct.unpack_from('>II', signature, 12+8*i)
        if offset < 12+8*count or offset+8 > length: raise ValueError('Signature slot')
        magic, size = struct.unpack_from('>II', signature, offset)
        if size < 8 or offset+size > length: raise ValueError('Signature blob')
        if slot == 0 or 0x1000 <= slot <= 0x1005:
            if magic != 0xfade0c02 or size < 44: raise ValueError('CodeDirectory')
            kind = signature[offset+37]
            algorithm = {1:'sha1', 2:'sha256', 3:'sha256', 4:'sha384'}.get(kind)
            if not algorithm: raise ValueError('CodeDirectory hash algorithm')
            result.append(hashlib.new(algorithm, signature[offset:offset+size]).digest()[:20])
    if not result: raise ValueError('Missing CodeDirectory')
    return result
