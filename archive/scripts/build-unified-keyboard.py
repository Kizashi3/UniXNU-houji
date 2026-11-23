#!/usr/bin/env python3
"""Build one geometry library and automatically bind system APPL bundles to it.

No device access. Each main executable retains its code/data and entitlements;
only a weak absolute dependency, the high-rate opt-in and resource signing change.
"""
import hashlib
import json
import plistlib
import shutil
import struct
import subprocess
from pathlib import Path

P = Path(__file__).resolve().parents[1]
N = Path('${HOUJI_ARTIFACTS}/native-port')
ROOT = N / 'ios-userland/phone-after-native-r213/inspect-root'
OUT = P / 'out/keyboard-unified-v18'
LOAD = '/usr/lib/HoujiKeyboardGeometry.dylib'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entitlements(path):
    raw = subprocess.check_output(['codesign', '-d', '--entitlements', ':-', str(path)], stderr=subprocess.DEVNULL)
    return (plistlib.loads(raw) if raw.strip() else None), raw


def dependency(before):
    header = struct.unpack_from('<8I', before)
    assert header[:4] == (0xfeedfacf, 0x100000c, 0, 2)
    offset, first, previous = 32, len(before), None
    for _ in range(header[4]):
        command, size = struct.unpack_from('<II', before, offset)
        assert size >= 8 and size % 8 == 0
        if command == 0x19:
            for i in range(struct.unpack_from('<I', before, offset + 64)[0]):
                start = struct.unpack_from('<I', before, offset + 72 + i * 80 + 48)[0]
                if start:
                    first = min(first, start)
        if command == 0x2c:
            assert struct.unpack_from('<I', before, offset + 16)[0] == 0
        if command in (0xc, 0x80000018):
            name_at = struct.unpack_from('<I', before, offset + 8)[0]
            name = before[offset + name_at:offset + size].split(b'\0')[0]
            if name.endswith(b'/HoujiKeyboardGeometry.dylib'):
                assert previous is None
                previous = (offset, size)
        offset += size
    assert offset == 32 + header[5]
    name = LOAD.encode() + b'\0'
    size = (24 + len(name) + 7) & ~7
    modified = bytearray(before)
    if previous:
        offset, room = previous
        assert size <= room
        size = room
    else:
        assert offset + size <= first and before[offset:offset + size] == bytes(size)
        struct.pack_into('<II', modified, 16, header[4] + 1, header[5] + size)
    command = struct.pack('<6I', 0x80000018, size, 24, 0, 0x10000, 0x10000) + name
    modified[offset:offset + size] = command.ljust(size, b'\0')
    assert modified[first:] == before[first:]
    return modified


def main():
    assert not OUT.exists()
    OUT.mkdir(parents=True)
    source = P / 'native/display/UnifiedKeyboardGeometry.mm'
    library = OUT / 'HoujiKeyboardGeometry.dylib'
    sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
    cmd = ['xcrun', 'clang++', '-target', 'arm64-apple-ios16.0', '-isysroot', sdk,
           '-O2', '-fstack-protector-strong', '-std=c++17', '-fobjc-arc',
           '-Wno-deprecated-declarations', '-dynamiclib', '-install_name', LOAD,
           str(source), '-lobjc', '-framework', 'Foundation', '-o', str(library)]
    (OUT / 'compile-command.json').write_text(json.dumps(cmd, indent=2) + '\n')
    subprocess.run(cmd, check=True)
    subprocess.run(['strip', '-x', str(library)], check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', '--pagesize', '4096', str(library)], check=True)
    subprocess.run(['codesign', '--verify', '--strict', str(library)], check=True)
    shutil.copyfile(source, OUT / source.name)
    apps = []
    for directory in (ROOT / 'Applications', ROOT / 'System/Library/CoreServices'):
        for bundle in sorted(directory.rglob('*.app')):
            info_path = bundle / 'Info.plist'
            if not info_path.is_file():
                continue
            info = plistlib.loads(info_path.read_bytes())
            if info.get('CFBundlePackageType') != 'APPL':
                continue
            executable = bundle / info['CFBundleExecutable']
            if not executable.is_file():
                continue
            relative = str(bundle.relative_to(ROOT))
            app = OUT / 'apps' / relative
            app.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(['cp', '-cR', str(bundle), str(app)], check=True)
            binary = app / executable.name
            before = binary.read_bytes()
            original_entitlements, raw = entitlements(executable)
            binary.write_bytes(dependency(before))
            info['CADisableMinimumFrameDurationOnPhone'] = True
            (app / 'Info.plist').write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY, sort_keys=False))
            sign = ['codesign', '--force', '--sign', '-', '--pagesize', '4096']
            if original_entitlements is not None:
                ent = OUT / 'entitlements' / (str(len(apps)) + '.plist')
                ent.parent.mkdir(exist_ok=True)
                ent.write_bytes(raw)
                sign += ['--entitlements', str(ent), '--generate-entitlement-der']
            subprocess.run(sign + [str(app)], check=True, capture_output=True)
            subprocess.run(['codesign', '--verify', '--strict', str(app)], check=True, capture_output=True)
            assert entitlements(binary)[0] == original_entitlements
            changed = [executable.name, 'Info.plist', '_CodeSignature/CodeResources']
            before_files = {str(f.relative_to(bundle)): sha(f) for f in bundle.rglob('*') if f.is_file()}
            after_files = {str(f.relative_to(app)): sha(f) for f in app.rglob('*') if f.is_file()}
            assert before_files.keys() == after_files.keys()
            assert {f for f in after_files if before_files[f] != after_files[f]} <= set(changed)
            metadata = {}
            for rel in changed:
                st = (bundle / rel).stat()
                metadata[rel] = dict(before_sha256=before_files[rel], sha256=after_files[rel],
                                     uid=st.st_uid, gid=st.st_gid, mode=st.st_mode & 0o777,
                                     original_links=st.st_nlink)
            apps.append(dict(app=relative, executable=executable.name, items=metadata,
                             untouched={f: v for f, v in before_files.items() if f not in changed},
                             original_entitlements_preserved=True,
                             original_code_data_unchanged_before_resigning=True,
                             high_rate_opt_in=True, signed=True))
            if len(apps) % 25 == 0:
                print(f'{len(apps)} application bundles prepared', flush=True)
    required = {'Applications/Preferences.app', 'Applications/Spotlight.app',
                'System/Library/CoreServices/SpringBoard.app'}
    assert required <= {r['app'] for r in apps} and len(apps) > 100
    report = dict(status='local-build-and-signatures-passed', source_sha256=sha(source),
                  library_sha256=sha(library), load_command=LOAD,
                  dependency_kind='LC_LOAD_WEAK_DYLIB', applications=apps,
                  application_count=len(apps), phone_accessed=False, hardware_tested=False,
                  scope='One shared iOS16 keyboard rule, automatically bound to system APPL bundles; per-app high-frame-rate permission; no screen resampling')
    (OUT / 'build-result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ('status', 'application_count', 'library_sha256', 'phone_accessed')}, indent=2))


if __name__ == '__main__':
    main()
