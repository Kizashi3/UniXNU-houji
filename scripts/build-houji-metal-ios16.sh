#!/usr/bin/env bash
set -euo pipefail

project=$(git rev-parse --show-toplevel)
work=$(mktemp -d)
out="$project/out/houji-metal-ios16"
rm -rf "$out"
mkdir -p "$out"

core="$work/unixnu"
mesa="$core/.cache/mesa-work"
houji_ref="$work/houji-ref"
m2v_raw="$work/m2v-raw"
m2v_houji="$work/m2v-houji"

checkout() {
    local path=$1 url=$2 revision=$3
    mkdir -p "$path"
    git init -q "$path"
    git -C "$path" fetch --no-tags --depth=1 "$url" "$revision"
    git -C "$path" checkout --detach FETCH_HEAD
    test "$(git -C "$path" rev-parse HEAD)" = "$revision"
}

echo "== [1/6] Checking out pinned sources (UniXNU Turnip v2 + Houji-ref iOS 16 Metal + m2v@219f0136)"
checkout "$core" https://github.com/UniXNU/UniXNU.git e7bddb9a7eecdcf81f36da9fa38bd9d4d3f155c2
checkout "$core/drivers/Adreno740" https://github.com/UniXNU/Adreno740.git 2962e289c9690aeb668072c170679e6fb28bf8de
checkout "$core/kits/AdrenoPM4" https://github.com/UniXNU/AdrenoPM4.git 445f8fe6d115738352b9d78dc70af6d61aa7f62f
checkout "$mesa" https://chromium.googlesource.com/external/gitlab.freedesktop.org/mesa/mesa \
    85fda3b36405bcaea8bffc64aa4f2651dc90770d
git clone --depth=1 https://github.com/lonzzi/UniXNU-houji.git "$houji_ref"
checkout "$m2v_raw" https://github.com/steelbrain/metal2vulkan.git 219f01365dc4c8eb346816c405b5b17403793764

echo "== [2/6] Installing host tools & Rust 1.98.0 iOS target"
brew install bison ninja glslang shaderc spirv-tools pkg-config llvm
export PATH="$(brew --prefix bison)/bin:$(brew --prefix llvm)/bin:$PATH"

if ! command -v rustup >/dev/null 2>&1; then
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
    export PATH="$HOME/.cargo/bin:$PATH"
fi

RUST_TC="1.98.0"
rustup toolchain install "$RUST_TC" --profile minimal
rustup target add aarch64-apple-ios --toolchain "$RUST_TC"
rustup default "$RUST_TC"
echo "Selected Rust toolchain: $(rustc +$RUST_TC --version)"

echo "== [3/6] Patching Mesa (26 upstream Turnip patches for ABI v2) & assembling Houji-ref m2v@219f0136"
python3 -m venv "$core/.cache/mesa-venv"
"$core/.cache/mesa-venv/bin/python" -m pip install 'meson==1.9.1' 'Mako==1.3.10' 'packaging==25.0' 'PyYAML==6.0.2'

python3 - "$core" "$mesa" "$houji_ref" <<'PY'
import json, re, subprocess, sys
from pathlib import Path

core, mesa, houji_ref = map(Path, sys.argv[1:])
pins = json.loads((core / "scripts/data/adreno-compiler-inputs.json").read_text())
assert subprocess.check_output(["git", "-C", str(mesa), "rev-parse", "HEAD^{tree}"], text=True).strip() == pins["mesa"]["tree"]
abi = (core / "drivers/Adreno740/NativeAdrenoABI.h").read_text()
assert re.search(r"NativeAdrenoAbiVersion\s*=\s*2,", abi)
for path in pins["patches"]:
    patch = core / path
    subprocess.run(["git", "-C", str(mesa), "apply", "--check", str(patch)], check=True)
    subprocess.run(["git", "-C", str(mesa), "apply", str(patch)], check=True)
print(f"Applied {len(pins['patches'])} Mesa/Turnip patches cleanly")

# Retarget build-turnip-darwin.py to iOS 16.0
p = core / "scripts/build-turnip-darwin.py"
s = p.read_text().replace("arm64-apple-ios17.0", "arm64-apple-ios16.0").replace("IPHONEOS_DEPLOYMENT_TARGET'] = '17.0'", "IPHONEOS_DEPLOYMENT_TARGET'] = '16.0'").replace("17.0", "16.0")
p.write_text(s)
print("Retargeted build-turnip-darwin.py to iOS 16.0")

# Allow all processes when NativeAdrenoMetal.clients is absent (compatible with smooth10 unlimited SMMU)
pl = houji_ref / "graphics/metal/AdrenoMetal/NativeAdrenoMetalPlugin.mm"
pls = pl.read_text()
old_cl = '    if (!requestedPath("NativeAdrenoMetal.clients", path, sizeof path)) return false;'
new_cl = '    if (!requestedPath("NativeAdrenoMetal.clients", path, sizeof path)) return true;'
assert old_cl in pls, "expected listedClient fallback line not found"
pls = pls.replace(old_cl, new_cl, 1)
pl.write_text(pls)
print("Patched Houji-ref NativeAdrenoMetalPlugin.mm listedClient fallback -> true")
PY

python3 "$houji_ref/tools/prepare-sources.py" graphics/runtime --upstream "$m2v_raw" --output "$m2v_houji"

echo "== [4/6] Building iOS 16 Turnip (libvulkan_freedreno.dylib, ABI v2, 128-IB)"
python3 "$core/scripts/build-turnip-darwin.py" --target ios
turnip_dylib="$core/build/mesa-tu-ios/src/freedreno/vulkan/libvulkan_freedreno.dylib"
test -f "$turnip_dylib"

echo "== [5/6] Building Houji-ref iOS 16 NativeAdrenoMetal.bundle (m2v@219f0136 + sysmem,nocb)"
cat > "$work/dummy.metal" <<'METAL'
#include <metal_stdlib>
using namespace metal;
kernel void dummy_k(device uint *out [[buffer(0)]], uint id [[thread_position_in_grid]]) { out[id] = id; }
METAL
xcrun -sdk iphoneos metal -c "$work/dummy.metal" -o "$work/runtime_examples.air"
cp "$work/runtime_examples.air" "$work/function_constant.air"

python3 "$houji_ref/tools/build-metal.py" \
    --runtime "$m2v_houji" \
    --mesa-include "$mesa/include" \
    --fixture-air "$work/runtime_examples.air" \
    --function-constant-air "$work/function_constant.air" \
    --turnip "$turnip_dylib" \
    --turnip-render-mode sysmem \
    --toolchain "$RUST_TC" \
    --output "$work/metal-out"

echo "== [6/6] Collecting outputs, CDHashes, and tarball"
cp -R "$work/metal-out/NativeAdrenoMetal.bundle" "$out/"
cp "$work/metal-out/NativeAdrenoMetal.clients" "$out/" || true
cp "$turnip_dylib" "$out/"

(cd "$out" && shasum -a 256 NativeAdrenoMetal.bundle/NativeAdrenoMetal NativeAdrenoMetal.bundle/libvulkan_freedreno.dylib libvulkan_freedreno.dylib > SHA256SUMS)
{
    for bin in \
        "$out/NativeAdrenoMetal.bundle/NativeAdrenoMetal" \
        "$out/NativeAdrenoMetal.bundle/libvulkan_freedreno.dylib"; do
        rel="${bin#$out/}"
        cdh=$(codesign --display --verbose=4 "$bin" 2>&1 | awk -F= '/^CDHash=/{print $2; exit}')
        echo "${cdh}  ${rel}"
    done
} > "$out/CDHashes.txt"
cat "$out/CDHashes.txt"

tar -C "$out" -czf "$out/houji-metal-ios16.tar.gz" \
    NativeAdrenoMetal.bundle NativeAdrenoMetal.clients libvulkan_freedreno.dylib SHA256SUMS CDHashes.txt
ls -lh "$out"
