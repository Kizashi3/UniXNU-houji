#!/usr/bin/env python3
"""Build the board's keyboard and status-bar compatibility library; no installation."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True, help='new local build directory')
args = parser.parse_args()
out = args.output.resolve()
out.mkdir(parents=True, exist_ok=False)
sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
source = ROOT / 'userland/display/UnifiedKeyboardGeometry.mm'
digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
sources = (source, source.with_name('HoujiStatusBarGeometry.h'))
inputs = {str(path.relative_to(ROOT)): digest(path) for path in sources}
library = out / 'HoujiKeyboardGeometry.dylib'
command = ['xcrun', 'clang++', '-target', 'arm64-apple-ios16.0', '-isysroot', sdk,
           '-O2', '-fstack-protector-strong', '-std=c++17', '-fobjc-arc',
           '-Wall', '-Wextra', '-Werror', '-Wno-deprecated-declarations', '-dynamiclib',
           '-install_name', '/usr/lib/HoujiKeyboardGeometry.dylib', str(source),
           '-lobjc', '-framework', 'Foundation', '-o', str(library)]
(out / 'compile-command.json').write_text(json.dumps(command, indent=2) + '\n')
with (out / 'compile.log').open('w') as log:
    subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
subprocess.run(['codesign', '--force', '--sign', '-', '--timestamp=none', str(library)], check=True)
subprocess.run(['codesign', '--verify', '--strict', str(library)], check=True)
assert inputs == {str(path.relative_to(ROOT)): digest(path) for path in sources}, 'sources changed during build'
report = dict(status='built-not-hardware-qualified', inputs=inputs, sdk=sdk,
              library_sha256=digest(library), installed=False, device_accessed=False)
(out / 'build-result.json').write_text(json.dumps(report, indent=2) + '\n')
print('Built compatibility library; target-userland imports and runtime behavior still require validation')
