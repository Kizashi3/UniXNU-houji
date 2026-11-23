#!/usr/bin/env python3
"""Pack the houji firmware for a RAM-only fastboot boot; no device commands."""
import argparse
import gzip
import hashlib
import json
import lzma
from pathlib import Path
import struct
import subprocess
import tempfile
import tomllib
import zlib
import uuid


def require(value, message):
    if not value:
        raise ValueError(message)


def verify_ram_payload_identity(fd, driver, payload):
    """Check the identity used by the actual driver inside the compressed FD."""
    guided = uuid.UUID('ee4e5898-3914-4259-9d6e-dc7bd79403cf').bytes_le
    # SEC also contains the decompressor's GUID as ordinary data. Only admit
    # a bounded EFI_GUID_DEFINED_SECTION, not every occurrence of that GUID.
    sections = []
    position = 0
    while (position := fd.find(guided, position)) >= 0:
        start = position - 4
        if start >= 0 and fd[start + 3] == 2 and start + 24 <= len(fd):
            size = int.from_bytes(fd[start:start + 3], 'little')
            offset, attributes = struct.unpack_from('<HH', fd, start + 20)
            if 24 <= offset < size and start + size <= len(fd) and attributes & 1:
                sections.append((start, size, offset))
        position += len(guided)
    require(len(sections) == 1, 'Expected one bounded LZMA-guided firmware section')
    start, size, offset = sections[0]
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
    expanded = decoder.decompress(fd[start + offset:start + size], max_length=16 * 1024**2)
    require(decoder.eof and not decoder.unused_data, 'Incomplete firmware LZMA section')
    magic = b'HJRAMID1'
    expected = struct.pack('<8sII', magic, len(payload), zlib.crc32(payload))
    for name, data in [('linked RAM driver', driver), ('actual decompressed firmware', expanded)]:
        require(data.count(magic) == 1 and expected in data,
                name + ' payload size/CRC differs from the embedded payload')
    return {'status': 'PASS', 'payload_bytes': len(payload), 'payload_crc32': f'{zlib.crc32(payload):08x}',
            'actual_driver_sha256': hashlib.sha256(driver).hexdigest(),
            'actual_expanded_firmware_sha256': hashlib.sha256(expanded).hexdigest()}


def image_body(shim, fd, embedded=b''):
    """Keep FD relocation unchanged; carry the FAT volume in the loaded Image.

    The Android header's ramdisk field is optional on recent ABL versions.
    BootShim relocates only FD_SIZE bytes, leaving this payload in the reserved
    Kernel window. Its ARM64 image_size must describe the entire loaded Image.
    """
    raw = shim + fd
    if embedded:
        raw += bytes((-len(raw)) % 4096) + embedded
        require(len(raw) <= 0x10000000, 'Image exceeds the reserved Kernel window')
        raw = bytearray(raw)
        struct.pack_into('<Q', raw, 16, len(raw))
        raw = bytes(raw)
    return raw


def verify(image, shim, fd, dtb, config, ramdisk=b'', embedded=b''):
    require(image[:8] == b'ANDROID!', 'Invalid Android image magic')
    u32 = lambda offset: struct.unpack_from('<I', image, offset)[0]
    require(u32(40) == 4 and u32(20) == 1584, 'Expected header v4 / 1584 bytes')
    require(u32(12) == len(ramdisk) and u32(1580) == 4096, 'Unexpected ramdisk or signature size')
    require(image[24:40] == bytes(16), 'Nonzero reserved header words')
    version = [int(x) for x in config['boot_image']['os_version'].split('.')]
    year, month = map(int, config['boot_image']['os_patch_level'].split('-'))
    os_field = version[0] << 25 | version[1] << 18 | version[2] << 11 | (year - 2000) << 4 | month
    require(u32(16) == os_field, 'Android wrapper OS field differs from the device config')
    require(len(fd) == config['uefi_fd']['size'], 'Incorrect firmware size')
    require(shim[56:60] == b'ARM\x64', 'Missing ARM64 Image magic')
    require(struct.unpack_from('<QQ', shim, 8) == (config['uefi_fd']['base'], len(shim) + len(fd)),
            'Compiled BootShim has an unexpected ARM64 header')
    require(dtb[:4] == b'\xd0\x0d\xfe\xed' and struct.unpack_from('>I', dtb, 4)[0] == len(dtb),
            'Invalid DTB size or magic')
    ramdisk_start = 4096 + (u32(8) + 4095) // 4096 * 4096
    signature_start = ramdisk_start + (len(ramdisk) + 4095) // 4096 * 4096
    require(image[ramdisk_start:ramdisk_start + len(ramdisk)] == ramdisk, 'RAM payload differs')
    require(len(image) == signature_start + 4096, 'Unexpected image size')
    require(image[signature_start:] == bytes(4096), 'Unexpected signing payload')
    kernel = image[4096:4096 + u32(8)]
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    raw = decoder.decompress(kernel) + decoder.flush()
    require(decoder.eof and raw == image_body(shim, fd, embedded) and decoder.unused_data == dtb,
            'Gzip / BootShim / FD / embedded payload / DTB do not round-trip')
    require(struct.unpack_from('<Q', raw, 16)[0] == len(raw),
            'ARM64 image_size does not cover the complete Image')
    return {name: hashlib.sha256(value).hexdigest()
            for name, value in [('image', image), ('shim', shim), ('fd', fd), ('dtb', dtb)]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--uefi', type=Path, required=True)
    p.add_argument('--dtb', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--ramdisk', type=Path)
    p.add_argument('--payload-in-image', action='store_true',
                   help='Carry --ramdisk inside the compressed Image, not Android initrd')
    a = p.parse_args()
    config = tomllib.loads((a.uefi / 'Resources/Configs/houji.toml').read_text())
    fd = (a.uefi / 'Build/houjiPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd').read_bytes()
    shim = (a.uefi / 'BootShim/BootShim.bin').read_bytes()
    dtb = a.dtb.read_bytes()
    require(not a.payload_in_image or a.ramdisk, '--payload-in-image needs --ramdisk')
    payload = a.ramdisk.read_bytes() if a.ramdisk else b''
    ramdisk = b'' if a.payload_in_image else payload
    embedded = payload if a.payload_in_image else b''
    payload_record = json.loads(a.ramdisk.with_suffix('.json').read_text()) if a.ramdisk else None
    if payload_record:
        require(hashlib.sha256(payload).hexdigest() == payload_record['sha256'], 'RAM payload provenance differs')
    ram_identity = verify_ram_payload_identity(fd,
        (a.uefi / 'Build/houjiPkg/DEBUG_CLANGPDB/AARCH64/HoujiRamDiskDxe.efi').read_bytes(), payload) if payload else None
    raw = image_body(shim, fd, embedded)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        (temp / 'kernel').write_bytes(gzip.compress(raw, mtime=0) + dtb)
        (temp / 'ramdisk').write_bytes(ramdisk)
        subprocess.run(['python3', str(a.uefi / 'Resources/Scripts/mkbootimg.py'),
                        '--kernel', str(temp / 'kernel'), '--ramdisk', str(temp / 'ramdisk'),
                        '--header_version', '4', '--os_version', config['boot_image']['os_version'],
                        '--os_patch_level', config['boot_image']['os_patch_level'],
                        '-o', str(temp / 'boot.img')], check=True)
        image = (temp / 'boot.img').read_bytes()
    hashes = verify(image, shim, fd, dtb, config, ramdisk, embedded)
    # Reject malformed candidates using the reader, before saving any boot image.
    for offset, value in [(40, 3), (12, 1), (1580, 1), (4096, 0)]:
        corrupt = bytearray(image)
        struct.pack_into('<I', corrupt, offset, value)
        try:
            verify(corrupt, shim, fd, dtb, config, ramdisk, embedded)
        except (ValueError, zlib.error):
            pass
        else:
            raise ValueError(f'Malformed image accepted at {offset}')
    a.output.write_bytes(image)
    report = {'status': 'offline-image-checks-passed', 'device': 'houji', 'header_version': 4,
              'bytes': len(image), 'sha256': hashes, 'contains_xnu': bool(payload_record and payload_record['contains_xnu']),
              'ramdisk_bytes': len(ramdisk), 'ramdisk_sha256': payload_record['sha256'] if payload_record else None,
              'payload_transport': 'embedded-image' if embedded else 'android-ramdisk',
              'embedded_payload_bytes': len(embedded), 'decompressed_image_bytes': len(raw),
              'embedded_payload_offset': len(raw) - len(embedded) if embedded else None,
              'ram_payload_identity': ram_identity,
              'hardware_tested': False,
              'physical_storage_drivers': bool(payload_record and payload_record.get('physical_storage_drivers', False)),
              'test_scope': payload_record.get('test_scope') if payload_record else None,
              'storage_write_policy': payload_record.get('storage_write_policy') if payload_record else None,
              'native_storage_policy': payload_record.get('native_storage_policy') if payload_record else None,
              'contains_oem_diagnostic_patches': bool(payload_record and payload_record.get('contains_oem_diagnostic_patches', False)),
              'clock_bsp_policy': payload_record.get('clock_bsp_policy') if payload_record else None,
              'usage': 'fastboot boot only'}
    a.output.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
