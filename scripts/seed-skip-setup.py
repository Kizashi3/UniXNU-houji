#!/usr/bin/env python3
"""Seed the Data volume so iOS boots to SpringBoard instead of Setup.

macOS only: copies the raw APFS seed, attaches the copy read-write with
hdiutil, merges the Setup/SpringBoard preferences into mobile/Library/
Preferences, creates the container directories and the launchd disabled
override, then detaches. The volume UUID is unchanged.

usage: seed-skip-setup.py BASE.cdr OUTPUT.cdr [--keep-services] [--preserve-services] [--gpu-probe-dir DIR] [--launchdaemons-dir DIR]

--keep-services removes the launchd disabled override.
--preserve-services leaves the base seed's disabled override unchanged.
--gpu-probe-dir stages vktest and libvulkan_freedreno.dylib plus a launchd job.
--launchdaemons-dir supplies the complete system LaunchDaemons directory for the bind mount.
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


def mark_platform_binary(path):
    subprocess.run(['codesign', '--force', '--sign', '-', '--timestamp=none', str(path)], check=True)
    from hashlib import sha256
    from struct import pack_into, unpack_from

    data = bytearray(path.read_bytes())
    commands = unpack_from('<I', data, 16)[0]
    offset = 32
    signature = None
    for _ in range(commands):
        command, size = unpack_from('<II', data, offset)
        if command == 0x1d:
            signature = unpack_from('<II', data, offset + 8)
        offset += size
    if signature is None:
        subprocess.run(['codesign', '--force', '--sign', '-', '--timestamp=none', str(path)], check=True)
        data = bytearray(path.read_bytes())
        commands = unpack_from('<I', data, 16)[0]
        offset = 32
        for _ in range(commands):
            command, size = unpack_from('<II', data, offset)
            if command == 0x1d:
                signature = unpack_from('<II', data, offset + 8)
            offset += size
    if signature is None:
        raise ValueError(f'{path}: no code signature')
    data_offset, _ = signature
    count = unpack_from('>I', data, data_offset + 8)[0]
    changed = 0
    for index in range(count):
        entry_type, relative = unpack_from('>II', data, data_offset + 12 + index * 8)
        if entry_type != 0:
            continue
        directory = data_offset + relative
        flags = unpack_from('>I', data, directory + 12)[0]
        pack_into('>I', data, directory + 12, flags | 0x04000000)
        changed += 1
    if not changed:
        raise ValueError(f'{path}: no code directory')
    path.write_bytes(data)
    cdhash = None
    for index in range(count):
        entry_type, relative = unpack_from('>II', data, data_offset + 12 + index * 8)
        if entry_type == 0:
            directory = data_offset + relative
            cd_len = unpack_from('>I', data, directory + 4)[0]
            cdhash = sha256(data[directory:directory + cd_len]).hexdigest()[:40]
            break
    print('platform binary', path.name, sha256(data).hexdigest(), 'cdhash', cdhash)
    return cdhash


def stage_gpu_probe(root, probe_dir, launchd_dir, extensions_dir=None, cdhash_out=None):
    ngpu = root / 'ngpu'
    bin_dir = ngpu / 'bin'
    launchd_out = ngpu / 'launchd'
    bin_dir.mkdir(parents=True, exist_ok=True)
    launchd_out.mkdir(parents=True, exist_ok=True)
    cdhashes = []

    bundle_src = probe_dir / 'NativeAdrenoMetal.bundle'
    has_metal = bundle_src.is_dir()

    for name in ('vktest', 'libvulkan_freedreno.dylib'):
        source = (bundle_src / name) if (has_metal and name == 'libvulkan_freedreno.dylib' and (bundle_src / name).is_file()) else (probe_dir / name)
        if not source.is_file():
            continue
        target = bin_dir / name if name == 'vktest' else ngpu / name
        shutil.copy2(source, target)
        cdh = mark_platform_binary(target)
        cdhashes.append((cdh, name))
        os.chmod(target, 0o755)
        os.chown(target, 0, 0)

    if has_metal:
        mtl_src = probe_dir / 'mtltest'
        if mtl_src.is_file():
            mtl_dst = bin_dir / 'mtltest'
            shutil.copy2(mtl_src, mtl_dst)
            cdh = mark_platform_binary(mtl_dst)
            cdhashes.append((cdh, 'mtltest'))
            os.chmod(mtl_dst, 0o755)
            os.chown(mtl_dst, 0, 0)

        addons = ngpu / 'addons'
        addons.mkdir(parents=True, exist_ok=True)
        if extensions_dir and Path(extensions_dir).is_dir():
            shutil.copytree(extensions_dir, addons, symlinks=True, dirs_exist_ok=True)
        bundle_dst = addons / 'NativeAdrenoMetal.bundle'
        if bundle_dst.exists():
            shutil.rmtree(bundle_dst)
        shutil.copytree(bundle_src, bundle_dst, symlinks=True)
        for bname in ('NativeAdrenoMetal', 'libvulkan_freedreno.dylib'):
            bp = bundle_dst / bname
            if bp.is_file():
                cdh = mark_platform_binary(bp)
                cdhashes.append((cdh, 'NativeAdrenoMetal.bundle/' + bname))
                os.chmod(bp, 0o755)
                os.chown(bp, 0, 0)
        info_p = bundle_dst / 'Info.plist'
        if info_p.is_file():
            os.chmod(info_p, 0o644)
            os.chown(info_p, 0, 0)
        clients = addons / 'NativeAdrenoMetal.clients'
        clients.write_text('backboardd\nSpringBoard\niconservicesagent\nPosterBoard\nSBRendererService\nAegirPoster\nCollectionsPoster\nPhotosPosterProvider\nGradientPosterExtension\nEmojiPosterExtension\nExtragalacticPoster\nPridePosterExtension\nMobileSlideShow\nPreferences\nvktest\nmtltest\n', encoding='utf-8')
        os.chmod(clients, 0o644)
        os.chown(clients, 0, 0)
        for d in (addons, bundle_dst):
            os.chmod(d, 0o755)
            os.chown(d, 0, 0)
        print('metal bundle staged in', addons, 'entries:', len(list(addons.iterdir())))

    if cdhash_out:
        seen = set()
        lines = []
        for cdh, label in cdhashes:
            if cdh and cdh not in seen:
                seen.add(cdh)
                lines.append(f'{cdh}  {label}\n')
        Path(cdhash_out).write_text(''.join(lines), encoding='utf-8')
        print('wrote platform cdhashes:', len(lines), '->', cdhash_out)

    shutil.copytree(launchd_dir, launchd_out, symlinks=True, dirs_exist_ok=True)
    prog_args = ['/private/var/ngpu/bin/vktest'] if has_metal else [
        '/private/var/ngpu/bin/vktest',
        '/private/var/ngpu/libvulkan_freedreno.dylib',
    ]
    plist = {
        'Label': 'com.houji.vktest',
        'ProgramArguments': prog_args,
        'EnvironmentVariables': {
            'TU_DARWIN_SERVICE': 'IOAcceleratorES',
            'TU_DARWIN_OPEN_TYPE': '0x4147',
            'TU_DEBUG': 'sysmem,nocb',
        },
        'RunAtLoad': False,
        'KeepAlive': False,
        'ThrottleInterval': 30,
        'StandardOutPath': '/dev/console',
        'StandardErrorPath': '/dev/console',
    }
    job = launchd_out / 'com.houji.vktest.plist'
    job.write_bytes(plistlib.dumps(plist, fmt=plistlib.FMT_BINARY))
    for directory, dirnames, filenames in os.walk(launchd_out):
        os.chmod(directory, 0o755)
        os.chown(directory, 0, 0)
        for name in filenames:
            path = Path(directory) / name
            if not path.is_symlink():
                os.chmod(path, 0o644)
                os.chown(path, 0, 0)
    os.chmod(job, 0o644)
    os.chown(job, 0, 0)
    print('gpu probe staged', len(list(launchd_out.iterdir())), 'launchd entries')


def main():
    args = [x for x in sys.argv[1:] if x not in ('--keep-services', '--preserve-services')]
    keep_services = '--keep-services' in sys.argv[1:]
    preserve_services = '--preserve-services' in sys.argv[1:]
    if keep_services and preserve_services:
        sys.exit('--keep-services and --preserve-services are mutually exclusive')
    probe_dir = None
    launchd_dir = None
    extensions_dir = None
    cdhash_out = None
    if '--gpu-probe-dir' in args:
        index = args.index('--gpu-probe-dir')
        probe_dir = Path(args[index + 1]).resolve()
        del args[index:index + 2]
        # Override with latest metal-ios16-15 release (sudo strips GITHUB_ACTIONS)
        tag_override = 'metal-ios16-22'
        if tag_override:
            import tarfile, urllib.request
            url = f'https://github.com/Kizashi3/UniXNU-houji/releases/download/{tag_override}/houji-metal-ios16.tar.gz'
            tb = probe_dir.parent / 'houji-metal-ios16-override.tar.gz'
            print(f'Overriding gpu-probe-dir with {url}', flush=True)
            urllib.request.urlretrieve(url, tb)
            shutil.rmtree(probe_dir)
            probe_dir.mkdir(parents=True, exist_ok=True)
            with tarfile.open(tb, 'r:gz') as tf:
                tf.extractall(probe_dir)
    if '--launchdaemons-dir' in args:
        index = args.index('--launchdaemons-dir')
        launchd_dir = Path(args[index + 1]).resolve()
        del args[index:index + 2]
    if '--extensions-dir' in args:
        index = args.index('--extensions-dir')
        extensions_dir = Path(args[index + 1]).resolve()
        del args[index:index + 2]
    if '--cdhash-out' in args:
        index = args.index('--cdhash-out')
        cdhash_out = Path(args[index + 1]).resolve()
        del args[index:index + 2]
    if bool(probe_dir) != bool(launchd_dir):
        sys.exit('--gpu-probe-dir and --launchdaemons-dir must be used together')
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
        # Force 8-bit BGRA8 framebuffer in backboardd so SweetDisplay copies match the 8-bit panel format
        merge_pref(mount, 'com.apple.backboardd', {
            'CAEnableDeepFramebuffer': False,
        })
        merge_pref(mount, '.GlobalPreferences', {
            'CAEnableDeepFramebuffer': False,
        })
        root_pref = mount / 'root/Library/Preferences/com.apple.backboardd.plist'
        root_pref.parent.mkdir(parents=True, exist_ok=True)
        root_pref.write_bytes(plistlib.dumps({'CAEnableDeepFramebuffer': False}, fmt=plistlib.FMT_BINARY))
        os.chmod(root_pref, 0o644)
        os.chown(root_pref, 0, 0)
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
        for ark_uuid in ('3F2A9C1E-5B7D-4A62-9E10-8C4D6B2F77A1', '62339402-23CD-44D6-A850-53E6216F1EBC1'):
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
            for d in (ark, ark / 'Library', internal):
                os.chmod(d, 0o755)
                os.chown(d, MOBILE, MOBILE)
            os.chmod(meta, 0o644)
            os.chown(meta, 0, 0)
            os.chmod(internal / 'data_ark.plist', 0o600)
            os.chown(internal / 'data_ark.plist', MOBILE, MOBILE)
            print('activation ark', ark_uuid)

        if probe_dir:
            stage_gpu_probe(mount, probe_dir, launchd_dir, extensions_dir, cdhash_out)

        db = mount / 'db/com.apple.xpc.launchd'
        db.mkdir(parents=True, exist_ok=True)
        if keep_services:
            stale = db / 'disabled.plist'
            if stale.exists():
                stale.unlink()
            print('services kept complete')
        elif preserve_services:
            print('services preserved from base seed')
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
