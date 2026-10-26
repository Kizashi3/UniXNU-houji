#!/usr/bin/env bash
set -euo pipefail
port_root="$(cd "$(dirname "$0")/.." && pwd)"
work="${1:?Usage: build-uefi.sh /absolute/build/workspace}"
prepare_args=(--workspace "$work")
if [ -n "${GIULIA_PAYLOAD_IDENTITY:-}" ]; then
  prepare_args+=(--payload-identity "$GIULIA_PAYLOAD_IDENTITY")
fi
python3 "$port_root/scripts/prepare.py" "${prepare_args[@]}"
python3 "$port_root/scripts/verify-wifi-native-abi.py" --uefi "$work/uefi-giulia" --when-enabled
if [ "${GIULIA_BOOT_ABI:-darwin23}" = darwin22 ]; then
  python3 "$port_root/scripts/ios16-loader.py" "$work/uefi-giulia/UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver"
  python3 "$port_root/scripts/enable-touch-diagnostics.py" "$work/uefi-giulia/UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver"
  python3 "$port_root/scripts/enable-wifi-diagnostics.py" "$work/uefi-giulia/UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver"
  if python3 -c 'import pathlib,sys; sys.exit("#define GIULIA_HALL_PREPARE 1\n" not in pathlib.Path(sys.argv[1]).read_text())' "$work/uefi-giulia/Platforms/OnePlus/giuliaPkg/Drivers/GiuliaInitrdDxe/PayloadIdentity.h"; then
    python3 "$port_root/scripts/verify-wifi-native-abi.py" --uefi "$work/uefi-giulia"
    python3 "$port_root/scripts/enable-hall-diagnostics.py" "$work/uefi-giulia/UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver"
  fi
  python3 "$port_root/tests/ios16_dram_handoff.py" --driver "$work/uefi-giulia/UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver"
fi
python3 -m venv "$work/.venv"
"$work/.venv/bin/pip" install -r "$work/uefi-giulia/pip-requirements.txt"
cd "$work/uefi-giulia"
export CLANGPDB_AARCH64_PREFIX=aarch64-linux-gnu-
# Explicit setup/update also repairs an interrupted first build with an existing Build/.
"$work/.venv/bin/python" Platforms/OnePlus/giuliaPkg/DeviceBuild.py --setup -t DEBUG
"$work/.venv/bin/python" Platforms/OnePlus/giuliaPkg/DeviceBuild.py --update -t DEBUG
"$work/.venv/bin/python" build_uefi.py -d giulia -m 0 -r DEBUG
python3 "$port_root/scripts/verify-image.py" "$work/uefi-giulia" --output "$work/image-verification.json"
