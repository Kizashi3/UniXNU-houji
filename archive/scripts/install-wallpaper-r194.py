#!/usr/bin/env python3
"""Install/restore only the pinned r168 probe delta in an unmounted rescue root.

Rollback accepts only a mixture of the pinned pre/post chunks, before iOS runs.
Once iOS has run, restore from the full immutable snapshot instead.
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
D = N / 'ios-userland/wallpaper-bootstrap-r194'
ADB = '${USER_HOME}/Library/Android/sdk/platform-tools/adb'
BEFORE = '183e122c655ede56b06340dfe436485485ce207950bef85c62ac01a8d57c679c'
HELPER_SHA = '6ddf56c560d466ca1fc7d66cb436846e8713f1429d9038a9019c916bad7f676b'
CHUNK = 134217728


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb-port', type=int, choices=(5037, 5038, 5047), required=True)
    parser.add_argument('--expected-plan-sha256', required=True)
    parser.add_argument('--rollback', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    raw = (D / 'delta.json').read_bytes()
    assert re.fullmatch('[0-9a-f]{64}', args.expected_plan_sha256)
    assert hashlib.sha256(raw).hexdigest() == args.expected_plan_sha256
    plan = json.loads(raw)
    assert plan['bytes'] == 96 * CHUNK and plan['chunk_bytes'] == CHUNK
    assert plan['before_sha256'] == BEFORE and not plan['probe_only'] and plan['desktop_selected']
    assert plan['before_image'] == str(N / 'ios-userland/phone-before-dvfs-wallpaper-r191/ios16-phone.hfsx')
    assert plan['after_image'] == str(D / 'ios16-desktop.hfsx')
    assert len(plan['chunks']) == 96 and 1 <= len(plan['changed_chunks']) <= 32
    for i, row in enumerate(plan['chunks']):
        assert row['index'] == i and all(re.fullmatch('[0-9a-f]{64}', row[k]) for k in ('before', 'after'))
        assert (row['before'] != row['after']) == (i in plan['changed_chunks'])
    assert plan['changed_chunks'] == sorted(set(plan['changed_chunks']))
    for name in ('preparation', 'owners-finalized'):
        key = 'preparation_sha256' if name == 'preparation' else 'owners_proof_sha256'
        assert hashlib.sha256((D / (name + '.json')).read_bytes()).hexdigest() == plan[key]
    # Independently re-read every byte of both host images before accessing the phone.
    for kind in ('before', 'after'):
        image = Path(plan[kind + '_image'])
        assert not image.is_symlink() and image.stat().st_size == 96 * CHUNK
        whole = hashlib.sha256()
        with image.open('rb') as stream:
            for row in plan['chunks']:
                data = stream.read(CHUNK)
                assert len(data) == CHUNK and hashlib.sha256(data).hexdigest() == row[kind]
                whole.update(data)
            assert not stream.read(1) and whole.hexdigest() == plan[kind + '_sha256']
    target = 'before' if args.rollback else 'after'
    adb = [ADB, '-P', str(args.adb_port), '-s', 'DEVICE_SERIAL']
    journal = D / ('rollback.jsonl' if args.rollback else 'install.jsonl')

    def record(value):
        with journal.open('a') as out:
            out.write(json.dumps({'time': datetime.datetime.now().astimezone().isoformat(), **value}) + '\n')

    def root(command):
        result = subprocess.run(adb + ['exec-out', command], capture_output=True, timeout=120)
        if result.returncode or result.stderr:
            record({'command_failed': command, 'returncode': result.returncode,
                'stderr': result.stderr.decode(errors='replace')})
            raise RuntimeError('Recovery command failed; preserve journal')
        return result.stdout

    def identity():
        assert root('id -u; getprop ro.product.device; getprop ro.houji.native_rescue; getprop ro.boot.slot_suffix; readlink -f /dev/block/by-name/userdata; blockdev --getsize64 /dev/block/by-name/userdata').splitlines() == [b'0', b'houji', b'1', b'_a', b'/dev/block/sda33', b'515465261056']
        assert not any(line.split()[1] == b'/data' for line in root('cat /proc/mounts').splitlines())

    identity()
    spec = importlib.util.spec_from_file_location('guard', Path(__file__).with_name('try-native-userland-boot.py'))
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)

    def critical():
        for name, sha in guard.BOOT.items():
            assert root('sha256sum /dev/block/by-name/' + name).split()[0].decode() == sha, name
        for disk in json.loads((N / 'partition-backup-20261024/manifest.json').read_text())['disks']:
            for suffix, skip in (('primary', 0), ('backup', disk['backup_start_lba'])):
                expected = guard.expected_gpt(disk, suffix)
                assert root(f'dd if={disk["device"]} bs=4096 skip={skip} count={len(expected)//4096} status=none') == expected

    critical()
    misc = root('cat /dev/block/by-name/misc')
    assert len(misc) == 4194304 and misc == root('cat /dev/block/by-name/misc')
    misc_backup = D / ('misc-before-rollback.bin' if args.rollback else 'misc-before-install.bin')
    if misc_backup.exists():
        assert (args.resume or args.rollback) and misc_backup.read_bytes() == misc
    else:
        misc_backup.write_bytes(misc)
    helper = N / 'native-ios-candidate/root-chunk-read'
    assert hashlib.sha256(helper.read_bytes()).hexdigest() == HELPER_SHA
    subprocess.run(adb + ['push', str(helper), '/tmp/houji-root-chunk-read'], capture_output=True, check=True)
    root('chmod 755 /tmp/houji-root-chunk-read')
    assert root('sha256sum /tmp/houji-root-chunk-read').split()[0].decode() == HELPER_SHA

    def live_index():
        data = root('set -e -o pipefail; i=0; while [ "$i" -lt 96 ]; do printf "%s " "$i"; /tmp/houji-root-chunk-read "$i" | sha256sum; i=$((i+1)); done')
        lines = data.splitlines()
        assert len(lines) == 96
        result = []
        for i, line in enumerate(lines):
            match = re.fullmatch(rb'([0-9]+) ([0-9a-f]{64})  -', line)
            assert match and int(match[1]) == i
            result.append(match[2].decode())
        return result

    live = live_index()
    record({'phase': 'before', 'live_index': live, 'target': target, 'plan_sha256': args.expected_plan_sha256})
    for i, value in enumerate(live):
        allowed = {plan['chunks'][i]['before'], plan['chunks'][i]['after']} if (args.rollback or args.resume) else {plan['chunks'][i]['before']}
        assert value in allowed, 'Phone root differs; no writes requested'
    stage = D / 'chunk-to-install.bin'
    with Path(plan[target + '_image']).open('rb') as stream:
        for i in plan['changed_chunks']:
            expected = plan['chunks'][i][target]
            if live[i] == expected:
                continue
            stream.seek(i * CHUNK)
            data = stream.read(CHUNK)
            assert len(data) == CHUNK and hashlib.sha256(data).hexdigest() == expected
            stage.write_bytes(data)
            subprocess.run(adb + ['push', str(stage), '/tmp/houji-adrenometal-chunk.bin'], capture_output=True, check=True)
            assert root('stat -c %s /tmp/houji-adrenometal-chunk.bin; sha256sum /tmp/houji-adrenometal-chunk.bin').split()[:2] == [str(CHUNK).encode(), expected.encode()]
            identity()
            current = root(f'set -e -o pipefail; /tmp/houji-root-chunk-read {i} | sha256sum').split()[0].decode()
            assert current == live[i]
            record({'phase': 'write-intent', 'index': i, 'before': current, 'after': expected})
            root(f'set -e; dd if=/tmp/houji-adrenometal-chunk.bin of=/dev/block/by-name/userdata bs=4096 seek={i*32768} count=32768 conv=notrunc,fsync status=none; sync')
            assert root(f'set -e -o pipefail; /tmp/houji-root-chunk-read {i} | sha256sum').split()[0].decode() == expected
            record({'phase': 'verified', 'index': i, 'sha256': expected})
            print(f'Chunk {i}: direct readback PASS', flush=True)
    assert live_index() == [row[target] for row in plan['chunks']]
    critical()
    identity()
    assert root('cat /dev/block/by-name/misc') == misc
    root('rm -f /tmp/houji-adrenometal-chunk.bin')
    stage.unlink(missing_ok=True)
    report = {'status': 'PASS', 'direction': target, 'full_96_chunk_readback_matches': True,
        'boot_and_gpt_unchanged': True, 'misc_unchanged': True, 'changed_chunks': plan['changed_chunks'],
        'immutable_preimage': plan['before_image'], 'expected_root_sha256': plan[target + '_sha256'],
        'plan_sha256': args.expected_plan_sha256, 'probe_only': False, 'desktop_selected': True}
    (D / ('rollback-result.json' if args.rollback else 'install-result.json')).write_text(json.dumps(report, indent=2) + '\n')
    record(report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
