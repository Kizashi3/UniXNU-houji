#!/usr/bin/env python3
"""Verify the known houji baseline, then use only fastboot boot on that device."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import time

ARTIFACTS = Path('${HOUJI_ARTIFACTS}/native-port')
TOOLS = Path('${USER_HOME}/Library/Android/sdk/platform-tools')
SERIAL = 'DEVICE_SERIAL'
LOGFS_POLICY = {
    'kind': 'logfs-file-create', 'physical_lun': 0, 'block_bytes': 4096,
    'first_lba': 4096, 'end_lba_exclusive': 6144, 'file': 'UniXNU.log',
    'existing_file': 'refuse', 'max_text_bytes': 131072,
    'backup_sha256': '81ecc867395a3757f5644321668e7084f3ee944d65ff38ac15665d0ca77444ab',
}
NATIVE_READ_POLICY = {'kind': 'gpt-read-only', 'physical_lun': 0,
    'first_lba': 1, 'end_lba_exclusive': 4, 'media_writes': False,
    'publishes_root_media': False,
    'kernel_sha256': 'b10bb1c267b7a06961ac386e64f4d2c93a2715053563039fa6ccb8dde4139558'}
NATIVE_LOG_POLICY = {'kind': 'fixed-fat-file-data', 'physical_lun': 0,
    'file': 'XnuLog.bin', 'file_bytes': 65536,
    'data_lbas': list(range(4170, 4186)), 'metadata_read_lbas': [4096, 4103],
    'run_id': 'ce304c0b298341848bf514b7187fc451',
    'initial_sha256': 'dd3441b05193d539323faa5924bca07048031d229b300f73fb85b6e72ca2e3b4',
    'kernel_sha256': '5f79e2e671473aedca5d684b375ecb722d2a5ebf744414b51f554ec53e2da6a7',
    'media_writes': True, 'fat_metadata_writes': False, 'publishes_root_media': False}
STATE = ('id; getprop ro.boot.slot_suffix; getprop ro.build.version.incremental; '
         'getprop ro.boot.vbmeta.digest; '
         'for p in boot_a init_boot_a vendor_boot_a recovery_a vbmeta_a; '
         'do sha256sum /dev/block/by-name/$p; done')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image', type=Path, required=True)
    p.add_argument('--label', required=True)
    p.add_argument('--adb-port', type=int, required=True)
    a = p.parse_args()
    if not re.fullmatch(r'[a-z0-9-]+', a.label) or a.adb_port not in (5037, 5038, 5047):
        raise ValueError('Unexpected trial label or ADB port')
    metadata = json.loads(a.image.with_suffix('.json').read_text())
    storage_profile_ok = (metadata['physical_storage_drivers'] is False or
                          (metadata['physical_storage_drivers'] is True and
                           metadata.get('test_scope') == 'uefi-oem-ufs-readonly-preflight') or
                          (metadata['physical_storage_drivers'] is True and
                           metadata.get('test_scope') == 'uefi-logfs-file-write-test' and
                           metadata.get('storage_write_policy') == LOGFS_POLICY) or
                          (metadata['physical_storage_drivers'] is True and
                           metadata.get('test_scope') == 'xnu-native-ufs-gpt-read-probe' and
                           metadata.get('storage_write_policy') == LOGFS_POLICY and
                           metadata.get('native_storage_policy') == NATIVE_READ_POLICY))
    storage_profile_ok = storage_profile_ok or (
        metadata['physical_storage_drivers'] is True and
        metadata.get('test_scope') == 'xnu-native-fixed-log-test' and
        metadata.get('storage_write_policy') == LOGFS_POLICY and
        metadata.get('native_storage_policy') == NATIVE_LOG_POLICY)
    if (metadata['device'] != 'houji' or not storage_profile_ok
            or metadata['usage'] != 'fastboot boot only'
            or hashlib.sha256(a.image.read_bytes()).hexdigest() != metadata['sha256']['image']):
        raise ValueError('Boot image provenance differs')
    log = ARTIFACTS / (a.label + '-trial.jsonl')

    def run(args, timeout=30):
        args = list(map(str, args))
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        with log.open('a') as stream:
            stream.write(json.dumps({'time': datetime.datetime.now().astimezone().isoformat(),
                                    'args': args, 'returncode': result.returncode,
                                    'stdout': result.stdout, 'stderr': result.stderr}) + '\n')
        if result.returncode:
            raise RuntimeError(result.stderr)
        return result.stdout + result.stderr

    if metadata.get('test_scope') in ('uefi-logfs-file-write-test', 'xnu-native-ufs-gpt-read-probe', 'xnu-native-fixed-log-test'):
        backup = ARTIFACTS / 'logfs-backup-before-native-log-r25-final/logfs.bin'
        if len(backup.read_bytes()) != 8388608 or hashlib.sha256(backup.read_bytes()).hexdigest() != LOGFS_POLICY['backup_sha256']:
            raise RuntimeError('Verified logfs backup is absent or differs')
        identity = run([TOOLS / 'adb', '-P', a.adb_port, '-s', SERIAL, 'shell',
            '/debug_ramdisk/su -c ' + shlex.quote(
                'id -u; getprop ro.product.device; readlink -f /dev/block/by-name/logfs; '
                'blockdev --getsize64 /dev/block/by-name/logfs; '
                'if [ -e /dev/logfs/UniXNU.log ]; then echo EXISTS; else echo ABSENT; fi')])
        expected = ['0', 'houji', '/dev/block/sda13', '8388608', 'ABSENT']
        if identity.splitlines() != expected:
            raise RuntimeError('Logfs identity changed, file exists, or fresh backup is required')
        # Mounted FAT writes may leave the raw block page cache stale. The fixed
        # helper opens O_RDONLY|O_DIRECT and refuses any device except sda13.
        direct = subprocess.run([str(TOOLS / 'adb'), '-P', str(a.adb_port), '-s', SERIAL,
             'exec-out', '/debug_ramdisk/su -c /data/local/tmp/houji-logfs-read'],
             capture_output=True, check=True, timeout=30)
        digest = hashlib.sha256(direct.stdout).hexdigest()
        if direct.stderr or len(direct.stdout) != 8388608 or digest != LOGFS_POLICY['backup_sha256']:
            raise RuntimeError('Direct on-media logfs bytes differ from verified backup')
        if metadata.get('test_scope') == 'xnu-native-fixed-log-test':
            actual = run([TOOLS / 'adb', '-P', a.adb_port, '-s', SERIAL, 'shell',
                 '/debug_ramdisk/su -c ' + shlex.quote('sha256sum /dev/logfs/XnuLog.bin')])
            if actual.split() != [NATIVE_LOG_POLICY['initial_sha256'], '/dev/logfs/XnuLog.bin']:
                raise RuntimeError('Native log initial file changed')
    state = run([TOOLS / 'adb', '-P', a.adb_port, '-s', SERIAL, 'shell',
                 '/debug_ramdisk/su -c ' + shlex.quote(STATE)])
    if state != (ARTIFACTS / 'device-baseline/bootstate-before-xnu-r1.txt').read_text():
        raise RuntimeError('Android baseline changed; boot aborted')
    (ARTIFACTS / 'device-baseline' / ('bootstate-before-' + a.label + '.txt')).write_text(state)
    print('Android baseline unchanged; rebooting bootloader.', flush=True)
    run([TOOLS / 'adb', '-P', a.adb_port, '-s', SERIAL, 'reboot', 'bootloader'])
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if SERIAL in run([TOOLS / 'fastboot', 'devices']):
            break
        time.sleep(0.5)
    else:
        raise RuntimeError('Fastboot not found within 45 seconds')
    if 'product: houji' not in run([TOOLS / 'fastboot', '-s', SERIAL, 'getvar', 'product']):
        raise RuntimeError('Device product differs')
    print(run([TOOLS / 'fastboot', '-s', SERIAL, 'boot', a.image], 60), flush=True)


if __name__ == '__main__':
    main()
