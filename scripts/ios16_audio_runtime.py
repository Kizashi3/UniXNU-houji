"""Check the audio coordinator and locally embedded assets, not hardware support."""
import hashlib
import re
import struct
from pathlib import Path


def check_runtime(kernel, report):
    marker = b'GIULIA AUDIO: compiled runtime disabled;'
    if marker not in kernel:
        if report.get('audio_runtime_included'):
            raise ValueError('Runtime metadata without compiled AUDIO driver')
        return None
    if not report.get('audio_runtime_included') or not report.get('audio_firmware'):
        raise ValueError('AUDIO kernel requires verified local firmware embedding')
    if b'GIULIA AUDIO: firmware pack mapped read-only and digest verified' not in kernel:
        raise ValueError('AUDIO kernel lacks the explicit firmware RAM mapping')
    if len(kernel) < 32:
        raise ValueError('Truncated Mach-O')
    magic, cpu, subtype, kind, count, command_bytes = struct.unpack_from('<6I', kernel)
    if (magic, cpu, subtype, kind) != (0xfeedfacf, 0x100000c, 0, 2) or not 0 < count <= 128 or command_bytes > len(kernel)-32:
        raise ValueError('Invalid Mach-O header')
    at, end, found = 32, 32+command_bytes, None
    ranges = []
    for _ in range(count):
        if at+8 > end:
            raise ValueError('Truncated Mach-O command')
        cmd, size = struct.unpack_from('<II', kernel, at)
        if size < 8 or size % 8 or size > end-at:
            raise ValueError('Invalid Mach-O command')
        if cmd == 0x1d:
            raise ValueError('Signed audio development kernel is unsupported')
        if cmd == 0x19:
            if size < 72:
                raise ValueError('Truncated segment')
            _, _, name, va, vm, offset, length, maximum, protection, sections, flags = struct.unpack_from('<II16sQQQQiiII', kernel, at)
            if size != 72+80*sections or offset > len(kernel) or length > len(kernel)-offset:
                raise ValueError('Invalid kernel segment file/section bounds')
            if vm:
                if length > vm or va > 2**64-vm or any(va < stop and start < va+vm for start,stop in ranges):
                    raise ValueError('Invalid kernel virtual bounds or overlapping segments')
                ranges.append((va,va+vm))
            if name.rstrip(b'\0') == b'__AUDIO_FW':
                if found or size != 72 or sections or flags or maximum != 1 or protection != 1 or not length or length > vm or (va|vm|offset)&0x3fff or offset < end or vm != (length+0x3fff)&~0x3fff:
                    raise ValueError('Invalid AUDIO firmware segment')
                found = dict(segment='__AUDIO_FW', virtual_address=hex(va), virtual_bytes=vm,
                             file_offset=offset, bytes=length,
                             sha256=hashlib.sha256(kernel[offset:offset+length]).hexdigest())
        at += size
    if at != end or not found or found != report['audio_firmware']:
        raise ValueError('Firmware segment metadata mismatch')
    if not ranges or max(stop for _,stop in ranges)-(min(start for start,_ in ranges)&~0x1ffffff) > 0x20000000-0x200000:
        raise ValueError('Audio firmware exceeds loader window')
    pin = (Path(__file__).resolve().parents[1]/'ios16/audio/giulia_audio_firmware_pin.h').read_text()
    digest = bytes(int(x, 16) for x in re.findall(r'0x([0-9a-f]{2})\b', pin))
    sizes = re.findall(r'^#define GA_FIRMWARE_PACK_BYTES ([0-9]+)u$', pin, re.M)
    if len(sizes) != 1 or found['bytes'] != int(sizes[0]):
        raise ValueError('Compiled firmware size mismatch')
    if len(digest) != 32 or found['sha256'] != digest.hex() or digest not in kernel[:found['file_offset']]:
        raise ValueError('Compiled firmware pin mismatch')
    return {'firmware': found, 'stage': 'firmware-and-runtime-coordinator',
            'native_platform_provider': False, 'hardware_verified': False, 'playback': False}
