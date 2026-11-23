#!/usr/bin/env bash
# SPDX-License-Identifier: BSD-2-Clause-Patent
# Classic EDK2 build in the pinned Linux build container; no device operations.
set -euo pipefail
uefi_root=${1:?Usage: build-uefi.sh UEFI_ROOT UNIXNU_ROOT VENDOR_ROOT}
unixnu_root=${2:?UniXNU source root required}
vendor_root=${3:?Local extracted OEM package root required}
port_root=$(cd "$(dirname "$0")/.." && pwd)
python3 "$port_root/scripts/check-uefi.py" --uefi "$uefi_root" --vendor "$vendor_root"
export WORKSPACE="$uefi_root"
export EDK_TOOLS_PATH="$uefi_root/Mu_Basecore/BaseTools"
export PACKAGES_PATH="$uefi_root/Platforms/Xiaomi:$uefi_root/Common/Mu:$uefi_root/Common/Mu_OEM_Sample:$uefi_root/Mu_Basecore:$uefi_root/Silicon/Qualcomm:$uefi_root/Silicon/Silicium:$unixnu_root/package:$vendor_root"
extra_defines=()
if [ -n "${4:-}" ]; then
  export PACKAGES_PATH="$4:$PACKAGES_PATH"
  extra_defines=(-D WITH_DARWINBOOT=1)
fi
if [ -n "${HOUJI_RAM_PAYLOAD:-}" ]; then
  python3 "$port_root/scripts/stage-ram-payload.py" --payload "$HOUJI_RAM_PAYLOAD" --uefi "$uefi_root"
  extra_defines+=(-D WITH_PAYLOAD=1)
fi
# Explicit experimental profiles; default stage-1 builds remain unchanged.
for feature in HIGH_RAM ROOT_RAM RAM_PROBE STORAGE_PROBE CLOCK_MMIO UFS_MMIO; do
  variable="HOUJI_${feature}"
  value=${!variable:-0}
  if [ "$value" = 1 ]; then
    extra_defines+=(-D "WITH_HOUJI_${feature}=TRUE")
  elif [ "$value" != 0 ]; then
    echo "Expected $variable=0 or 1" >&2; exit 2
  fi
done
if [ "${HOUJI_HIGH_RAM:-0}" = 1 ]; then
  python3 "$port_root/scripts/patch-low-uefi-alloc.py" --uefi "$uefi_root"
fi
if [ "${HOUJI_RAM_PROBE:-0}" = 1 ] && { [ "${HOUJI_HIGH_RAM:-0}" = 1 ] || [ "${HOUJI_ROOT_RAM:-0}" = 1 ]; }; then
  echo "Reserved probe cannot run with a conventional/root allocation profile" >&2; exit 2
fi
export CLANG_BIN=/usr/bin/
export PYTHON_COMMAND=python3
export PATH="$EDK_TOOLS_PATH/BinWrappers/PosixLike:$PATH"
cd "$uefi_root"
# Project Mu intentionally omits edksetup.sh. Use its pinned BaseTools
# templates directly rather than depending on a workstation's saved setup.
export CONF_PATH="$uefi_root/Conf"
mkdir -p "$CONF_PATH"
for template in build_rule tools_def target; do
  cp "$EDK_TOOLS_PATH/Conf/$template.template" "$CONF_PATH/$template.txt"
done
build -p Platforms/Xiaomi/houjiPkg/houji.dsc -a AARCH64 -b DEBUG -t CLANGPDB -n 4 \
  -D DEVICE_MODEL=0 -D ENABLE_SECUREBOOT=0 -D FD_BASE=0xA7100000 \
  -D FD_SIZE=0x300000 -D FD_BLOCKS=0x300 "${extra_defines[@]}"
