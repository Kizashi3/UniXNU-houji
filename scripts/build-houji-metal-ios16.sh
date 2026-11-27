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

echo "== [1/5] Checking out matched UniXNU + AdrenoMetal@0b7094bf + m2v@87a869f7 (Zero-Copy)"
checkout "$core" https://github.com/UniXNU/UniXNU.git e7bddb9a7eecdcf81f36da9fa38bd9d4d3f155c2
checkout "$core/drivers/Adreno740" https://github.com/UniXNU/Adreno740.git 2962e289c9690aeb668072c170679e6fb28bf8de
checkout "$core/drivers/AdrenoMetal" https://github.com/UniXNU/AdrenoMetal.git 0b7094bfdd221c210fb68b8927c3625d610df671
checkout "$core/drivers/GopFramebuffer" https://github.com/UniXNU/GopFramebuffer.git b0d812d578efa2acb005b66f73168891719af09a
checkout "$core/kits/AdrenoPM4" https://github.com/UniXNU/AdrenoPM4.git 445f8fe6d115738352b9d78dc70af6d61aa7f62f
checkout "$m2v" https://github.com/UniXNU/metal2vulkan.git 87a869f7fc4b73265d4812c40d8cccb6a83c7b17
checkout "$mesa" https://chromium.googlesource.com/external/gitlab.freedesktop.org/mesa/mesa \
    85fda3b36405bcaea8bffc64aa4f2651dc90770d

echo "== [2/5] Installing host tools & Rust 1.98.0 iOS target"
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

echo "== [3/5] Patching Mesa (26 Turnip patches) & retargeting UniXNU AdrenoMetal to iOS 16.0"
python3 -m venv "$core/.cache/mesa-venv"
"$core/.cache/mesa-venv/bin/python" -m pip install 'meson==1.9.1' 'Mako==1.3.10' 'packaging==25.0' 'PyYAML==6.0.2'

python3 - "$core" "$mesa" <<'PY'
import json, re, subprocess, sys
from pathlib import Path

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

# Retarget Turnip, Rust bridge, and Metal plugin builders to iOS 16.0
for rel in ("scripts/build-turnip-darwin.py", "scripts/build-adreno-metal-bridge.py", "scripts/build-adreno-metal-plugin.py"):
    p = core / rel
    s = p.read_text()
    s2 = s.replace("arm64-apple-ios17.0", "arm64-apple-ios16.0").replace("'17.0'", "'16.0'").replace('"17.0"', '"16.0"')
    if rel.endswith("turnip-darwin.py"):
        s2 = s2.replace("17.0", "16.0")
    if rel.endswith("plugin.py"):
        s2 = s2.replace("'-Werror'", "'-Wno-unguarded-availability-new'")
        s2 = s2.replace(
            "subprocess.run([sys.executable, ROOT / 'scripts/macho-self-bind-weak-imports.py', turnip_lib], check=True)",
            "pass  # iOS 16 dylib has no chained fixups",
        )
    p.write_text(s2)
    print(f"Retargeted {rel} to iOS 16.0")

# Patch upstream NativeBridgeMetalFrontend.mm:
#   1) waitUntilScheduled -> waitUntilCompleted (eliminates flicker/tearing/black-flash while keeping commit async!)
#   2) MTLBarrierScopeRenderTargets is macOS-only in iOS SDK 18.5 -> use literal (MTLBarrierScope)(1 << 2)
fe = core / "drivers/AdrenoMetal/NativeBridgeMetalFrontend.mm"
fes = fe.read_text()
old_ws = "- (void)waitUntilScheduled {\n"
new_ws = "- (void)waitUntilScheduled {\n [self waitUntilCompleted]; return;\n"
assert old_ws in fes, "expected waitUntilScheduled not found"
fes = fes.replace(old_ws, new_ws, 1)
assert "MTLBarrierScopeRenderTargets" in fes
fes = fes.replace("MTLBarrierScopeRenderTargets", "((MTLBarrierScope)(1 << 2))")
fe.write_text(fes)

# Patch upstream NativeAdrenoMetalPlugin.mm:
#   1) always publish (no separate .publish marker file needed)
#   2) in SpringBoard only: reposition Volume HUD to right edge, 2/3 up from bottom (1/3 from top = 297pt)
pl = core / "drivers/AdrenoMetal/NativeAdrenoMetalPlugin.mm"
pls = pl.read_text()
old_req = 'static bool requested() {\n    char path[1024];\n    return requestedPath("NativeAdrenoMetal.publish", path, sizeof path);\n}'
new_req = 'static bool requested() {\n    return true;\n}'
assert old_req in pls, "expected requested() not found"
pls = pls.replace(old_req, new_req, 1)

vhud_hook = r'''
#if !TARGET_OS_OSX
#include <objc/runtime.h>
namespace {
struct HoujiCGPoint { double x, y; };
struct HoujiCGSize  { double w, h; };
struct HoujiCGRect  { HoujiCGPoint o; HoujiCGSize s; };

static double houji_volumeButtonsCenterY(id self, SEL _cmd) {
    (void)self; (void)_cmd;
    // Xiaomi 14 (1200x2670 @3x = 400x890 pt): 2/3 up from bottom = 1/3 down from top = 296.7 pt
    return 297.0;
}

static void (*gOrigVhudLayout1)(id, SEL) = nullptr;
static void (*gOrigVhudLayout2)(id, SEL) = nullptr;

static void houji_mirror_vhud_view(id vc) {
    @try {
        id view = ((id (*)(id, SEL))objc_msgSend)(vc, sel_registerName("view"));
        if (!view) return;
        HoujiCGRect b = ((HoujiCGRect (*)(id, SEL))objc_msgSend)(view, sel_registerName("bounds"));
        if (b.s.w <= 100.0 || b.s.h <= 100.0 || b.s.w >= b.s.h) return; // portrait only
        NSArray *subs = ((NSArray *(*)(id, SEL))objc_msgSend)(view, sel_registerName("subviews"));
        for (id sub in subs) {
            HoujiCGRect f = ((HoujiCGRect (*)(id, SEL))objc_msgSend)(sub, sel_registerName("frame"));
            if (f.s.w > 1.0 && f.s.w < b.s.w * 0.5) {
                HoujiCGPoint c = ((HoujiCGPoint (*)(id, SEL))objc_msgSend)(sub, sel_registerName("center"));
                if (c.x < b.s.w * 0.5) {
                    c.x = b.s.w - c.x;
                    ((void (*)(id, SEL, HoujiCGPoint))objc_msgSend)(sub, sel_registerName("setCenter:"), c);
                }
            }
        }
    } @catch (NSException *e) {}
}

static void houji_vhud_layout1(id self, SEL _cmd) {
    if (gOrigVhudLayout1) gOrigVhudLayout1(self, _cmd);
    houji_mirror_vhud_view(self);
}
static void houji_vhud_layout2(id self, SEL _cmd) {
    if (gOrigVhudLayout2) gOrigVhudLayout2(self, _cmd);
    houji_mirror_vhud_view(self);
}

__attribute__((constructor))
static void houji_install_vhud_hook() {
    if (!getprogname() || strcmp(getprogname(), "SpringBoard") != 0) return;
    dispatch_async(dispatch_get_main_queue(), ^{
        @try {
            if (Class c = objc_getClass("SBVolumeHUDSettings")) {
                if (Method m = class_getInstanceMethod(c, sel_registerName("volumeButtonsCenterY"))) {
                    method_setImplementation(m, (IMP)houji_volumeButtonsCenterY);
                    fprintf(stderr, "HOUJI-VHUD: hooked SBVolumeHUDSettings.volumeButtonsCenterY -> 297.0\n");
                }
            }
            const char *vcs[2] = {"SBElasticVolumeViewController", "SBVolumeHUDViewController"};
            for (int i = 0; i < 2; ++i) {
                if (Class c = objc_getClass(vcs[i])) {
                    SEL s = sel_registerName("viewDidLayoutSubviews");
                    if (Method m = class_getInstanceMethod(c, s)) {
                        IMP orig = method_getImplementation(m);
                        IMP rep = (i == 0) ? (IMP)houji_vhud_layout1 : (IMP)houji_vhud_layout2;
                        if (i == 0) gOrigVhudLayout1 = (void (*)(id, SEL))orig;
                        else        gOrigVhudLayout2 = (void (*)(id, SEL))orig;
                        if (!class_addMethod(c, s, rep, method_getTypeEncoding(m))) {
                            method_setImplementation(m, rep);
                        }
                        fprintf(stderr, "HOUJI-VHUD: hooked %s.viewDidLayoutSubviews (right edge)\n", vcs[i]);
                    }
                }
            }
        } @catch (NSException *e) {}
    });
}
} // namespace
#endif
'''
pls = pls + vhud_hook
pl.write_text(pls)
print("Patched upstream AdrenoMetal@0b7094bf (waitUntilScheduled->waitUntilCompleted + always publish + SpringBoard right-2/3 VHUD)")
PY

echo "== [4/5] Building iOS 16 Turnip (ABI v2, 128-IB) + Matched Upstream Zero-Copy Plugin Bundle"
python3 "$core/scripts/build-turnip-darwin.py" --target ios
python3 "$core/scripts/build-adreno-metal-plugin.py" --target ios --no-replay --translator-source "$m2v"

bundle="$core/build/adreno-metal-plugin/NativeAdrenoMetal.bundle"
turnip_dylib="$bundle/libvulkan_freedreno.dylib"
test -f "$bundle/NativeAdrenoMetal"
test -f "$turnip_dylib"

echo "== [5/5] Collecting outputs, CDHashes, and tarball"
cp -R "$bundle" "$out/"
cp "$turnip_dylib" "$out/libvulkan_freedreno.dylib"
cat > "$out/NativeAdrenoMetal.clients" <<'CLIENTS'
backboardd
SpringBoard
iconservicesagent
PosterBoard
SBRendererService
AegirPoster
CollectionsPoster
PhotosPosterProvider
GradientPosterExtension
EmojiPosterExtension
ExtragalacticPoster
PridePosterExtension
MobileSlideShow
Preferences
vktest
mtltest
CLIENTS

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
