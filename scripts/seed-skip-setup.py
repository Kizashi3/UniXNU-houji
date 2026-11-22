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
    # ios-sweet's proven first-boot list plus the activation daemon: SpringBoard
    # blocks in a synchronous MobileActivation XPC that never answers while the
    # daemon traps on every request.
    'com.apple.identityservicesd',
    'com.apple.locationd',
    'com.apple.CommCenter',
    'com.apple.iconservices.iconservicesagent',
    'com.apple.mobileactivationd',
)
# A diagnostic build can replace the whole list, e.g. keep the proven entries
# and add one job to attribute a boot behaviour to it.
_override = os.environ.get('HOUJI_DISABLED')
if _override:
    DISABLED = tuple(x.strip() for x in _override.split(',') if x.strip())

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
    # iOS keeps the system-preference domain at /private/var/preferences and some
    # consumers copy the any-user value only; keep both copies identical so the
    # per-user file and the system file never disagree.
    anyuser = root / 'preferences'
    if anyuser.is_dir():
        tgt = anyuser / (name + '.plist')
        tgt.write_bytes(plistlib.dumps(data, fmt=plistlib.FMT_BINARY))
        os.chmod(tgt, 0o644)
        os.chown(tgt, 0, 0)


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
        # mobileactivationd keeps its state in a data ark inside its system data
        # container. Without one it traps on every request and SpringBoard's
        # synchronous MobileActivation call never returns.
        ark_uuid = '3F2A9C1E-5B7D-4A62-9E10-8C4D6B2F77A1'
        ark = mount / 'containers' / 'Data' / 'System' / ark_uuid
        internal = ark / 'Library' / 'internal'
        internal.mkdir(parents=True, exist_ok=True)
        meta = ark / '.com.apple.mobile_container_manager.metadata.plist'
        meta.write_bytes(plistlib.dumps({
            'MCMMetadataIdentifier': 'com.apple.mobileactivationd',
            'MCMMetadataUUID': ark_uuid,
            'MCMMetadataContentClass': 1,
            'MCMMetadataSchemaVersion': 1,
        }, fmt=plistlib.FMT_BINARY))
        (internal / 'data_ark.plist').write_bytes(plistlib.dumps({
            '-ActivationState': 'Activated',
            '-BrickState': False,
            '-BuildVersion': BUILD,
            '-ProductVersion': '16.7.16',
            '-DataMigrationCompleted': True,
            '-PreSydroDataMigrationCompleted': True,
        }, fmt=plistlib.FMT_BINARY))
        for d in (ark, ark / 'Library'):
            os.chmod(d, 0o755)
            os.chown(d, 0, 0)
        os.chmod(internal, 0o755)
        os.chown(internal, MOBILE, MOBILE)
        os.chmod(meta, 0o644)
        os.chown(meta, 0, 0)
        os.chmod(internal / 'data_ark.plist', 0o600)
        os.chown(internal / 'data_ark.plist', MOBILE, MOBILE)
        print('activation ark', ark_uuid)

        if os.environ.get('HOUJI_PROBE_AGENT') == '1':
            # A user LaunchAgent that answers questions through the kernel console
            # ring, which is the only channel we can read back from Linux.
            la = mount / 'mobile/Library/LaunchAgents'
            la.mkdir(parents=True, exist_ok=True)
            cmd = ('sleep 60; { echo HOUJI-PROBE-BEGIN; id; '
                   'ls -l /private/var/preferences; '
                   'ls -l /private/var/mobile/Library/LaunchAgents; '
                   'launchctl list | head -140; echo HOUJI-PROBE-END; } > /dev/console 2>&1')
            tgt = la / 'com.houji.probe.plist'
            tgt.write_bytes(plistlib.dumps({'Label': 'com.houji.probe',
                'ProgramArguments': ['/bin/sh', '-c', cmd],
                'RunAtLoad': True, 'UserName': 'mobile'}, fmt=plistlib.FMT_XML))
            os.chmod(tgt, 0o644)
            os.chown(tgt, MOBILE, MOBILE)
            print('probe agent installed')

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
