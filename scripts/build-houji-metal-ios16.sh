#!/usr/bin/env bash
set -euo pipefail

project=$(git rev-parse --show-toplevel)
work=$(mktemp -d)
out="$project/out/houji-metal-ios16"
rm -rf "$out"
mkdir -p "$out"

core="$work/unixnu"
mesa="$core/.cache/mesa-work"
m2v="$core/.cache/gpu-reference/metal2vulkan"

checkout() {
    local path=$1 url=$2 revision=$3
    mkdir -p "$path"
    git init -q "$path"
    git -C "$path" fetch --no-tags --depth=1 "$url" "$revision"
    git -C "$path" checkout --detach FETCH_HEAD
    test "$(git -C "$path" rev-parse HEAD)" = "$revision"
}

echo "== [1/6] Checking out pinned 2026-11-25 upstream sources"
checkout "$core" https://github.com/UniXNU/UniXNU.git e7bddb9a7eecdcf81f36da9fa38bd9d4d3f155c2
checkout "$core/drivers/Adreno740" https://github.com/UniXNU/Adreno740.git 2962e289c9690aeb668072c170679e6fb28bf8de
checkout "$core/drivers/AdrenoMetal" https://github.com/UniXNU/AdrenoMetal.git 0b7094bfdd221c210fb68b8927c3625d610df671
checkout "$core/kits/AdrenoPM4" https://github.com/UniXNU/AdrenoPM4.git 445f8fe6d115738352b9d78dc70af6d61aa7f62f
checkout "$core/drivers/GopFramebuffer" https://github.com/UniXNU/GopFramebuffer.git b0d812d578efa2acb005b66f73168891719af09a
checkout "$m2v" https://github.com/UniXNU/metal2vulkan.git 87a869f7fc4b73265d4812c40d8cccb6a83c7b17
checkout "$mesa" https://chromium.googlesource.com/external/gitlab.freedesktop.org/mesa/mesa \
    85fda3b36405bcaea8bffc64aa4f2651dc90770d

echo "== [2/6] Installing host tools & Rust iOS target"
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

echo "== [3/6] Patching Mesa (26 upstream Turnip patches) & adapting scripts for iOS 16.0"
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
print(f"Applied {len(pins['patches'])} Mesa/Turnip patches cleanly")

# Retarget iOS deployment target 17.0 -> 16.0 across Turnip, bridge, and plugin builders
for rel in ("scripts/build-turnip-darwin.py", "scripts/build-adreno-metal-bridge.py", "scripts/build-adreno-metal-plugin.py"):
    p = core / rel
    s = p.read_text()
    s2 = s.replace("arm64-apple-ios17.0", "arm64-apple-ios16.0").replace("IPHONEOS_DEPLOYMENT_TARGET'] = '17.0'", "IPHONEOS_DEPLOYMENT_TARGET'] = '16.0'").replace('17.0', '16.0') if rel.endswith('turnip-darwin.py') else s.replace("arm64-apple-ios17.0", "arm64-apple-ios16.0").replace("'17.0'", "'16.0'").replace('"17.0"', '"16.0"')
    if rel.endswith("build-adreno-metal-plugin.py"):
        s2 = s2.replace("'-Wno-deprecated-declarations'", "'-Wno-deprecated-declarations', '-Wno-unguarded-availability-new'")
    if s2 != s:
        p.write_text(s2)
        print(f"Retargeted {rel} to iOS 16.0")

# Adapt AdrenoMetal for iOS 16.7:
# 1) Accept _MTLDevice instance size 528 (iOS 16.7) in addition to 536 (iPadOS 17.7)
fe = core / "drivers/AdrenoMetal/NativeBridgeMetalFrontend.mm"
fes = fe.read_text()
old_abi = "if(!base || class_getInstanceSize(base)!=536)"
new_abi = "if(!base || (class_getInstanceSize(base)!=536 && class_getInstanceSize(base)!=528))"
assert old_abi in fes, "expected _MTLDevice 536 check not found"
fes = fes.replace(old_abi, new_abi, 1).replace("MTLLanguageVersion3_1", "MTLLanguageVersion3_0").replace("MTLBarrierScopeRenderTargets", "((MTLBarrierScope)4)")
fe.write_text(fes)
print("Adapted NativeBridgeMetalFrontend.mm for iOS 16 _MTLDevice size 528 & MTLLanguageVersion3_0")

# 2) Skip A740 stage-1 self-test when NativeAdrenoMetal.publish is absent; always use publish::deviceForPort
pl = core / "drivers/AdrenoMetal/NativeAdrenoMetalPlugin.mm"
pls = pl.read_text()
old_pub = "    if (publish::requested()) return publish::deviceForPort(port);"
new_pub = "    (void)publish::requested(); return publish::deviceForPort(port);"
assert old_pub in pls, "expected publish::requested() line not found"
pl.write_text(pls.replace(old_pub, new_pub, 1))
print("Adapted NativeAdrenoMetalPlugin.mm to always use publish::deviceForPort")
PY

echo "== [4/6] Building iOS 16 Turnip (libvulkan_freedreno.dylib)"
python3 "$core/scripts/build-turnip-darwin.py" --target ios

echo "== [5/6] Building NativeAdrenoMetal.bundle (bridge + frontend + Turnip)"
python3 "$core/scripts/build-adreno-metal-plugin.py" --target ios --no-replay --translator-source "$m2v"

echo "== [6/6] Collecting outputs, CDHashes, and tarball"
cp -R "$core/build/adreno-metal-plugin/NativeAdrenoMetal.bundle" "$out/"
cp "$core/build/mesa-tu-ios/src/freedreno/vulkan/libvulkan_freedreno.dylib" "$out/"

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
    NativeAdrenoMetal.bundle libvulkan_freedreno.dylib SHA256SUMS CDHashes.txt
ls -lh "$out"
