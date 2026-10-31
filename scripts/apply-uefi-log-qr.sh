#!/usr/bin/env bash
set -euo pipefail

ROOT=${1:-}
if [[ -z "$ROOT" || ! -d "$ROOT" ]]; then
  echo "usage: $0 /path/to/UniXNU" >&2
  exit 2
fi
ROOT=$(cd "$ROOT" && pwd)
PATCH_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../patches/uefi" && pwd)
PATCH="$PATCH_DIR/unixnu-efi-log-qr.patch"
test -f "$PATCH"

git -C "$ROOT" apply --check "$PATCH"
git -C "$ROOT" apply "$PATCH"
git -C "$ROOT" diff --check
echo "UEFI FAT log + QR marker patch applied to $ROOT"
echo 'Log path: \\EFI\\UniXNU\\logs\\boot.log'
