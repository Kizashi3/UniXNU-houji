"""Extract pinned firmware trust caches and audit every staged application."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import struct
import zipfile
from ios16_trust_catalog import im4p_payload, modules, code_hashes


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ipsw', type=Path, required=True)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--root-report', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    expected = json.loads((Path(__file__).resolve().parents[1]/'ios16/firmware.json').read_text())
    def sha(path):
        with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()
    if a.ipsw.stat().st_size != expected['bytes'] or sha(a.ipsw) != expected['sha256']:
        raise ValueError('IPSW identity mismatch')
    root = json.loads(a.root_report.read_text())
    if root['build'] != expected['build'] or a.root.stat().st_size != root['bytes'] or sha(a.root) != root['sha256']:
        raise ValueError('Root identity mismatch')
    payloads = []; sources = []
    with zipfile.ZipFile(a.ipsw) as archive:
        manifest = plistlib.loads(archive.read('BuildManifest.plist'))
        identities = [i for i in manifest['BuildIdentities'] if i['Info']['DeviceClass'] == expected['device_class']
                      and i['Info']['RestoreBehavior'] == 'Erase']
        if len(identities) != 1: raise ValueError('Ambiguous restore identity')
        for key, kind in (('StaticTrustCache',b'trst'), ('Cryptex1,SystemTrustCache',b'trcs'), ('Cryptex1,AppTrustCache',b'trca')):
            path = identities[0]['Manifest'][key]['Info']['Path']
            data = archive.read(path); payload = im4p_payload(data, kind)
            checked = modules(struct.pack('<II', 1, 8)+payload)[0]
            payloads.append(payload)
            sources.append({'component':key, 'path':path, 'sha256':hashlib.sha256(data).hexdigest(),
                            'uuid':checked['uuid'], 'entries':checked['entries']})
    offset = 4+4*len(payloads); offsets = []
    for payload in payloads:
        offsets.append(offset); offset += len(payload)
    bundle = struct.pack('<I'+'I'*len(offsets), len(offsets), *offsets)+b''.join(payloads)
    hashes = {h for m in modules(bundle) for h in m['hashes']}
    import pytsk3
    fs = pytsk3.FS_Info(pytsk3.Img_Info(str(a.root)))
    def read(path):
        f = fs.open(path)
        if f.info.meta.size > 128*1024**2: raise ValueError('Unexpected application size')
        return f.read_random(0, f.info.meta.size)
    staged = '/private/var/staged_system_apps'; applications = []
    for entry in fs.open_dir(staged):
        name = entry.info.name.name.decode()
        if not name.endswith('.app'): continue
        path = staged+'/'+name
        info = plistlib.loads(read(path+'/Info.plist'))
        executable = info['CFBundleExecutable']
        if '/' in executable: raise ValueError('Unexpected executable name')
        cdhashes = code_hashes(read(path+'/'+executable))
        if not all(h in hashes for h in cdhashes): raise ValueError(f'Untrusted staged executable: {name}')
        applications.append({'path':path, 'bundle_id':info['CFBundleIdentifier'],
                             'cdhashes':[h.hex() for h in cdhashes], 'all_hashes_present':True})
    if len(applications) != 32: raise ValueError('Staged app inventory changed')
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out/'kernel.macho.trustcache').write_bytes(bundle)
    report = {'build':expected['build'], 'source_ipsw_sha256':expected['sha256'],
              'audited_root_sha256':root['sha256'], 'sha256':hashlib.sha256(bundle).hexdigest(),
              'bytes':len(bundle), 'modules':sources, 'unique_hashes':len(hashes),
              'staged_applications':sorted(applications, key=lambda app: app['path']),
              'query_only':True, 'hardware_verified':False}
    (a.out/'trust-catalog.json').write_text(json.dumps(report, indent=2)+'\n')
    print(f'Official trust catalogue: {len(hashes)} unique hashes; all {len(applications)} staged applications match')


if __name__ == '__main__': main()
