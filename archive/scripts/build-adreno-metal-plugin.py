#!/usr/bin/env python3
"""Build the pinned AdrenoMetal frontend for houji/iOS 16; never access the phone.

The output is a frontend candidate, not evidence of a working A750 backend.
The translator is the exact upstream pin plus AdrenoMetal's seven recorded patches.
Source adaptations are applied to an output copy, leaving AdrenoMetal untouched.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PINS = {
    'adrenometal': '454ff2ce83766ce7b3e0f355e83f1d72907708b3',
    'translator': '720ef1ce9ae2a2068999a8675717418b9416283e',
    'native_adreno': 'b686b9054f57d393c80195b82568a09f8ca106a2',
    'pm4': '445f8fe6d115738352b9d78dc70af6d61aa7f62f',
    'gop_framebuffer': '8666a9950c9699b368931d18cac92c0fdb2ce9c0',
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(argv, *, env=None, cwd=None, output=False):
    result = subprocess.run([str(x) for x in argv], cwd=cwd, env=env,
                            stdout=subprocess.PIPE if output else None,
                            stderr=subprocess.STDOUT if output else None, check=True)
    return result.stdout.decode() if output else None


def canonical(diff):
    blocks = [b for b in re.split(r'(?=^diff --git )', diff, flags=re.M) if b]
    names = [b.splitlines()[0] for b in blocks]
    if len(names) != len(set(names)):
        raise RuntimeError('overlapping translator patches require a combined-source update')
    return ''.join(sorted(blocks, key=lambda b: b.splitlines()[0]))


def macho(path):
    data = path.read_bytes()
    magic, cpu, subtype, kind, count, size, flags, reserved = struct.unpack_from('<8I', data)
    if (magic, cpu, subtype & 0xffffff, kind) != (0xfeedfacf, 0x100000c, 0, 8):
        raise RuntimeError('expected ordinary ARM64 Mach-O bundle')
    at = 32
    minimum = None
    for _ in range(count):
        cmd, length = struct.unpack_from('<2I', data, at)
        if length < 8 or at + length > 32 + size:
            raise RuntimeError('invalid Mach-O load commands')
        if cmd == 0x25:  # LC_VERSION_MIN_IPHONEOS
            minimum = struct.unpack_from('<I', data, at + 8)[0]
        elif cmd == 0x32:  # LC_BUILD_VERSION
            platform, version = struct.unpack_from('<2I', data, at + 8)
            if platform != 2:
                raise RuntimeError('bundle is not for the iOS device platform')
            minimum = version
        at += length
    if minimum != 0x100000:
        raise RuntimeError(f'expected iOS 16.0 minimum, got {minimum!r}')
    return {'cpu': 'arm64', 'platform': 'iOS', 'minimum_os': '16.0', 'filetype': 'MH_BUNDLE'}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in PINS:
        ap.add_argument('--' + name.replace('_', '-'), type=Path, required=True)
    ap.add_argument('--llvm-as', type=Path, required=True)
    ap.add_argument('--spirv-val', type=Path, required=True)
    ap.add_argument('--vulkan-include', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--cargo', default='cargo')
    ap.add_argument('--cargo-target-dir', type=Path)
    ap.add_argument('--adaptation', type=Path,
                    default=ROOT / 'native/gpu/metal/adrenometal-ios16.patch')
    ap.add_argument('--glslc', default='glslc')
    args = ap.parse_args()
    sources = {key: getattr(args, key).resolve() for key in PINS}
    for key, pin in PINS.items():
        if run(['git', '-C', sources[key], 'rev-parse', 'HEAD'], output=True).strip() != pin:
            raise RuntimeError(f'{key} revision does not match {pin}')
        if key != 'translator' and run(['git', '-C', sources[key], 'status', '--porcelain', '--untracked-files=no'], output=True):
            raise RuntimeError(f'{key} has unrecorded source changes')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    # Never leave a stale success report after an unsuccessful rebuild.
    (out / 'build-result.json').unlink(missing_ok=True)
    patches = sorted((sources['adrenometal'] / 'bridge/patches').glob('000*.patch'))
    if len(patches) != 7:
        raise RuntimeError('this build qualifies exactly seven AdrenoMetal translator patches')
    expected = canonical(''.join(p.read_text() for p in patches))
    diff = run(['git', '-C', sources['translator'], 'diff', '--abbrev=7', 'HEAD', '--'], output=True)
    if not diff:
        run(['git', '-C', sources['translator'], 'apply', '--check', *patches])
        run(['git', '-C', sources['translator'], 'apply', *patches])
        diff = run(['git', '-C', sources['translator'], 'diff', '--abbrev=7', 'HEAD', '--'], output=True)
    if diff != expected:
        raise RuntimeError('translator differs from the pin plus its exact recorded patches')
    (out / 'translator.diff').write_text(diff)
    candidate = out / 'source/AdrenoMetal'
    if candidate.exists():
        shutil.rmtree(candidate)
    candidate.mkdir(parents=True)
    tracked = run(['git', '-C', sources['adrenometal'], 'ls-files'], output=True).splitlines()
    for name in tracked:
        dest = candidate / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sources['adrenometal'] / name, dest)
    # The canonical repository name is GopFramebuffer; the preserved runtime
    # source include still names its former sibling NativeMobileDisplay.
    wire = out / 'source/NativeMobileDisplay/NativeGOPWire.h'
    wire.parent.mkdir(exist_ok=True)
    shutil.copy2(sources['gop_framebuffer'] / 'NativeGOPWire.h', wire)
    adaptation = args.adaptation.resolve()
    run(['git', 'apply', '--no-index', '--check', adaptation], cwd=candidate)
    run(['git', 'apply', '--no-index', adaptation], cwd=candidate)
    llvm_env = dict(os.environ)
    env = dict(os.environ, IPHONEOS_DEPLOYMENT_TARGET='16.0')
    # An extracted LLVM bottle may need local dylib search paths. Do not inject
    # its libc++ into Rust, Xcode, codesign or other unrelated build tools.
    env.pop('DYLD_LIBRARY_PATH', None)
    air = out / 'runtime_examples.air'
    fc_air = out / 'function_constant.air'
    fixtures = sources['translator'] / 'crates/metal2vulkan-validation/fixtures/public'
    run([args.llvm_as, '-o', air, fixtures / 'examples/runtime_examples.ll'], env=llvm_env)
    run([args.llvm_as, '-o', fc_air, fixtures / 'kernel_function_constant_gate_fold.ll'], env=llvm_env)
    runtime_id = hashlib.sha256((PINS['translator'] + '\n' + diff).encode()).hexdigest()[:32]
    env.update(NMB_RUNTIME_ID=runtime_id, NMB_FIXTURE_AIR=str(air), NMB_FC_AIR=str(fc_air))
    manifest = out / 'Cargo.toml'
    manifest.write_text('\n'.join([
        '[package]', 'name = "native-metal-bridge"', 'version = "0.1.0"',
        'edition = "2024"', 'rust-version = "1.98"', '[workspace]', '[lib]',
        'crate-type = ["staticlib"]', 'path = ' + json.dumps(str(candidate / 'bridge/NativeMetalBridge.rs')),
        '[dependencies]',
        'metal2vulkan = { path = ' + json.dumps(str(sources['translator'] / 'crates/metal2vulkan')) + ', features = ["ash"] }',
        'metal2vulkan-runtime = { path = ' + json.dumps(str(sources['translator'] / 'crates/metal2vulkan-runtime')) + ' }',
        'libc = "0.2"', 'sha2 = { version = "0.10", features = ["asm"] }',
        '[profile.release]', 'panic = "unwind"', 'debug = 1', '',
    ]))
    cargo = [args.cargo, '+1.98.0']
    if not (out / 'Cargo.lock').exists():
        run([*cargo, 'generate-lockfile', '--manifest-path', manifest], env=env)
    target_dir = args.cargo_target_dir.resolve() if args.cargo_target_dir else out / 'target'
    run([*cargo, 'build', '--locked', '--release', '--manifest-path', manifest,
         '--target', 'aarch64-apple-ios', '--target-dir', target_dir], env=env)
    bridge = target_dir / 'aarch64-apple-ios/release/libnative_metal_bridge.a'
    gen = out / 'gen'
    gen.mkdir(exist_ok=True)
    header = ['// Generated from AdrenoMetal authored smoke shaders; validated SPIR-V.', '#pragma once', '#include <stdint.h>']
    shaders = []
    for source in sorted((candidate / 'shaders').glob('smoke_*')):
        spv = out / (source.name + '.spv')
        run([args.glslc, '--target-env=vulkan1.1', '-O', source, '-o', spv], env=env)
        run([args.spirv_val, '--target-env', 'vulkan1.1', spv], env=env)
        data = spv.read_bytes()
        words = struct.unpack('<' + str(len(data) // 4) + 'I', data)
        if words[0] != 0x07230203:
            raise RuntimeError('SPIR-V magic mismatch')
        header.append('static const uint32_t kSpv_' + source.name.replace('.', '_') + '[] = {')
        header.extend('  ' + ', '.join(f'0x{w:08x}' for w in words[i:i+8]) + ',' for i in range(0, len(words), 8))
        header.append('};')
        shaders.append({'name': source.name, 'sha256': sha(spv), 'spirv_val': 'pass'})
    (gen / 'NativeTurnipShaders.h').write_text('\n'.join(header) + '\n')
    sdk = run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], output=True).strip()
    base = ['-target', 'arm64-apple-ios16.0', '-isysroot', sdk, '-O2', '-g', '-fstack-protector-strong']
    pm4 = out / 'AdrenoPM4.o'
    run(['xcrun', 'clang', *base, '-std=c11', '-c', sources['pm4'] / 'AdrenoPM4.c', '-o', pm4], env=env)
    bundle = out / 'NativeAdrenoMetal.bundle'
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir()
    exe = bundle / 'NativeAdrenoMetal'
    run(['xcrun', 'clang++', *base, '-std=c++17', '-fobjc-arc', '-Wno-deprecated-declarations', '-bundle',
         '-I', sources['native_adreno'], '-I', sources['pm4'], '-I', args.vulkan_include, '-I', gen,
         '-x', 'objective-c++', candidate / 'NativeAdrenoMetalPlugin.mm', candidate / 'NativeBridgeMetalFrontend.mm',
         '-x', 'none', pm4, bridge, '-Wl,-dead_strip', '-lobjc', '-framework', 'Foundation',
         '-framework', 'Metal', '-framework', 'IOSurface', '-o', exe], env=env)
    run(['strip', '-x', exe])
    dsym = bundle / 'NativeAdrenoMetal.dSYM'
    if dsym.exists():
        target = out / dsym.name
        if target.exists():
            shutil.rmtree(target)
        shutil.move(dsym, target)
    (bundle / 'Info.plist').write_bytes(plistlib.dumps({
        'CFBundleIdentifier': 'org.blu-sharky.NativeAdrenoMetal', 'CFBundleExecutable': 'NativeAdrenoMetal',
        'CFBundlePackageType': 'BNDL', 'CFBundleVersion': '1', 'CFBundleShortVersionString': '1',
        'NSPrincipalClass': 'NativeAdrenoMetalDevice', 'MinimumOSVersion': '16.0',
    }))
    # Finder can tag a newly generated bundle in an iCloud-backed output folder.
    # Remove only signing-incompatible metadata from our own generated artifacts.
    for path in (bundle, *bundle.rglob('*')):
        names = run(['/usr/bin/xattr', path], output=True).splitlines()
        for name in ('com.apple.FinderInfo', 'com.apple.ResourceFork'):
            if name in names:
                run(['/usr/bin/xattr', '-d', name, path])
    run(['codesign', '--force', '--sign', '-', '--pagesize', '4096', '--identifier',
         'org.blu-sharky.NativeAdrenoMetal', bundle])
    run(['codesign', '--verify', '--strict', bundle])
    signature = run(['codesign', '-d', '--verbose=4', bundle], output=True)
    cdhash = re.search(r'^CDHash=([a-f0-9]{40})$', signature, re.M)[1]
    if not re.search(r'^Page size=4096$', signature, re.M):
        raise RuntimeError('expected a 4 KiB signing page')
    probe = out / 'adrenometalprobe'
    run(['xcrun', 'clang++', *base, '-std=c++17', '-fobjc-arc', '-Wall', '-Wextra', '-Werror',
         '-I', sources['native_adreno'], '-I', candidate / 'bridge',
         ROOT / 'native/gpu/metal/AdrenoMetalProbe.mm', '-framework', 'Foundation', '-framework', 'Metal',
         '-framework', 'IOSurface', '-o', probe], env=env)
    entitlements = out / 'probe-entitlements.plist'
    entitlements.write_bytes(plistlib.dumps({
        'com.apple.private.security.no-container': True,
        'com.apple.security.iokit-user-client-class': ['AGXDeviceUserClient'],
    }))
    run(['codesign', '--force', '--sign', '-', '--pagesize', '4096', '--identifier',
         'org.unixnu.houji.adrenometalprobe', '--entitlements', entitlements, probe])
    run(['codesign', '--verify', '--strict', probe])
    result = {
        'component': 'AdrenoMetal', 'board': 'houji', 'os': 'iOS 16.7.16 20H392',
        'pins': PINS, 'translator_runtime_id': runtime_id,
        'translator_patch_sha256': {p.name: sha(p) for p in patches},
        'adaptation_sha256': sha(adaptation), 'cargo_lock_sha256': sha(out / 'Cargo.lock'),
        'adaptation_path': str(adaptation),
        'bundle': str(bundle), 'executable_sha256': sha(exe), 'executable_bytes': exe.stat().st_size,
        'bridge_sha256': sha(bridge), 'cdhash': cdhash, 'code_signing_page_size': 4096,
        'probe': str(probe), 'probe_sha256': sha(probe),
        'probe_source_sha256': sha(ROOT / 'native/gpu/metal/AdrenoMetalProbe.mm'),
        'probe_hardware_tested': False,
        'mach_o': macho(exe), 'smoke_shaders': shaders,
        'linked_libraries': run(['otool', '-L', exe], output=True).splitlines()[1:],
        'hardware_tested': False, 'phone_accessed': False, 'gpu_acceleration_verified': False,
        'device_deployable': False,
        'remaining': ['iOS Turnip native backend', 'A750 XNU command submission and real fence/writeback',
                      'on-device ABI/plugin test', 'render/IOSurface readback', 'desktop acceleration'],
    }
    (out / 'build-result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'result': str(out / 'build-result.json'), 'bundle': str(bundle),
                      'minimum_os': '16.0', 'hardware_tested': False}, indent=2))


if __name__ == '__main__':
    main()
