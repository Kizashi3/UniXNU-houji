#!/usr/bin/env python3
"""Package the verified local frontend artifacts; never install or boot anything."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sign(path, identifier):
    subprocess.run(['codesign', '--force', '--sign', '-', '--pagesize', '4096',
                    '--identifier', identifier, str(path)], check=True)
    subprocess.run(['codesign', '--verify', '--strict', str(path)], check=True)
    result = subprocess.run(['codesign', '-d', '--verbose=4', str(path)], capture_output=True, text=True, check=True).stderr
    if not re.search(r'^Page size=4096$', result, re.M):
        raise RuntimeError('code signing page size differs')
    return re.search(r'^CDHash=([a-f0-9]{40})$', result, re.M)[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for key in ('plugin-build', 'turnip-build', 'import-audit', 'output'):
        ap.add_argument('--' + key, type=Path, required=True)
    a = ap.parse_args()
    plugin = json.loads((a.plugin_build / 'build-result.json').read_text())
    turnip = json.loads((a.turnip_build / 'build-result.json').read_text())
    audit = json.loads(a.import_audit.read_text())
    inputs = [(Path(plugin['bundle']) / 'NativeAdrenoMetal', plugin['executable_sha256']),
              (Path(plugin['probe']), plugin['probe_sha256']),
              (Path(turnip['library']), turnip['sha256'])]
    audited = {x['sha256'] for x in audit['binaries']}
    if not audit['pass'] or any(sha(path) != expected or expected not in audited for path, expected in inputs):
        raise RuntimeError('an input changed after the successful iOS 16 import audit')
    if plugin['pins']['translator'] != '720ef1ce9ae2a2068999a8675717418b9416283e' or turnip['target'] != 'arm64-apple-ios16.0':
        raise RuntimeError('source/OS profiles differ')
    out = a.output.resolve()
    if out.exists():
        raise RuntimeError('candidate output must be new; preserve previous packages')
    out.mkdir(parents=True)
    bundle = out / 'payload/System/Library/Extensions/NativeAdrenoMetal.bundle'
    bundle.parent.mkdir(parents=True)
    shutil.copytree(plugin['bundle'], bundle, copy_function=shutil.copyfile)
    (bundle / 'NativeAdrenoMetal').chmod(0o755)
    library = bundle / 'libvulkan_freedreno.dylib'
    shutil.copyfile(turnip['library'], library)
    library.chmod(0o755)
    turnip_hash = sign(library, 'org.blu-sharky.turnip')
    plugin_hash = sign(bundle, 'org.blu-sharky.NativeAdrenoMetal')
    # The probe's real initializer checks the existing upstream allowlist. The
    # desktop is not selected until its backend and rendering tests actually pass.
    (bundle.parent / 'NativeAdrenoMetal.clients').write_text('adrenometalprobe\n')
    probe = out / 'payload/private/var/ngpu/bin/adrenometalprobe'
    probe.parent.mkdir(parents=True)
    shutil.copyfile(plugin['probe'], probe)
    probe.chmod(0o755)
    subprocess.run(['codesign', '--verify', '--strict', str(probe)], check=True)
    info = subprocess.run(['codesign', '-d', '--verbose=4', str(probe)], capture_output=True, text=True, check=True).stderr
    probe_hash = re.search(r'^CDHash=([a-f0-9]{40})$', info, re.M)[1]
    files = {str(path.relative_to(out)): sha(path) for path in out.rglob('*') if path.is_file()}
    result = {
        'component': 'AdrenoMetal', 'board': 'houji', 'os': 'iOS 16.7.16 20H392',
        'source_pins': plugin['pins'], 'mesa_revision': turnip['mesa_revision'],
        'translator_runtime_id': plugin['translator_runtime_id'], 'turnip_source_id': turnip['source_id'],
        'files': files, 'additional_owner_trust_cdhashes': {
            'AdrenoMetal': plugin_hash, 'Turnip': turnip_hash, 'probe': probe_hash},
        'import_audit_sha256': sha(a.import_audit),
        'clients': ['adrenometalprobe'], 'desktop_selected': False,
        'phone_accessed': False, 'hardware_tested': False, 'gpu_acceleration_verified': False,
        'installable_now': False,
        'remaining': ['real A750 XNU GPU service with working command/fence/writeback',
                      'iOS probe execution', 'desktop composition and stability test'],
    }
    (out / 'manifest.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'candidate': str(out), 'files': len(files), 'hardware_tested': False}))


if __name__ == '__main__':
    main()
