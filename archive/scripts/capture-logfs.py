#!/usr/bin/env python3
"""Read houji's mounted logfs files through root ADB without device writes.

OEM logs alone do not prove the port's log writer works. The r22 app snapshot
was verified across Android return; this reader still records absence and
stability rather than assuming any later run succeeded.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import zlib
from pathlib import Path
import shlex
import struct
import subprocess

ADB = '${USER_HOME}/Library/Android/sdk/platform-tools/adb'
SERIAL = 'DEVICE_SERIAL'
FILES = tuple(f'UefiLog{i}.txt' for i in range(5)) + ('UefiLog_other0.txt', 'UniXNU.log', 'XnuLog.bin')
MAX_FILE_BYTES = 4 * 1024 * 1024


def parse_remote_digest(output, remote):
    fields = output.decode().split()
    if len(fields) != 2 or not re.fullmatch('[0-9a-f]{64}', fields[0]) or fields[1] != remote:
        raise RuntimeError('Incomplete ADB digest response; reconnect and retry capture: ' + remote)
    return fields[0]


def verify_native_snapshot(data):
    footer = re.search(rb'HOUJI LOGFS CHECKSUM: payload-bytes=([0-9]+) payload-crc32=([0-9A-Fa-f]{8})\r?\n\Z', data)
    if not footer:
        return {'checksum_footer_present': False, 'valid': False}
    size = int(footer[1]); expected = int(footer[2], 16)
    payload = data[:footer.start()]
    actual = zlib.crc32(payload)
    return {'checksum_footer_present': True, 'payload_bytes': size,
            'expected_crc32': f'{expected:08x}', 'actual_crc32': f'{actual:08x}',
            'valid': (len(data) <= 524288 and size == len(payload) and expected == actual
                      and any((b'HOUJI LOGFS r' + str(v).encode() + b':') in payload
                              and (b'r' + str(v).encode() + b' snapshot end; app text only; commit/readback follows') in payload
                              for v in (23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125, 126, 127, 128, 129, 130, 131, 132, 133, 134, 135, 136, 137, 138, 139, 140)))}


def decode_xnu_snapshot(data, expected_run_id=None):
    result = {'valid': False, 'committed': False}
    if len(data) != 65536 or data[:8] != b'HJXNU001':
        return result, None
    state, version = struct.unpack_from('<II', data, 8)
    run_id = data[16:32].hex()
    result.update({'committed': state == 1, 'version': version, 'run_id': run_id,
                   'expected_run_id_matches': run_id == expected_run_id if expected_run_id else None})
    if state != 1 or version != 1:
        return result, None
    length, crc, header_crc = struct.unpack_from('<III', data, 32)
    header = bytearray(data[:4096]); header[40:44] = bytes(4)
    result.update({'payload_bytes': length, 'payload_crc32': f'{crc:08x}',
                   'header_crc32': f'{header_crc:08x}'})
    if (length > 61440 or header_crc != zlib.crc32(header) or
            crc != zlib.crc32(data[4096:4096+length]) or
            data[44:4096] != bytes(4096-44) or
            any(data[4096+length:]) or
            (expected_run_id and run_id != expected_run_id)):
        return result, None
    result['valid'] = True
    return result, data[4096:4096+length]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb-port', type=int, choices=(5037, 5038, 5047, 15049), required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--xnu-run-id', help='Expected 32-hex-digit trial ID from allocation layout.json')
    parser.add_argument('--recovery', action='store_true', help='Use the verified root recovery shell')
    parser.add_argument('--retry-adb-ports', action='store_true',
                        help='On a missing USB transport, retry the other existing ADB servers')
    args = parser.parse_args()
    if args.xnu_run_id and not re.fullmatch(r'[0-9a-f]{32}', args.xnu_run_id):
        raise ValueError('Invalid XNU run ID')
    os.umask(0o077)

    def root(command):
        ports = [args.adb_port]
        if args.retry_adb_ports:
            ports += [port for port in (5037, 5038, 5047, 15049) if port != args.adb_port]
        for port in ports:
            result = subprocess.run(
                [ADB, '-P', str(port), '-s', SERIAL, 'exec-out',
                 command if args.recovery else '/debug_ramdisk/su -c ' + shlex.quote(command)],
                capture_output=True, timeout=30)
            transport_missing = result.returncode and any(
                marker in result.stderr for marker in
                (b'not found', b'device offline', b'no devices/emulators found'))
            if transport_missing and args.retry_adb_ports:
                continue
            result.check_returncode()
            if result.stderr:
                raise RuntimeError(result.stderr.decode(errors='replace'))
            args.adb_port = port
            return result.stdout
        result.check_returncode()
        raise RuntimeError('No existing ADB server has the expected device')

    identity = root('id -u; getprop ro.product.device; '
                    'readlink -f /dev/block/by-name/logfs; '
                    'blockdev --getsize64 /dev/block/by-name/logfs').decode().splitlines()
    if identity != ['0', 'houji', '/dev/block/sda13', '8388608']:
        raise RuntimeError('Unexpected device, root status or logfs geometry')
    mounts = root('cat /proc/mounts').decode().splitlines()
    valid_mounts = [line.split() for line in mounts
                    if len(line.split()) >= 3 and line.split()[1] == '/dev/logfs']
    if (len(valid_mounts) != 1 or valid_mounts[0][2] != 'vfat' or
            valid_mounts[0][0] not in ('/dev/block/sda13', '/dev/block/by-name/logfs',
                                     '/dev/block/bootdevice/by-name/logfs')):
        raise RuntimeError('Expected OEM FAT mount is absent')
    # New private directory only; device names and log content never form paths.
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    report = {'device': 'houji', 'serial': SERIAL,
              'captured_at': datetime.datetime.now().astimezone().isoformat(),
              'adb_port': args.adb_port, 'device_writes_requested': False,
              'native_log_file_present': False, 'xnu_log_file_present': False, 'files': []}
    for name in FILES:
        remote = '/dev/logfs/' + name
        size_text = root(f'if [ -f {shlex.quote(remote)} ]; then '
                         f'stat -c %s {shlex.quote(remote)}; else echo MISSING; fi').decode().strip()
        if size_text == 'MISSING':
            report['files'].append({'file': name, 'status': 'missing'})
            continue
        size = int(size_text)
        if size < 0 or size > MAX_FILE_BYTES:
            raise RuntimeError('Unexpected log file size: ' + name)
        before = parse_remote_digest(root('sha256sum ' + shlex.quote(remote)), remote)
        data = root('cat ' + shlex.quote(remote))
        after = parse_remote_digest(root('sha256sum ' + shlex.quote(remote)), remote)
        if len(data) > MAX_FILE_BYTES:
            raise RuntimeError('Log grew beyond read limit: ' + name)
        digest = hashlib.sha256(data).hexdigest()
        (args.output / name).write_bytes(data)
        report['files'].append({'file': name, 'status': 'captured', 'bytes': len(data),
                                'sha256': digest, 'stable': len(data) == size and before == digest == after,
                                'houji_markers': data.count(b'HOUJI'),
                                'darwinboot_markers': data.lower().count(b'darwinboot')})
        if name == 'UniXNU.log':
            report['native_log_file_present'] = True
            report['native_snapshot_integrity'] = verify_native_snapshot(data)
        if name == 'XnuLog.bin':
            report['xnu_log_file_present'] = True
            integrity, payload = decode_xnu_snapshot(data, args.xnu_run_id)
            report['xnu_snapshot_integrity'] = integrity
            if payload is not None:
                (args.output / 'XnuLog.txt').write_bytes(payload)
    (args.output / 'capture.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'output': str(args.output),
                      'captured_files': sum(f['status'] == 'captured' for f in report['files']),
                      'native_log_file_present': report['native_log_file_present'],
                      'xnu_snapshot_integrity': report.get('xnu_snapshot_integrity'),
                      'device_writes_requested': False}, indent=2))


if __name__ == '__main__':
    main()
