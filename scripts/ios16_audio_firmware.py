"""Verify pinned split ADSP firmware offline; never loads or executes firmware."""
import hashlib
from pathlib import Path
import re
import struct


ELF32 = struct.Struct('<16sHHIIIIIHHHHHH')
PHDR32 = struct.Struct('<8I')
PT_LOAD = 1
QCOM_MDT_TYPE_MASK = 0x07000000
QCOM_MDT_TYPE_HASH = 0x02000000
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_BUNDLE_BYTES = 128 * 1024 * 1024
MAX_PROGRAM_HEADERS = 100
# The original ADSP is Hexagon. Its DTB container uses ELF machine 1.
IMAGE_MACHINES = {'adsp.mdt': 164, 'adsp_dtb.mdt': 1}
ASSET_NAME = re.compile(r'(?:adsp|adsp_dtb)\.(?:mdt|b[0-9]{2})\Z')


def _uint(value, name, *, positive=False):
    if type(value) is not int or not int(positive) <= value <= 0xffffffff:
        raise ValueError('Invalid firmware ' + name)
    return value


def _catalog(root, entries):
    if not isinstance(entries, list) or not 2 <= len(entries) <= 202:
        raise ValueError('Invalid firmware asset count')
    files, metadata, total = {}, {}, 0
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError('Invalid firmware asset record')
        name = item.get('path')
        if not isinstance(name, str) or not ASSET_NAME.fullmatch(name):
            raise ValueError('Invalid firmware path')
        if name in files:
            raise ValueError('Duplicate firmware asset: ' + name)
        size = _uint(item.get('bytes'), 'asset size', positive=True)
        digest = item.get('sha256')
        if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('Invalid firmware SHA256: ' + name)
        total += size
        if size > MAX_FILE_BYTES or total > MAX_BUNDLE_BYTES:
            raise ValueError('Firmware asset size limit exceeded')
        path = root / name
        if path.is_symlink() or path.resolve().parent != root:
            raise ValueError('Firmware path escapes bundle: ' + name)
        try:
            if not path.is_file() or path.stat().st_size != size:
                raise ValueError('Missing firmware asset or size mismatch: ' + name)
            actual = hashlib.sha256()
            content, count = [], 0
            with path.open('rb') as stream:
                while block := stream.read(1024 * 1024):
                    count += len(block)
                    if count > size:
                        raise ValueError('Firmware asset size changed: ' + name)
                    actual.update(block)
                    if name.endswith('.mdt'):
                        content.append(block)
        except OSError as error:
            raise ValueError('Cannot read firmware asset: ' + name) from error
        if count != size or actual.hexdigest() != digest:
            raise ValueError('Firmware size or SHA256 mismatch: ' + name)
        files[name] = item
        if name.endswith('.mdt'):
            metadata[name] = b''.join(content)
    return files, metadata, total


def _image(data, image, files):
    name = image['path']
    base = _uint(image.get('base'), 'carveout base')
    capacity = _uint(image.get('bytes'), 'carveout size', positive=True)
    pas_id = _uint(image.get('pas_id'), 'PAS ID', positive=True)
    end = base + capacity
    if end > 1 << 32:
        raise ValueError('Firmware carveout exceeds ELF32 physical space')
    if len(data) < ELF32.size:
        raise ValueError('Truncated firmware ELF: ' + name)
    header = ELF32.unpack_from(data)
    ident, elf_type, machine, version, entry = header[:5]
    if (ident[:7] != b'\x7fELF\x01\x01\x01' or elf_type != 2 or version != 1
            or machine != IMAGE_MACHINES[name]):
        raise ValueError('Unsupported firmware ELF encoding/type/machine: ' + name)
    phoff, ehsize, phsize, phnum = header[5], header[8], header[9], header[10]
    if ehsize != ELF32.size or phsize != PHDR32.size or not 1 <= phnum <= MAX_PROGRAM_HEADERS:
        raise ValueError('Invalid firmware ELF header sizes: ' + name)
    if phoff < ehsize or phoff + phsize * phnum > len(data):
        raise ValueError('Truncated firmware program table: ' + name)
    if not base <= entry < end:
        raise ValueError('Firmware entry escapes carveout: ' + name)
    required, loads, hash_segments, payload_bytes = set(), [], 0, 0
    for index in range(phnum):
        kind, offset, vaddr, paddr, filesz, memsz, flags, align = PHDR32.unpack_from(
            data, phoff + index * phsize)
        # Qualcomm authentication hashes are not executable/loadable payloads,
        # even when a header happens to mark the hash segment as PT_LOAD.
        if flags & QCOM_MDT_TYPE_MASK == QCOM_MDT_TYPE_HASH:
            hash_segments += 1
            continue
        if kind != PT_LOAD:
            continue
        if not memsz or filesz > memsz:
            raise ValueError('Invalid PT_LOAD memory/file size: ' + name)
        if paddr < base or paddr + memsz > end:
            raise ValueError('PT_LOAD escapes firmware carveout: ' + name)
        segment = {'index': index, 'physical': paddr, 'bytes': memsz,
                   'file_bytes': filesz, 'flags': flags}
        if filesz:
            # Split MDT p_offset describes the original ELF, not this metadata
            # file. The external payload uses the decimal program-header index.
            payload = name[:-4] + f'.b{index:02d}'
            if payload not in files or files[payload]['bytes'] != filesz:
                raise ValueError('Missing or incorrectly sized PT_LOAD payload: ' + payload)
            required.add(payload)
            payload_bytes += filesz
            segment['path'] = payload
        loads.append(segment)
    if not required:
        raise ValueError('Firmware has no nonzero PT_LOAD payload: ' + name)
    result = {'path': name, 'pas_id': pas_id, 'base': base, 'bytes': capacity,
              'elf_machine': machine, 'entry': entry, 'program_headers': phnum,
              'load_segments': len(loads), 'payload_files': len(required),
              'payload_bytes': payload_bytes, 'hash_segments': hash_segments,
              'bss_segments': sum(not s['file_bytes'] for s in loads),
              'load_min': min(s['physical'] for s in loads),
              'load_end': max(s['physical'] + s['bytes'] for s in loads),
              'segments': loads}
    return result, required


def verify_firmware(root, firmware_manifest):
    """Check manifest digests and split ELF payloads; return a verification summary.

    The caller supplies the trusted file pins and physical carveouts. Success
    establishes local package integrity, not PAS authentication or DSP readiness.
    BSS and Qualcomm metadata/hash headers do not require separate .bNN files.
    """
    if not isinstance(firmware_manifest, dict):
        raise ValueError('Invalid firmware manifest')
    images = firmware_manifest.get('images')
    if not isinstance(images, list) or len(images) != len(IMAGE_MACHINES):
        raise ValueError('Expected ADSP and ADSP DTB image records')
    names = []
    for image in images:
        if not isinstance(image, dict) or image.get('path') not in IMAGE_MACHINES:
            raise ValueError('Unsupported firmware image record')
        names.append(image['path'])
    if set(names) != set(IMAGE_MACHINES):
        raise ValueError('Duplicate or missing firmware image record')
    root = Path(root).resolve()
    files, metadata, total = _catalog(root, firmware_manifest.get('files'))
    required, results = set(names), []
    for image in images:
        if image['path'] not in metadata:
            raise ValueError('Missing firmware MDT: ' + image['path'])
        result, payloads = _image(metadata[image['path']], image, files)
        results.append(result)
        required.update(payloads)
    if set(files) != required:
        raise ValueError('Unexpected firmware assets: ' + ', '.join(sorted(set(files) - required)))
    return {'file_count': len(files), 'total_bytes': total, 'images': results}
