"""Deterministic ADSP PAS package. No firmware bytes are stored in source.

Wire format: 4096-byte header, two 64-byte image records at 64 (DTB then
ADSP), and 32-byte segment records at 192. All integers are little endian.
Payloads follow in image order: compact authentication metadata, then each
nonempty PT_LOAD. Every payload starts on a 4096-byte boundary.
"""
import hashlib
from pathlib import Path
import struct

from ios16_audio_firmware import ELF32, PHDR32, verify_firmware


MAGIC = b'GAFWPK1\0'
PAGE = 4096
MAX_SEGMENTS = 100
MAX_PACK_BYTES = 128 * 1024 * 1024
IMAGE_NAMES = ('adsp_dtb.mdt', 'adsp.mdt')
IMAGE_LIMITS = ((36, 0x9DE80000, 0x80000), (1, 0x9DF00000, 0x5280000))


def _metadata(data, expected_machine):
    """Validate the stock compact ELF-header-plus-hash authentication blob.

    The hash's original ELF p_offset is deliberately not used for a split MDT.
    It is already appended to the header table in the pinned stock .mdt files.
    The main ADSP hash header is index 56, not index 1.
    """
    if len(data) < ELF32.size:
        raise ValueError('Truncated PAS metadata')
    h = ELF32.unpack_from(data)
    if (h[0][:7] != b'\x7fELF\x01\x01\x01' or h[1:4] != (2, expected_machine, 1)
            or h[5] != ELF32.size or h[8:10] != (ELF32.size, PHDR32.size)
            or not 3 <= h[10] <= MAX_SEGMENTS):
        raise ValueError('Unsupported PAS metadata encoding')
    table_end = ELF32.size + h[10] * PHDR32.size
    if table_end > len(data):
        raise ValueError('Truncated PAS program table')
    headers = [PHDR32.unpack_from(data, h[5] + i * PHDR32.size) for i in range(h[10])]
    first = headers[0]
    if first[0] != 0 or first[1] != 0 or first[4] != table_end or first[5] != 0:
        raise ValueError('Invalid PAS header segment')
    hashes = [(i, p) for i, p in enumerate(headers) if p[6] & 0x7000000 == 0x2000000]
    if len(hashes) != 1:
        raise ValueError('Expected exactly one PAS hash segment')
    hash_index, hash_header = hashes[0]
    if (hash_index == 0 or hash_header[0] != 0 or not hash_header[4]
            or hash_header[4] != hash_header[5]
            or table_end + hash_header[4] != len(data)):
        raise ValueError('Invalid compact PAS hash layout')
    for i, p in enumerate(headers):
        if i not in (0, hash_index) and (
                p[0] != 1 or not p[5] or p[4] > p[5] or not p[6] & 0x8000000
                or p[3] + p[5] > 1 << 32 or (p[7] and p[7] & (p[7] - 1))):
            raise ValueError('Unsupported PAS segment or relocation')
    return headers


def _read_pinned(folder, pin):
    """Bound the second read as well, and pin exactly the bytes we package."""
    path = folder / pin['path']
    if path.is_symlink() or path.resolve().parent != folder:
        raise ValueError('Firmware path changed while packing')
    with path.open('rb') as stream:
        data = stream.read(pin['bytes'] + 1)
    if len(data) != pin['bytes'] or hashlib.sha256(data).hexdigest() != pin['sha256']:
        raise ValueError('PAS payload or metadata changed while packing')
    return data


def build_pack(folder, manifest):
    """Verify every manifest pin, then construct the bounded loader input."""
    folder = Path(folder).resolve()
    verified = verify_firmware(folder, manifest)
    pins = {item['path']: item for item in manifest['files']}
    images = {item['path']: item for item in verified['images']}
    count = sum(item['load_segments'] for item in images.values())
    if not 2 <= count <= MAX_SEGMENTS:
        raise ValueError('PAS segment count exceeds pack capacity')
    output = bytearray(PAGE)
    output[:8] = MAGIC
    struct.pack_into('<6I', output, 8, 0, 2, count, 1, 64, 192)

    def append(data):
        offset = len(output)
        if (offset + len(data) + PAGE - 1) // PAGE * PAGE > MAX_PACK_BYTES:
            raise ValueError('PAS package exceeds loader capacity')
        output.extend(data)
        output.extend(bytes((-len(output)) % PAGE))
        return offset

    segment_index = 0
    for image_index, name in enumerate(IMAGE_NAMES):
        image = images[name]
        limits = IMAGE_LIMITS[image_index]
        if (image['pas_id'], image['base'], image['bytes']) != limits:
            raise ValueError('Image does not match the giulia PAS carveout')
        metadata = _read_pinned(folder, pins[name])
        _metadata(metadata, (1, 164)[image_index])
        meta_offset = append(metadata)
        load_min = image['load_min']
        load_size = (image['load_end'] + PAGE - 1) // PAGE * PAGE - load_min
        if (load_min % PAGE or load_size > image['bytes']
                or not load_min <= image['entry'] < image['load_end']):
            raise ValueError('Invalid relocated PAS memory span')
        ranges = []
        for segment in image['segments']:
            offset = segment['physical'] - load_min
            end = offset + segment['bytes']
            if any(offset < b and a < end for a, b in ranges):
                raise ValueError('Overlapping PAS load segments')
            ranges.append((offset, end))
            if segment['file_bytes']:
                payload = _read_pinned(folder, pins[segment['path']])
                data_offset = append(payload)
            else:
                data_offset = 0
            struct.pack_into('<8I', output, 192 + segment_index * 32,
                             image_index, segment['index'], offset, segment['bytes'],
                             data_offset, segment['file_bytes'], segment['flags'], 0)
            segment_index += 1
        struct.pack_into('<10I', output, 64 + image_index * 64,
                         *limits, meta_offset, len(metadata),
                         segment_index - image['load_segments'], image['load_segments'],
                         load_size, image['entry'], 1)
    struct.pack_into('<I', output, 8, len(output))
    return bytes(output)


def pin_header(pack):
    digest = hashlib.sha256(pack).digest()
    return ('/* SPDX-License-Identifier: BSD-2-Clause-Patent */\n'
            '/* Generated by make-audio-firmware-pack.py; no firmware bytes. */\n'
            '#ifndef GIULIA_AUDIO_FIRMWARE_PIN_H\n#define GIULIA_AUDIO_FIRMWARE_PIN_H\n'
            f'#define GA_FIRMWARE_PACK_BYTES {len(pack)}u\n'
            'static const unsigned char ga_firmware_pack_sha256[32] = {\n    ' +
            ','.join(f'0x{b:02x}' for b in digest) + '\n};\n#endif\n')
