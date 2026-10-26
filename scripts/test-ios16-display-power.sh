#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
test_dir="$(mktemp -d -t giulia-display-power-tests.XXXXXXXX)"
trap 'rm -f "$test_dir"/*; rmdir "$test_dir"' EXIT
clang -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -fno-sanitize-recover=all \
  tests/ios16_display_power.c -o "$test_dir/power"
"$test_dir/power"
python3 tests/ios16_display_power_runtime.py
