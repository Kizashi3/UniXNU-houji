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
#   3) _MTLDevice instance size is 536 on iPadOS 17 but different on iOS 16 -> accept any valid _MTLDevice class!
fe = core / "drivers/AdrenoMetal/NativeBridgeMetalFrontend.mm"
fes = fe.read_text()
old_ws = "- (void)waitUntilScheduled {\n"
new_ws = "- (void)waitUntilScheduled {\n [self waitUntilCompleted]; return;\n"
assert old_ws in fes, "expected waitUntilScheduled not found"
fes = fes.replace(old_ws, new_ws, 1)
assert "MTLBarrierScopeRenderTargets" in fes
fes = fes.replace("MTLBarrierScopeRenderTargets", "((MTLBarrierScope)(1 << 2))")
old_abi = 'if(!base || class_getInstanceSize(base)!=536){NBLOG(@"native-metal: unexpected _MTLDevice ABI");return nil;}'
new_abi = 'if(!base){NBLOG(@"native-metal: no _MTLDevice");return nil;}'
assert old_abi in fes, "expected _MTLDevice 536 check not found"
fes = fes.replace(old_abi, new_abi, 1)
old_nblog = 'if(logToStderr())fprintf(stderr,"%s: %.140s\\n",getprogname(),nbText.UTF8String?:"?");}while(0)'
new_nblog = '{static std::atomic<int> nbLogCnt{0}; if(nbLogCnt.fetch_add(1)<80) NSLog(@"%@",nbText);}}while(0)'
assert old_nblog in fes, "expected NBLOG stderr line not found"
fes = fes.replace(old_nblog, new_nblog, 1)
old_nberr = 'static NSError *nbError(NSString *why) {\n return [NSError errorWithDomain:@"org.blu-sharky.native-metal" code:-1 userInfo:@{NSLocalizedDescriptionKey:why?:@"refused"}];\n}'
new_nberr = 'static NSError *nbError(NSString *why) {\n static std::atomic<int> nbErrCnt{0}; if(nbErrCnt.fetch_add(1)<80) NSLog(@"native-metal-err: %@",why);\n return [NSError errorWithDomain:@"org.blu-sharky.native-metal" code:-1 userInfo:@{NSLocalizedDescriptionKey:why?:@"refused"}];\n}'
assert old_nberr in fes, "expected nbError not found"
fes = fes.replace(old_nberr, new_nberr, 1)
old_np = 'static void noteProblem(NSString *what) {\n gProblems++;'
new_np = 'static void noteProblem(NSString *what) {\n gProblems++;\n static std::atomic<int> nbProbCnt{0}; if(nbProbCnt.fetch_add(1)<80) NSLog(@"native-metal-prob: %@",what);'
assert old_np in fes, "expected noteProblem not found"
fes = fes.replace(old_np, new_np, 1)
old_libf = 'if(!bytes){if(path)reportUnreadableLibrary(path);return nil;}'
new_libf = 'if(!bytes){NSLog(@"HOUJI-DBG: newLibraryWithFile FAILED path=%@",path);if(path)reportUnreadableLibrary(path);return nil;} else { static std::atomic<int> lfCnt{0}; if(lfCnt.fetch_add(1)<10) NSLog(@"HOUJI-DBG: newLibraryWithFile OK path=%@ len=%lu",path.lastPathComponent,(unsigned long)bytes.length); }'
assert old_libf in fes, "expected newLibraryWithFile check not found"
fes = fes.replace(old_libf, new_libf, 1)
old_rp = 'if(reflection)*reflection=nil;\n auto *p=new NBRenderDescriptor();'
new_rp = 'if(reflection)*reflection=nil;\n static std::atomic<int> rpCnt{0}; if(rpCnt.fetch_add(1)<20) NSLog(@"HOUJI-DBG: newRenderPipe v=%@ f=%@",d.vertexFunction.name,d.fragmentFunction.name);\n auto *p=new NBRenderDescriptor();'
assert old_rp in fes, "expected newRenderPipelineState start not found"
fes = fes.replace(old_rp, new_rp, 1)
old_fnfail = 'if(!handle){\n  NSString *detail=[NSString stringWithFormat:@"specialized function: %@",lastError()];'
new_fnfail = 'if(!handle){\n  static std::atomic<int> fnFailCnt{0}; if(fnFailCnt.fetch_add(1)<40) NSLog(@"HOUJI-DBG: specFunc FAILED %@ err=%@",name,lastError());\n  NSString *detail=[NSString stringWithFormat:@"specialized function: %@",lastError()];'
assert old_fnfail in fes, "expected specFunc fail not found"
fes = fes.replace(old_fnfail, new_fnfail, 1)
fe.write_text(fes)

# Patch upstream NativeAdrenoMetalPlugin.mm:
#   1) always publish (no separate .publish marker file needed)
#   2) disable CAEnableDeepFramebuffer on iOS 16 & skip NativeGOP serveScanout (houji uses AppleCLCD dblbuf4)
#   3) log missing selectors + device open via NSLog in ALL callers (including backboardd P614!)
#   4) in SpringBoard only: reposition Volume HUD to right edge, 2/3 up from bottom (1/3 from top)
pl = core / "drivers/AdrenoMetal/NativeAdrenoMetalPlugin.mm"
pls = pl.read_text()
old_req = 'static bool requested() {\n    char path[1024];\n    return requestedPath("NativeAdrenoMetal.publish", path, sizeof path);\n}'
new_req = 'static bool requested() {\n    return true;\n}'
assert old_req in pls, "expected requested() not found"
pls = pls.replace(old_req, new_req, 1)
old_open = 'device = native_bridge_metal_open(turnip, candidates[i], registryID, nullptr);'
new_open = 'device = native_bridge_metal_open(turnip, candidates[i], registryID, [](const char *c, const char *s){ static int mc=0; if(++mc<=60) NSLog(@"HOUJI-MISSING: %s.%s", c?:"?", s?:"?"); }); if (device) NSLog(@"HOUJI-DBG: opened Metal device for %s cache=%s", getprogname(), candidates[i]);'
assert pls.count(old_open) >= 2, f"expected >=2 native_bridge_metal_open, got {pls.count(old_open)}"
pls = pls.replace(old_open, new_open)
old_fbc = 'CFPreferencesSetAppValue(CFSTR("CAEnableFramebufferCompression"), kCFBooleanFalse, kCFPreferencesCurrentApplication);'
new_fbc = 'CFPreferencesSetAppValue(CFSTR("CAEnableDeepFramebuffer"), kCFBooleanFalse, kCFPreferencesCurrentApplication);\n        ' + old_fbc
assert old_fbc in pls, "expected CAEnableFramebufferCompression not found"
pls = pls.replace(old_fbc, new_fbc, 1)
old_scan = 'bridgephase::serveScanout(*g, device);'
new_scan = '(void)g; /* houji uses AppleCLCD dblbuf4 scanout */'
assert old_scan in pls, "expected serveScanout not found"
pls = pls.replace(old_scan, new_scan, 1)

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
static void (*gOrigSliderSetCenter)(id, SEL, HoujiCGPoint) = nullptr;
static Class gHookedSliderCls = Nil;

static void houji_slider_setCenter(id self, SEL _cmd, HoujiCGPoint pt) {
    @try {
        id sup = ((id (*)(id, SEL))objc_msgSend)(self, sel_registerName("superview"));
        if (sup) {
            HoujiCGRect b = ((HoujiCGRect (*)(id, SEL))objc_msgSend)(sup, sel_registerName("bounds"));
            if (b.s.w > 200.0 && b.s.h > 400.0 && b.s.w < b.s.h) { // portrait
                if (pt.x < b.s.w * 0.5) pt.x = b.s.w - pt.x;
                pt.y = b.s.h / 3.0; // 2/3 up from bottom = 1/3 down from top
            }
        }
    } @catch (NSException *e) {}
    if (gOrigSliderSetCenter) gOrigSliderSetCenter(self, _cmd, pt);
}

static void houji_hook_slider_class(Class cls) {
    if (!cls || cls == gHookedSliderCls) return;
    const char *cname = class_getName(cls);
    if (!cname || strcmp(cname, "UIView") == 0) return;
    SEL s = sel_registerName("setCenter:");
    if (Method m = class_getInstanceMethod(cls, s)) {
        gOrigSliderSetCenter = (void (*)(id, SEL, HoujiCGPoint))method_getImplementation(m);
        if (!class_addMethod(cls, s, (IMP)houji_slider_setCenter, method_getTypeEncoding(m))) {
            method_setImplementation(m, (IMP)houji_slider_setCenter);
        }
        gHookedSliderCls = cls;
        fprintf(stderr, "HOUJI-VHUD: hooked %s.setCenter: (right edge, y=h/3)\n", cname);
    }
}

static void houji_walk_vhud(id view, HoujiCGRect rootB, int depth) {
    if (!view || depth > 3) return;
    NSArray *subs = ((NSArray *(*)(id, SEL))objc_msgSend)(view, sel_registerName("subviews"));
    for (id sub in subs) {
        HoujiCGRect f = ((HoujiCGRect (*)(id, SEL))objc_msgSend)(sub, sel_registerName("frame"));
        if (f.s.w > 3.0 && f.s.w < rootB.s.w * 0.45 && f.s.h > 40.0 && f.s.h < rootB.s.h * 0.5) {
            houji_hook_slider_class(object_getClass(sub));
            HoujiCGPoint c = ((HoujiCGPoint (*)(id, SEL))objc_msgSend)(sub, sel_registerName("center"));
            if (c.x < rootB.s.w * 0.5) c.x = rootB.s.w - c.x;
            c.y = rootB.s.h / 3.0;
            ((void (*)(id, SEL, HoujiCGPoint))objc_msgSend)(sub, sel_registerName("setCenter:"), c);
        } else {
            houji_walk_vhud(sub, rootB, depth + 1);
        }
    }
}

static void houji_mirror_vhud_view(id vc) {
    @try {
        id view = ((id (*)(id, SEL))objc_msgSend)(vc, sel_registerName("view"));
        if (!view) return;
        HoujiCGRect b = ((HoujiCGRect (*)(id, SEL))objc_msgSend)(view, sel_registerName("bounds"));
        if (b.s.w <= 200.0 || b.s.h <= 400.0 || b.s.w >= b.s.h) return; // portrait only
        houji_walk_vhud(view, b, 0);
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
            if (Class c = objc_getClass("SBElasticSliderView")) houji_hook_slider_class(c);
            else if (Class c2 = objc_getClass("SBVolumeHUDView")) houji_hook_slider_class(c2);
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
                        fprintf(stderr, "HOUJI-VHUD: hooked %s.viewDidLayoutSubviews\n", vcs[i]);
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
