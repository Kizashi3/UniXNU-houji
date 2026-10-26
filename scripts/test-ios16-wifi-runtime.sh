#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
test_dir="$(mktemp -d -t giulia-wifi-tests.XXXXXXXX)"
trap 'rm -f "$test_dir"/*; rmdir "$test_dir"' EXIT
for transport in link pci smmu mhi qmi qmp pmu ce wmi scan apple mapping station dp network; do
  clang -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -fno-sanitize-recover=all \
    "tests/ios16_wifi_${transport}.c" -o "$test_dir/$transport"
  "$test_dir/$transport"
done
python3 tests/ios16_wifi_rsn.py
python3 tests/ios16_wifi_sae.py
python3 tests/ios16_wifi_pmf.py
python3 tests/ios16_wifi_dma_bytes.py
python3 tests/ios16_wifi_runtime.py
python3 -m unittest discover -s tests -p test_wifi_runtime_metadata.py
clang -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -fno-sanitize-recover=all \
  tests/ios16_display.c -o "$test_dir/display"
"$test_dir/display"
clang++ -std=c++14 -Wall -Wextra -Werror -c tests/ios16_wifi_headers.cpp -o "$test_dir/headers.o"
