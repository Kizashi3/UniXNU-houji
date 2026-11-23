#!/usr/bin/env python3
"""Build the iOS 16 system-app registration helper. No image or device writes."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
out = args.output.resolve()
out.mkdir(parents=True, exist_ok=False)
source = ROOT / 'userland/apps'
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
inputs = {str(p.relative_to(ROOT)): sha(p) for p in source.iterdir() if p.is_file()}
catalog = json.loads((source / 'system-apps.json').read_text())
identifier = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
entries = ',\n'.join('@' + json.dumps(k) + ':@' + json.dumps(v) for k,v in catalog['applications'].items())
(out / 'SystemAppsManifest.h').write_text('static NSString *const kSystemAppsManifest=@"' + identifier + '";\n'
    'static NSDictionary *expectedSystemApps(void){return @{\n' + entries + '\n};}\n')
sdk = subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-path'], text=True).strip()
binary = out / 'houji-system-apps'
command = ['xcrun','clang','-target','arm64-apple-ios16.0','-isysroot',sdk,'-O2',
           '-fstack-protector-strong','-fobjc-arc','-Wall','-Wextra','-Werror',
           '-Wno-deprecated-declarations','-I',str(out),str(source/'HoujiSystemApps.m'),
           '-framework','Foundation','-o',str(binary)]
(out/'compile-command.json').write_text(json.dumps(command,indent=2)+'\n')
with (out/'compile.log').open('w') as log:
    subprocess.run(command,check=True,stdout=log,stderr=subprocess.STDOUT)
subprocess.run(['codesign','--force','--sign','-','--timestamp=none','--entitlements',
                str(source/'entitlements.plist'),str(binary)],check=True)
subprocess.run(['codesign','--verify','--strict',str(binary)],check=True)
assert all(sha(ROOT/name)==digest for name,digest in inputs.items())
(out/'build-result.json').write_text(json.dumps({'status':'BUILT_NOT_RUNTIME_VERIFIED',
    'source_inputs':inputs,'manifest':identifier,'binary_sha256':sha(binary),
    'expected_system_apps':len(catalog['applications']),'phone_accessed':False},indent=2)+'\n')
print('Built and signed system-app registrar; actual OS registration is unverified')
