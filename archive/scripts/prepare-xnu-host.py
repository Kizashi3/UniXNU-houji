#!/usr/bin/env python3
"""Make the pinned dxb build use an extracted local KDK and strict project patches."""
import argparse
from pathlib import Path
import shutil
import subprocess


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dxb', type=Path, required=True)
    p.add_argument('--profile', type=Path, required=True)
    a = p.parse_args()
    commit = subprocess.check_output(['git', '-C', str(a.dxb), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != '663906528d1cd5ea8fde7de6f16de73db9511549':
        raise ValueError('Inspect the changed dxb revision before building')
    path = a.dxb / 'build.sh'
    text = subprocess.check_output(['git', '-C', str(a.dxb), 'show', 'HEAD:build.sh'], text=True)
    start, end = text.index('install_deps() {'), text.index('\ninstall_ipsw() {')
    text = text[:start] + '''install_deps() {
    # Dependencies are prepared locally; never install Homebrew/Xcode/KDK here.
    command -v jq >/dev/null
    command -v ninja >/dev/null
    test -x "${WORK_DIR}/venv/bin/cmake"
    test -n "${MACOS_VERSION}"
    test -n "${KDKROOT:-}"
    test -d "${KDKROOT}"
}
''' + text[end:]
    start = text.index('    if [ ! -d "$KDKROOT" ]; then\n        KDK_URL=')
    end = text.index('\n    fi\n}', start) + len('\n    fi')
    text = text[:start] + '''    if [ ! -d "$KDKROOT" ]; then
        error "Pass KDKROOT pointing at a locally extracted KDK; no system installation is performed"
        exit 1
    fi''' + text[end:]
    marker = '                warning "Skipping patch ${PATCH} (already upstream, previously applied, or malformed): ${APPLY_CHECK}"'
    if text.count(marker) != 1:
        raise ValueError('Unexpected patch loader')
    guard = '''                case "${PATCH##*/}" in
                    [0-9][0-9][0-9][0-9]-*)
                        if ! git apply --reverse --check "$PATCH"; then
                            printf 'Required project patch rejected: %s\\n%s\\n' "$PATCH" "$APPLY_CHECK" >&2
                            exit 1
                        fi
                        ;;
                esac
'''
    text = text.replace(marker, guard + marker)
    text = text.replace('ARCHS="x86_64 arm64e" VALID_ARCHS="x86_64 arm64e"',
                        'ARCHS="x86_64 arm64e arm64" VALID_ARCHS="x86_64 arm64e arm64"')
    # Source preparation is isolated; no changes to the selected Mac toolchain.
    path.write_text(text)
    patches = sorted(a.profile.glob('*.patch'))
    if len(patches) != 20:
        raise ValueError('Expected all 20 storage-free early patches')
    for patch in patches:
        shutil.copy2(patch, a.dxb / 'patches' / patch.name)
    print('Local KDK only; no dependency installer or Xcode selection; 20 strict early patches staged.')


if __name__ == '__main__':
    main()
