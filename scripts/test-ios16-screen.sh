#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
test_dir="$(mktemp -d -t giulia-screen-tests.XXXXXXXX)"
trap 'rm -f "$test_dir"/*; rmdir "$test_dir"' EXIT
clang -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -fno-sanitize-recover=all \
  tests/ios16_screen.c -o "$test_dir/screen"
"$test_dir/screen" "$test_dir/kernel-screen.bin"
clang++ -std=c++14 -Wall -Wextra -Werror -fsanitize=address,undefined -fno-sanitize-recover=all \
  tests/ios16_screen_framebuffer.cpp -o "$test_dir/framebuffer"
"$test_dir/framebuffer"
clang -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -fno-sanitize-recover=all \
  tests/ios16_input.c -o "$test_dir/input"
"$test_dir/input"
clang++ -std=c++14 -Wall -Wextra -Werror -fsanitize=address,undefined -fno-sanitize-recover=all \
  tests/ios16_input_hid.cpp -o "$test_dir/input-hid"
"$test_dir/input-hid"
GIULIA_SCREEN_FIXTURE="$test_dir/kernel-screen.bin" python3 -m unittest discover -s tests -p 'test_screen*.py' -v
python3 -m unittest discover -s tests -p 'test_terminal.py' -v
