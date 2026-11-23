#!/usr/bin/env python3
"""Build the isolated XR blend candidate; never access a phone or system image."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

P = Path(__file__).resolve().parents[1]
N = Path('${HOUJI_ARTIFACTS}/native-port')
OUT = P / 'out/adrenometal-timing-v16'
CORE = P / 'out/adrenometal-xr-v14/runtime'
TARGET = N / 'adrenometal-timing-v16-target'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert (CORE / 'crates/metal2vulkan-runtime/src/exit_guard.rs').is_file()
    blend = (CORE / 'crates/metal2vulkan/src/lower/arith/extended_range/blend.rs').read_text()
    assert 'let math = if math == BlendMath::Fast && narrow_only' in blend
    assert 'if self.math == BlendMath::Rounded {' in blend
    assert 'new_image_as_it_lies' in (CORE / 'crates/metal2vulkan-runtime/src/texture/surface_two_planes.rs').read_text()
    files = {str(f.relative_to(CORE)): digest(f) for f in sorted((CORE / 'crates').rglob('*.rs'))}
    runtime_id = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:32]
    env = dict(os.environ, CARGO_HOME=str(N / 'build-tools/cargo'),
               RUSTUP_HOME=str(N / 'build-tools/rustup'), CARGO_INCREMENTAL='0',
               IPHONEOS_DEPLOYMENT_TARGET='16.0', NMB_RUNTIME_ID=runtime_id,
               NMB_FIXTURE_AIR=str(N / 'adrenometal-ios16/runtime_examples.air'),
               NMB_FC_AIR=str(N / 'adrenometal-ios16/function_constant.air'))
    env['PATH'] = str(N / 'build-tools/cargo/bin') + os.pathsep + env['PATH']
    env.pop('DYLD_LIBRARY_PATH', None)
    with (OUT / 'rust-build.log').open('w') as log:
        subprocess.run(['cargo', '+1.98.0', 'build', '--locked', '--release',
                        '--manifest-path', str(OUT / 'bridge-build/Cargo.toml'), '--target', 'aarch64-apple-ios',
                        '--target-dir', str(TARGET)], env=env, check=True, stdout=log, stderr=subprocess.STDOUT)
    print('iOS Rust runtime built', flush=True)
    bundle = OUT / 'NativeAdrenoMetal.bundle'
    assert not bundle.exists()
    shutil.copytree(P / 'out/adrenometal-xr-v14/NativeAdrenoMetal.bundle', bundle)
    command = json.loads((P / 'out/adrenometal-xr-v14/objc-command.json').read_text())
    command = [s.replace(str(P / 'out/adrenometal-xr-v14'), str(OUT))
               .replace(str(N / 'adrenometal-xr-v14-target'), str(TARGET)) for s in command]
    (OUT / 'objc-command.json').write_text(json.dumps(command, indent=2) + '\n')
    with (OUT / 'objc-build.log').open('w') as log:
        subprocess.run(command, env=env, check=True, stdout=log, stderr=subprocess.STDOUT)
    dsym = bundle / 'NativeAdrenoMetal.dSYM'
    if dsym.exists():
        symbols = OUT / 'symbols'
        symbols.mkdir(exist_ok=True)
        assert not (symbols / dsym.name).exists()
        shutil.move(str(dsym), str(symbols / dsym.name))
    exe = bundle / 'NativeAdrenoMetal'
    subprocess.run(['strip', '-x', str(exe)], check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', '--timestamp=none', str(bundle)], check=True)
    subprocess.run(['codesign', '--verify', '--strict', str(bundle)], check=True)
    assert digest(bundle / 'libvulkan_freedreno.dylib') == '7827fc5543b661273e8242cec84b8ae9af356883747d8a33f840817a116f3157'
    report = dict(status='built-not-hardware-qualified', upstream_commit='0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35',
                  reference_repository='rootstockos/AdrenoMetal', reference_commit='16e8125525a64d34439ef924213a6fea4530e239',
                  runtime_id=runtime_id, runtime_files=files, plugin_sha256=digest(exe),
                  turnip_sha256=digest(bundle / 'libvulkan_freedreno.dylib'),
                  runtime_archive_sha256=digest(TARGET / 'aarch64-apple-ios/release/libnative_metal_bridge.a'),
                  native_astc_adapter_retained=True, ios_qos_adapter_retained=True,
                  kernel_driver_changed=False, clock_voltage_changed=False, profiling_only=True, translation_runtime_unchanged=True)
    (OUT / 'build-result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'runtime_files'}, indent=2))


if __name__ == '__main__':
    main()
