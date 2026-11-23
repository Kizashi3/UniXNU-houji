#!/usr/bin/env python3
"""Replay an unchanged, captured desktop image with separately archived logs.

The fixed log marker must reuse the UUID compiled into that exact image.
Reset only the existing FAT file through its mounted filesystem; never restore
a raw partition. The original image/metadata checks and boot preflight remain.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import uuid

P = Path(__file__).resolve().parents[1]
N = Path('${HOUJI_ARTIFACTS}/native-port')
ADB = '${USER_HOME}/Library/Android/sdk/platform-tools/adb'
HELPER_SHA = '716048584c1c6e85e64335e9528704f0e80c46a893f0e3e5d723bb3bd778b6a0'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=int, required=True)
    parser.add_argument('--attempt', type=int, required=True)
    parser.add_argument('--adb-port', type=int, choices=(5037, 5038, 5047), required=True)
    parser.add_argument('--boot-only', action='store_true', help='Resume a verified local replay preparation')
    args = parser.parse_args()
    require(182 <= args.run <= 999 and 2 <= args.attempt <= 99, 'Invalid desktop replay identity')
    c = N / 'native-ios-candidate'
    name = f'r{args.run}-attempt{args.attempt}'
    directory = N / 'evidence' / ('replay-' + name)
    receipt = directory / 'preparation.json'
    allocation = json.loads((c / f'r{args.run}-allocation/layout.json').read_text())
    policy = json.loads((c / f'r{args.run}-policy.json').read_text())
    # Use the same frozen preflight that belonged to this image, even after
    # a later experiment has updated the working tree's POLICY assignment.
    boot = module('replay_boot', c / f'r{args.run}-source/scripts/try-native-userland-boot.py')
    require(boot.POLICY == policy, 'Frozen preflight policy differs')
    original_image = N / f'images/houji-native-ios-r{args.run}.img'
    original_meta = json.loads(original_image.with_suffix('.json').read_text())
    original_backup = (N / f'logfs-backup-before-native-ios-r{args.run}/logfs.bin').read_bytes()
    original_validate = boot.validate_metadata
    original_validate(original_meta, original_image.read_bytes(), original_backup)
    require(allocation['run_id'] == policy['log_run_id'], 'Compiled run ID differs')
    initial = (c / f'r{args.run}-allocation/XnuLog.initial.bin').read_bytes()
    require(sha(initial) == policy['log_initial_sha256'], 'Original compiled marker differs')

    def root(command):
        result = subprocess.run([ADB, '-P', str(args.adb_port), '-s', 'DEVICE_SERIAL', 'exec-out', command],
                                capture_output=True, timeout=30)
        require(result.returncode == 0 and not result.stderr and result.stdout,
                'Recovery read/operation failed: ' + command)
        return result.stdout

    require(root('id -u; getprop ro.product.device; getprop ro.houji.native_rescue').splitlines() ==
            [b'0', b'houji', b'1'], 'Verified recovery required')
    require(not any(row.split()[1] == b'/data' for row in root('cat /proc/mounts').splitlines()),
            'userdata unexpectedly mounted')
    # Recovery tmpfs is fresh after a reboot. Stage the same pinned read-only
    # helper when absent; never replace an unknown executable already there.
    helper = N / 'native-log-candidate/logfs-direct-read'
    require(sha(helper.read_bytes()) == HELPER_SHA, 'Local read-only helper differs')
    exists = root('if [ -e /tmp/houji-logfs-read ]; then echo PRESENT; else echo ABSENT; fi').strip()
    if exists == b'ABSENT':
        subprocess.run([ADB, '-P', str(args.adb_port), '-s', 'DEVICE_SERIAL', 'push',
                        str(helper), '/tmp/houji-logfs-read'], check=True, capture_output=True, timeout=30)
        root('chmod 755 /tmp/houji-logfs-read; echo READY')
    else:
        require(exists == b'PRESENT', 'Unexpected helper existence response')
    require(root('sha256sum /tmp/houji-logfs-read').split() ==
            [HELPER_SHA.encode(), b'/tmp/houji-logfs-read'], 'Remote read-only helper differs')
    allocator = module('replay_allocator', P / 'scripts/prepare-xnu-log.py')
    reader = module('replay_reader', P / 'scripts/capture-logfs.py')
    protected = {}

    def check_protected():
        for partition, expected in boot.BOOT.items():
            require(root('sha256sum /dev/block/by-name/' + partition).split() ==
                    [expected.encode(), ('/dev/block/by-name/' + partition).encode()],
                    'Protected boot changed: ' + partition)
        for disk in json.loads((N / 'partition-backup-20261024/manifest.json').read_text())['disks']:
            for kind, skip in (('primary', 0), ('backup', disk['backup_start_lba'])):
                expected = boot.expected_gpt(disk, kind)
                require(root(f'dd if={disk["device"]} bs=4096 skip={skip} count={len(expected)//4096} status=none') == expected,
                        'Protected GPT changed')
        misc = root('cat /dev/block/by-name/misc')
        baseline = (N / f'device-baseline/misc-before-native-ios-r{args.run}.bin').read_bytes()
        require(len(misc) == len(baseline) == 4194304 and misc[864:] == baseline[864:],
                'misc reserved/A-B changed')
        if protected:
            require(sha(misc) == protected['misc_sha256'], 'misc changed during preparation')
        protected['misc_sha256'] = sha(misc)

    if not args.boot_only:
        require(not directory.exists(), 'Replay directory exists; retain it and use --boot-only only when prepared')
        directory.mkdir(parents=True, mode=0o700)
        state = {'run': args.run, 'attempt': args.attempt, 'status': 'INCOMPLETE_DO_NOT_BOOT',
                 'image_sha256': sha(original_image.read_bytes()), 'recompilation': False,
                 'raw_partition_restore': False, 'compiled_run_id_reused_explicitly': policy['log_run_id']}
        receipt.write_text(json.dumps(state, indent=2) + '\n')
        capture = N / f'evidence/logfs-recovery-r{args.run}'
        archived = (capture / 'XnuLog.bin').read_bytes()
        integrity, _ = reader.decode_xnu_snapshot(archived, policy['log_run_id'])
        require(integrity.get('valid') and integrity.get('committed'), 'Archived committed log required')
        native = (capture / 'UniXNU.log').read_bytes()
        require(reader.verify_native_snapshot(native).get('valid'), 'Archived native log checksum invalid')
        require(root('cat /dev/logfs/XnuLog.bin') == archived and root('cat /dev/logfs/UniXNU.log') == native,
                'Current logs differ from archived run; capture first')
        check_protected()
        require(root('sha256sum /tmp/houji-logfs-read').split() == [HELPER_SHA.encode(), b'/tmp/houji-logfs-read'],
                'Pinned read-only direct helper absent/different')
        raw = root('/tmp/houji-logfs-read')
        require(len(raw) == 8388608 and raw == root('/tmp/houji-logfs-read'), 'Unstable FAT backup')
        before_layout = allocator.layout(raw)
        keys = ('clusters', 'lbas', 'file_bytes', 'physical_lun', 'short_name')
        require(all(before_layout[k] == allocation[k] for k in keys), 'Compiled log allocation moved')
        (directory / 'logfs-before.bin').write_bytes(raw)
        # The allocator normally generates a new UUID. Here the human asked
        # to rerun the same compiled image, so pin its marker explicitly.
        previous_uuid, previous_argv = allocator.uuid.uuid4, sys.argv
        try:
            allocator.uuid.uuid4 = lambda: uuid.UUID(hex=policy['log_run_id'])
            sys.argv = [str(P / 'scripts/prepare-xnu-log.py'), '--adb-port', str(args.adb_port),
                        '--recovery', '--reuse-sha256', sha(archived), '--output', str(directory / 'allocation'),
                        '--header', str(directory / 'HoujiLogAllocation.h')]
            allocator.main()
        finally:
            allocator.uuid.uuid4, sys.argv = previous_uuid, previous_argv
            readonly = subprocess.run([ADB, '-P', str(args.adb_port), '-s', 'DEVICE_SERIAL', 'exec-out',
                                       'mount -o remount,ro /dev/logfs'], capture_output=True, timeout=30)
            require(readonly.returncode == 0 and not readonly.stderr, 'Could not return FAT mount to read-only')
        require((directory / 'allocation/XnuLog.initial.bin').read_bytes() == initial and
                (directory / 'HoujiLogAllocation.h').read_bytes() ==
                (c / f'r{args.run}-allocation/HoujiLogAllocation.h').read_bytes(),
                'Replayed marker/header is not byte-identical to compiled allocation')
        coordinator = module('replay_bounds', P / 'scripts/prepare-xnu-runtime-trial.py')
        coordinator.validate_in_place(raw, (directory / 'allocation/logfs-after.bin').read_bytes(), before_layout)
        require(root('cat /dev/logfs/UniXNU.log') == native, 'Native log changed before archived deletion')
        result = subprocess.run([ADB, '-P', str(args.adb_port), '-s', 'DEVICE_SERIAL', 'exec-out',
            'set -e; mount -o remount,rw /dev/logfs; rm /dev/logfs/UniXNU.log; sync; mount -o remount,ro /dev/logfs'],
            capture_output=True, timeout=30)
        require(result.returncode == 0 and not result.stderr, 'Archived native log deletion failed')
        fresh = root('/tmp/houji-logfs-read')
        require(fresh == root('/tmp/houji-logfs-read') and len(fresh) == 8388608, 'Fresh FAT backup unstable')
        require(all(allocator.layout(fresh)[k] == allocation[k] for k in keys) and
                root('cat /dev/logfs/XnuLog.bin') == initial, 'Compiled marker/allocation changed')
        (directory / 'logfs-ready.bin').write_bytes(fresh)
        check_protected()
        state.update(status='PREPARED_FOR_BYTE_IDENTICAL_REPLAY', fresh_backup_sha256=sha(fresh),
                     original_backup_sha256=sha(original_backup), protected=protected,
                     previous_capture=str(capture), prepared_at=datetime.datetime.now().astimezone().isoformat())
        receipt.write_text(json.dumps(state, indent=2) + '\n')

    state = json.loads(receipt.read_text())
    fresh = (directory / 'logfs-ready.bin').read_bytes()
    require(state['status'] == 'PREPARED_FOR_BYTE_IDENTICAL_REPLAY' and
            state['image_sha256'] == sha(original_image.read_bytes()) and sha(fresh) == state['fresh_backup_sha256'],
            'Replay receipt/image/backup binding differs')
    label = f'native-ios-r{args.run}-attempt{args.attempt}'
    image = N / f'images/houji-{label}.img'
    if not image.exists():
        subprocess.run(['/bin/cp', '-c', str(original_image), str(image)], check=True)
        image.with_suffix('.json').write_bytes(original_image.with_suffix('.json').read_bytes())
    require(image.read_bytes() == original_image.read_bytes() and
            image.with_suffix('.json').read_bytes() == original_image.with_suffix('.json').read_bytes(),
            'Replay image/metadata differs from original')

    def validate(meta, data, backup):
        original_validate(meta, data, original_backup)
        require(backup == fresh, 'Replay fresh FAT backup differs')

    old_watch_spec = boot.recovery_watch_spec

    def watch_spec(actual_label, port, run_id):
        require(actual_label == label and run_id == policy['log_run_id'], 'Replay watcher identity differs')
        return old_watch_spec(f'native-ios-r{args.run}', port, run_id, evidence=directory)

    boot.validate_metadata = validate
    boot.recovery_watch_spec = watch_spec
    sys.argv = [str(boot.__file__), '--image', str(image), '--label', label,
                '--adb-port', str(args.adb_port), '--backup', str(directory / 'logfs-ready.bin')]
    boot.main()


if __name__ == '__main__':
    main()
