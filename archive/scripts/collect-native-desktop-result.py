#!/usr/bin/env python3
"""Verify protected storage and summarize an already captured desktop trial.

Only root recovery reads are sent to the phone. This neither boots the phone
nor changes log allocation. Camera feedback remains separate from GPU counters.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import time

N = Path('${HOUJI_ARTIFACTS}/native-port')
ADB = '${USER_HOME}/Library/Android/sdk/platform-tools/adb'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def desktop_samples(text):
    """An unavailable per-client observation is not a zero-work sample."""
    samples = []
    for line in text.splitlines():
        status = re.search(r'HOUJI DESKTOP: observed=([0-9a-fA-F]+)\b', line)
        if not status:
            continue
        row = {key: int(value) for key, value in re.findall(r'([\w-]+)=([0-9]+)\b', line)
               if key != 'observed'}
        row['observation_status'] = int(status[1], 16)
        row['observation_available'] = row['observation_status'] == 0
        stamp = re.search(r'\[\s*([0-9]+\.[0-9]+)\]:', line)
        row['uptime_seconds'] = float(stamp[1]) if stamp else None
        samples.append(row)
    return samples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=int, required=True)
    parser.add_argument('--adb-port', type=int, choices=(5037, 5038, 5047, 15049), required=True)
    parser.add_argument('--feedback', required=True)
    parser.add_argument('--capture', type=Path, help='Separate capture directory for an unchanged-image replay')
    parser.add_argument('--output', type=Path, help='Separate result path for a replay')
    args = parser.parse_args()
    if not 182 <= args.run <= 999:
        parser.error('Desktop runtime trial required')
    evidence = N / 'evidence'
    capture = args.capture if args.capture else evidence / f'logfs-recovery-r{args.run}'
    if not capture.resolve().is_relative_to(evidence.resolve()):
        raise ValueError('Capture must remain under the task evidence directory')
    policy = json.loads((N / f'native-ios-candidate/r{args.run}-policy.json').read_text())
    reader = module('log_reader', Path(__file__).with_name('capture-logfs.py'))
    preflight = module('boot_policy', Path(__file__).with_name('try-native-userland-boot.py'))
    report = json.loads((capture / 'capture.json').read_text())
    xnu, payload = reader.decode_xnu_snapshot((capture / 'XnuLog.bin').read_bytes(), policy['log_run_id'])
    native = reader.verify_native_snapshot((capture / 'UniXNU.log').read_bytes())
    if not xnu.get('valid') or not xnu.get('committed') or not native.get('valid'):
        raise RuntimeError('Committed capture identity or checksum invalid')
    if f'HOUJI LOGFS r{args.run}:'.encode() not in (capture / 'UniXNU.log').read_bytes():
        raise RuntimeError('Native capture run differs')
    for entry in report['files']:
        if entry['status'] != 'captured':
            continue
        raw = (capture / entry['file']).read_bytes()
        if not entry.get('stable') or hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise RuntimeError('Capture file no longer matches receipt')

    ports = [args.adb_port] + [p for p in (5037, 5038, 5047, 15049) if p != args.adb_port]

    def root(command):
        for _ in range(3):
            for port in ports:
                try:
                    result = subprocess.run([ADB, '-P', str(port), '-s', 'DEVICE_SERIAL', 'exec-out', command],
                                            capture_output=True, timeout=10)
                except subprocess.TimeoutExpired:
                    continue
                if result.returncode == 0 and not result.stderr and result.stdout:
                    ports.remove(port)
                    ports.insert(0, port)
                    return result.stdout
            time.sleep(0.25)
        raise RuntimeError('Recovery read failed: ' + command)

    if root('id -u; getprop ro.product.device; getprop ro.houji.native_rescue').splitlines() != [b'0', b'houji', b'1']:
        raise RuntimeError('Verified houji recovery required')
    for name, expected in preflight.BOOT.items():
        if root('sha256sum /dev/block/by-name/' + name).split() != [expected.encode(), ('/dev/block/by-name/' + name).encode()]:
            raise RuntimeError('Protected boot differs: ' + name)
    gpt = []
    for disk in json.loads((N / 'partition-backup-20261024/manifest.json').read_text())['disks']:
        for kind, skip in (('primary', 0), ('backup', disk['backup_start_lba'])):
            expected = preflight.expected_gpt(disk, kind)
            actual = root(f'dd if={disk["device"]} bs=4096 skip={skip} count={len(expected)//4096} status=none')
            if actual != expected:
                raise RuntimeError('Protected GPT differs: ' + disk['device'] + '/' + kind)
            gpt.append({'device': disk['device'], 'kind': kind, 'sha256': hashlib.sha256(actual).hexdigest()})
    misc = root('cat /dev/block/by-name/misc')
    baseline = (N / f'device-baseline/misc-before-native-ios-r{args.run}.bin').read_bytes()
    if len(misc) != 4194304 or len(baseline) != len(misc) or misc[864:] != baseline[864:]:
        raise RuntimeError('Reserved misc/A-B differs')
    text = payload.decode(errors='replace')

    def rows(marker):
        found = []
        for line in text.splitlines():
            if marker in line:
                found.append({key: int(value) for key, value in re.findall(r'([\w-]+)=([0-9]+)', line)})
        return found

    desktop = desktop_samples(text)
    last = desktop[-1] if desktop else {}
    current = last if last.get('observation_available') else {}
    last_success = next((row for row in reversed(desktop) if row['observation_available']), None)
    sync = rows('HOUJI PRESENT SYNC:')
    display_sync = rows('HOUJI DISPLAY SYNC:')
    lines = [line for line in text.splitlines() if any(marker in line for marker in
             ('HOUJI METAL ROW', 'HOUJI FULL STOP', 'HOUJI GATE PERF', 'HOUJI PRESENT SYNC', 'HOUJI DISPLAY SYNC'))]
    result = {
        'run': f'r{args.run}', 'captured_at': report['captured_at'],
        'capture_directory': str(capture),
        'verified_at': datetime.datetime.now().astimezone().isoformat(),
        'valid_committed_log': True, 'xnu_run_id': xnu['run_id'],
        'xnu_log_sha256': hashlib.sha256((capture / 'XnuLog.bin').read_bytes()).hexdigest(),
        'boot_partitions_unchanged': True, 'all_12_gpt_ranges_unchanged': len(gpt) == 12,
        'gpt': gpt, 'misc_reserved_unchanged': True,
        'desktop_last_observation_available': bool(current),
        'desktop_last_observation_status': last.get('observation_status'),
        'last_successful_desktop_sample': last_success,
        'desktop_counter_scope': 'last available per-client observation; not accumulated across process restarts',
        'actual_backboardd_submits': current.get('backboard-submits'),
        'actual_backboardd_submit_errors': current.get('submit-errors'),
        'actual_GPU_fence_submitted': current.get('ring-last'),
        'actual_GPU_fence_observed': current.get('real-completed'),
        'GPU_jobs_outstanding': current.get('jobs'),
        'display_swaps': last.get('swaps'), 'display_presents': last.get('presents'),
        'present_sync': sync[-1] if sync else None,
        'display_sync': display_sync[-1] if display_sync else None,
        'desktop_samples': desktop, 'display_windows': rows('HOUJI DISPLAY PERF:'),
        'physical_UI_confirmation': args.feedback,
        'usable_desktop_acceleration': False,
        'counters_are_not_panel_FPS': True,
        'terminal_metrics': lines,
    }
    output = args.output if args.output else evidence / f'native-ios-r{args.run}-result.json'
    if not output.resolve().is_relative_to(evidence.resolve()):
        raise ValueError('Result must remain under the task evidence directory')
    if output.exists():
        raise FileExistsError('Preserve existing analysis before replacement')
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('run', 'valid_committed_log', 'boot_partitions_unchanged',
          'all_12_gpt_ranges_unchanged', 'misc_reserved_unchanged', 'actual_backboardd_submits',
          'actual_GPU_fence_observed', 'present_sync', 'display_sync', 'physical_UI_confirmation')},
          ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
