#!/usr/bin/env python3
"""Seed the Data volume so iOS boots to SpringBoard instead of Setup.

macOS only: copies the raw APFS seed, attaches the copy read-write with
hdiutil, merges the Setup/SpringBoard preferences into mobile/Library/
Preferences, creates the container directories and the launchd disabled
override, then detaches. The volume UUID is unchanged.

usage: seed-skip-setup.py BASE.cdr OUTPUT.cdr
"""
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

BUILD = '20H392'
DISABLED = (
    'com.apple.identityservicesd',
    'com.apple.locationd',
    'com.apple.CommCenter',
    'com.apple.iconservices.iconservicesagent',
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
    print('pref', name, sorted(values))


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src, dst = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    if dst.exists():
        sys.exit('refuse to overwrite ' + str(dst))
    shutil.copyfile(src, dst)
    mount = Path('/tmp/houji-skip-setup-mnt')
    mount.mkdir(exist_ok=True)
    info = plistlib.loads(subprocess.check_output([
        'hdiutil', 'attach', '-imagekey', 'diskimage-class=CRawDiskImage',
        '-readwrite', '-nobrowse', '-owners', 'off',
        '-mountpoint', str(mount), '-plist', str(dst)]))
    device = info['system-entities'][0]['dev-entry']
    try:
        if not (mount / 'mobile').is_dir():
            sys.exit('the seed has no /mobile; wrong base image?')
        merge_pref(mount, 'com.apple.purplebuddy', {
            'SetupDone': True,
            'SetupFinishedAllSteps': True,
            'SetupVersion': 11,
            'daemonizeNeedsToRun': False,
        })
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
        merge_pref(mount, 'com.apple.migration', {
            'LastSystemVersion': BUILD,
            'DMUserDataDisposition': {
                'SyntheticDidUpgrade': False,
                'buildVersion': BUILD,
            },
        })
        for sub in ('Bundle', 'Data/System', 'Shared/SystemGroup', 'Temp'):
            (mount / 'containers' / sub).mkdir(parents=True, exist_ok=True)
        db = mount / 'db/com.apple.xpc.launchd'
        db.mkdir(parents=True, exist_ok=True)
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
