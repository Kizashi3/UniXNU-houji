#!/usr/bin/env python3
"""Patch the assembled XNU recipe and validate the generated Python driver."""
import ast
from pathlib import Path
import sys

MARKER = "    script = ctx.tree / 'scripts/build-xnu-4k-baseline.sh'\n"
END = '    if not script.is_file():\n'
CLONE = '  git clone --shared refer/xnu .cache/xnu-work\n'
STAGE = CLONE + '''  mkdir -p .cache/xnu-work/EXTERNAL_HEADERS/os
  firehose=$(find ../../feeds -path '*/os/firehose_buffer_private.h' -type f -print -quit 2>/dev/null || true)
  if [ -n "$firehose" ]; then cp "$firehose" .cache/xnu-work/EXTERNAL_HEADERS/os/firehose_buffer_private.h; fi
'''
FLAGS = 'EXTRA_CFLAGS="$EXTRA_CFLAGS -DXNU_BOOT_PROGRESS=$BOOT_PROGRESS"'
CRYPTO = 'if [ "${XNU_SOURCE_CORECRYPTO14:-0}" = 1 ]; then\n'
BOOTSTRAP = '''# Firehose must also be available to the bootstrap link.
if [ "$BOOTSTRAP" = 1 ]; then
  test -f "$KERNEL_SDKROOT/usr/local/lib/kernel/libfirehose_kernel.a"
  EXTRA_MAKE_ARGS+=("LD_KERNEL_ARCHIVES=-L$KERNEL_SDKROOT/usr/local/lib/kernel -lfirehose_kernel")
fi
'''
REPLACEMENTS = (
    (CLONE, STAGE),
    (FLAGS, 'EXTRA_CFLAGS="$EXTRA_CFLAGS -DOS_FIREHOSE_SPI=1"\n' + FLAGS),
    (CRYPTO, BOOTSTRAP + CRYPTO),
)


def patch_driver(text):
    if text.count(MARKER) != 1:
        raise ValueError('Expected exactly one XNU build script marker')
    start = text.index(MARKER) + len(MARKER)
    end = text.index(END, start)
    existing = text[start:end]
    if existing.strip() and 'baseline' not in existing:
        raise ValueError('Unexpected code before build script validation')
    # repr serializes each shell string into valid Python, including newlines.
    block = (
        '    # Device Firehose recipe adjustments after tree assembly.\n'
        '    # Assemble the full upstream series plus device-specific changes.\n'
        '    import shutil\n'
        "    upstream_patches = ctx.root / 'patches/xnu'\n"
        "    device_patches = ctx.device / 'patches/xnu'\n"
        '    if not upstream_patches.is_dir():\n'
        "        raise Error(f'Upstream XNU patches missing: {upstream_patches}')\n"
        "    selected = {p.name: p for p in upstream_patches.glob('*.patch')}\n"
        '    # These device fixes are superseded by the upstream versions. In particular,\n'
        '    # upstream public-entitlements-header also fixes necp_client.c.\n'
        "    superseded = {'availability-fakeroot.patch', 'pmap-reserved-field.patch',\n"
        "                  'public-entitlements-header.patch'}\n"
        "    selected.update({p.name: p for p in device_patches.glob('*.patch') if p.name not in superseded})\n"
        "    if not ctx.need_config().get('XNU_BOOT_PROGRESS'):\n"
        '        # This optional display hook overlaps persistent kprintf mirroring.\n'
        '        # The device already selects persistent logging and BOOT_PROGRESS=n.\n'
        "        selected.pop('zzz-boot-progress.patch', None)\n"
        "    series = ctx.tree / '.cache/xnu-patch-series'\n"
        '    series.mkdir(parents=True, exist_ok=True)\n'
        "    for stale in series.glob('*.patch'):\n"
        '        if stale.name not in selected:\n'
        '            stale.unlink()\n'
        '    for name, patch in sorted(selected.items()):\n'
        '        shutil.copyfile(patch, series / name)\n'
        "    log(f'kernel: assembled {len(selected)} upstream/device XNU patches')\n"
        '    baseline_text = script.read_text()\n'
        "    baseline_text = baseline_text.replace('/patches/xnu/', '/.cache/xnu-patch-series/')\n"
        f'    for old, new in {REPLACEMENTS!r}:\n'
        '        if new in baseline_text:\n'
        '            continue\n'
        '        if baseline_text.count(old) != 1:\n'
        '            raise Error(f"Firehose recipe anchor missing or ambiguous: {old!r}")\n'
        '        baseline_text = baseline_text.replace(old, new, 1)\n'
        '    script.write_text(baseline_text)\n'
    )
    result = text[:start] + block + text[end:]
    ast.parse(result)
    return result


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('scripts/unixnu/kernel.py')
    result = patch_driver(path.read_text())
    path.write_text(result)
    print(f'patched and syntax-validated {path}')


if __name__ == '__main__':
    main()
