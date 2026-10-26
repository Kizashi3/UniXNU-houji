"""Prepare pinned sources for the UEFI-only giulia bring-up. Does not access USB."""
import argparse
import json
import pathlib
import shutil
import subprocess
from ios16_modem_stock import preflight_memory_overlay, verify_prepared_memory_map

ROOT = pathlib.Path(__file__).resolve().parents[1]

def run(*cmd, cwd=None):
    subprocess.run([str(x) for x in cmd], cwd=cwd, check=True)

def checkout(source, destination):
    if not destination.exists():
        run('git', 'init', destination)
        run('git', 'remote', 'add', 'origin', source['url'], cwd=destination)
        run('git', 'fetch', '--depth', '1', 'origin', source['commit'], cwd=destination)
        run('git', 'checkout', '--detach', 'FETCH_HEAD', cwd=destination)
    actual = subprocess.check_output(['git', '-C', str(destination), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != source['commit']:
        raise SystemExit(f'{destination}: unexpected source commit {actual}')


def apply_uefi_overlay(uefi):
    """Stage the production overlay after board patches, preserving drift errors.

    Exact previously staged content is allowed for repeat preparation. The
    imported function deliberately propagates ValueError to build validators.
    """
    uefi = pathlib.Path(uefi)
    overlay = ROOT / 'uefi-overlay'
    if not overlay.is_dir():
        raise ValueError('Missing production UEFI overlay directory')
    preflight_memory_overlay(uefi, ROOT)
    shutil.copytree(overlay, uefi, dirs_exist_ok=True)
    return verify_prepared_memory_map(uefi, ROOT)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', type=pathlib.Path, required=True)
    parser.add_argument('--payload-identity', type=pathlib.Path, default=ROOT / 'hardware/xnu-payload.json')
    args = parser.parse_args()
    work = args.workspace.resolve()
    work.mkdir(parents=True, exist_ok=True)
    pins = json.loads((ROOT / 'sources.json').read_text())
    paths = {'uefi': work / 'uefi-giulia', 'unixnu': work / 'UniXNU', 'darwinboot': work / 'DarwinBoot'}
    for name, path in paths.items():
        checkout(pins[name], path)
    uefi = paths['uefi']
    patch = ROOT / 'patches/giulia-unixnu.patch'
    # Upstream mixes CRLF SEC sources with LF board files. The distributed patch
    # is LF; normalize only its named text inputs, keeping the pinned source.
    for line in patch.read_text().splitlines():
        if line.startswith('+++ b/'):
            target = uefi / line[6:]
            if not target.resolve().is_relative_to(uefi.resolve()):
                raise SystemExit('Patch path escapes UEFI source')
            if target.is_file():
                target.write_bytes(target.read_bytes().replace(b'\r\n', b'\n'))
    applied = subprocess.run(['git', 'apply', '--reverse', '--check', str(patch)], cwd=uefi, capture_output=True)
    if applied.returncode:
        run('git', 'apply', '--check', patch, cwd=uefi)
        run('git', 'apply', patch, cwd=uefi)
    run('git', 'submodule', 'update', '--init', '--depth', '1', '--jobs', '4', cwd=uefi)
    try:
        apply_uefi_overlay(uefi)
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
    identity = json.loads(args.payload_identity.read_text())
    size = identity['payload_bytes']
    crc = int(identity['payload_crc32'], 16)
    if not 0 < size <= 224 * 1024**2 or not 0 <= crc < 2**32:
        raise SystemExit('Invalid pinned payload identity')
    header = uefi / 'Platforms/OnePlus/giuliaPkg/Drivers/GiuliaInitrdDxe/PayloadIdentity.h'
    header.write_text(f'// Generated from hardware/xnu-payload.json\n'
                      f'#define GIULIA_PAYLOAD_BYTES {size}U\n'
                      f'#define GIULIA_PAYLOAD_CRC32 0x{crc:08x}U\n'
                      f'#define GIULIA_TOUCH_CLOCK {int(identity.get("touch_clock_handoff") is True)}\n'
                      f'#define GIULIA_TOUCH_POWER {int(identity.get("touch_gpio") is True)}\n'
                      f'#define GIULIA_WIFI_PCIE {int(identity.get("wifi_pcie_handoff") is True)}\n'
                      f'#define GIULIA_HALL_PREPARE {int(identity.get("hall_prepare_handoff") is True)}\n')
    shutil.copytree(paths['unixnu'] / 'package', uefi / 'UniXNU/package', dirs_exist_ok=True)
    shutil.copytree(paths['darwinboot'], uefi / 'UniXNU/drivers/DarwinBoot', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('.git', '__pycache__'))
    run('python3', ROOT / 'scripts/enable-initrd-diagnostics.py', uefi)
    print(f'Prepared {uefi}; build with build-uefi.sh')

if __name__ == '__main__':
    main()
