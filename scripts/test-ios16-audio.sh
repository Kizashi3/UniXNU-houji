#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
test_dir="$(mktemp -d -t giulia-audio-tests.XXXXXXXX)"
trap 'rm -f "$test_dir"/*; rmdir "$test_dir"' EXIT
python3 scripts/check-audio-mapping.py
for name in mapping terminal boot transport power scm native graph; do
  clang -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -fno-sanitize-recover=all \
    "tests/ios16_audio_${name}.c" -o "$test_dir/$name"
  "$test_dir/$name"
done
# The same immutable mapping must also be usable by future IOKit C++ code.
clang++ -x c++ -std=c++14 -Wall -Wextra -Werror -c tests/ios16_audio_mapping.c -o "$test_dir/mapping.o"
python3 -m unittest discover -s tests -p 'test_audio*.py' -v
