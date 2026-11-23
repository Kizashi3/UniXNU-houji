#!/usr/bin/env python3
"""Back up logfs, then allocate one 64 KiB native-log file through Android FAT.

Never writes a raw block device. The exported cluster list authorizes only this
file's existing data sectors after a second in-kernel FAT/GPT validation.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shlex
import struct
import subprocess
import uuid
import zlib

ADB = '${USER_HOME}/Library/Android/sdk/platform-tools/adb'
SERIAL = 'DEVICE_SERIAL'
FILE_BYTES = 65536
MAGIC = b'HJXNU001'


def layout(data):
    if len(data) != 8388608 or data[510:512] != b'\x55\xaa':
        raise ValueError('logfs size/signature differs')
    if struct.unpack_from('<HBHBHHBHHH', data, 11) != (4096, 1, 1, 2, 512, 1280, 248, 1, 1, 1):
        raise ValueError('FAT12 geometry differs')
    fat = data[4096:8192]
    if fat != data[8192:12288]:
        raise ValueError('FAT copies differ')

    def chain(start, size):
        out = []
        current = start
        for _ in range((size + 4095) // 4096):
            if not 2 <= current < 1275 or current in out:
                raise ValueError('FAT chain outside volume or looped')
            out.append(current)
            at = current + current // 2
            pair = struct.unpack_from('<H', fat, at)[0]
            current = pair >> 4 if current & 1 else pair & 0xfff
        if current < 0xff8:
            raise ValueError('FAT chain does not end at file size')
        return out

    files = []
    for pos in range(3 * 4096, 7 * 4096, 32):
        e = data[pos:pos + 32]
        if e[0] == 0:
            break
        if e[0] == 0xe5 or e[11] == 0xf or e[11] & 8:
            continue
        if e[11] & 0x10 or struct.unpack_from('<H', e, 20)[0]:
            raise ValueError('Unexpected subdirectory or FAT32 cluster')
        size = struct.unpack_from('<I', e, 28)[0]
        files.append((e[:11], size, chain(struct.unpack_from('<H', e, 26)[0], size)))
    own = [f for f in files if f[0] == b'XNULOG  BIN']
    if len(own) != 1 or own[0][1] != FILE_BYTES:
        raise ValueError('Native log file absent, duplicated or wrong size')
    clusters = own[0][2]
    if any(set(clusters) & set(f[2]) for f in files if f is not own[0]):
        raise ValueError('Native log data overlaps another file')
    return {'clusters': clusters, 'lbas': [4096 + 7 + c - 2 for c in clusters],
            'file_bytes': FILE_BYTES, 'physical_lun': 0,
            'metadata_lbas': [4096, 4103], 'short_name': 'XNULOG  BIN'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--adb-port', type=int, choices=(5037, 5038, 5047, 15049), required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--header', type=Path, required=True)
    p.add_argument('--recovery', action='store_true')
    p.add_argument('--reuse-sha256', help='Exact archived 64 KiB file hash required for in-place reuse')
    a = p.parse_args()
    os.umask(0o077)

    def root(command, data=None):
        r = subprocess.run([ADB, '-P', str(a.adb_port), '-s', SERIAL, 'exec-out',
                            command if a.recovery else '/debug_ramdisk/su -c ' + shlex.quote(command)],
                           input=data, capture_output=True, check=True, timeout=40)
        if r.stderr:
            raise RuntimeError(r.stderr.decode(errors='replace'))
        return r.stdout

    if root('id -u; getprop ro.product.device; readlink -f /dev/block/by-name/logfs; '
            'blockdev --getsize64 /dev/block/by-name/logfs').splitlines() != [
                b'0', b'houji', b'/dev/block/sda13', b'8388608']:
        raise RuntimeError('Device identity differs')
    mounts = [line.split() for line in root('cat /proc/mounts').splitlines()]
    if not any(len(m) >= 3 and m[1:3] == [b'/dev/logfs', b'vfat'] for m in mounts):
        raise RuntimeError('Expected FAT mount absent')
    exists = root('if [ -e /dev/logfs/XnuLog.bin ]; then echo EXISTS; else echo ABSENT; fi').strip()
    if a.reuse_sha256:
        current = root('cat /dev/logfs/XnuLog.bin')
        if len(current)!=65536 or hashlib.sha256(current).hexdigest()!=a.reuse_sha256:
            raise RuntimeError('Existing native log differs from archived bytes')
    elif exists != b'ABSENT':
        raise RuntimeError('Refusing to overwrite existing native log')
    a.output.mkdir(parents=True, mode=0o700, exist_ok=False)

    def backup(name):
        # A mounted FAT and ordinary raw-block reads have distinct caches.
        # Require the fixed O_RDONLY|O_DIRECT helper and two matching reads.
        helper = '/tmp/houji-logfs-read' if a.recovery else '/data/local/tmp/houji-logfs-read'
        raw = root(helper)
        again = root(helper)
        digest = hashlib.sha256(raw).hexdigest()
        if len(raw) != 8388608 or raw != again:
            raise RuntimeError('Partition changed during backup; no further writes')
        (a.output / name).write_bytes(raw)
        return raw, digest

    root('sync')
    _, before_sha = backup('logfs-before.bin')
    run_id = uuid.uuid4().bytes
    initial = bytearray(FILE_BYTES)
    initial[:8] = MAGIC
    struct.pack_into('<II', initial, 8, 0, 1)
    initial[16:32] = run_id
    (a.output / 'XnuLog.initial.bin').write_bytes(initial)
    # Magisk su does not forward exec-out stdin reliably. Stage bytes with adb
    # sync, then let the root shell read an ordinary file. Refuse collisions.
    remote = ('/tmp/' if a.recovery else '/data/local/tmp/') + 'houji-xnu-log-' + run_id.hex() + '.bin'
    if root('if [ -e ' + remote + ' ]; then echo EXISTS; else echo ABSENT; fi').strip() != b'ABSENT':
        raise RuntimeError('Staging file collision')
    subprocess.run([ADB, '-P', str(a.adb_port), '-s', SERIAL, 'push',
                    str(a.output / 'XnuLog.initial.bin'), remote], check=True, timeout=30)
    if a.recovery:
        root('mount -o remount,rw /dev/logfs')
    if a.reuse_sha256:
        root('dd if=' + remote + ' of=/dev/logfs/XnuLog.bin bs=4096 count=16 conv=notrunc,fsync')
    else:
        root('set -C; cat ' + remote + ' > /dev/logfs/XnuLog.bin')
    root('sync')
    if root('cat /dev/logfs/XnuLog.bin') != initial:
        raise RuntimeError('File allocation/readback differs')
    # Reading a mounted FAT file can dirty LastAccessDate across midnight.
    # Flush that metadata before taking the exact O_DIRECT post-write image.
    root('sync')
    root('rm ' + remote)
    raw, after_sha = backup('logfs-after.bin')
    record = layout(raw)
    rebuilt = b''.join(raw[(lba-4096)*4096:(lba-4096+1)*4096] for lba in record['lbas'])
    if rebuilt != initial:
        raise RuntimeError('Raw FAT allocation does not match mounted file')
    record.update({'run_id': run_id.hex(), 'initial_crc32': f'{zlib.crc32(initial):08x}',
                   'initial_sha256': hashlib.sha256(initial).hexdigest(),
                   'backup_before_sha256': before_sha, 'backup_after_sha256': after_sha,
                   'created_at': datetime.datetime.now().astimezone().isoformat(),
                   'writes': 'one mounted FAT file prepared; no raw block writes'})
    (a.output / 'layout.json').write_text(json.dumps(record, indent=2) + '\n')
    header = ('// Generated from verified FAT allocation; one explicitly bound trial.\n'
              'static const uint8_t kHoujiLogRunId[16] = {' + ','.join(str(x) for x in run_id) + '};\n'
              'static const uint16_t kHoujiLogClusters[16] = {' + ','.join(map(str, record['clusters'])) + '};\n'
              'static const uint32_t kHoujiLogLbas[16] = {' + ','.join(map(str, record['lbas'])) + '};\n'
              f'static const uint32_t kHoujiLogInitialCrc = 0x{zlib.crc32(initial):08x}U;\n')
    a.header.write_text(header)
    if a.recovery:
        root('mount -o remount,ro /dev/logfs')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
