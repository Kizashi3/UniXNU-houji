#!/usr/bin/env bash
set -euo pipefail

# Prepare the Xiaomi 14 / houji XNU tree. Kernel compilation itself requires
# Apple's Xcode toolchain; this script performs the portable source, config,
# tree, ADT and static checks on Ubuntu first.
port_root="$(cd "$(dirname "$0")/.." && pwd)"
unixnu_root="${UNIXNU_ROOT:-$(cd "$port_root/../UniXNU" && pwd)}"
out_root="${UNIXNU_OUT:-$unixnu_root/out}"
board_out="$out_root/houji"
temp_root="${HOUJI_TEMP_ROOT:-$port_root/.xnu-prep}"

test -x "$unixnu_root/unixnu" || {
  echo "UniXNU driver not found: $unixnu_root/unixnu" >&2
  exit 1
}

"$unixnu_root/unixnu" defconfig houji_defconfig -D "$port_root"
"$unixnu_root/unixnu" fetch xnu libplatform libdispatch AvailabilityVersions libpthread corecrypto-2023 -D "$port_root"
"$unixnu_root/unixnu" tree -D "$port_root"

mkdir -p "$temp_root"
python3 "$port_root/scripts/make-houji-adt.py" \
  --output "$temp_root/houji-adt.bin" \
  --dram-size 0x10000000 \
  --owned-memory-size 0x10000000 \
  --cpu-regs 0 \
  --psci-method smc

python3 "$port_root/scripts/verify-houji-port.py" \
  --root "$port_root" \
  --mu-root "${HOUJI_MU_ROOT:-$port_root/../Mu-Silicium}" \
  --adt "$temp_root/houji-adt.bin" \
  --output "$temp_root/houji-static-report.json"

echo "Prepared houji XNU tree: $board_out/tree"
echo "XNU source: $board_out/tree/refer/xnu"
echo "ADT: $temp_root/houji-adt.bin"

if [[ "$(uname -s)" != Darwin ]]; then
  echo "Source preparation complete. Kernel compilation requires macOS with Xcode." >&2
  exit 0
fi

"$unixnu_root/unixnu" build kernel -D "$port_root" -j "${JOBS:-3}"
