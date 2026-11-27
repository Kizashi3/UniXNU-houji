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
houji_ref="$work/houji-ref"

checkout() {
    local path=$1 url=$2 revision=$3
    mkdir -p "$path"
    git init -q "$path"
    git -C "$path" fetch --no-tags --depth=1 "$url" "$revision"
    git -C "$path" checkout --detach FETCH_HEAD
    test "$(git -C "$path" rev-parse HEAD)" = "$revision"
}

echo "== [1/6] Checking out sources (UniXNU Turnip v2 + m2v@87a869f7 zero-copy + Houji-ref iOS 16 frontend)"
checkout "$core" https://github.com/UniXNU/UniXNU.git e7bddb9a7eecdcf81f36da9fa38bd9d4d3f155c2
checkout "$core/drivers/Adreno740" https://github.com/UniXNU/Adreno740.git 2962e289c9690aeb668072c170679e6fb28bf8de
checkout "$core/drivers/AdrenoMetal" https://github.com/UniXNU/AdrenoMetal.git 0b7094bfdd221c210fb68b8927c3625d610df671
checkout "$core/kits/AdrenoPM4" https://github.com/UniXNU/AdrenoPM4.git 445f8fe6d115738352b9d78dc70af6d61aa7f62f
checkout "$m2v" https://github.com/UniXNU/metal2vulkan.git 87a869f7fc4b73265d4812c40d8cccb6a83c7b17
checkout "$mesa" https://chromium.googlesource.com/external/gitlab.freedesktop.org/mesa/mesa \
    85fda3b36405bcaea8bffc64aa4f2651dc90770d
git clone --depth=1 https://github.com/lonzzi/UniXNU-houji.git "$houji_ref"

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

echo "== [3/6] Patching Mesa (26 Turnip patches) & adapting build scripts for iOS 16.0"
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

# Retarget Turnip and bridge builders to iOS 16.0
for rel in ("scripts/build-turnip-darwin.py", "scripts/build-adreno-metal-bridge.py"):
    p = core / rel
    s = p.read_text()
    s2 = s.replace("arm64-apple-ios17.0", "arm64-apple-ios16.0").replace("IPHONEOS_DEPLOYMENT_TARGET'] = '17.0'", "IPHONEOS_DEPLOYMENT_TARGET'] = '16.0'").replace("17.0", "16.0") if rel.endswith("turnip-darwin.py") else s.replace("arm64-apple-ios17.0", "arm64-apple-ios16.0").replace("'17.0'", "'16.0'").replace('"17.0"', '"16.0"')
    p.write_text(s2)
    print(f"Retargeted {rel} to iOS 16.0")

# Patch Houji-ref iOS 16 NativeBridgeMetalFrontend.mm:
#   waitUntilScheduled -> waitUntilCompleted (eliminates flicker/tearing/black-flash while keeping commit async!)
fe = houji_ref / "graphics/metal/AdrenoMetal/NativeBridgeMetalFrontend.mm"
fes = fe.read_text()
old_ws = "- (void)waitUntilScheduled {\n"
new_ws = "- (void)waitUntilScheduled {\n [self waitUntilCompleted]; return;\n"
assert old_ws in fes, "expected waitUntilScheduled not found"
fes = fes.replace(old_ws, new_ws, 1)
fe.write_text(fes)

# Patch Houji-ref NativeAdrenoMetalPlugin.mm: allow all if .clients absent
pl = houji_ref / "graphics/metal/AdrenoMetal/NativeAdrenoMetalPlugin.mm"
pls = pl.read_text()
old_cl = '    if (!requestedPath("NativeAdrenoMetal.clients", path, sizeof path)) return false;'
new_cl = '    if (!requestedPath("NativeAdrenoMetal.clients", path, sizeof path)) return true;'
assert old_cl in pls
pl.write_text(pls.replace(old_cl, new_cl, 1))
print("Patched Houji-ref iOS 16 frontend (waitUntilScheduled->waitUntilCompleted + clients fallback)")
PY

echo "== [4/6] Building iOS 16 Turnip (libvulkan_freedreno.dylib, ABI v2, 128-IB)"
python3 "$core/scripts/build-turnip-darwin.py" --target ios
turnip_dylib="$core/build/mesa-tu-ios/src/freedreno/vulkan/libvulkan_freedreno.dylib"
codesign --force --sign - --timestamp=none "$turnip_dylib"

echo "== [5/6] Building Upstream Rust Bridge (m2v@87a869f7 zero-copy) + Linking with Houji-ref iOS 16 Frontend"
python3 "$core/scripts/build-adreno-metal-bridge.py" --target ios --source "$m2v"
archive="$core/build/adreno-metal-bridge/ios/libadreno_metal_bridge.a"
echo "Found bridge archive: $archive"
test -f "$archive"

sdk=$(xcrun --sdk iphoneos --show-sdk-path)
bundle="$work/NativeAdrenoMetal.bundle"
mkdir -p "$bundle"

common=(
    -target arm64-apple-ios16.0 -isysroot "$sdk" -O2
    -DHOUJI_TURNIP_RENDER_AUTOTUNE=1
    -DHOUJI_GPU_STAGE_TRACE=0
    -DHOUJI_GPU_CPU_PROFILE=0
    -I "$houji_ref/graphics/include"
    -I "$mesa/include"
)
xcrun clang "${common[@]}" -c "$houji_ref/graphics/include/AdrenoPM4.c" -o "$work/AdrenoPM4.o"
xcrun clang++ "${common[@]}" -g -fstack-protector-strong -std=c++17 \
    -fobjc-arc -Wno-deprecated-declarations -Wno-unguarded-availability-new -bundle \
    -x objective-c++ \
    "$houji_ref/graphics/metal/AdrenoMetal/NativeAdrenoMetalPlugin.mm" \
    "$houji_ref/graphics/metal/AdrenoMetal/NativeBridgeMetalFrontend.mm" \
    -x none "$work/AdrenoPM4.o" "$archive" \
    -Wl,-dead_strip -lobjc -framework Foundation -framework Metal -framework IOSurface \
    -o "$bundle/NativeAdrenoMetal"

python3 - "$bundle/Info.plist" <<'PY'
import plistlib, sys
from pathlib import Path
info = dict(
    CFBundleExecutable="NativeAdrenoMetal",
    CFBundleIdentifier="org.blu-sharky.NativeAdrenoMetal",
    CFBundlePackageType="BNDL",
    CFBundleShortVersionString="1",
    CFBundleVersion="1",
    MinimumOSVersion="16.0",
    NSPrincipalClass="NativeAdrenoMetalDevice",
)
Path(sys.argv[1]).write_bytes(plistlib.dumps(info))
PY
cp "$turnip_dylib" "$bundle/libvulkan_freedreno.dylib"
strip -x "$bundle/NativeAdrenoMetal"
codesign --force --sign - --timestamp=none "$bundle/libvulkan_freedreno.dylib"
codesign --force --sign - --timestamp=none "$bundle"
codesign --verify --strict "$bundle"

echo "== [6/6] Collecting outputs, CDHashes, and tarball"
cp -R "$bundle" "$out/"
cp "$houji_ref/graphics/metal/NativeAdrenoMetal.clients" "$out/"
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
