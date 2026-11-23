#!/usr/bin/env python3
"""Register the installed observer in an offline, disposable iOS image copy.

The iOS 16 launchd cache contains the actual job dictionaries. Installing a
loose plist in /Library/LaunchDaemons alone does not add a cached system job.
This tool does not mount, install, chown, or access a phone.
"""
from pathlib import Path
import argparse
import hashlib
import json
import plistlib

ROOT = Path(__file__).resolve().parents[1]
OLD = 'Library/LaunchDaemons/moe.houji.power-probe.plist'
NEW = 'System/Library/LaunchDaemons/moe.houji.power-probe.plist'
CACHE = 'System/Library/xpc/launchd.plist'
PROGRAM = 'usr/libexec/houji-power-probe'


def checked(root, relative):
    path = root
    for component in Path(relative).parts:
        path /= component
        if path.is_symlink():
            raise ValueError('Unexpected symlink in observer installation path')
    return path


def register(root, job_bytes):
    root = Path(root).resolve(strict=True)
    if root == Path('/'):
        raise ValueError('An offline image copy is required')
    job = plistlib.loads(job_bytes)
    if job.get('Label') != 'moe.houji.power-probe' or job.get('ProgramArguments') != ['/' + PROGRAM]:
        raise ValueError('Observer job identity differs')
    old, new, cache, program = [checked(root, p) for p in (OLD, NEW, CACHE, PROGRAM)]
    if not program.is_file() or not program.stat().st_mode & 0o111:
        raise ValueError('The verified observer must already be installed')
    if old.exists() == new.exists():
        raise ValueError('Expected exactly one observer plist location')
    installed = old if old.exists() else new
    if installed.read_bytes() != job_bytes or not new.parent.is_dir():
        raise ValueError('Installed observer plist or system directory differs')
    before_bytes = cache.read_bytes()
    before = plistlib.loads(before_bytes)
    jobs = before.get('LaunchDaemons')
    if not isinstance(jobs, dict):
        raise ValueError('iOS launchd cache has no job dictionary')
    key = '/' + NEW
    for name, value in jobs.items():
        if isinstance(value, dict) and value.get('Label') == job['Label']:
            if name != key or value != job:
                raise ValueError('Conflicting cached observer job')
    if key in jobs and jobs[key] != job:
        raise ValueError('Existing cached path belongs to another job')
    after = {**before, 'LaunchDaemons': {**jobs, key: job}}
    encoded = plistlib.dumps(after, fmt=plistlib.FMT_BINARY, sort_keys=False)
    decoded = plistlib.loads(encoded)
    expected = {**before, 'LaunchDaemons': {**jobs, key: job}}
    if decoded != expected:
        raise ValueError('Cache serialization changed unrelated entries')
    cache_stat, job_stat = cache.stat(), installed.stat()
    moved = installed == old
    # Rename preserves the root-owned plist inode. Rewriting the existing cache
    # preserves its ownership too; the caller discards this image on any failure.
    if moved:
        old.rename(new)
    cache.write_bytes(encoded)
    for path, prior in ((new, job_stat), (cache, cache_stat)):
        now = path.stat()
        if (now.st_ino, now.st_uid, now.st_gid, now.st_mode) != (prior.st_ino, prior.st_uid, prior.st_gid, prior.st_mode):
            raise ValueError('Ownership, mode or inode changed')
    if plistlib.loads(cache.read_bytes()) != expected or new.read_bytes() != job_bytes:
        raise ValueError('Observer startup readback differs')
    return dict(status='PASS', moved_to_system_directory=moved, registered_job=key,
                cached_jobs_before=len(jobs), cached_jobs_after=len(decoded['LaunchDaemons']),
                unrelated_cache_entries_preserved=True, ownership_and_inodes_preserved=True,
                cache_before_sha256=hashlib.sha256(before_bytes).hexdigest(),
                cache_after_sha256=hashlib.sha256(encoded).hexdigest(),
                observer_plist_sha256=hashlib.sha256(job_bytes).hexdigest(), phone_accessed=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    result = register(args.root, (ROOT / 'userland/power/moe.houji.power-probe.plist').read_bytes())
    args.receipt.write_text(json.dumps(result, indent=2) + '\n')
    print('Registered power observer in system launchd cache; phone installation and runtime still unverified')
