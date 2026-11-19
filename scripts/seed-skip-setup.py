#!/usr/bin/env python3
"""Seed the Data volume so iOS boots to SpringBoard instead of Setup.

macOS only: copies the raw APFS seed, attaches the copy read-write with
hdiutil, merges the Setup/SpringBoard preferences into mobile/Library/
Preferences, creates the container directories and the launchd disabled
override, then detaches. The volume UUID is unchanged.

usage: seed-skip-setup.py BASE.cdr OUTPUT.cdr [--keep-services]

--keep-services keeps every launchd service enabled (no disabled.plist), so the
Data seed ships the same service set as the OS image it was built from.
"""
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

BUILD = '20H392'
MOBILE = 501
DISABLED = (
    # watchdogd is the one job that has to stay out of the boot: it asserts about
    # checked-in daemons long before data migration finishes and takes the whole
    # system down with panic-on-crash.
    'com.apple.watchdogd',
    'com.apple.datamigrator',
)
MINI = (
    'ShouldRunDiagnosticsMiniBuddy',
    'ShouldRunHSA2MiniBuddy',
    'ShouldRunKeychainSyncMiniBuddy',
    'ShouldRunMesaMiniBuddy',
    'ShouldRunPaymentMiniBuddy',
    'ShouldRunStandardMiniBuddy',
    'SilentICDPUpgrade',
)


def merge_pref(root, name, values):
    path = root / 'mobile/Library/Preferences' / (name + '.plist')
    path.parent.mkdir(parents=True, exist_ok=True)
    data = plistlib.loads(path.read_bytes()) if path.exists() else {}
    data.update(values)
    path.write_bytes(plistlib.dumps(data, fmt=plistlib.FMT_BINARY))
    os.chmod(path, 0o600)
    # ios-sweet writes these as the mobile user; cfprefsd runs as mobile and
    # ignores a root-owned 0600 file it cannot read.
    os.chown(path, MOBILE, MOBILE)
    print('pref', name, sorted(values))


def main():
    args = [x for x in sys.argv[1:] if x != '--keep-services']
    keep_services = '--keep-services' in sys.argv[1:]
    if len(args) != 2:
        sys.exit(__doc__)
    src, dst = Path(args[0]).resolve(), Path(args[1]).resolve()
    if dst.exists():
        sys.exit('refuse to overwrite ' + str(dst))
    shutil.copyfile(src, dst)
    mount = Path('/tmp/houji-skip-setup-mnt')
    mount.mkdir(exist_ok=True)
    info = plistlib.loads(subprocess.check_output([
        'hdiutil', 'attach', '-imagekey', 'diskimage-class=CRawDiskImage',
        '-readwrite', '-nobrowse', '-owners', 'on',
        '-mountpoint', str(mount), '-plist', str(dst)]))
    device = info['system-entities'][0]['dev-entry']
    try:
        if not (mount / 'mobile').is_dir():
            sys.exit('the seed has no /mobile; wrong base image?')
        run_setup = os.environ.get('HOUJI_RUN_SETUP') == '1'
        if not run_setup:
            merge_pref(mount, 'com.apple.purplebuddy', {
                'SetupDone': True,
                'SetupFinishedAllSteps': True,
                'SetupVersion': 11,
                'daemonizeNeedsToRun': False,
            })
        else:
            print('setup left to run')
        merge_pref(mount, 'com.apple.purplebuddy.notbackedup',
                   {key: False for key in MINI})
        merge_pref(mount, 'com.apple.managedconfiguration.notbackedup', {
            'LockdownActivationIndicatesCloudConfigurationAvailable': False,
        })
        merge_pref(mount, 'com.apple.springboard', {
            'BKNoWatchdogs': True,
            'FBLaunchWatchdogExceptions': {'com.apple.purplebuddy': 100.0},
            'MCForceShowCloudConfigurationUI': False,
            'SBDisableAutoDim': True,
            'SBDontDimOrLockOnAC': True,
            'SBDisableIdleSleep': True,
        })
        # ios-sweet v12: claiming the current build is what stops the one-hour data
        # migration that runs on every boot. backboardd holds the system shell
        # check-in until migration returns, so a forced migration keeps SpringBoard
        # out of its UI forever.
        merge_pref(mount, 'com.apple.DataMigration', {'LastSystemVersion': BUILD})
        merge_pref(mount, 'com.apple.migration', {
            'LastSystemVersion': BUILD,
            'DMUserDataDisposition': {
                'SyntheticDidUpgrade': False,
                'buildVersion': BUILD,
            },
        })
        for sub in ('Bundle', 'Data/System', 'Shared/SystemGroup', 'Temp'):
            d = mount / 'containers' / sub
            d.mkdir(parents=True, exist_ok=True)
            os.chown(d, MOBILE, MOBILE)
        db = mount / 'db/com.apple.xpc.launchd'
        db.mkdir(parents=True, exist_ok=True)
        if keep_services:
            stale = db / 'disabled.plist'
            if stale.exists():
                stale.unlink()
            print('services kept complete')
        else:
            (db / 'disabled.plist').write_bytes(plistlib.dumps(
                {label: True for label in DISABLED}, fmt=plistlib.FMT_BINARY))
            print('disabled', list(DISABLED))
    finally:
        subprocess.run(['hdiutil', 'detach', device], check=True)
    data = dst.read_bytes()
    if data[32:36] != b'NXSB':
        sys.exit('the edited image is no APFS container any more')
    print('wrote', dst, len(data))


if __name__ == '__main__':
    main()
