#!/usr/bin/env python3
"""Install the verified r47 startup baseline in the pinned userdata chunks.

Before iOS runs, --rollback restores the same preimage, including after a partial
install. After iOS has run, use the immutable full root snapshot instead: its
catalog can no longer be restored independently of changed user data.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import re
import subprocess
from pathlib import Path

N = Path('${HOUJI_ARTIFACTS}/native-port')
D = N / 'ios-userland/startup-baseline-r47'
ADB = '${USER_HOME}/Library/Android/sdk/platform-tools/adb'
HELPER_SHA = '6ddf56c560d466ca1fc7d66cb436846e8713f1429d9038a9019c916bad7f676b'
BEFORE = '1a343c2a79706a898dbb69711661fc493a855e95b8c1192207a4fbc8badb0fe0'
AFTER = 'b98cdbecbecbcd550d8953a66a7d677315ce800eaecaa6fdd68ff68b939aea79'
CHUNK = 134217728


def validate(plan):
    if (plan['bytes'] != 96 * CHUNK or plan['chunk_bytes'] != CHUNK or
        plan['before_sha256'] != BEFORE or plan['after_sha256'] != AFTER or
        plan['changed_chunks'] != [0, 1, 3, 4, 5, 6, 7, 9, 13, 18, 19, 27, 29, 32, 35, 36, 37, 38, 41, 42, 44, 46, 48, 51, 53, 55, 56, 57, 58, 59, 60, 61, 65, 90, 91, 92, 93, 94, 95] or len(plan['chunks']) != 96 or
        plan['before_image'] != str(N / 'ios-userland/phone-after-r46/ios16-phone.hfsx') or
        plan['after_image'] != str(D / 'ios16-baseline.hfsx')):
        raise ValueError('Pinned r47 root delta differs')
    for i, entry in enumerate(plan['chunks']):
        if entry['index'] != i or not all(re.fullmatch('[0-9a-f]{64}', entry[k]) for k in ('before', 'after')):
            raise ValueError('Invalid chunk inventory')
        if (entry['before'] != entry['after']) != (i in (0, 1, 3, 4, 5, 6, 7, 9, 13, 18, 19, 27, 29, 32, 35, 36, 37, 38, 41, 42, 44, 46, 48, 51, 53, 55, 56, 57, 58, 59, 60, 61, 65, 90, 91, 92, 93, 94, 95)):
            raise ValueError('Changed chunk list disagrees')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb-port', type=int, choices=(5037, 5038, 5047), required=True)
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    plan = json.loads((D / 'delta.json').read_text()); validate(plan)
    target = 'before' if args.rollback else 'after'
    source = Path(plan[target + '_image'])
    # Re-read both immutable images. No plan-supplied chunk digest is trusted
    # until it matches the complete, independently pinned pre/post images.
    for kind in ('before', 'after'):
        digest = hashlib.sha256()
        with Path(plan[kind + '_image']).open('rb') as stream:
            for entry in plan['chunks']:
                data = stream.read(CHUNK)
                if len(data) != CHUNK or hashlib.sha256(data).hexdigest() != entry[kind]:
                    raise ValueError('Host image chunk differs')
                digest.update(data)
            if stream.read(1) or digest.hexdigest() != plan[kind + '_sha256']:
                raise ValueError('Host image digest differs')
    log = D / ('rollback.jsonl' if args.rollback else 'install.jsonl')
    adb = [ADB, '-P', str(args.adb_port), '-s', 'DEVICE_SERIAL']
    def record(value):
        with log.open('a') as out:
            out.write(json.dumps({'time': datetime.datetime.now().astimezone().isoformat(), **value}) + '\n')
    def root(command):
        r = subprocess.run(adb + ['exec-out', command], capture_output=True, timeout=120)
        if r.returncode or r.stderr:
            record({'failed_command': command, 'returncode': r.returncode, 'stderr': r.stderr.decode(errors='replace')})
            raise RuntimeError('Recovery command failed')
        return r.stdout
    def identity():
        if root('id -u; getprop ro.product.device; getprop ro.houji.native_rescue; getprop ro.boot.slot_suffix; readlink -f /dev/block/by-name/userdata; blockdev --getsize64 /dev/block/by-name/userdata').splitlines() != [b'0', b'houji', b'1', b'_a', b'/dev/block/sda33', b'515465261056']:
            raise RuntimeError('Rescue/userdata identity differs')
        if any(line.split()[1] == b'/data' for line in root('cat /proc/mounts').splitlines()):
            raise RuntimeError('userdata mounted')
    identity()
    spec = importlib.util.spec_from_file_location('boot_guard', Path(__file__).with_name('try-native-userland-boot.py'))
    guard = importlib.util.module_from_spec(spec); spec.loader.exec_module(guard)
    def critical():
        for name, sha in guard.BOOT.items():
            if root('sha256sum /dev/block/by-name/' + name).split()[0].decode() != sha:
                raise RuntimeError('Boot partition changed: ' + name)
        for disk in json.loads((N / 'partition-backup-20261024/manifest.json').read_text())['disks']:
            for suffix, skip in [('primary', 0), ('backup', disk['backup_start_lba'])]:
                saved = guard.expected_gpt(disk, suffix)
                if root(f'dd if={disk["device"]} bs=4096 skip={skip} count={len(saved)//4096} status=none') != saved:
                    raise RuntimeError('GPT differs')
    critical()
    helper = N / 'native-ios-candidate/root-chunk-read'
    if hashlib.sha256(helper.read_bytes()).hexdigest() != HELPER_SHA:
        raise ValueError('Read-only helper differs')
    subprocess.run(adb + ['push', str(helper), '/tmp/houji-root-chunk-read'], check=True, capture_output=True)
    root('chmod 755 /tmp/houji-root-chunk-read')
    if root('sha256sum /tmp/houji-root-chunk-read').split()[0].decode() != HELPER_SHA:
        raise ValueError('Staged read helper differs')
    def live_index():
        text = root('set -e -o pipefail; i=0; while [ "$i" -lt 96 ]; do printf "%s " "$i"; /tmp/houji-root-chunk-read "$i" | sha256sum; i=$((i+1)); done')
        lines = text.splitlines()
        if len(lines) != 96:
            raise RuntimeError('Incomplete live index')
        result = []
        for i, line in enumerate(lines):
            match = re.fullmatch(rb'([0-9]+) ([0-9a-f]{64})  -', line)
            if not match or int(match[1]) != i:
                raise RuntimeError('Invalid live index')
            result.append(match[2].decode())
        return result
    live = live_index(); record({'phase': 'before', 'live_index': live, 'target': target})
    for i, value in enumerate(live):
        allowed = {plan['chunks'][i]['before'], plan['chunks'][i]['after']} if args.rollback else {plan['chunks'][i]['before']}
        if value not in allowed:
            raise RuntimeError('Live root changed; no writes requested')
    with source.open('rb') as stream:
        for i in plan['changed_chunks']:
            expected = plan['chunks'][i][target]
            if live[i] == expected:
                continue
            stream.seek(i * CHUNK); data = stream.read(CHUNK)
            if len(data) != CHUNK or hashlib.sha256(data).hexdigest() != expected:
                raise ValueError('Staging source differs')
            stage = D / 'chunk-to-install.bin'; stage.write_bytes(data)
            subprocess.run(adb + ['push', str(stage), '/tmp/houji-startup-chunk.bin'], capture_output=True, check=True)
            if root('stat -c %s /tmp/houji-startup-chunk.bin; sha256sum /tmp/houji-startup-chunk.bin').split()[:2] != [str(CHUNK).encode(), expected.encode()]:
                raise RuntimeError('Staged tmpfs chunk differs')
            identity()
            current = root(f'set -e -o pipefail; /tmp/houji-root-chunk-read {i} | sha256sum').split()[0].decode()
            if current != live[i]:
                raise RuntimeError('Live chunk changed before write')
            record({'phase': 'write-intent', 'index': i, 'before': current, 'after': expected})
            # Fixed whitelist, verified 128 MiB source and bounded 12 GiB seek.
            root(f'set -e; dd if=/tmp/houji-startup-chunk.bin of=/dev/block/by-name/userdata bs=4096 seek={i*32768} count=32768 conv=notrunc,fsync status=none; sync')
            readback = root(f'set -e -o pipefail; /tmp/houji-root-chunk-read {i} | sha256sum').split()[0].decode()
            if readback != expected:
                raise RuntimeError('Direct chunk readback differs; preserve journal for rollback')
            record({'phase': 'verified', 'index': i, 'sha256': expected})
            print(f'Chunk {i}: direct readback PASS', flush=True)
    final = live_index()
    if final != [x[target] for x in plan['chunks']]:
        raise RuntimeError('Final full root chunk index differs')
    critical(); identity()
    root('rm -f /tmp/houji-startup-chunk.bin'); stage.unlink(missing_ok=True)
    report = {'status': 'PASS', 'direction': target, 'full_96_chunk_readback_matches': True,
              'boot_and_gpt_unchanged': True, 'changed_chunks': plan['changed_chunks'],
              'immutable_preimage': plan['before_image'], 'expected_root_sha256': plan[target + '_sha256']}
    (D / ('rollback-result.json' if args.rollback else 'install-result.json')).write_text(json.dumps(report, indent=2) + '\n')
    record(report); print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
