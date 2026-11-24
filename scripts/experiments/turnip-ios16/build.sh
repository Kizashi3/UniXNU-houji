#!/usr/bin/env bash
set -euo pipefail

project=$(git rev-parse --show-toplevel)
work=$(mktemp -d)
out="$project/out/houji-turnip-ios16"
mkdir -p "$out"
core="$work/unixnu"
abi="$core/drivers/Adreno740"
mesa="$core/.cache/mesa-work"
nx="$work/nx769j"

checkout() {
    local path=$1 url=$2 revision=$3
    git init -q "$path"
    git -C "$path" fetch --no-tags --depth=1 "$url" "$revision"
    git -C "$path" checkout --detach FETCH_HEAD
    test "$(git -C "$path" rev-parse HEAD)" = "$revision"
}
checkout "$core" https://github.com/UniXNU/UniXNU.git 8542980d02b4d2cc5c32ee3542de1760b2562aac
checkout "$abi" https://github.com/UniXNU/Adreno740.git 6fa7bae2a5b3b523e790eb3e0348af4d98969e4d
checkout "$nx" https://github.com/xwsjjctz/UniXNU-NX769J.git 841a86ace1caa36c0528fbf6133df36acc41b516
checkout "$mesa" https://chromium.googlesource.com/external/gitlab.freedesktop.org/mesa/mesa \
    85fda3b36405bcaea8bffc64aa4f2651dc90770d

brew install bison ninja glslang pkg-config
export PATH="$(brew --prefix bison)/bin:$PATH"
python3 -m venv "$core/.cache/mesa-venv"
"$core/.cache/mesa-venv/bin/python" -m pip install 'meson==1.9.1' 'Mako==1.3.10' 'packaging==25.0' 'PyYAML==6.0.2'
python3 - "$core" "$mesa" <<'PY'
import json
from pathlib import Path
import re
import subprocess
import sys
core, mesa = map(Path, sys.argv[1:])
pins = json.loads((core / "scripts/data/adreno-compiler-inputs.json").read_text())
assert subprocess.check_output(["git", "-C", str(mesa), "rev-parse", "HEAD^{tree}"], text=True).strip() == pins["mesa"]["tree"]
abi = (core / "drivers/Adreno740/NativeAdrenoABI.h").read_text()
assert re.search(r"NativeAdrenoAbiVersion\s*=\s*2,", abi)
uses = set()
for path in pins["patches"]:
    patch = core / path
    for line in patch.read_text().splitlines():
        if line.startswith("+"):
            uses.update(re.findall(r"\bNativeAdreno(?:Abi|Method|Params)[A-Za-z0-9]+", line))
    subprocess.run(["git", "-C", str(mesa), "apply", "--check", str(patch)], check=True)
    subprocess.run(["git", "-C", str(mesa), "apply", str(patch)], check=True)
assert uses <= set(re.findall(r"\bNativeAdreno[A-Za-z0-9]+", abi)), sorted(uses - set(re.findall(r"\bNativeAdreno[A-Za-z0-9]+", abi)))
builder = core / "scripts/build-turnip-darwin.py"
source = builder.read_text()
assert source.count("arm64-apple-ios17.0") == 1
builder.write_text(source.replace("arm64-apple-ios17.0", "arm64-apple-ios16.0"))
PY
python3 "$core/scripts/build-turnip-darwin.py" --target ios
library="$core/build/mesa-tu-ios/src/freedreno/vulkan/libvulkan_freedreno.dylib"
cp "$library" "$out/"
cp "$core/build/mesa-tu-ios/builtin-build-profile.json" "$out/"
cp "$core/.cache/mesa-tu-ios-configure.log" "$out/"
cp "$core/.cache/mesa-tu-ios-build.log" "$out/"
xcrun vtool -show-build "$out/libvulkan_freedreno.dylib" | tee "$out/turnip-build-version.txt"
grep -Eq 'minos[[:space:]]+16\.0$' "$out/turnip-build-version.txt"
nm -gU "$out/libvulkan_freedreno.dylib" > "$out/turnip-exports.txt"
grep -F ' T _vk_icdGetInstanceProcAddr' "$out/turnip-exports.txt"
codesign --force --sign - --pagesize 4096 "$out/libvulkan_freedreno.dylib"
codesign --verify --strict "$out/libvulkan_freedreno.dylib"

probe="$nx/third_party/data-a-live/vktest"
sdk=$(xcrun --sdk iphoneos --show-sdk-path)
mkdir "$work/test"
glslangValidator -V --target-env vulkan1.1 --vn fill_spv -o "$work/test/fill_spv.h" "$probe/fill.comp"
python3 "$project/scripts/experiments/turnip-ios16/adapt-vktest.py" "$probe/vktest.c" "$work/test/vktest.c"
xcrun --sdk iphoneos clang -target arm64-apple-ios16.0 -isysroot "$sdk" -O2 \
    -I "$mesa/include" -I "$work/test" "$work/test/vktest.c" -o "$out/vktest"
codesign --force --sign - --pagesize 4096 "$out/vktest"
codesign --verify --strict "$out/vktest"
(cd "$out" && shasum -a 256 libvulkan_freedreno.dylib vktest > SHA256SUMS)
