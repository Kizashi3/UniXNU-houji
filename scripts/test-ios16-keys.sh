#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
test_dir="$(mktemp -d -t giulia-keys-tests.XXXXXXXX)"
trap 'rm -f "$test_dir"/*; rmdir "$test_dir"' EXIT
clang -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -fno-sanitize-recover=all \
  tests/ios16_keys.c -o "$test_dir/keys"
"$test_dir/keys"
clang -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -fno-sanitize-recover=all \
  tests/ios16_keys_terminal.c -o "$test_dir/keys-terminal"
"$test_dir/keys-terminal"
clang++ -std=c++14 -Wall -Wextra -Werror -fsanitize=address,undefined -fno-sanitize-recover=all \
  tests/ios16_input_hid.cpp -o "$test_dir/input-hid"
"$test_dir/input-hid"
