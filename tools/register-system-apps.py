#!/usr/bin/env python3
"""Add the bounded system-app registrar to an offline iOS launchd cache.

New files need numeric root ownership verified by the image packager before
installation. This tool does not chown, mount, or access a phone.
"""
from pathlib import Path
import argparse
import hashlib
import json
import plistlib
import stat

ROOT = Path(__file__).resolve().parents[1]
PROGRAM = 'usr/libexec/houji-system-apps'
JOB = 'System/Library/LaunchDaemons/moe.houji.system-apps.plist'
CACHE = 'System/Library/xpc/launchd.plist'
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()


def checked(root, name):
    path = root
    for part in Path(name).parts:
        path /= part
        if path.is_symlink():
            raise ValueError('Unexpected symlink in startup path')
    return path


def register(root, build):
    root,build=Path(root).resolve(strict=True),Path(build).resolve(strict=True)
    if root == Path('/'):
        raise ValueError('An offline image copy is required')
    report=json.loads((build/'build-result.json').read_text())
    binary=build/'houji-system-apps'
    if sha(binary)!=report['binary_sha256'] or any(sha(ROOT/n)!=s for n,s in report['source_inputs'].items()):
        raise ValueError('Registrar build or public sources changed')
    job_bytes=(ROOT/'userland/apps/moe.houji.system-apps.plist').read_bytes()
    job=plistlib.loads(job_bytes)
    if job['ProgramArguments']!=['/'+PROGRAM] or job['UserName']!='mobile' or job.get('KeepAlive'):
        raise ValueError('Unexpected registrar startup policy')
    program,plist,cache=[checked(root,n) for n in [PROGRAM,JOB,CACHE]]
    if program.exists() or plist.exists():
        raise ValueError('Registrar already exists; explicit upgrade is required')
    before=cache.read_bytes();parsed=plistlib.loads(before);jobs=parsed['LaunchDaemons']
    if any(x.get('Label')==job['Label'] for x in jobs.values() if isinstance(x,dict)):
        raise ValueError('Registrar label already cached')
    expected={**parsed,'LaunchDaemons':{**jobs,'/'+JOB:job}}
    encoded=plistlib.dumps(expected,fmt=plistlib.FMT_BINARY,sort_keys=False)
    if plistlib.loads(encoded)!=expected:
        raise ValueError('Launchd cache serialization differs')
    prior=cache.stat()
    program.write_bytes(binary.read_bytes());program.chmod(0o755)
    plist.write_bytes(job_bytes);plist.chmod(0o644)
    cache.write_bytes(encoded)
    now=cache.stat()
    if (now.st_ino,now.st_uid,now.st_gid,stat.S_IMODE(now.st_mode)) != (prior.st_ino,prior.st_uid,prior.st_gid,stat.S_IMODE(prior.st_mode)):
        raise ValueError('Existing cache ownership or inode changed')
    if cache.read_bytes()!=encoded or sha(program)!=report['binary_sha256'] or plist.read_bytes()!=job_bytes:
        raise ValueError('Startup file readback differs')
    return {'status':'INSTALLED_IN_OFFLINE_IMAGE','program_sha256':sha(program),
            'cache_before_sha256':hashlib.sha256(before).hexdigest(),'cache_after_sha256':sha(cache),
            'new_files':[PROGRAM,JOB],'numeric_root_ownership_verification_required':True,
            'unrelated_cached_jobs_preserved':True,'phone_accessed':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--build',type=Path,required=True)
    parser.add_argument('--receipt',type=Path,required=True)
    args=parser.parse_args()
    if args.receipt.exists():
        raise SystemExit('Refuse to overwrite receipt')
    result=register(args.root,args.build)
    args.receipt.write_text(json.dumps(result,indent=2)+'\n')
    print('Offline startup registered; numeric file owners and runtime result still require verification')
