"""Stage a signed daemon and shell/tool bundle into an OFFLINE mounted root.

Writes only the explicitly supplied root directory; never opens a phone/image.
Produces a cdhash manifest for --debug-userland in prepare-ios16.py.
"""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import re
import struct
from ios16_trust_catalog import code_hashes

PREFIX = '/usr/local/giulia'
JOB = '/System/Library/LaunchDaemons/org.uniunx.giulia-debugd.plist'
CACHE = '/System/Library/xpc/launchd.plist'


def binary_record(data):
    if len(data) < 32 or data[:4] != bytes.fromhex('cffaedfe'):
        raise ValueError('Expected a thin signed ARM64 Mach-O executable')
    cpu, subtype, filetype = struct.unpack_from('<III', data, 4)
    if cpu != 0x100000c or subtype & 0xffffff or filetype not in (2, 6):
        raise ValueError('Only ARM64 executables/dylibs can be staged (not arm64e)')
    count,size=struct.unpack_from('<II',data,16)
    at=32; platform=None
    if count>4096 or at+size>len(data):raise ValueError('Invalid Mach-O load commands')
    for _ in range(count):
        if at+8>32+size:raise ValueError('Truncated Mach-O command')
        command,length=struct.unpack_from('<II',data,at)
        if length<8 or at+length>32+size:raise ValueError('Invalid Mach-O command length')
        if command==0x32:
            if length<24 or platform is not None:raise ValueError('Invalid platform command')
            platform=struct.unpack_from('<I',data,at+8)[0]
        elif command==0x25:
            if length<16 or platform is not None:raise ValueError('Invalid iOS version command')
            platform=2
        at+=length
    if at!=32+size or platform not in (2,7):
        raise ValueError('Expected iOS/iOS-simulator ARM64, not a macOS executable')
    return {'sha256': hashlib.sha256(data).hexdigest(),
            'cdhashes': [h.hex() for h in code_hashes(data)],'platform':platform,'filetype':filetype}


def stage(root, daemon, tools):
    # Read and validate every input before changing the root.
    cache = plistlib.loads(root.read(CACHE))
    jobs = cache.get('LaunchDaemons')
    if not isinstance(jobs, dict) or JOB in jobs or root.exists(PREFIX) or root.exists(JOB):
        raise ValueError('Expected an unstaged offline root with a launchd job cache')
    files = {PREFIX+'/giulia-debugd': daemon}
    for name, data in tools.items():
        if not re.fullmatch(r'(?:bin|lib)/[A-Za-z0-9_.+-]+', name):
            raise ValueError('Tool paths must be bin/NAME or lib/NAME; no symlinks')
        files[PREFIX+'/'+name] = data
    if PREFIX+'/bin/sh' not in files:
        raise ValueError('Supply a real signed ARM64 Darwin shell as tools/bin/sh')
    inventory = {name: binary_record(data) for name, data in files.items()}
    if any(inventory[name]['filetype']!=2 for name in (PREFIX+'/giulia-debugd',PREFIX+'/bin/sh')):
        raise ValueError('Daemon and shell must be executables, not dylibs')
    job = {'Label':'org.uniunx.giulia-debugd', 'UserName':'root',
           'ProgramArguments':[PREFIX+'/giulia-debugd', PREFIX+'/bin/sh'],
           'RunAtLoad':True, 'KeepAlive':True, 'ThrottleInterval':10,
           'StandardOutPath':'/private/var/log/giulia-debugd.log',
           'StandardErrorPath':'/private/var/log/giulia-debugd.log'}
    for name in ('/usr/local', PREFIX, PREFIX+'/bin', PREFIX+'/lib'):
        root.directory(name, 0)
    for name, data in files.items():
        root.write(name, data, uid=0, mode=0o755)
        if root.read(name) != data:
            raise ValueError('Staged binary verification failed: '+name)
    root.write(JOB, plistlib.dumps(job, fmt=plistlib.FMT_BINARY), uid=0, mode=0o644)
    jobs[JOB] = job
    encoded = plistlib.dumps(cache, fmt=plistlib.FMT_BINARY, sort_keys=False)
    root.write(CACHE, encoded)
    if root.read(CACHE) != encoded:
        raise ValueError('Launchd job cache verification failed')
    return {'schema':1, 'purpose':'giulia-debug-userland', 'files':inventory,
            'launchd_cache_sha256':hashlib.sha256(encoded).hexdigest(),
            'hardware_tested':False, 'required_bootargs':['giulia_debug=1']}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True, help='Offline writable mounted COPY of the iOS root')
    p.add_argument('--daemon', type=Path, required=True)
    p.add_argument('--tools', type=Path, required=True, help='Directory containing bin/sh and optional bin/*, lib/*')
    p.add_argument('--manifest', type=Path, required=True)
    a=p.parse_args()
    if a.manifest.exists():p.error('Use a new manifest output path')
    from ios16_root_layout import MountedRoot
    root=MountedRoot(a.root)
    if root.root == Path('/') or not root.exists('/System/Library/CoreServices/SystemVersion.plist'):
        p.error('Expected an offline iOS root copy, not the host root')
    tools={}
    for source in a.tools.rglob('*'):
        if source.is_symlink():p.error('Resolve tool symlinks into signed binaries before staging')
        if source.is_file():tools[source.relative_to(a.tools).as_posix()]=source.read_bytes()
    result=stage(root,a.daemon.read_bytes(),tools)
    a.manifest.write_text(json.dumps(result,indent=2)+'\n')
    print('Staged offline files; regenerate kernel profile with --debug-userland '+str(a.manifest))


if __name__=='__main__':main()
