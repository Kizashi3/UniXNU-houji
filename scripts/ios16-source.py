"""Fetch a pinned IPSW, verify it, and extract the exact erase identity."""
import argparse
import hashlib
import json
import plistlib
import subprocess
import zipfile
from pathlib import Path


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--ipsw', type=Path)
    args = p.parse_args()
    spec = json.loads((Path(__file__).resolve().parents[1] / 'ios16/firmware.json').read_text())
    args.out.mkdir(parents=True, exist_ok=True)
    ipsw = args.ipsw or args.out / 'source.ipsw'
    if not ipsw.exists():
        partial = ipsw.with_suffix('.partial')
        subprocess.run(['curl', '--fail', '--location', '--retry', '8',
                        '--continue-at', '-', '--output', str(partial), spec['url']], check=True)
        if partial.stat().st_size != spec['bytes'] or digest(partial) != spec['sha256']:
            raise RuntimeError('Downloaded IPSW does not match pinned digest')
        partial.rename(ipsw)
    if ipsw.stat().st_size != spec['bytes'] or digest(ipsw) != spec['sha256']:
        raise RuntimeError('Cached IPSW does not match pinned digest')
    records = {}
    with zipfile.ZipFile(ipsw) as z:
        manifest = plistlib.loads(z.read('BuildManifest.plist'))
        if manifest['ProductBuildVersion'] != spec['build']:
            raise RuntimeError('Unexpected firmware build')
        identities = [i for i in manifest['BuildIdentities']
                      if i['Info'].get('DeviceClass') == spec['device_class']
                      and i['Info'].get('RestoreBehavior') == 'Erase']
        if len(identities) != 1:
            raise RuntimeError('Erase identity is ambiguous')
        for component, name in [('OS', 'OS.dmg'), ('Cryptex1,SystemOS', 'SystemOS.dmg'),
                                ('Cryptex1,AppOS', 'AppOS.dmg'), ('DeviceTree', 'DeviceTree.im4p')]:
            member = identities[0]['Manifest'][component]['Info']['Path']
            target = args.out / name
            sha = hashlib.sha256()
            with z.open(member) as source, target.with_suffix('.partial').open('wb') as dest:
                while block := source.read(8 * 1024 * 1024):
                    dest.write(block)
                    sha.update(block)
            target.with_suffix('.partial').replace(target)
            records[component] = {'file': name, 'member': member,
                                  'bytes': target.stat().st_size, 'sha256': sha.hexdigest()}
            print(component, records[component], flush=True)
    report = {'firmware': spec, 'ipsw_verified': True, 'components': records}
    (args.out / 'source.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
