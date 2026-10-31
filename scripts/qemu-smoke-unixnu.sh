#!/usr/bin/env bash
# Read-only AArch64 QEMU smoke test for the UniXNU UEFI chain.
# It validates UEFI/config/driver/DT/initrd/variable handoff, not Xiaomi 14
# SM8650 UFS/PMIC/GPU behaviour and not a boot of the iOS XNU kernel itself.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
QEMU_ROOT=${QEMU_ROOT:-$HOME/qemu-user}
if [ ! -x "$QEMU_ROOT/usr/bin/qemu-system-aarch64" ]; then
    echo "error: qemu-system-aarch64 missing under $QEMU_ROOT" >&2
    exit 1
fi
export PATH="$QEMU_ROOT/usr/bin:$PATH"
export LD_LIBRARY_PATH="$QEMU_ROOT/usr/lib/x86_64-linux-gnu:$QEMU_ROOT/lib/x86_64-linux-gnu:$QEMU_ROOT/usr/lib:$QEMU_ROOT/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
ESP=${UNIXNU_QEMU_ESP:-$HOME/unixnu-qemu-esp}
FIRMWARE=${UNIXNU_QEMU_FIRMWARE:-$QEMU_ROOT/usr/share/AAVMF/AAVMF_CODE.no-secboot.fd}
OUT=${UNIXNU_QEMU_OUT:-$ROOT/build/qemu}
RUNNER=${UNIXNU_QEMU_RUNNER:-$ROOT/package/Scripts/qemu-run.py}
if [ ! -f "$RUNNER" ] && [ -f "$HOME/UniXNU/package/Scripts/qemu-run.py" ]; then
    RUNNER="$HOME/UniXNU/package/Scripts/qemu-run.py"
fi
if [ ! -f "$RUNNER" ]; then
    echo "error: qemu-run.py not found; set UNIXNU_QEMU_RUNNER" >&2
    exit 1
fi
mkdir -p "$OUT"
python3 "$RUNNER" "$ESP" \
    --firmware "$FIRMWARE" \
    --log "$OUT/unixnu.log" \
    --timeout "${UNIXNU_QEMU_TIMEOUT:-30}" \
    --no-gop \
    --expect 'UNIXNU: menu: shown' \
    --expect 'UNIXNU-HELLO: RESULT PASS' \
    --finish-on-expect \
    > "$OUT/run.txt" 2>&1
sha256sum "$OUT/unixnu.log" "$OUT/unixnu.clean.log" "$OUT/run.txt" > "$OUT/SHA256SUMS"
cat "$OUT/run.txt"
