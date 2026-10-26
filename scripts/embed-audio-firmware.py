"""Append a pinned ADSP pack as a bounded DarwinBoot __AUDIO_FW segment.

Derived from the existing Wi-Fi embedding path, kept independent so mixed
kernels can carry both segments without changing the Wi-Fi pack contract.

The compiled kernel contains only its digest. Vendor bytes never enter source
control or the kernel CI artifact. Existing load commands and file offsets are
preserved; only unused header padding and the end of the image are used.
"""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path


def append_pack(kernel: bytes, pack: bytes, digest: bytes, required=True):
    def require(ok, message):
        if not ok:
            raise ValueError(message)
    require(len(digest) == 32 and hashlib.sha256(pack).digest() == digest, 'Firmware digest mismatch')
    require(pack[:8] == b'GAFWPK1\0' and 4096 <= len(pack) <= 128*1024**2, 'Invalid firmware container')
    require(struct.unpack_from('<I', pack, 8)[0] == len(pack), 'Firmware container length mismatch')
    require(len(kernel) >= 32, 'Truncated kernel')
    magic, cpu, subtype, kind, count, size, _, _ = struct.unpack_from('<8I', kernel)
    require((magic, cpu, subtype, kind) == (0xfeedfacf, 0x100000c, 0, 2), 'Expected ARM64 executable')
    require(0 < count < 128 and size <= len(kernel) - 32, 'Invalid Mach-O commands')
    if required:
        require(digest in kernel and b'GIULIA AUDIO: compiled runtime disabled;' in kernel,
                'Kernel does not contain the matching AUDIO preparation service/digest')
        require(b'GIULIA AUDIO: firmware pack mapped read-only and digest verified' in kernel,
                'Kernel does not contain the explicit firmware RAM mapping')
    end = 32 + size
    require(end + 72 <= len(kernel) and not any(kernel[end:end+72]), 'No zero header space for firmware segment')
    at = 32
    segments = []
    first_data = len(kernel)
    for _ in range(count):
        require(at + 8 <= end, 'Truncated load command')
        command, length = struct.unpack_from('<II', kernel, at)
        require(length >= 8 and not length % 8 and length <= end - at, 'Invalid load command')
        if command == 0x1d:
            raise ValueError('Signed kernel must not be modified')
        if command == 0x19:
            require(length >= 72, 'Truncated segment')
            _, _, name, va, vm, off, amount, maximum, initial, sections, flags = struct.unpack_from('<II16sQQQQiiII', kernel, at)
            require(name.rstrip(b'\0') != b'__AUDIO_FW', 'Firmware segment already present')
            require(length == 72 + 80 * sections, 'Invalid section table')
            require(off <= len(kernel) and amount <= len(kernel) - off, 'Segment file bounds')
            if vm:
                require(amount <= vm and va <= 2**64 - vm, 'Segment virtual bounds')
                for start, stop in segments:
                    require(va >= stop or va + vm <= start, 'Overlapping kernel segments')
                segments.append((va, va + vm))
                if off:
                    first_data = min(first_data, off)
            for i in range(sections):
                section = at + 72 + i * 80
                secsize = struct.unpack_from('<Q', kernel, section + 40)[0]
                secoff = struct.unpack_from('<I', kernel, section + 48)[0]
                if secsize and secoff:
                    first_data = min(first_data, secoff)
        at += length
    require(at == end and segments and end + 72 <= first_data, 'Header padding overlaps a section')
    align = lambda n: (n + 0x3fff) & ~0x3fff
    va, offset, vm = align(max(stop for _, stop in segments)), align(len(kernel)), align(len(pack))
    require(va + vm < 2**64 and va + vm - (min(x for x, _ in segments) & ~0x1ffffff) <= 0x20000000 - 0x200000,
            'Firmware exceeds the bounded loader image window')
    output = bytearray(kernel)
    output[end:end+72] = struct.pack('<II16sQQQQiiII', 0x19, 72, b'__AUDIO_FW', va, vm, offset, len(pack), 1, 1, 0, 0)
    struct.pack_into('<II', output, 16, count + 1, size + 72)
    output.extend(bytes(offset - len(output)))
    output.extend(pack)
    return bytes(output), {'segment': '__AUDIO_FW', 'virtual_address': hex(va), 'virtual_bytes': vm,
                           'file_offset': offset, 'bytes': len(pack), 'sha256': digest.hex()}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kernel', type=Path, required=True)
    p.add_argument('--pack', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    if a.out.exists() or a.out.with_suffix('.json').exists():
        p.error('Output already exists')
    kernel, pack = a.kernel.read_bytes(), a.pack.read_bytes()
    metadata = json.loads(a.kernel.with_suffix('.json').read_text())
    if metadata.get('output_sha256') != hashlib.sha256(kernel).hexdigest() or metadata.get('boot_args_bytes') != 736:
        p.error('Kernel handoff metadata mismatch')
    pin = (Path(__file__).resolve().parents[1] / 'ios16/audio/giulia_audio_firmware_pin.h').read_text()
    digest = bytes(int(x, 16) for x in re.findall(r'0x([0-9a-f]{2})\b', pin))
    output, firmware = append_pack(kernel, pack, digest)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_bytes(output)
    metadata.update(pre_audio_firmware_sha256=metadata['output_sha256'], output_sha256=hashlib.sha256(output).hexdigest(),
                    audio_firmware=firmware, audio_runtime_included=True, audio_platform_provider_included=False, hardware_verified=False)
    a.out.with_suffix('.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(json.dumps({'output': str(a.out), 'sha256': metadata['output_sha256'], 'firmware': firmware}, indent=2))


if __name__ == '__main__':
    main()
