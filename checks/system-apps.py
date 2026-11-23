#!/usr/bin/env python3
"""Exercise staged-app moves in disposable directories, never a device."""
from pathlib import Path
import importlib.util
import hashlib
import json
import plistlib
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('restore_system_apps', ROOT/'tools/restore-system-apps.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
catalog = {'os_build':'20H392','applications':{'One.app':'com.apple.one','Two.app':'com.apple.two'}}


def fixture(root):
    version = root/'System/Library/CoreServices/SystemVersion.plist'
    version.parent.mkdir(parents=True)
    version.write_bytes(plistlib.dumps({'ProductBuildVersion':'20H392'}))
    (root/'Applications').mkdir()
    signatures = root/'System/Library/AppSignatures'
    signatures.mkdir()
    for name,identifier in catalog['applications'].items():
        app=root/'private/var/staged_system_apps'/name
        app.mkdir(parents=True)
        (app/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':identifier,'CFBundleExecutable':'Main'}))
        (app/'Main').write_bytes(b'owner app fixture')
        (app/'Main').chmod(0o755)
        (app/'Resource').symlink_to('Info.plist')
        (signatures/identifier).write_bytes(b'fixture')


with tempfile.TemporaryDirectory(prefix='houji-apps-') as tmp:
    root=Path(tmp);fixture(root)
    assert module.restore(root,catalog)['status']=='PLANNED'
    # A conflict in the last bundle must be rejected before moving the first.
    (root/'Applications/Two.app').mkdir()
    try:module.restore(root,catalog,True)
    except ValueError:pass
    else:raise AssertionError('conflicting app accepted')
    assert (root/'private/var/staged_system_apps/One.app').is_dir()
    (root/'Applications/Two.app').rmdir()
    r=module.restore(root,catalog,True)
    assert r['moved']==2 and not r['app_bytes_modified']
    assert module.restore(root,catalog,True)['moved']==0
    assert (root/'Applications/One.app/Resource').is_symlink()
    info=root/'Applications/Two.app/Info.plist'
    info.write_bytes(plistlib.dumps({'CFBundleIdentifier':'com.apple.other','CFBundleExecutable':'Main'}))
    try:module.restore(root,catalog,True)
    except ValueError:pass
    else:raise AssertionError('wrong bundle accepted')
with tempfile.TemporaryDirectory(prefix='houji-apps-') as tmp:
    root=Path(tmp);fixture(root)
    original=Path.rename
    def fail_second(path,destination):
        if path.name=='Two.app' and path.parent.name=='staged_system_apps':
            raise OSError('injected rename failure')
        return original(path,destination)
    Path.rename=fail_second
    try:
        try:module.restore(root,catalog,True)
        except OSError:pass
        else:raise AssertionError('failure not propagated')
    finally:Path.rename=original
    assert all((root/'private/var/staged_system_apps'/n).is_dir() for n in catalog['applications'])
    assert not list((root/'Applications').iterdir())
    # Never follow an application location outside the selected image.
    (root/'private/var/staged_system_apps/One.app').rename(root/'Elsewhere.app')
    (root/'private/var/staged_system_apps/One.app').symlink_to(root/'Elsewhere.app')
    try:module.restore(root,catalog,True)
    except ValueError:pass
    else:raise AssertionError('symlink application accepted')
job=plistlib.loads((ROOT/'userland/apps/moe.houji.system-apps.plist').read_bytes())
assert job['UserName']=='mobile' and job['RunAtLoad'] and not job.get('KeepAlive')
source=(ROOT/'userland/apps/HoujiSystemApps.m').read_text()
assert ')(workspace,rebuild,YES,YES,NO)' in source
assert 'registered' in source and 'TIMEOUT' in source
spec=importlib.util.spec_from_file_location('register_apps',ROOT/'tools/register-system-apps.py')
startup=importlib.util.module_from_spec(spec);spec.loader.exec_module(startup)
with tempfile.TemporaryDirectory(prefix='houji-app-startup-') as tmp:
    root=Path(tmp)/'root';build=Path(tmp)/'build';build.mkdir()
    for relative in ['usr/libexec','System/Library/LaunchDaemons','System/Library/xpc']:
        (root/relative).mkdir(parents=True,exist_ok=True)
    cache=root/startup.CACHE
    original={'LaunchDaemons':{'/existing.plist':{'Label':'existing','RunAtLoad':True}},'unrelated':['retained']}
    cache.write_bytes(plistlib.dumps(original));before=cache.stat()
    binary=build/'houji-system-apps';binary.write_bytes(b'non-executable fixture')
    report={'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'source_inputs':{}}
    (build/'build-result.json').write_text(json.dumps(report))
    result=startup.register(root,build)
    after=plistlib.loads(cache.read_bytes());after['LaunchDaemons'].pop('/'+startup.JOB)
    assert after==original and result['numeric_root_ownership_verification_required']
    assert cache.stat().st_ino==before.st_ino and cache.stat().st_mode==before.st_mode
    try:startup.register(root,build)
    except ValueError:pass
    else:raise AssertionError('existing helper overwritten')
print('PASS: staged-app identity, whole-plan preflight, inode/content/owner preservation, idempotence, failure rollback, symlink rejection; runtime registration remains a device check')
