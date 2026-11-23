#!/usr/bin/env python3
"""Move the owner's staged iOS apps within an offline image copy.

No phone access, cache deletion, app byte edits, or launchd registration.
The image owner must retain the pre-change image and discard a failed copy.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import plistlib
import stat

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'userland/apps/system-apps.json'


def path_at(root, relative):
    path = root
    for part in Path(relative).parts:
        path /= part
        if path.is_symlink():
            raise ValueError('Symlink in application root path')
    return path


def inventory(bundle):
    rows = {}
    for path in [bundle, *sorted(bundle.rglob('*'))]:
        meta = path.lstat()
        row = {'inode': meta.st_ino, 'uid': meta.st_uid, 'gid': meta.st_gid,
               'mode': stat.S_IMODE(meta.st_mode)}
        if stat.S_ISLNK(meta.st_mode):
            row.update(kind='symlink', target=os.readlink(path))
        elif stat.S_ISREG(meta.st_mode):
            row.update(kind='file', bytes=meta.st_size,
                       sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        elif stat.S_ISDIR(meta.st_mode):
            row.update(kind='directory')
        else:
            raise ValueError('Special file in staged application')
        rows[str(path.relative_to(bundle))] = row
    return rows


def restore(root, catalog, apply=False):
    root = Path(root).resolve(strict=True)
    if root == Path('/'):
        raise ValueError('An offline image copy is required')
    version = plistlib.loads(path_at(root, 'System/Library/CoreServices/SystemVersion.plist').read_bytes())
    if version.get('ProductBuildVersion') != catalog['os_build']:
        raise ValueError('Application catalog does not match the OS build')
    source = path_at(root, 'private/var/staged_system_apps')
    target = path_at(root, 'Applications')
    if not source.is_dir() or not target.is_dir() or source.stat().st_dev != target.stat().st_dev:
        raise ValueError('Staged and installed apps must be on the same image filesystem')
    plan = []
    for name, identifier in catalog['applications'].items():
        if Path(name).name != name or not name.endswith('.app') or not identifier.startswith('com.apple.'):
            raise ValueError('Invalid system application catalog')
        old, new = path_at(source, name), path_at(target, name)
        if old.exists() == new.exists():
            raise ValueError('Expected exactly one bundle location: ' + name)
        bundle = old if old.exists() else new
        info = plistlib.loads(path_at(bundle, 'Info.plist').read_bytes())
        executable = info.get('CFBundleExecutable', '')
        if info.get('CFBundleIdentifier') != identifier or Path(executable).name != executable or not executable:
            raise ValueError('Bundle identity differs: ' + name)
        if not path_at(bundle, executable).is_file():
            raise ValueError('Bundle executable missing: ' + name)
        if not path_at(root, 'System/Library/AppSignatures/' + identifier).is_file():
            raise ValueError('Original removable-system-app signature record missing: ' + name)
        plan.append({'name': name, 'identifier': identifier,
                     'source': str(bundle.relative_to(root)),
                     'destination': 'Applications/' + name, 'move': old.exists(),
                     'inventory': inventory(bundle)})
    moved = []
    if apply:
        try:
            for row in plan:
                if row['move']:
                    old, new = source / row['name'], target / row['name']
                    old.rename(new)
                    moved.append((old, new))
            for row in plan:
                if inventory(target / row['name']) != row['inventory']:
                    raise ValueError('Application content, inode or ownership changed: ' + row['name'])
        except BaseException:
            for old, new in reversed(moved):
                new.rename(old)
            raise
    return {'status': 'MOVED_AND_VERIFIED' if apply else 'PLANNED', 'os_build': catalog['os_build'],
            'count': len(plan), 'moved': len(moved), 'applications': plan,
            'app_bytes_modified': False, 'caches_deleted': False,
            'launch_services_registration_verified': False, 'phone_accessed': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.receipt.exists():
        raise SystemExit('Refuse to replace an existing receipt')
    result = restore(args.root, json.loads(CATALOG.read_text()), args.apply)
    args.receipt.write_text(json.dumps(result, indent=2) + '\n')
    print(result['status'], 'applications:', result['count'], 'moved:', result['moved'])
