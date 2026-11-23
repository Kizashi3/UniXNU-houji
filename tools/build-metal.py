#!/usr/bin/env python3
"""Build the pinned iOS 16 Metal bundle from public sources and local inputs.

No image mounting, installation or device access. SDK, AIR and Turnip stay local.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_primelist(path):
    """Keep an OS-specific list in the bundle when its sandbox cannot read a sidecar."""
    text = path.read_text()
    if len(text.encode()) > 256 * 1024:
        raise ValueError('shader prime list exceeds 256 KiB')
    paths = set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if '\0' in line or not line.startswith('/') or '..' in Path(line).parts or not line.endswith('.metallib'):
            raise ValueError('prime list must contain absolute OS .metallib paths')
        paths.add(line)
    if not paths:
        raise ValueError('shader prime list is empty')
    return ''.join(path + '\n' for path in sorted(paths))


def extract_debug_symbols(bundle, output):
    """Keep clang's adjacent dSYM out of the signed runtime resource envelope."""
    symbols = bundle / 'NativeAdrenoMetal.dSYM'
    if not symbols.exists():
        return
    destination = output / symbols.name
    if symbols.is_symlink() or destination.is_symlink() or destination == symbols:
        raise ValueError('debug symbols require distinct ordinary output directories')
    if destination.exists():
        shutil.rmtree(destination)
    shutil.move(str(symbols), str(destination))


def runtime_variant_id(source_id, diagnostic):
    """Keep diagnostic texture contents and ordinary cached artifacts distinct."""
    if diagnostic not in (None, 'green'):
        raise ValueError('unknown fresh-pattern diagnostic')
    if diagnostic is None:
        return source_id
    return hashlib.sha256((source_id + ':houji-fresh-pattern:' + diagnostic).encode()).hexdigest()[:32]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, default=ROOT / '.deps/metal2vulkan')
    parser.add_argument('--mesa-include', type=Path, required=True)
    parser.add_argument('--fixture-air', type=Path, required=True)
    parser.add_argument('--function-constant-air', type=Path, required=True)
    parser.add_argument('--turnip', type=Path, required=True, help='Matching local libvulkan_freedreno.dylib')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--target-dir', type=Path, help='Optional reusable Cargo build directory')
    parser.add_argument('--primelist', type=Path, help='OS-specific absolute .metallib paths to embed for idle shader priming')
    parser.add_argument('--toolchain', default='1.98.0')
    parser.add_argument('--gpu-stage-trace', action='store_true',
                        help='backboardd only: bounded command timeline, max 16 MiB / 360 s; default off')
    parser.add_argument('--gpu-cpu-profile', action='store_true',
                        help='Diagnostic only: sample the compositor thread for 90 s; perturbs timing; default off')
    parser.add_argument('--turnip-render-mode', choices=['sysmem', 'autotune'], default='sysmem',
                        help='Explicit comparison: allow Turnip to select GMEM; concurrent binning stays off')
    parser.add_argument('--diagnostic-fresh-pattern', choices=['green'],
                        help='Diagnostic only: mark fresh optimized RGBA8/BGRA8 private texture patterns; not a rendering fix')
    args = parser.parse_args()
    if args.gpu_cpu_profile and not args.gpu_stage_trace:
        parser.error('--gpu-cpu-profile requires --gpu-stage-trace for uptime correlation')
    runtime, out = args.runtime.resolve(), args.output.resolve()
    lock = json.loads((ROOT / 'sources.lock.json').read_text())
    origin = json.loads((runtime / '.houji-source.json').read_text())
    if origin != {'component': 'graphics/runtime', 'revision': lock['components']['graphics/runtime']['revision']}:
        parser.error('prepare the locked graphics/runtime with tools/prepare-sources.py first')
    files = {str(f.relative_to(runtime)): digest(f) for f in sorted((runtime / 'crates').rglob('*.rs'))}
    source_id = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:32]
    if source_id != lock['metal_frontend']['runtime_id']:
        parser.error('runtime sources differ from the locked identity; review and update the source lock first')
    runtime_id = runtime_variant_id(source_id, args.diagnostic_fresh_pattern)
    for path in [args.fixture_air, args.function_constant_air, args.turnip,
                 args.mesa_include / 'vulkan/vulkan_core.h']:
        if not path.is_file():
            parser.error('missing local input: ' + str(path))
    out.mkdir(parents=True, exist_ok=True)
    clients = (ROOT / 'graphics/metal/NativeAdrenoMetal.clients').read_text().splitlines()
    if not clients or len(clients) != len(set(clients)) or any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', name) for name in clients):
        parser.error('client allowlist must contain unique, explicit process names')
    client_list = out / 'NativeAdrenoMetal.clients'
    client_list.write_text('\n'.join(clients) + '\n')
    prime = out / 'NativeAdrenoMetal.primelist'
    if args.primelist:
        try:
            prime.write_text(read_primelist(args.primelist))
        except (OSError, ValueError) as error:
            parser.error(str(error))
    bridge, bundle = out / 'bridge', out / 'NativeAdrenoMetal.bundle'
    bridge.mkdir(exist_ok=True)
    bundle.mkdir(exist_ok=True)
    # Keep generated absolute paths out of the public Cargo manifest.
    manifest = (ROOT / 'graphics/bridge/Cargo.toml').read_text()
    manifest = manifest.replace('"../metal/AdrenoMetal/bridge/NativeMetalBridge.rs"',
                                json.dumps(str(ROOT / 'graphics/metal/AdrenoMetal/bridge/NativeMetalBridge.rs')))
    for crate in ['metal2vulkan', 'metal2vulkan-runtime']:
        manifest = manifest.replace('"../../.deps/metal2vulkan/crates/' + crate + '"',
                                    json.dumps(str(runtime / 'crates' / crate)))
    (bridge / 'Cargo.toml').write_text(manifest)
    shutil.copyfile(ROOT / 'graphics/bridge/Cargo.lock', bridge / 'Cargo.lock')
    env = dict(os.environ, CARGO_INCREMENTAL='0', IPHONEOS_DEPLOYMENT_TARGET='16.0',
               NMB_RUNTIME_ID=runtime_id, NMB_FIXTURE_AIR=str(args.fixture_air.resolve()),
               NMB_FC_AIR=str(args.function_constant_air.resolve()))
    env.pop('DYLD_LIBRARY_PATH', None)
    # Do not inherit an ambient diagnostic setting. Rust tracks option_env!
    # in its dependency fingerprint, so a reused target directory rebuilds it.
    env['HOUJI_DIAGNOSTIC_FRESH_PATTERN'] = args.diagnostic_fresh_pattern or ''
    target = args.target_dir.resolve() if args.target_dir else out / 'target'
    sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
    rust = ['cargo', '+' + args.toolchain, 'build', '--locked', '--release', '--manifest-path',
            str(bridge / 'Cargo.toml'), '--target', 'aarch64-apple-ios', '--target-dir', str(target)]
    common = ['-target', 'arm64-apple-ios16.0', '-isysroot', sdk, '-O2',
              '-DHOUJI_TURNIP_RENDER_AUTOTUNE=' + str(int(args.turnip_render_mode == 'autotune')),
              '-DHOUJI_GPU_STAGE_TRACE=' + str(int(args.gpu_stage_trace)),
              '-DHOUJI_GPU_CPU_PROFILE=' + str(int(args.gpu_cpu_profile)),
              '-I', str(ROOT / 'graphics/include'), '-I', str(args.mesa_include.resolve())]
    pm4 = ['xcrun', 'clang', *common, '-c', str(ROOT / 'graphics/include/AdrenoPM4.c'), '-o', str(out / 'AdrenoPM4.o')]
    archive = target / 'aarch64-apple-ios/release/libnative_metal_bridge.a'
    objc = ['xcrun', 'clang++', *common, '-g', '-fstack-protector-strong', '-std=c++17',
            '-fobjc-arc', '-Wno-deprecated-declarations', '-bundle', '-x', 'objective-c++',
            str(ROOT / 'graphics/metal/AdrenoMetal/NativeAdrenoMetalPlugin.mm'),
            str(ROOT / 'graphics/metal/AdrenoMetal/NativeBridgeMetalFrontend.mm'), '-x', 'none',
            str(out / 'AdrenoPM4.o'), str(archive), '-Wl,-dead_strip', '-lobjc',
            '-framework', 'Foundation', '-framework', 'Metal', '-framework', 'IOSurface',
            '-o', str(bundle / 'NativeAdrenoMetal')]
    if args.primelist:
        # Separate linker arguments preserve spaces and commas in host paths.
        for argument in ['-sectcreate', '__DATA', '__primelist', str(prime)]:
            objc.extend(['-Xlinker', argument])
    for name, command in [('rust', rust), ('pm4', pm4), ('objc', objc)]:
        (out / (name + '-command.json')).write_text(json.dumps(command, indent=2) + '\n')
        with (out / (name + '-build.log')).open('w') as log:
            subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        print(name + ' build passed', flush=True)
    info = dict(CFBundleExecutable='NativeAdrenoMetal', CFBundleIdentifier='org.blu-sharky.NativeAdrenoMetal',
                CFBundlePackageType='BNDL', CFBundleShortVersionString='1', CFBundleVersion='1',
                MinimumOSVersion='16.0', NSPrincipalClass='NativeAdrenoMetalDevice')
    (bundle / 'Info.plist').write_bytes(plistlib.dumps(info))
    shutil.copyfile(args.turnip, bundle / 'libvulkan_freedreno.dylib')
    extract_debug_symbols(bundle, out)
    subprocess.run(['strip', '-x', str(bundle / 'NativeAdrenoMetal')], check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', '--timestamp=none', str(bundle)], check=True)
    subprocess.run(['codesign', '--verify', '--strict', str(bundle)], check=True)
    report = dict(status='built-not-hardware-qualified', runtime_revision=origin['revision'],
                  runtime_id=runtime_id, runtime_source_id=source_id,
                  diagnostic_fresh_pattern=args.diagnostic_fresh_pattern,
                  gpu_cpu_profile=args.gpu_cpu_profile,
                  runtime_archive_sha256=digest(archive),
                  plugin_sha256=digest(bundle / 'NativeAdrenoMetal'),
                  turnip_sha256=digest(args.turnip), fixture_air_sha256=digest(args.fixture_air),
                  function_constant_air_sha256=digest(args.function_constant_air),
                  device_accessed=False, installed=False)
    report['gpu_stage_trace'] = dict(enabled=args.gpu_stage_trace, process='backboardd',
                                    maximum_bytes=16*1024**2, maximum_seconds=360)
    report['client_allowlist'] = dict(file=client_list.name, processes=len(clients), sha256=digest(client_list),
                                    requires_matching_kernel_client_windows=True)
    report['turnip_policy'] = dict(render_mode=args.turnip_render_mode,
                                  default_debug_flags='nocb' if args.turnip_render_mode == 'autotune' else 'sysmem,nocb',
                                  explicit_environment_preserved=True, hardware_qualified=False)
    report['shader_prime_list'] = (dict(embedded=True, libraries=len(prime.read_text().splitlines()),
                                      sha256=digest(prime)) if args.primelist else dict(embedded=False))
    (out / 'build-result.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Built ' + str(bundle) + '; target-userland imports and hardware still require validation')


if __name__ == '__main__':
    main()
