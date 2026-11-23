#!/usr/bin/env python3
"""Read houji's existing 8 MiB logfs in Recovery, or decode a saved copy.

No reboot, mount, server restart, or device writes. The target and ADB server
must be explicit. Raw evidence survives an invalid/incomplete snapshot.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import zlib

PARTITION_BYTES = 8 * 1024 * 1024
FILES = {b'UNIXNU  LOG': 'UniXNU.log', b'XNULOG  BIN': 'XnuLog.bin'}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def fat_files(raw):
    """Decode only the two known files in the verified FAT12 geometry."""
    if len(raw) != PARTITION_BYTES or raw[510:512] != b'\x55\xaa':
        raise ValueError('logfs size or FAT signature differs')
    u16 = lambda at: struct.unpack_from('<H', raw, at)[0]
    u32 = lambda at: struct.unpack_from('<I', raw, at)[0]
    if (u16(11), raw[13], u16(14), raw[16], u16(17), u16(19),
            raw[21], u16(22), u32(32)) != (4096, 1, 1, 2, 512, 1280, 248, 1, 0):
        raise ValueError('logfs FAT12 geometry differs')
    fat = raw[4096:8192]
    if fat != raw[8192:12288]:
        raise ValueError('FAT copies disagree')
    result, claimed = {}, set()
    for at in range(3 * 4096, 7 * 4096, 32):
        entry = raw[at:at + 32]
        if entry[0] == 0:
            break
        if entry[0] == 229 or entry[11] == 15 or entry[11] & 8:
            continue
        name = FILES.get(bytes(entry[:11]))
        if name is None:
            continue
        if name in result or entry[11] & 16 or entry[20:22] != b'\0\0':
            raise ValueError('duplicate file or unsupported directory entry')
        cluster, size = struct.unpack_from('<HI', entry, 26)
        limit = 65536 if name == 'XnuLog.bin' else 524288
        if not 0 < size <= limit:
            raise ValueError('unexpected diagnostic file size')
        data, chain = bytearray(), []
        for _ in range((size + 4095) // 4096):
            if not 2 <= cluster < 1275 or cluster in claimed:
                raise ValueError('file chain overlaps, loops, or leaves the FAT volume')
            claimed.add(cluster)
            chain.append(cluster)
            offset = (7 + cluster - 2) * 4096
            data.extend(raw[offset:offset + 4096])
            word = struct.unpack_from('<H', fat, cluster + cluster // 2)[0]
            cluster = word >> 4 if cluster & 1 else word & 4095
        if cluster < 4088:
            raise ValueError('file chain has no exact end marker')
        result[name] = (bytes(data[:size]), chain)
    return result


def decode_xnu(data, run_id):
    result = {'valid': False}
    if len(data) != 65536 or data[:8] != b'HJXNU001':
        return result, None
    state, version = struct.unpack_from('<II', data, 8)
    actual_run = data[16:32].hex()
    length, crc, header_crc = struct.unpack_from('<III', data, 32)
    result.update(committed=state == 1, version=version, run_id=actual_run,
                  expected_run_id_matches=actual_run == run_id, payload_bytes=length)
    header = bytearray(data[:4096])
    header[40:44] = bytes(4)
    if (state != 1 or version != 1 or actual_run != run_id or length > 61440
            or zlib.crc32(header) != header_crc or any(data[44:4096])
            or zlib.crc32(data[4096:4096 + length]) != crc
            or any(data[4096 + length:])):
        return result, None
    result['valid'] = True
    return result, data[4096:4096 + length]


def verify_firmware(data):
    footer = re.search(rb'HOUJI LOGFS CHECKSUM: payload-bytes=([0-9]+) '
                       rb'payload-crc32=([0-9A-Fa-f]{8})\r?\n\Z', data)
    if footer is None:
        return {'valid': False, 'checksum_footer_present': False}
    payload = data[:footer.start()]
    starts = set(re.findall(rb'HOUJI LOGFS r([0-9]+):', payload))
    ends = set(re.findall(rb'r([0-9]+) snapshot end; app text only; commit/readback follows', payload))
    # Older checkpoint sections retain their original labels inside newer
    # firmware logs. These labels are not the XNU trial ID or its proof.
    ended = bool(starts & ends)
    return {'valid': bool(ended and int(footer[1]) == len(payload)
                         and int(footer[2], 16) == zlib.crc32(payload)),
            'checksum_footer_present': True, 'payload_bytes': len(payload)}


def read_recovery(adb, port, serial):
    # Do not let adb start a new default server or claim another device.
    with socket.create_connection(('127.0.0.1', port), timeout=3):
        pass
    env = dict(os.environ, ADB_LIBUSB='0', ADB_MDNS_AUTO_CONNECT='0')

    def read(command):
        result = subprocess.run([adb, '-P', str(port), '-s', serial, 'exec-out', command],
                                capture_output=True, timeout=45, env=env)
        if result.returncode or result.stderr:
            error = result.stderr.decode(errors='replace').replace(serial, '<target>')
            raise RuntimeError('ADB read failed: ' + error)
        return result.stdout

    identity = read('id -u; getprop ro.product.device; getprop ro.houji.native_rescue; '
                    'readlink -f /dev/block/by-name/logfs; '
                    'blockdev --getsize64 /dev/block/by-name/logfs').splitlines()
    if identity != [b'0', b'houji', b'1', b'/dev/block/sda13', str(PARTITION_BYTES).encode()]:
        raise ValueError('expected houji root Recovery and logfs geometry absent')
    before = read('sha256sum /dev/block/by-name/logfs').split()[0].decode()
    raw = read('dd if=/dev/block/by-name/logfs bs=4096 count=2048 status=none')
    after = read('sha256sum /dev/block/by-name/logfs').split()[0].decode()
    return raw, len(raw) == PARTITION_BYTES and before == sha256(raw) == after


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--input', type=Path, help='saved 8 MiB logfs copy; no device access')
    source.add_argument('--serial', help='explicit target; never written into the report')
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--adb-port', type=int, help='existing dedicated ADB server')
    parser.add_argument('--run-id', required=True, help='32 hex digits from the trial layout')
    parser.add_argument('--output', type=Path, required=True, help='new private evidence directory')
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9a-f]{32}', args.run_id):
        parser.error('--run-id must contain 32 lowercase hex digits')
    if args.serial and (not args.adb_port or not 1024 <= args.adb_port <= 65535):
        parser.error('an explicit existing --adb-port is required')
    if args.input and args.adb_port is not None:
        parser.error('--adb-port is only used with --serial')
    os.umask(0o077)
    args.output.mkdir(parents=True, mode=0o700, exist_ok=False)
    report = dict(captured_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  expected_run_id=args.run_id, device_writes_requested=False,
                  source='saved copy' if args.input else 'houji Recovery', files={})
    try:
        if args.input:
            if args.input.stat().st_size != PARTITION_BYTES:
                raise ValueError('input must be an 8 MiB logfs copy')
            raw, stable = args.input.read_bytes(), None
        else:
            raw, stable = read_recovery(args.adb, args.adb_port, args.serial)
            report['adb_port'] = args.adb_port
        (args.output / 'logfs.bin').write_bytes(raw)
        report.update(raw_bytes=len(raw), raw_sha256=sha256(raw), device_read_stable=stable)
        if stable is False:
            raise ValueError('logfs changed during capture; raw evidence retained')
        for name, (data, chain) in fat_files(raw).items():
            (args.output / name).write_bytes(data)
            report['files'][name] = dict(bytes=len(data), sha256=sha256(data), clusters=chain)
            if name == 'XnuLog.bin':
                check, text = decode_xnu(data, args.run_id)
                report['xnu_snapshot_integrity'] = check
                if text is not None:
                    (args.output / 'XnuLog.txt').write_bytes(text)
            else:
                report['native_snapshot_integrity'] = verify_firmware(data)
        if not report.get('xnu_snapshot_integrity', {}).get('valid'):
            raise ValueError('XNU snapshot missing, incomplete, corrupt, or from another trial')
        if not report.get('native_snapshot_integrity', {}).get('valid'):
            raise ValueError('firmware snapshot missing, incomplete, or corrupt')
        report['status'] = 'PASS'
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        report.update(status='FAIL', error=str(error).replace(args.serial, '<target>')
                      if args.serial else str(error))
    (args.output / 'capture.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'output': str(args.output),
                      'error': report.get('error'), 'device_writes_requested': False}, indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
