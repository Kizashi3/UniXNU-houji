#!/usr/bin/env python3
"""Build a bounded iOS power-state observer. Does not install or access a device."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True, help='new private build directory')
args = parser.parse_args()
out = args.output.resolve()
out.mkdir(parents=True, exist_ok=False)
sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
source = ROOT / 'userland/power/HoujiPowerProbe.m'
entitlements = ROOT / 'userland/power/entitlements.plist'
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
inputs = {str(path.relative_to(ROOT)): sha(path) for path in
          [source, entitlements, ROOT / 'userland/power/moe.houji.power-probe.plist']}
binary = out / 'houji-power-probe'
command = ['xcrun', 'clang', '-target', 'arm64-apple-ios16.0', '-isysroot', sdk,
           '-O2', '-fstack-protector-strong', '-fobjc-arc', '-Wall', '-Wextra', '-Werror',
           str(source), '-framework', 'Foundation', '-framework', 'CoreFoundation', '-o', str(binary)]
(out / 'compile-command.json').write_text(json.dumps(command, indent=2) + '\n')
with (out / 'compile.log').open('w') as log:
    subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
subprocess.run(['codesign', '--force', '--sign', '-', '--timestamp=none',
                '--entitlements', str(entitlements), str(binary)], check=True)
subprocess.run(['codesign', '--verify', '--strict', str(binary)], check=True)
assert inputs == {name: sha(ROOT / name) for name in inputs}, 'source changed during build'
(out / 'build-result.json').write_text(json.dumps(dict(status='built-not-runtime-verified',
    inputs=inputs, binary_sha256=sha(binary), installed=False, device_accessed=False,
    observes=['NSProcessInfo power/thermal', 'IOPMPowerSource', 'IOPowerSources'],
    power_policy_writes=False, samples=25, interval_seconds=5), indent=2) + '\n')
print('Built and signed iOS power observer; installation and runtime evidence still required')
