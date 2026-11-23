#!/usr/bin/env python3
"""Build AdrenoMetal's recorded Turnip Darwin backend for iOS 16, without phone access."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess


def run(cmd, *, env=None, output=False):
    result = subprocess.run([str(x) for x in cmd], env=env, check=True,
                            stdout=subprocess.PIPE if output else None,
                            stderr=subprocess.STDOUT if output else None)
    return result.stdout.decode().strip() if output else None


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for key in ('unixnu', 'mesa', 'native-adreno', 'meson', 'tool-bin', 'output'):
        ap.add_argument('--' + key, type=Path, required=True)
    args = ap.parse_args()
    u, source, abi, out = (x.resolve() for x in (args.unixnu, args.mesa, args.native_adreno, args.output))
    pins = json.loads((u / 'scripts/data/adreno-compiler-inputs.json').read_text())
    pin = '85fda3b36405bcaea8bffc64aa4f2651dc90770d'
    if pins['mesa']['commit'] != pin or run(['git', '-C', source, 'rev-parse', 'HEAD'], output=True) != pin:
        raise RuntimeError('Mesa source must match the recorded AdrenoMetal compiler pin')
    if run(['git', '-C', abi, 'rev-parse', 'HEAD'], output=True) != 'b686b9054f57d393c80195b82568a09f8ca106a2':
        raise RuntimeError('NativeAdreno ABI pin mismatch')
    if run(['git', '-C', abi, 'status', '--porcelain', '--untracked-files=no'], output=True):
        raise RuntimeError('NativeAdreno has unrecorded changes')
    out.mkdir(parents=True, exist_ok=True)
    (out / 'build-result.json').unlink(missing_ok=True)
    diff = run(['git', '-C', source, 'diff', 'HEAD', '--binary'], output=True)
    if not diff:
        for name in pins['patches']:
            run(['git', '-C', source, 'apply', '--check', u / name])
            run(['git', '-C', source, 'apply', u / name])
    spec = importlib.util.spec_from_file_location('mesa_patch_identity', u / 'scripts/mesa_patch_identity.py')
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    (u / '.cache').mkdir(exist_ok=True)
    guard.validate_recorded_patches(u, source, pins)
    diff = run(['git', '-C', source, 'diff', '--abbrev=7', 'HEAD', '--binary'], output=True)
    extras = run(['git', '-C', source, 'ls-files', '--others', '--exclude-standard'], output=True).splitlines()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('IR3_', 'FD_MESA_', 'NIR_', 'MESA_SHADER_', 'TU_'))}
    env.pop('DYLD_LIBRARY_PATH', None)
    env['PATH'] = str(args.meson.resolve().parent) + ':' + str(args.tool_bin.resolve()) + ':' + env['PATH']
    sdk = run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], output=True)
    find = lambda tool: run(['xcrun', '--sdk', 'iphoneos', '--find', tool], output=True)
    cc, cxx = find('clang'), find('clang++')
    flags = ['-target', 'arm64-apple-ios16.0', '-isysroot', sdk, '-fstack-protector-strong']
    cross = out / 'ios.cross'
    cross.write_text('[binaries]\n' + ''.join(f'{k} = {v!r}\n' for k, v in {
        'c': cc, 'cpp': cxx, 'objc': cc, 'ar': find('ar'), 'strip': find('strip'), 'pkg-config': '/usr/bin/false',
    }.items()) + "[host_machine]\nsystem = 'darwin'\ncpu_family = 'aarch64'\ncpu = 'arm64'\nendian = 'little'\n"
        '[properties]\nneeds_exe_wrapper = true\n[built-in options]\n' +
        ''.join(f'{key} = {flags!r}\n' for key in ('c_args', 'cpp_args', 'objc_args', 'c_link_args', 'cpp_link_args', 'objc_link_args')))
    options = [
        '-Dgallium-drivers=', '-Dvulkan-drivers=freedreno', '-Dfreedreno-kmds=darwin',
        '-Dtu-darwin-abi-dir=' + str(abi), '-Dplatforms=macos', '-Dglx=disabled', '-Degl=disabled',
        '-Dgbm=disabled', '-Dopengl=false', '-Dgles1=disabled', '-Dgles2=disabled', '-Dllvm=disabled',
        '-Dshared-glapi=disabled', '-Dxmlconfig=disabled', '-Dshader-cache=disabled', '-Dtools=',
        '-Dbuild-tests=false', '-Dvideo-codecs=', '-Dvulkan-layers=', '-Dlibunwind=disabled',
        '-Dlmsensors=disabled', '-Dvalgrind=disabled', '-Dexpat=disabled', '-Dzstd=disabled',
        '-Dbuildtype=release', '-Db_ndebug=true',
    ]
    identity = {
        'mesa_revision': pin, 'diff_sha256': hashlib.sha256(diff.encode()).hexdigest(),
        'added_sources': {name: digest(source / name) for name in extras},
        'patch_sha256': {name: digest(u / name) for name in pins['patches']},
        'abi_sha256': digest(abi / 'NativeAdrenoABI.h'), 'target': 'arm64-apple-ios16.0',
        'compiler': run([cxx, '--version'], output=True), 'options': options,
    }
    source_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    options += ['-Dtu-builtin-source-id=' + source_id, '-Dtu-builtin-pack-header=']
    (out / 'source-identity.json').write_text(json.dumps(identity, indent=2) + '\n')
    env.update(CC=cc, CXX=cxx, CFLAGS='', CXXFLAGS='', CPPFLAGS='', LDFLAGS='')
    build = out / 'build'
    setup = [args.meson, 'setup', build, source, '--cross-file', cross, '--wrap-mode=nodownload']
    if (build / 'build.ninja').exists():
        setup = [args.meson, 'setup', '--reconfigure', '--clearcache', build, source,
                 '--cross-file', cross, '--wrap-mode=nodownload']
    run([*setup, *options], env=env)
    run(['ninja', '-C', build, '-j6', 'src/freedreno/vulkan/libvulkan_freedreno.dylib'], env=env)
    library = out / 'libvulkan_freedreno.dylib'
    shutil.copy2(build / 'src/freedreno/vulkan/libvulkan_freedreno.dylib', library)
    run(['install_name_tool', '-id', '/usr/lib/libvulkan_freedreno.dylib', library])
    run(['strip', '-x', library])
    symbols = run(['nm', '-gU', library], output=True)
    if ' T _vk_icdGetInstanceProcAddr' not in symbols or ' T _vkGetInstanceProcAddr' not in symbols:
        raise RuntimeError('Turnip Vulkan entrypoints are missing')
    commands = run(['otool', '-l', library], output=True)
    if 'version 16.0' not in commands and 'minos 16.0' not in commands:
        raise RuntimeError('expected iOS 16.0 minimum')
    run(['codesign', '--force', '--sign', '-', '--pagesize', '4096', '--identifier', 'org.blu-sharky.turnip', library])
    run(['codesign', '--verify', '--strict', library])
    result = {
        'component': 'Turnip Darwin for AdrenoMetal', 'source_id': source_id, 'mesa_revision': pin,
        'library': str(library), 'sha256': digest(library), 'bytes': library.stat().st_size,
        'abi_sha256': identity['abi_sha256'], 'target': 'arm64-apple-ios16.0',
        'linked_libraries': run(['otool', '-L', library], output=True).splitlines()[1:],
        'signature': run(['codesign', '-d', '--verbose=4', library], output=True),
        'hardware_tested': False, 'phone_accessed': False, 'gpu_acceleration_verified': False,
    }
    (out / 'build-result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'result': str(out / 'build-result.json'), 'library': str(library), 'hardware_tested': False}))


if __name__ == '__main__':
    main()
