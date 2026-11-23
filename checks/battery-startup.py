#!/usr/bin/env python3
"""Exercise the actual cache update, preserving existing jobs and ownership."""
from pathlib import Path
import importlib.util
import plistlib
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('power_startup', ROOT / 'tools/register-power-probe.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
job_bytes = (ROOT / 'userland/power/moe.houji.power-probe.plist').read_bytes()
with tempfile.TemporaryDirectory(prefix='houji-power-startup-') as temp:
    root = Path(temp)
    for relative in (module.OLD, module.NEW, module.CACHE, module.PROGRAM):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
    cache = root / module.CACHE
    before = {'VersionNumber': 7, 'SystemLibraryTreeState': {'unchanged': b'abc'},
              'LaunchDaemons': {'/System/Library/LaunchDaemons/com.apple.powerd.plist':
                               {'Label': 'com.apple.powerd', 'KeepAlive': True}}}
    cache.write_bytes(plistlib.dumps(before, fmt=plistlib.FMT_BINARY))
    program = root / module.PROGRAM
    program.write_bytes(b'host test fixture; never executed')
    program.chmod(0o755)
    old, new = root / module.OLD, root / module.NEW
    old.write_bytes(job_bytes)
    inode = old.stat().st_ino
    result = module.register(root, job_bytes)
    assert result['cached_jobs_before'] == 1 and result['cached_jobs_after'] == 2
    assert not old.exists() and new.stat().st_ino == inode
    after = plistlib.loads(cache.read_bytes())
    after['LaunchDaemons'].pop('/' + module.NEW)
    assert after == before
    assert module.register(root, job_bytes)['cached_jobs_after'] == 2  # No duplicate on retry.
    new.unlink()
    new.symlink_to(program)
    saved = cache.read_bytes()
    try:
        module.register(root, job_bytes)
    except ValueError:
        pass
    else:
        raise AssertionError('A symlink must not be followed')
    assert cache.read_bytes() == saved
print('PASS: actual iOS launchd cache update, idempotence, unrelated jobs, inode/owner retention and symlink rejection')
