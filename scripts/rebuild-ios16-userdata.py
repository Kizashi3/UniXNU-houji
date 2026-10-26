"""Rebuild one raw userdata image from the verified local firmware base.

Uses the exact OS/SystemOS/AppOS content already assembled and verified on
macOS. Edits an isolated overlay, exports a new image, checks its filesystem,
and retains normal migration unless the user-selected baseline is requested.
No handset connection or flashing commands.
Setup is retained unless --skip-setup is selected for this new image.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess

from ios16_root_layout import DIRECTORIES, GuestRoot, MIGRATION, prepare_layout


def digest(path, native_python=None):
    if native_python:
        windows_path = subprocess.check_output(['wslpath', '-w', str(path)], text=True).strip()
        code = ('import hashlib,sys\nh=hashlib.sha256()\n'
                'with open(sys.argv[1],"rb") as f:\n'
                ' while b:=f.read(8*1024**2):h.update(b)\n'
                'print(h.hexdigest())')
        value = subprocess.check_output([str(native_python), '-c', code, windows_path], text=True).strip()
        if not re.fullmatch('[0-9a-f]{64}', value):
            raise ValueError('Invalid digest returned by native reader')
        return value
    state = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(8*1024**2):
            state.update(chunk)
    return state.hexdigest()


def volume_header(path):
    with path.open('rb') as stream:
        stream.seek(1024)
        data = stream.read(512)
    if data[:4] != b'HX\0\x05' or struct.unpack_from('>II', data, 40) != (4096, 4194304):
        raise ValueError('Unexpected HFSX volume or geometry')
    if struct.unpack_from('>I', data, 4)[0] & 0x2900 != 0x2100:
        raise ValueError('Expected a consistent, cleanly unmounted journaled HFSX volume')
    return data


def prepare_root(root, build, *, startup_compat=False, migration_baseline=False,
                 full_boot_log=False, skip_setup=False, cellular_policy=None,
                 modem_runtime=None, modem_adt=None):
    if full_boot_log and not migration_baseline:
        raise ValueError('--full-boot-log requires --migration-baseline')
    if cellular_policy == 'managed':
        from ios16_modem_apple import require_managed_contract
        if modem_runtime is None or modem_adt is None:
            raise ValueError('Managed cellular requires runtime contract and actual ADT bytes')
        require_managed_contract(modem_runtime, modem_adt)
    result = prepare_layout(root, build)
    if startup_compat:
        from ios16_startup_compat import prepare_startup
        result.update(prepare_startup(root, cellular_policy or 'disabled',
                                     runtime=modem_runtime, adt=modem_adt))
        result['scope'] = 'normal first-boot migration with explicit hardware startup compatibility'
    elif cellular_policy is not None:
        from ios16_startup_compat import prepare_cellular
        result.update(prepare_cellular(root, cellular_policy, runtime=modem_runtime, adt=modem_adt))
    if migration_baseline:
        from ios16_boot_baseline import prepare_baseline
        result.update(prepare_baseline(root, full_boot_log))
    from ios16_setup import prepare_setup
    result.update(prepare_setup(root, skip_setup))
    if skip_setup:
        result['scope'] = ('fresh-root migration baseline with Setup UI skipped' if migration_baseline
                           else 'normal first-boot migration with Setup UI skipped')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--startup-compat', action='store_true', help='Apply evidenced no-baseband/audio/GPU startup configuration')
    parser.add_argument('--cellular-policy', choices=('disabled', 'managed'),
                        help='Independent cellular launch policy (startup compatibility defaults to disabled)')
    parser.add_argument('--modem-runtime', type=Path, help='Linked modem runtime contract for managed cellular')
    parser.add_argument('--modem-adt', type=Path, help='Actual packaged ADT for managed cellular')
    parser.add_argument('--migration-baseline', action='store_true', help='User-selected upstream clean-root 20H392 migration baseline')
    parser.add_argument('--full-boot-log', action='store_true', help='Enable normal and failure logs for every launch daemon; requires baseline')
    parser.add_argument('--skip-setup', action=argparse.BooleanOptionalAction, default=False,
                        help='Skip the first-boot Setup UI in the new userdata image (default: disabled)')
    parser.add_argument('--native-python', type=Path,
                        help='Optional Windows Python executable for fast WSL-mounted-file hashing')
    args = parser.parse_args()
    if args.cellular_policy == 'managed' and (args.modem_runtime is None or args.modem_adt is None):
        parser.error('--cellular-policy managed requires --modem-runtime and --modem-adt')
    if args.cellular_policy != 'managed' and (args.modem_runtime or args.modem_adt):
        parser.error('--modem-runtime and --modem-adt require --cellular-policy managed')
    modem_runtime = json.loads(args.modem_runtime.read_text()) if args.modem_runtime else None
    modem_adt = args.modem_adt.read_bytes() if args.modem_adt else None
    if modem_runtime is not None:
        from ios16_modem_apple import require_managed_contract
        require_managed_contract(modem_runtime, modem_adt)
    if args.full_boot_log and not args.migration_baseline:parser.error('--full-boot-log requires --migration-baseline')
    source = args.source.resolve(strict=True)
    baseline = json.loads(args.report.read_text())
    if (baseline['build'] != '20H392' or baseline['route'] != 'ios-sweet base root'
            or baseline['partition_table'] or baseline['device_gui_tweaks_applied']
            or baseline['bytes'] != 16*1024**3 or source.stat().st_size != baseline['bytes']):
        raise ValueError('Expected the verified, untouched iOS16 firmware base')
    hash_file = lambda path: digest(path, args.native_python)
    if hash_file(source) != baseline['sha256']:
        raise ValueError('Base image SHA256 mismatch')
    before = volume_header(source)
    if before[104:112].hex() != baseline['hfs_finder_id']:
        raise ValueError('Base volume identity mismatch')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    overlay = out / 'rebuild-work.qcow2'
    subprocess.run(['qemu-img', 'create', '-q', '-f', 'qcow2', '-F', 'raw',
                    '-b', str(source), str(overlay)], check=True)
    print('Verified official-content base; building new userdata in an isolated overlay', flush=True)
    os.environ.setdefault('LIBGUESTFS_BACKEND', 'direct')
    import guestfs
    guest = guestfs.GuestFS(python_return_dict=True)
    guest.set_network(False)
    guest.set_memsize(1024)
    guest.add_drive_opts(str(overlay), format='qcow2')
    try:
        guest.launch()
        guest.mount_vfs('force,rw', 'hfsplus', '/dev/sda', '/')
        result = prepare_root(GuestRoot(guest), baseline['build'], startup_compat=args.startup_compat,
                              migration_baseline=args.migration_baseline,
                              full_boot_log=args.full_boot_log, skip_setup=args.skip_setup,
                              cellular_policy=args.cellular_policy, modem_runtime=modem_runtime,
                              modem_adt=modem_adt)
        for name, uid in DIRECTORIES:
            st = guest.statns(name)
            if (st['st_uid'], st['st_gid'], st['st_mode'] & 0o777) != (uid, uid, 0o755):
                raise ValueError(f'Unexpected container ownership: {name}')
        if args.migration_baseline:
            st=guest.statns(MIGRATION)
            if (st['st_uid'],st['st_gid'],st['st_mode']&0o777)!=(501,501,0o600):
                raise ValueError('Migration baseline ownership mismatch')
        elif guest.exists(MIGRATION):
            raise ValueError('Migration completion preference must be absent')
        for change in result.get('setup_skip', {}).get('preference_changes', []):
            st = guest.statns(change['path'])
            if (st['st_uid'], st['st_gid'], st['st_mode'] & 0o777) != (501, 501, 0o600):
                raise ValueError('Setup preference ownership mismatch: ' + change['path'])
        guest.sync()
        guest.umount_all()
        guest.shutdown()
    finally:
        guest.close()
    print('Root configuration and ownership verified; exporting userdata', flush=True)
    raw = out / 'giulia-ios16-userdata.img'
    subprocess.run(['qemu-img', 'convert', '-p', '-O', 'raw', str(overlay), str(raw)],
                   check=True, stdout=(out/'export-progress.log').open('w'))
    fsck = shutil.which('fsck.hfsplus') or '/usr/sbin/fsck.hfsplus'
    with (out/'filesystem-repair.log').open('wb') as log:
        subprocess.run([fsck, '-fy', str(raw)], stdout=log, stderr=subprocess.STDOUT, check=True)
    sha = hash_file(raw)
    # hfsprogs 540.1's -n dirty-bit path can leak a cache reference. Require a
    # successful full verification pass and an unchanged whole-image hash.
    with (out/'filesystem-check.log').open('wb') as log:
        subprocess.run([fsck, '-fy', str(raw)], stdout=log, stderr=subprocess.STDOUT, check=True)
    if hash_file(raw) != sha:
        raise ValueError('Filesystem verification still modified the image')
    after = volume_header(raw)
    if after[104:112] != before[104:112] or raw.stat().st_size != baseline['bytes']:
        raise ValueError('Export changed volume identity or size')
    if hash_file(source) != baseline['sha256']:
        raise ValueError('Original base image changed')
    result.update(source_sha256=baseline['sha256'], source_unchanged=True,
                  bytes=raw.stat().st_size, sha256=sha, block_size=4096,
                  hfs_finder_id=after[104:112].hex(), raw_file=raw.name,
                  partition_table=False, filesystem_check_passed=True,
                  filesystem_check_mode='full fsck with stable verification SHA256',
                  numeric_ownership_verified=True, target_partition='userdata',
                  flashed=False)
    (out/'root.json').write_text(json.dumps(result, indent=2)+'\n')
    overlay.unlink()
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
