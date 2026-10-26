"""Build an unpartitioned HFSX base root from verified iPhone firmware.

Equivalent base layout to ios-sweet/tools/mkiosroot.sh. --gui-layout optionally
creates container directories while preserving normal migration. It does not establish
that the kernel can mount this image or that account/activation services work.
"""
import argparse
import hashlib
import gzip
import json
import os
import plistlib
import shutil
import struct
import subprocess
import sys
from pathlib import Path

from ios16_root_layout import MountedRoot, prepare_layout


def run(*args):
    return subprocess.check_output([str(a) for a in args])


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--gui-layout', action='store_true',
                   help='Create container directories without seeding migration completion')
    args = p.parse_args()
    if sys.platform != 'darwin' or os.geteuid() != 0:
        raise RuntimeError('Run as root on macOS to preserve numeric file owners')
    args.out.mkdir(parents=True, exist_ok=True)
    dmg = args.out / 'ios16-base.dmg'
    raw = args.out / 'ios16-base.cdr'
    if dmg.exists() or raw.exists() or Path(str(raw)+'.gz').exists():
        raise RuntimeError('Refusing to overwrite an existing root image')
    report = json.loads((args.source / 'source.json').read_text())
    if not report['ipsw_verified']:
        raise RuntimeError('Source verification missing')
    for v in report['components'].values():
        with (args.source / v['file']).open('rb') as f:
            if hashlib.file_digest(f, 'sha256').hexdigest() != v['sha256']:
                raise RuntimeError('Component digest mismatch')
    devices = []

    def attach(path, readonly):
        options = ['-readonly'] if readonly else []
        info = plistlib.loads(run('hdiutil', 'attach', '-plist', '-nobrowse',
                                 '-owners', 'on', *options, path))
        entities = info['system-entities']
        devices.append(entities[0]['dev-entry'])
        mounts = [Path(e['mount-point']) for e in entities if 'mount-point' in e]
        if len(mounts) != 1:
            raise RuntimeError(f'Expected one mounted volume for {path}: {mounts}')
        return mounts[0]

    try:
        sources = {key: attach(args.source / name, True) for key, name in
                   [('OS', 'OS.dmg'), ('SystemOS', 'SystemOS.dmg'), ('AppOS', 'AppOS.dmg')]}
        run('hdiutil', 'create', '-size', '16g', '-layout', 'NONE', '-fs', 'JHFS+X',
            '-volname', 'iOSRoot', dmg)
        root = attach(dmg, False)
        for key, target in [('OS', root), ('SystemOS', root / 'private/preboot/Cryptexes/OS'),
                            ('AppOS', root / 'private/preboot/Cryptexes/App')]:
            target.mkdir(parents=True, exist_ok=True)
            run('/usr/bin/rsync', '-aH', '--numeric-ids', str(sources[key]) + '/', str(target) + '/')
        cache = root / 'System/Library/Caches/com.apple.dyld'
        cache.mkdir(parents=True, exist_ok=True)
        cryptex = root / 'private/preboot/Cryptexes'
        for source in (cryptex / 'OS/System/Library/Caches/com.apple.dyld').iterdir():
            target = cache / source.name
            if not os.path.lexists(target):
                os.link(source, target)
        for label in ['OS', 'App']:
            base = cryptex / label
            for parent, dirs, files in os.walk(base, followlinks=False):
                for name in files + [d for d in dirs if (Path(parent) / d).is_symlink()]:
                    source = Path(parent) / name
                    target = root / source.relative_to(base)
                    if os.path.lexists(target):
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if source.is_symlink():
                        os.symlink(os.readlink(source), target)
                        os.lchown(target, source.lstat().st_uid, source.lstat().st_gid)
                    else:
                        os.link(source, target)
        for name, mode in [('diagnostics', 0o751), ('uuidtext', 0o755), ('diagnostics/timesync', 0o755)]:
            directory = root / 'private/var/db' / name
            directory.mkdir(parents=True, exist_ok=True)
            os.chown(directory, 272, 272)
            os.chmod(directory, mode)
            marker = directory / '.migrated'
            marker.touch()
            os.chown(marker, 272, 272)
            os.chmod(marker, 0o644)
        bags = root / 'private/var/keybags'
        bags.mkdir(parents=True, exist_ok=True)
        os.chmod(bags, 0o700)
        keybag = bags / 'systembag.kb'
        keybag.write_bytes(plistlib.dumps({'KeyBagKeys': b'SWEET'}))
        os.chmod(keybag, 0o600)
        if args.gui_layout:
            prepare_layout(MountedRoot(root), report['firmware']['build'])
        run('diskutil', 'verifyVolume', root)
    finally:
        for device in reversed(devices):
            subprocess.run(['hdiutil', 'detach', device], check=True)
    # Stream the verified volume's raw block device into gzip. Converting to a
    # second 16 GiB file first exhausts the hosted runner's available storage.
    info=plistlib.loads(run('hdiutil','attach','-readonly','-nomount','-plist',dmg))
    device=info['system-entities'][0]['dev-entry']
    try:
      with open(device.replace('/dev/disk','/dev/rdisk'),'rb') as f:
        f.seek(1024)
        header = f.read(512)
        if header[:4] != b'HX\x00\x05':
            raise RuntimeError('Output is not unpartitioned HFSX')
        attributes = struct.unpack_from('>I', header, 4)[0]
        block_size, total_blocks = struct.unpack_from('>II', header, 40)
        volume_bytes=block_size*total_blocks
        if not attributes & (1 << 13) or volume_bytes != 16*1024**3 or block_size != 4096:
            raise RuntimeError('Journal or volume geometry validation failed')
        f.seek(0)
        sha_state=hashlib.sha256()
        remaining=volume_bytes
        with gzip.open(str(raw)+'.gz','wb',compresslevel=1) as out:
            while remaining:
                chunk=f.read(min(8*1024**2,remaining))
                if not chunk: raise RuntimeError('Truncated raw HFSX volume')
                out.write(chunk); sha_state.update(chunk); remaining-=len(chunk)
        sha=sha_state.hexdigest()
    finally:
        run('hdiutil','detach',device)
    result = {'route': 'ios-sweet base root', 'build': report['firmware']['build'],
              'bytes': volume_bytes, 'sha256': sha, 'block_size': block_size,
              'hfs_finder_id': header[104:112].hex(), 'hardware_verified': False,
              'device_gui_tweaks_applied': args.gui_layout, 'partition_table': False,
              'normal_migration_enabled': True, 'migration_completion_seeded': False,
              'gui_layout_scope': 'container directories only' if args.gui_layout else None}
    (args.out / 'root.json').write_text(json.dumps(result, indent=2) + '\n')
    dmg.unlink()
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
