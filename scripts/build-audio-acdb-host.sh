#!/usr/bin/env bash
# Build the pinned official parser for offline export; no device or DSP access.
set -euo pipefail
if [ "$#" != 2 ]; then
  echo 'Usage: build-audio-acdb-host.sh GRAPH_SERVICES_CHECKOUT NEW_OUTPUT_DIRECTORY' >&2
  exit 2
fi
source_dir="$(cd "$1" && pwd)"
output_dir="$2"
pin=76d04ffb30caa1fe609b94f9f6081210cb962fc1
test "$(git -C "$source_dir" rev-parse HEAD)" = "$pin"
# A Windows checkout under WSL may have CRLF and synthesized executable bits.
# Normalize only those Git comparison settings; do not modify the source tree.
git -c core.filemode=false -c core.autocrlf=true -C "$source_dir" diff --quiet HEAD -- acdb ar_osal
if [ -e "$output_dir" ]; then
  echo 'Refusing to overwrite an existing ACDB build directory' >&2
  exit 2
fi
mkdir -p "$output_dir"
output_dir="$(cd "$output_dir" && pwd)"
cd "$source_dir"
# Only the offline parser and the OS functions it consumes are linked.
# This build includes no GPR device, audio ion, remoteproc or kernel adapter.
gcc -shared -fPIC -O1 -Wno-error=incompatible-pointer-types \
  -DLINUX_ENABLED -D__unused= -DAR_OSAL_USE_SYSLOG \
  -Iacdb/api -Iacdb/inc -Iar_osal/api \
  acdb/src/*.c \
  ar_osal/src/linux/ar_osal_file_io.c ar_osal/src/linux/ar_osal_heap.c \
  ar_osal/src/linux/ar_osal_log.c ar_osal/src/linux/ar_osal_mem_op.c \
  ar_osal/src/linux/ar_osal_mutex.c ar_osal/src/linux/ar_osal_string.c \
  -lpthread -Wl,-z,defs -o "$output_dir/libacdb.so"
cp LICENSE "$output_dir/LICENSE"
printf '%s\n' "$pin" > "$output_dir/source-commit.txt"
