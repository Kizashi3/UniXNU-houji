#!/usr/bin/env python3
"""Build the offline Spotlight keyboard candidate; retain installed Preferences v16."""
import hashlib
import json
import plistlib
import shutil
import struct
import subprocess
from pathlib import Path

P = Path(__file__).resolve().parents[1]
N = Path('${HOUJI_ARTIFACTS}/native-port')
HOST = 'Spotlight'
APP = HOST + '.app'
SOURCE = N / ('ios-userland/phone-after-native-r210/inspect-root/Applications/' + APP)
OUT = P / 'out/keyboard-home-v17'
LOAD = '/Applications/' + APP + '/HoujiKeyboardGeometry.dylib'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entitlements(path):
    return subprocess.check_output(['codesign', '-d', '--entitlements', ':-', str(path)], stderr=subprocess.DEVNULL)


def main():
    assert not OUT.exists()
    OUT.mkdir(parents=True)
    app = OUT / APP
    shutil.copytree(SOURCE, app)
    original = app / HOST
    before = original.read_bytes()
    header = struct.unpack_from('<8I', before)
    assert header[:4] == (0xfeedfacf, 0x100000c, 0, 2)
    offset = 32
    first_section = len(before)
    for _ in range(header[4]):
        command, size = struct.unpack_from('<II', before, offset)
        assert size >= 8 and size % 8 == 0
        if command == 0x19:
            count = struct.unpack_from('<I', before, offset + 64)[0]
            for i in range(count):
                section_offset = struct.unpack_from('<I', before, offset + 72 + i * 80 + 48)[0]
                if section_offset:
                    first_section = min(first_section, section_offset)
        if command == 0x2c:
            assert struct.unpack_from('<I', before, offset + 16)[0] == 0, 'Encrypted executable'
        offset += size
    assert offset == 32 + header[5]
    name = LOAD.encode() + b'\0'
    size = (24 + len(name) + 7) & ~7
    assert offset + size <= first_section and before[offset:offset+size] == bytes(size)
    assert name not in before
    modified = bytearray(before)
    command = struct.pack('<6I', 0xc, size, 24, 0, 0x10000, 0x10000) + name
    modified[offset:offset+size] = command.ljust(size, b'\0')
    struct.pack_into('<II', modified, 16, header[4] + 1, header[5] + size)
    assert modified[first_section:] == before[first_section:], 'Original code/data changed'
    original.write_bytes(modified)
    entitlement_bytes = entitlements(SOURCE / HOST)
    entitlement_path = OUT / 'original-entitlements.plist'
    entitlement_path.write_bytes(entitlement_bytes)
    source = P / 'native/display/KeyboardGeometry.mm'
    shutil.copyfile(source, OUT / source.name)
    sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
    library = app / 'HoujiKeyboardGeometry.dylib'
    cmd = ['xcrun', 'clang++', '-target', 'arm64-apple-ios16.0', '-isysroot', sdk,
           '-O2', '-fstack-protector-strong', '-std=c++17', '-fobjc-arc',
           '-Wno-deprecated-declarations', '-DHOUJI_KEYBOARD_HOST=\"' + HOST + '\"', '-dynamiclib', '-install_name', LOAD,
           str(source), '-lobjc', '-framework', 'Foundation', '-o', str(library)]
    (OUT / 'compile-command.json').write_text(json.dumps(cmd, indent=2) + '\n')
    subprocess.run(cmd, check=True)
    subprocess.run(['strip', '-x', str(library)], check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', '--pagesize', '4096', str(library)], check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', '--pagesize', '4096',
                    '--entitlements', str(entitlement_path), '--generate-entitlement-der', str(app)], check=True)
    for path in (app, library):
        subprocess.run(['codesign', '--verify', '--strict', str(path)], check=True)
    assert plistlib.loads(entitlements(original)) == plistlib.loads(entitlement_bytes), 'Entitlements changed'
    original_files = {str(f.relative_to(SOURCE)): sha(f) for f in SOURCE.rglob('*') if f.is_file()}
    final_files = {str(f.relative_to(app)): sha(f) for f in app.rglob('*') if f.is_file()}
    changed = {f for f in final_files if final_files[f] != original_files.get(f)}
    assert changed == {HOST, '_CodeSignature/CodeResources', 'HoujiKeyboardGeometry.dylib'}
    assert set(original_files) <= set(final_files)
    report = dict(status='local-build-and-signatures-passed',
                  keyboard_host=HOST, original_executable_sha256=hashlib.sha256(before).hexdigest(),
                  source_sha256=sha(source), load_command=LOAD,
                  original_entitlements_preserved=True, original_code_data_unchanged_before_resigning=True,
                  changed_files={f: final_files[f] for f in sorted(changed)},
                  unchanged_files={f: final_files[f] for f in final_files if f not in changed},
                  scope='Spotlight portrait keyboard size only; installed Preferences v16 and display/GPU unchanged',
                  phone_accessed=False, hardware_tested=False)
    (OUT / 'build-result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
