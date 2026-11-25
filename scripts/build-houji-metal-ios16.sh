#!/usr/bin/env bash
set -euo pipefail

project=$(git rev-parse --show-toplevel)
work=$(mktemp -d)
out="$project/out/houji-metal-ios16"
rm -rf "$out"
mkdir -p "$out"

core="$work/unixnu"
abi="$core/drivers/Adreno740"
mesa="$core/.cache/mesa-work"
nx="$work/nx769j"

checkout() {
    local path=$1 url=$2 revision=$3
    mkdir -p "$path"
    git init -q "$path"
    git -C "$path" fetch --no-tags --depth=1 "$url" "$revision"
    git -C "$path" checkout --detach FETCH_HEAD
    test "$(git -C "$path" rev-parse HEAD)" = "$revision"
}

echo "== [1/6] Checking out pinned upstream sources"
checkout "$core" https://github.com/UniXNU/UniXNU.git 8542980d02b4d2cc5c32ee3542de1760b2562aac
checkout "$abi" https://github.com/UniXNU/Adreno740.git 6fa7bae2a5b3b523e790eb3e0348af4d98969e4d
checkout "$nx" https://github.com/xwsjjctz/UniXNU-NX769J.git 841a86ace1caa36c0528fbf6133df36acc41b516
checkout "$mesa" https://chromium.googlesource.com/external/gitlab.freedesktop.org/mesa/mesa \
    85fda3b36405bcaea8bffc64aa4f2651dc90770d

cache="$nx/.cache/gpu-user"
mkdir -p "$cache"
checkout "$cache/nativemetal" https://github.com/UniXNU/NativeMetal.git c6d29caad6d880cc8204ebe3bc34d77479a3255d
checkout "$cache/metal2vulkan" https://github.com/steelbrain/metal2vulkan.git 720ef1ce9ae2a2068999a8675717418b9416283e
checkout "$cache/AdrenoPM4" https://github.com/UniXNU/AdrenoPM4.git 445f8fe6d115738352b9d78dc70af6d61aa7f62f
checkout "$cache/NativeMobileDisplay" https://github.com/UniXNU/GopFramebuffer.git 8666a9950c9699b368931d18cac92c0fdb2ce9c0

echo "== [2/6] Installing host tools & Rust iOS target"
brew install bison ninja glslang shaderc spirv-tools pkg-config llvm
export PATH="$(brew --prefix bison)/bin:$(brew --prefix llvm)/bin:$PATH"

if ! command -v rustup >/dev/null 2>&1; then
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
    export PATH="$HOME/.cargo/bin:$PATH"
fi

RUST_TC="1.98.0"
if ! rustup toolchain install "$RUST_TC" --profile minimal >/dev/null 2>&1; then
    echo "Rust 1.98.0 not available via rustup; falling back to stable"
    RUST_TC="stable"
    rustup toolchain install stable --profile minimal
fi
rustup target add aarch64-apple-ios --toolchain "$RUST_TC"
RUST_VER=$(rustc +"$RUST_TC" --version)
echo "Selected Rust toolchain: $RUST_TC ($RUST_VER)"

if ! xcrun -sdk iphoneos metal -v >/dev/null 2>&1; then
    echo "== Downloading Xcode MetalToolchain component"
    xcodebuild -downloadComponent MetalToolchain || true
fi
xcrun -sdk iphoneos metal -v || echo "WARNING: metal compiler still unavailable"

echo "== [3/6] Patching Mesa and building iOS 16 Turnip"
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
for path in pins["patches"]:
    patch = core / path
    subprocess.run(["git", "-C", str(mesa), "apply", "--check", str(patch)], check=True)
    subprocess.run(["git", "-C", str(mesa), "apply", str(patch)], check=True)
builder = core / "scripts/build-turnip-darwin.py"
source = builder.read_text()
assert source.count("arm64-apple-ios17.0") == 1
builder.write_text(source.replace("arm64-apple-ios17.0", "arm64-apple-ios16.0"))
PY
python3 "$core/scripts/build-turnip-darwin.py" --target ios
mkdir -p "$core/build/mesa-tu-ios16/src/freedreno/vulkan"
cp "$core/build/mesa-tu-ios/src/freedreno/vulkan/libvulkan_freedreno.dylib" \
   "$core/build/mesa-tu-ios16/src/freedreno/vulkan/libvulkan_freedreno.dylib"

echo "== [4/6] Adapting build-nx769j-metal.sh for runner Rust toolchain ($RUST_TC)"
if [ "$RUST_TC" != "1.98.0" ]; then
    python3 - "$nx/scripts/build-nx769j-metal.sh" "$RUST_TC" <<'PY'
import sys
p, tc = sys.argv[1], sys.argv[2]
s = open(p).read()
s = s.replace('rust-version = "1.98"\n', '')
s = s.replace('cargo +1.98.0 ', f'cargo +{tc} ')
open(p, 'w').write(s)
PY
fi

echo "== [5/6] Building NativeAdrenoMetal.bundle, vktest, and mtltest"
bash "$nx/scripts/build-nx769j-metal.sh" "$core"

echo "== [6/6] Collecting outputs, CDHashes, and tarball"
cp -R "$cache/out/NativeAdrenoMetal.bundle" "$out/"
cp "$cache/out/libvulkan_freedreno.dylib" "$out/"
cp "$cache/out/vktest" "$out/"
if [ -f "$cache/out/mtltest" ]; then
    cp "$cache/out/mtltest" "$out/"
fi
cp "$cache/out/SHA256SUMS" "$out/"

{
    for bin in \
        "$out/NativeAdrenoMetal.bundle/NativeAdrenoMetal" \
        "$out/NativeAdrenoMetal.bundle/libvulkan_freedreno.dylib" \
        "$out/vktest" \
        "$out/mtltest"; do
        if [ -f "$bin" ]; then
            rel="${bin#$out/}"
            cdh=$(codesign --display --verbose=4 "$bin" 2>&1 | awk -F= '/^CDHash=/{print $2; exit}')
            echo "${cdh}  ${rel}"
        fi
    done
} > "$out/CDHashes.txt"
cat "$out/CDHashes.txt"

tar -C "$out" -czf "$out/houji-metal-ios16.tar.gz" \
    NativeAdrenoMetal.bundle libvulkan_freedreno.dylib vktest \
    $( [ -f "$out/mtltest" ] && echo mtltest ) \
    SHA256SUMS CDHashes.txt
ls -lh "$out"
