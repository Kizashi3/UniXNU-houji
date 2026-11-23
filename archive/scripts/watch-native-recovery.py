#!/usr/bin/env python3
"""Poll existing ADB servers and capture this trial as soon as rescue returns.

Start after fastboot reports Booting OKAY. No fixed grace sleep, server restart,
device reboot, partition write or automatic subsequent boot is performed.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ADB = '${USER_HOME}/Library/Android/sdk/platform-tools/adb'
SERIAL = 'DEVICE_SERIAL'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=int, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--first-port', type=int, choices=(5037, 5038, 5047, 15049), default=5038)
    parser.add_argument('--timeout', type=float, default=600)
    args = parser.parse_args()
    if not re.fullmatch('[0-9a-f]{32}', args.run_id) or args.run < 23 or args.timeout <= 0:
        parser.error('Invalid trial identity or observation deadline')
    if args.output.exists():
        parser.error('Capture destination already exists; preserve it before retrying')
    status_path = args.output.with_name(args.output.name + '-watch.json')
    start = time.monotonic()
    status = {'run': args.run, 'run_id': args.run_id, 'state': 'polling', 'attempts': 0,
              'started_at': datetime.datetime.now().astimezone().isoformat(),
              'fixed_grace_sleep': False, 'captures': []}

    def save(state):
        status.update(state=state, elapsed_seconds=round(time.monotonic() - start, 3))
        status_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = status_path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(status, indent=2) + '\n')
        temporary.replace(status_path)

    ports = [args.first_port] + [p for p in (5037, 5038, 5047, 15049) if p != args.first_port]
    last_invalid_signature = None
    stable_invalid_count = 0
    save('polling')
    print('Polling recovery; capture starts immediately on verified root rescue identity', flush=True)
    while time.monotonic() - start < args.timeout:
        for port in ports:
            try:
                identity = subprocess.run([ADB, '-P', str(port), '-s', SERIAL, 'exec-out',
                                          'id -u; getprop ro.houji.native_rescue'],
                                         capture_output=True, timeout=1.5)
            except subprocess.TimeoutExpired:
                continue
            status['attempts'] += 1
            if identity.returncode or identity.stdout.splitlines() != [b'0', b'1']:
                continue
            status.update(port=port, detected_at=datetime.datetime.now().astimezone().isoformat(),
                          detected_seconds=round(time.monotonic() - start, 3))
            save('capturing')
            print(f'Recovery detected on {port}; capturing now', flush=True)
            command = [sys.executable, str(Path(__file__).with_name('capture-logfs.py')),
                       '--adb-port', str(port), '--recovery', '--retry-adb-ports',
                       '--xnu-run-id', args.run_id, '--output', str(args.output)]
            try:
                signature = None
                capture = subprocess.run(command, capture_output=True, text=True, timeout=180)
                record = {'returncode': capture.returncode, 'stdout': capture.stdout[-4000:],
                          'stderr': capture.stderr[-4000:]}
                valid = False
                if capture.returncode == 0:
                    metadata = json.loads((args.output / 'capture.json').read_text())
                    required_files = {f.get('file'): f for f in metadata.get('files', [])}
                    native_file = required_files.get('UniXNU.log', {})
                    xnu_file = required_files.get('XnuLog.bin', {})
                    if (native_file.get('status') == 'missing' and
                            metadata.get('native_log_file_present') is False and
                            xnu_file.get('status') == 'captured' and xnu_file.get('stable')):
                        # A completed capture can prove that an early failure
                        # never created the native log. Keep it invalid, but
                        # allow identical stable evidence to stop recapture.
                        xnu = (args.output / 'XnuLog.bin').read_bytes()
                        signature = ('missing-native', hashlib.sha256(xnu).hexdigest(),
                                     metadata.get('xnu_snapshot_integrity', {}).get('run_id'))
                        record['native_log_missing'] = True
                        record['trial_identity_and_native_crc_valid'] = False
                    else:
                        native = (args.output / 'UniXNU.log').read_bytes()
                        stable = all(required_files.get(name, {}).get('stable')
                                     for name in ('UniXNU.log', 'XnuLog.bin'))
                        valid = (f'HOUJI LOGFS r{args.run}:'.encode() in native and
                                 metadata['native_snapshot_integrity']['valid'] and
                                 metadata['xnu_snapshot_integrity'].get('run_id') == args.run_id and stable)
                        record['trial_identity_and_native_crc_valid'] = bool(valid)
                        if not valid:
                            if stable:
                                signature = (hashlib.sha256(native).hexdigest(),
                                             metadata['xnu_snapshot_integrity'].get('run_id'),
                                             metadata['native_snapshot_integrity']['valid'])
            except (subprocess.TimeoutExpired, OSError, ValueError, KeyError) as error:
                record = {'error': str(error)}
                valid = False
                signature = None
            status['captures'].append(record)
            if valid:
                save('complete')
                print(json.dumps({'state': 'complete', 'port': port,
                                  'elapsed_seconds': status['elapsed_seconds'],
                                  'capture': str(args.output)}, indent=2), flush=True)
                return 0
            stable_invalid_count = stable_invalid_count + 1 if signature and signature == last_invalid_signature else (1 if signature else 0)
            last_invalid_signature = signature
            if stable_invalid_count >= 3:
                status['reason'] = 'Three identical stable invalid snapshots; latest evidence retained, automatic recapture stopped'
                save('invalid-stable-snapshot')
                print(status['reason'], flush=True)
                return 3
            if args.output.exists():
                partial = args.output.with_name(args.output.name + f'-partial-{len(status["captures"])}')
                if partial.exists():
                    raise RuntimeError('Partial archive already exists; refusing overwrite')
                args.output.rename(partial)
            save('polling')
        # Poll cadence only, not a boot grace period. Device readiness and
        # snapshot identity/CRC decide whether analysis can begin.
        time.sleep(0.5)
    save('deadline')
    print('Recovery not captured before observation deadline; last evidence preserved', flush=True)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
