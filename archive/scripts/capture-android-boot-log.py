#!/usr/bin/env python3
"""Read the bounded SHLOG001 window via this phone's root ADB; never write a block device.

The XNU/UEFI writer is a separate prerequisite. Unknown headers stop capture after
one 4 KiB read, without copying the surrounding Android data. Exports below the
32 MiB log window are intentionally not fetched by this reader.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import struct
import subprocess

ARTIFACTS = Path('${HOUJI_ARTIFACTS}/native-port')
ADB = '${USER_HOME}/Library/Android/sdk/platform-tools/adb'
SERIAL = 'DEVICE_SERIAL'
BLOCK = 4096
LOG_BLOCKS = 8192
HEADER = struct.Struct('<8sIIQQ14I32s')
FIELDS = ('magic', 'version', 'header_bytes', 'boot_id', 'first_lba',
          'window_blocks', 'msg_first', 'msg_blocks', 'msg_bytes',
          'slot_first', 'slot_blocks', 'slot_count', 'slots_written',
          'uptime_s', 'rounds', 'write_errors', 'gpt_open', 'gpt_last', 'state', 'tag')


def geometry(manifest):
    rows = [(d, p) for d in manifest['disks'] for p in d['partitions'] if p['name'] == 'userdata']
    if len(rows) != 1:
        raise ValueError('Expected one userdata partition in the captured GPT')
    disk, part = rows[0]
    if (disk['device'] != '/dev/block/sda' or disk['sector_bytes'] != BLOCK or
            not disk['gpt_crcs_valid'] or part['index'] != 33 or
            not 0 < part['start_lba'] <= part['end_lba'] < disk['bytes'] // BLOCK):
        raise ValueError('Unexpected device geometry')
    blocks = part['end_lba'] - part['start_lba'] + 1
    if blocks <= LOG_BLOCKS or part['bytes'] != blocks * BLOCK:
        raise ValueError('Invalid userdata size')
    return dict(device='/dev/block/sda33', bytes=part['bytes'],
                start=part['start_lba'], relative_log=blocks - LOG_BLOCKS,
                absolute_log=part['end_lba'] + 1 - LOG_BLOCKS)


def validate_header(blob, first_lba):
    if len(blob) < BLOCK:
        raise ValueError('Header shorter than 4096 bytes')
    h = dict(zip(FIELDS, HEADER.unpack_from(blob)))
    if h['magic'] != b'SHLOG001':
        raise ValueError('No SHLOG001 header')
    version = h['version']
    required = {1: 120, 2: 136, 3: 140, 4: 148}.get(version)
    if required is None or not required <= h['header_bytes'] <= BLOCK:
        raise ValueError('Unsupported version or header size')
    if h['first_lba'] != first_lba or h['window_blocks'] != LOG_BLOCKS:
        raise ValueError('Header names a different physical log window')
    msg_first, msg_blocks = h['msg_first'], h['msg_blocks']
    if (not 1 <= msg_first < LOG_BLOCKS or not 0 < msg_blocks <= LOG_BLOCKS - msg_first or
            h['msg_bytes'] > msg_blocks * BLOCK):
        raise ValueError('Message buffer outside log window')
    slot_first, slot_blocks, count = h['slot_first'], h['slot_blocks'], h['slot_count']
    if (not msg_first + msg_blocks <= slot_first < LOG_BLOCKS or slot_blocks == 0 or
            count == 0 or count > (LOG_BLOCKS - slot_first) // slot_blocks):
        raise ValueError('Text ring outside log window or overlapping message buffer')
    if version >= 2:
        h.update(zip(('export_first', 'export_blocks', 'export_bytes', 'export_generation'),
                     struct.unpack_from('<4I', blob, HEADER.size)))
    if version >= 3:
        h['export_below'], = struct.unpack_from('<I', blob, 136)
    if version >= 4:
        h['diag_first'], h['diag_bytes'] = struct.unpack_from('<II', blob, 140)
    h['magic'] = h['magic'].decode('ascii')
    h['tag'] = h['tag'].split(b'\0', 1)[0].decode('utf-8', errors='replace')
    return h


def decode(blob, first_lba, output):
    if len(blob) != BLOCK * LOG_BLOCKS:
        raise ValueError('Expected a complete 32 MiB log window')
    h = validate_header(blob, first_lba)
    # No paths or export lengths from the device are used as local filenames.
    (output / 'log.bin').write_bytes(blob)
    (output / 'header.json').write_text(json.dumps(h, indent=2) + '\n')
    at = h['msg_first'] * BLOCK
    (output / 'msgbuf.txt').write_bytes(blob[at:at + h['msg_bytes']])
    slots = []
    for index in range(max(0, h['slots_written'] - h['slot_count']), h['slots_written']):
        at = (h['slot_first'] + index % h['slot_count'] * h['slot_blocks']) * BLOCK
        slots.append(blob[at:at + h['slot_blocks'] * BLOCK].split(b'\0', 1)[0].decode('utf-8', errors='replace'))
    (output / 'slots.txt').write_text('\n'.join(slots))
    (output / 'latest.txt').write_text(slots[-1] if slots else '')
    return h


def capture(port, g, output):
    def run(command, timeout=30):
        r = subprocess.run([ADB, '-P', str(port), '-s', SERIAL, 'exec-out',
                            '/debug_ramdisk/su -c ' + shlex.quote(command)],
                           capture_output=True, timeout=timeout, check=True)
        return r.stdout

    devices = subprocess.check_output([ADB, '-P', str(port), 'devices'], text=True)
    if SERIAL + '\tdevice' not in devices:
        raise ValueError('Authorized phone is not available on this ADB service')
    state = run('id; getprop ro.product.device; readlink -f /dev/block/by-name/userdata; '
                'blockdev --getsize64 /dev/block/by-name/userdata; cat /sys/class/block/sda33/start').decode().splitlines()
    if (len(state) != 5 or not state[0].startswith('uid=0(root)') or state[1] != 'houji' or
            state[2] != g['device'] or int(state[3]) != g['bytes'] or
            int(state[4]) * 512 != g['start'] * BLOCK):
        raise ValueError('Phone identity, root or partition geometry differs')

    def read(blocks):
        data = run('dd if=/dev/block/by-name/userdata bs=4096 skip=' + str(g['relative_log']) +
                   ' count=' + str(blocks) + ' 2>/dev/null', 90)
        if len(data) != blocks * BLOCK:
            raise ValueError('Short device read')
        return data

    prefix = read(1)
    report = dict(serial=SERIAL, adb_port=port, read_only=True, first_lba=g['absolute_log'],
                  prefix_sha256=hashlib.sha256(prefix).hexdigest())
    if prefix[:8] != b'SHLOG001':
        report['status'] = 'no-log-header'
        report['device_bytes_read'] = BLOCK
        (output / 'capture.json').write_text(json.dumps(report, indent=2) + '\n')
        print('No SHLOG001 header. Read 4096 bytes only; no log or device writes.')
        return 2
    validate_header(prefix, g['absolute_log'])
    blob = read(LOG_BLOCKS)
    after = read(1)
    if blob[:BLOCK] != prefix or after != prefix:
        raise ValueError('Log header changed during capture; refusing inconsistent snapshot')
    h = decode(blob, g['absolute_log'], output)
    report.update(status='captured', bytes=len(blob), sha256=hashlib.sha256(blob).hexdigest(),
                  boot_id=h['boot_id'], external_exports_fetched=False)
    (output / 'capture.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Captured and decoded a stable 32 MiB log window to', output)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--adb-port', type=int, choices=(5037, 5038, 5047))
    ap.add_argument('--manifest', type=Path, default=ARTIFACTS / 'partition-backup-20261024/manifest.json')
    ap.add_argument('--decode', type=Path, help='decode a saved log window without device access')
    ap.add_argument('--output', type=Path, required=True, help='new private output directory')
    a = ap.parse_args()
    if a.decode is None and a.adb_port is None:
        ap.error('--adb-port is required for device reads')
    os.umask(0o077)
    g = geometry(json.loads(a.manifest.read_text()))
    a.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    if a.decode:
        decode(a.decode.read_bytes(), g['absolute_log'], a.output)
        print('Decoded local log window to', a.output)
        return 0
    return capture(a.adb_port, g, a.output)


if __name__ == '__main__':
    raise SystemExit(main())
