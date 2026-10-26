"""Make a GUI initialization candidate from a verified, untouched base image.

Linux/WSL dependencies: python3-guestfs, qemu-utils, libguestfs-hfsplus,
an appliance kernel with HFS+, and img2simg. Uses an isolated appliance and
a copy-on-write overlay. The input image is never opened for writing.
Does not connect to, reboot, or flash a handset.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import struct
import subprocess

from ios16_gui_seed import GuestRoot, seed


def digest(path):
    state = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(8 * 1024**2):
            state.update(chunk)
    return state.hexdigest()


def header(path):
    with path.open('rb') as stream:
        stream.seek(1024)
        data = stream.read(512)
    if data[:4] != b'HX\x00\x05':
        raise ValueError('Not an unpartitioned HFSX volume')
    if struct.unpack_from('>II', data, 40) != (4096, 4194304):
        raise ValueError('Unexpected volume geometry')
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    report = json.loads(args.report.read_text())
    if (report['route'] != 'ios-sweet base root' or report['partition_table']
            or report['device_gui_tweaks_applied'] or report['build'] != '20H392'
            or report['bytes'] != 16 * 1024**3):
        raise ValueError('Only the pinned, fresh iOS 16.7.16 base is supported')
    if source.stat().st_size != report['bytes'] or digest(source) != report['sha256']:
        raise ValueError('Source image differs from the verified base')
    before = header(source)
    attrs = struct.unpack_from('>I', before, 4)[0]
    if not attrs & (1 << 8) or not attrs & (1 << 13) or attrs & (1 << 11):
        raise ValueError('Base must be cleanly unmounted, journaled, and consistent')
    if before[104:112].hex() != report['hfs_finder_id']:
        raise ValueError('Source volume identity mismatch')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    overlay = out / 'seed-work.qcow2'
    subprocess.run(['qemu-img', 'create', '-q', '-f', 'qcow2', '-F', 'raw',
                    '-b', str(source), str(overlay)], check=True)
    print('Verified base; editing an isolated copy-on-write overlay', flush=True)
    os.environ.setdefault('LIBGUESTFS_BACKEND', 'direct')
    import guestfs
    guest = guestfs.GuestFS(python_return_dict=True)
    guest.set_network(False)
    guest.set_memsize(1024)
    guest.add_drive_opts(str(overlay), format='qcow2')
    try:
        guest.launch()
        guest.mount_vfs('force,rw', 'hfsplus', '/dev/sda', '/')
        result = seed(GuestRoot(guest), report['build'])
        guest.sync()
        guest.umount_all()
        guest.shutdown()
    finally:
        guest.close()
    raw = out / 'giulia-ios16-gui-seed.img'
    subprocess.run(['qemu-img', 'convert', '-O', 'raw', str(overlay), str(raw)], check=True)
    after = header(raw)
    if after[104:112] != before[104:112]:
        raise ValueError('Volume identity changed')
    if not struct.unpack_from('>I', after, 4)[0] & (1 << 8):
        raise ValueError('Output was not cleanly unmounted')
    # Normalize this copy, then require a second full check with no persistent
    # byte changes. hfsprogs 540.1's -n path can retain a cache reference after
    # a failed dirty-bit write and report EDEADLK as a bad primary header.
    with (out / 'filesystem-repair.log').open('wb') as log:
        subprocess.run(['fsck.hfsplus', '-fy', str(raw)], stdout=log,
                       stderr=subprocess.STDOUT, check=True)
    raw_sha = digest(raw)
    with (out / 'filesystem-check.log').open('wb') as log:
        subprocess.run(['fsck.hfsplus', '-fy', str(raw)], stdout=log,
                       stderr=subprocess.STDOUT, check=True)
    if digest(raw) != raw_sha:
        raise ValueError('Second filesystem check still changed the image')
    after = header(raw)
    if after[104:112] != before[104:112]:
        raise ValueError('Filesystem repair changed the volume identity')
    sparse = out / 'giulia-ios16-gui-seed.sparse.img'
    subprocess.run(['img2simg', str(raw), str(sparse), '4096'], check=True)
    verify = runpy.run_path(str(Path(__file__).with_name('prepare-ios16-userdata.py')))
    size, expanded_sha = verify['sparse_digest'](sparse)
    if size != report['bytes'] or expanded_sha != raw_sha:
        raise ValueError('Sparse transport does not reproduce the modified root')
    if digest(source) != report['sha256']:
        raise ValueError('Source image was unexpectedly changed')
    result.update(source_sha256=report['sha256'], source_unchanged=True,
                  bytes=size, sha256=raw_sha, hfs_finder_id=after[104:112].hex(),
                  block_size=4096, partition_table=False,
                  raw_file=raw.name, sparse_file=sparse.name,
                  sparse_bytes=sparse.stat().st_size, sparse_sha256=digest(sparse),
                  sparse_expansion_verified=True, filesystem_check_passed=True,
                  filesystem_check_mode='full fsck, second pass SHA256 unchanged',
                  target_partition='userdata', flashed=False)
    (out / 'root.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
