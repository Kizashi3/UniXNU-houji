#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
test_dir="$(mktemp -d -t giulia-slider-tests.XXXXXXXX)"
trap 'rm -f "$test_dir"/*; rmdir "$test_dir"' EXIT
clang -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -fno-sanitize-recover=all \
  tests/ios16_slider.c -o "$test_dir/slider"
"$test_dir/slider"
python3 tests/ios16_slider_runtime.py
