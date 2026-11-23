#!/usr/bin/env python3
"""Offline host checks only. Writes outputs beside this file, never to the repo."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess

HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--repo', type=Path, default=Path('${HOUJI_PORT_ROOT}'))
parser.add_argument('--firmware', type=Path, default=Path('${HOUJI_ARTIFACTS}/native-research/houji-gpu-firmware-20261025/gmu_gen70900.bin'))
args = parser.parse_args()
repo = args.repo.resolve()
firmware = args.firmware.resolve()
blob = firmware.read_bytes()
expected_sha = '9685f62c42543befcaee68d25355e16bf55cdb0d573bddcc9f6633f59eec3f72'
def identity(data):
    return len(data) == 78588 and hashlib.sha256(data).hexdigest() == expected_sha
assert identity(blob), 'caller firmware identity refused before bridge/allocation'
assert not identity(blob[:-1])
changed = bytearray(blob)
changed[1000] ^= 1
assert not identity(changed), 'caller must reject changed identity before bridge/allocation'
build = HERE / 'build'
build.mkdir(exist_ok=True)
gpu = repo / 'native/gpu'
sources = [
    HERE / 'houji_hfi_inactive.c',
    gpu / 'vendor/AdrenoFirmware/AdrenoFirmware.c',
    gpu / 'vendor/ArmSmmu4K/ArmSmmu4K.c',
    gpu / 'vendor/ArmSmmu4K/ArmSmmu4KContext.c',
    gpu / 'vendor/ArmSmmu4K/ArmSmmu4KProgram.c',
    gpu / 'vendor/ArmSmmu4K/ArmSmmu4KAudit.c',
]
common = ['-g', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
          '-Wno-misleading-indentation', '-Wno-sign-compare', '-fsanitize=address,undefined',
          '-fno-omit-frame-pointer', '-I', str(HERE), '-I', str(gpu), '-I', str(gpu / 'uefi')]
commands = []

def run(command):
    commands.append(command)
    subprocess.run(command, check=True)

objects = []
dependencies = set()
for index, source in enumerate(sources):
    obj = build / f'{index}-{source.stem}.o'
    depfile = build / f'{index}-{source.stem}.d'
    run(['clang', '-std=c11', *common, '-MMD', '-MF', str(depfile), '-c', str(source), '-o', str(obj)])
    prerequisite_text = depfile.read_text().replace('\\\n', ' ').split(':', 1)[1]
    dependencies.update(Path(name).resolve() for name in shlex.split(prerequisite_text))
    objects.append(str(obj))
for test, compiler, standard in [('test_houji_hfi_inactive.c', 'clang', 'c11'), ('test_cpp14.cpp', 'clang++', 'c++14')]:
    output = build / Path(test).stem
    run([compiler, f'-std={standard}', *common, str(HERE / test), *objects, '-o', str(output)])
    run([str(output), str(firmware)] if test.endswith('.c') else [str(output)])

# The isolated consumer sees only the public POD header, with no upstream
# implementation or include directories available.
run(['clang++', '-std=c++14', '-pedantic-errors', '-Wall', '-Wextra', '-Werror',
     '-I', str(HERE), '-fsyntax-only', str(HERE / 'test_cpp14.cpp')])
manifest = {
    'scope': 'offline CPU-only candidate; no device, MMIO, SMC, TTBR or firmware execution',
    'repo': str(repo), 'firmware': str(firmware), 'firmware_bytes': len(blob),
    'firmware_sha256': expected_sha, 'sanitizers': ['address', 'undefined'],
    'commands': commands,
    'sources': {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
    'compile_dependencies': {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in sorted(dependencies)},
    'tests': {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
              for name in ['houji_hfi_inactive.h', 'test_houji_hfi_inactive.c', 'test_cpp14.cpp', 'run_tests.py']},
    'result': 'PASS',
}
(build / 'verification.json').write_text(json.dumps(manifest, indent=2) + '\n')
print('PASS: caller SHA-256, ASan/UBSan C/C++14 binaries and isolated public-header syntax')
