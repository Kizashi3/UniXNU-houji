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

echo "== [3/6] Patching Mesa (26 Turnip patches) & ABI-aligning Houji-ref iOS 16 frontend to m2v@87a869f7"
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

for rel in ("scripts/build-turnip-darwin.py", "scripts/build-adreno-metal-bridge.py"):
    p = core / rel
    s = p.read_text()
    s2 = s.replace("arm64-apple-ios17.0", "arm64-apple-ios16.0").replace("'17.0'", "'16.0'").replace('"17.0"', '"16.0"')
    if rel.endswith("turnip-darwin.py"):
        s2 = s2.replace("17.0", "16.0")
    p.write_text(s2)
    print(f"Retargeted {rel} to iOS 16.0")

# --- 1. ABI-align Houji-ref bridge/NativeMetalObjects.h to upstream AdrenoMetal@0b7094bf ---
hdr = houji_ref / "graphics/metal/AdrenoMetal/bridge/NativeMetalObjects.h"
hs = hdr.read_text()

old_td = """struct NmbTextureDescriptor {
    uint64_t type, format, width, height, depth, levels, samples, array_length, usage, options;
    uint64_t allow_gpu_optimized_contents; /* exactly 0 or 1 */
    uint64_t swizzle[4]; /* Metal channel sources: red, green, blue, alpha */
    uint64_t rotation, framebuffer_only, is_drawable;
};
#if defined(__cplusplus)
static_assert(sizeof(NmbTextureDescriptor)==144, "matched Rust/C texture descriptor");
#endif"""
new_td = """struct NmbTextureDescriptor {
    uint64_t type, format, width, height, depth, levels, samples, array_length, usage, options;
    uint64_t rotation, framebuffer_only, is_drawable;
    uint64_t swizzle; /* RGBA bytes, bit 32 marks explicit */
    uint64_t allow_gpu_optimized_contents;
};
#if defined(__cplusplus)
static_assert(sizeof(NmbTextureDescriptor)==120, "matched upstream Rust/C texture descriptor");
#endif"""
assert old_td in hs, "NmbTextureDescriptor block not found"
hs = hs.replace(old_td, new_td, 1)

old_onsurf = """NmbTexture *nmb_texture_new_on_surface(NmbBuffer *, const struct NmbTextureDescriptor *, uint64_t offset, uint64_t bytes_per_row,
                                       uint32_t pixel_format, uint64_t plane, uint64_t width, uint64_t height, uint64_t chroma_offset,
                                       uint64_t chroma_bytes_per_row);"""
new_onsurf = """typedef uint32_t (*NmbSurfaceSeedFn)(const void *context);
NmbTexture *nmb_texture_new_on_surface(NmbDevice *, NmbBuffer *, const struct NmbTextureDescriptor *, uint64_t offset, uint64_t bytes_per_row,
                                       uint32_t pixel_format, uint64_t plane, uint64_t width, uint64_t height, uint64_t chroma_offset,
                                       uint64_t chroma_bytes_per_row, uint32_t ycbcr_matrix, NmbSurfaceSeedFn surface_seed, const void *surface_context);"""
assert old_onsurf in hs, "nmb_texture_new_on_surface decl not found"
hs = hs.replace(old_onsurf, new_onsurf, 1)

old_swz = 'NmbTexture *nmb_texture_new_view_swizzle(NmbTexture *, uint64_t format, uint64_t kind, const uint64_t levels[2], const uint64_t slices[2], const uint64_t swizzle[4]);'
new_swz = 'NmbTexture *nmb_texture_new_view_swizzle(NmbTexture *, uint64_t format, uint64_t kind, const uint64_t levels[2], const uint64_t slices[2], uint64_t swizzle);'
assert old_swz in hs, "nmb_texture_new_view_swizzle decl not found"
hs = hs.replace(old_swz, new_swz, 1)

old_rpipe = """struct NmbRenderPipelineDescriptor {
    NmbFunction *vertex, *fragment;
    struct NmbColorAttachment colors[8];
    uint64_t depth_format, stencil_format, samples, topology, rasterization;
    uint64_t vertex_inputs; /* 0: no vertex descriptor */
    struct NmbVertexAttribute attributes[31];
    struct NmbVertexLayout layouts[31];
};"""
new_rpipe = """struct NmbRenderPipelineDescriptor {
    NmbFunction *vertex, *fragment;
    struct NmbColorAttachment colors[8];
    uint64_t depth_format, stencil_format, samples, topology, rasterization;
    uint64_t vertex_inputs; /* 0: no vertex descriptor */
    struct NmbVertexAttribute attributes[31];
    struct NmbVertexLayout layouts[31];
    struct NmbTessellation {
        uint64_t tessellates, max_factor, partition_mode, factor_format, factor_step_function, output_winding, control_point_index_type, factor_scale_enabled;
    } tessellation;
    NmbFunction *const *vertex_linked; uint64_t vertex_linked_count;
    NmbFunction *const *vertex_private_linked; uint64_t vertex_private_linked_count;
    NmbFunction *const *fragment_linked; uint64_t fragment_linked_count;
    NmbFunction *const *fragment_private_linked; uint64_t fragment_private_linked_count;
};"""
assert old_rpipe in hs, "NmbRenderPipelineDescriptor block not found"
hs = hs.replace(old_rpipe, new_rpipe, 1)

old_rpass = """struct NmbRenderPassDescriptor {
    struct NmbPassAttachment colors[8], depth, stencil;
    uint64_t width, height, array_length, samples;
    NmbBuffer *visibility; /* the pass's visibility result buffer, or null */
};"""
new_rpass = """struct NmbRenderPassDescriptor {
    struct NmbPassAttachment colors[8], depth, stencil;
    uint64_t width, height, array_length, samples;
    NmbBuffer *visibility; /* the pass's visibility result buffer, or null */
    uint64_t tile_width, tile_height, imageblock_sample_length, threadgroup_memory_length;
};"""
assert old_rpass in hs, "NmbRenderPassDescriptor block not found"
hs = hs.replace(old_rpass, new_rpass, 1)
hdr.write_text(hs)

# --- 2. Update Houji-ref NativeBridgeMetalFrontend.mm to match new struct & calls + waitUntilScheduled fix ---
fe = houji_ref / "graphics/metal/AdrenoMetal/NativeBridgeMetalFrontend.mm"
fes = fe.read_text()

old_td_init = """static bool textureDescriptor(MTLTextureDescriptor *d,NmbTextureDescriptor *out) {
 if(!d)return false;
 const MTLTextureSwizzleChannels swizzle=d.swizzle;
 *out={(uint64_t)d.textureType,(uint64_t)d.pixelFormat,d.width,d.height,d.depth,d.mipmapLevelCount,d.sampleCount,d.arrayLength,(uint64_t)d.usage,(uint64_t)d.resourceOptions,
       (uint64_t)d.allowGPUOptimizedContents,{(uint64_t)swizzle.red,(uint64_t)swizzle.green,(uint64_t)swizzle.blue,(uint64_t)swizzle.alpha},
       textureRotation(d),textureFlag(d,"framebufferOnly"),textureFlag(d,"isDrawable")};"""
new_td_init = """static uint64_t packedSwizzle(MTLTextureSwizzleChannels s) {
 return (1ull<<32)|(uint64_t)s.red|((uint64_t)s.green<<8)|((uint64_t)s.blue<<16)|((uint64_t)s.alpha<<24);
}
static bool textureDescriptor(MTLTextureDescriptor *d,NmbTextureDescriptor *out) {
 if(!d)return false;
 const MTLTextureSwizzleChannels swizzle=d.swizzle;
 *out={(uint64_t)d.textureType,(uint64_t)d.pixelFormat,d.width,d.height,d.depth,d.mipmapLevelCount,d.sampleCount,d.arrayLength,(uint64_t)d.usage,(uint64_t)d.resourceOptions,
       textureRotation(d),textureFlag(d,"framebufferOnly"),textureFlag(d,"isDrawable"),packedSwizzle(swizzle),(uint64_t)d.allowGPUOptimizedContents};"""
assert old_td_init in fes, "textureDescriptor init not found"
fes = fes.replace(old_td_init, new_td_init, 1)

old_swz_get = 'return MTLTextureSwizzleChannelsMake((MTLTextureSwizzle)_descriptor.swizzle[0],(MTLTextureSwizzle)_descriptor.swizzle[1],(MTLTextureSwizzle)_descriptor.swizzle[2],(MTLTextureSwizzle)_descriptor.swizzle[3]);'
new_swz_get = 'const uint64_t s=_descriptor.swizzle; if(!(s&(1ull<<32))) return MTLTextureSwizzleChannelsDefault; return MTLTextureSwizzleChannelsMake((MTLTextureSwizzle)(s&0xff),(MTLTextureSwizzle)((s>>8)&0xff),(MTLTextureSwizzle)((s>>16)&0xff),(MTLTextureSwizzle)((s>>24)&0xff));'
assert old_swz_get in fes, "swizzle getter not found"
fes = fes.replace(old_swz_get, new_swz_get, 1)

old_swz_view = """ const uint64_t channels[4]={(uint64_t)swizzle.red,(uint64_t)swizzle.green,(uint64_t)swizzle.blue,(uint64_t)swizzle.alpha};
 gTextureSwizzledViews++;
 return [self view:nmb_texture_new_view_swizzle(_handle,format,type,l,s,channels)];"""
new_swz_view = """ gTextureSwizzledViews++;
 return [self view:nmb_texture_new_view_swizzle(_handle,format,type,l,s,packedSwizzle(swizzle))];"""
assert old_swz_view in fes, "swizzle view call not found"
fes = fes.replace(old_swz_view, new_swz_view, 1)

old_surf_call = """ NmbTexture *handle=nmb_texture_new_on_surface(buffer.handle,&descriptor,offset,row,IOSurfaceGetPixelFormat(surface),plane,
  IOSurfaceGetWidth(surface),IOSurfaceGetHeight(surface),chroma>=base?chroma-base:0,IOSurfaceGetBytesPerRowOfPlane(surface,1));"""
new_surf_call = """ NmbTexture *handle=nmb_texture_new_on_surface(gDevice,buffer.handle,&descriptor,offset,row,IOSurfaceGetPixelFormat(surface),plane,
  IOSurfaceGetWidth(surface),IOSurfaceGetHeight(surface),chroma>=base?chroma-base:0,IOSurfaceGetBytesPerRowOfPlane(surface,1),0,nullptr,nullptr);"""
assert old_surf_call in fes, "nmb_texture_new_on_surface call not found"
fes = fes.replace(old_surf_call, new_surf_call, 1)

old_ws = "- (void)waitUntilScheduled {\n"
new_ws = "- (void)waitUntilScheduled {\n [self waitUntilCompleted]; return;\n"
assert old_ws in fes, "expected waitUntilScheduled not found"
fes = fes.replace(old_ws, new_ws, 1)
fe.write_text(fes)

# --- 3. Patch Houji-ref NativeAdrenoMetalPlugin.mm: clients fallback + SpringBoard right-edge 2/3 Volume HUD ---
pl = houji_ref / "graphics/metal/AdrenoMetal/NativeAdrenoMetalPlugin.mm"
pls = pl.read_text()
old_cl = '    if (!requestedPath("NativeAdrenoMetal.clients", path, sizeof path)) return false;'
new_cl = '    if (!requestedPath("NativeAdrenoMetal.clients", path, sizeof path)) return true;'
assert old_cl in pls
pls = pls.replace(old_cl, new_cl, 1)

vhud_hook = r'''
#include <objc/runtime.h>
namespace {
struct HoujiCGPoint { double x, y; };
struct HoujiCGSize  { double w, h; };
struct HoujiCGRect  { HoujiCGPoint o; HoujiCGSize s; };

static void (*gOrigVhudLayout1)(id, SEL) = nullptr;
static void (*gOrigVhudLayout2)(id, SEL) = nullptr;
static void (*gOrigSliderSetCenter)(id, SEL, HoujiCGPoint) = nullptr;
static Class gHookedSliderCls = Nil;

static void houji_slider_setCenter(id self, SEL _cmd, HoujiCGPoint pt) {
    @try {
        id sup = ((id (*)(id, SEL))objc_msgSend)(self, sel_registerName("superview"));
        if (sup) {
            HoujiCGRect b = ((HoujiCGRect (*)(id, SEL))objc_msgSend)(sup, sel_registerName("bounds"));
            if (b.s.w > 200.0 && b.s.h > 400.0 && b.s.w < b.s.h) {
                if (pt.x < b.s.w * 0.5) pt.x = b.s.w - pt.x;
                pt.y = b.s.h / 3.0;
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
        if (b.s.w <= 200.0 || b.s.h <= 400.0 || b.s.w >= b.s.h) return;
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
'''
pl.write_text(pls + vhud_hook)
print("ABI-aligned Houji-ref iOS 16 frontend to m2v@87a869f7 + waitUntilScheduled fix + SpringBoard right-2/3 VHUD")
PY

echo "== [4/6] Building iOS 16 Turnip (libvulkan_freedreno.dylib, ABI v2, 128-IB)"
python3 "$core/scripts/build-turnip-darwin.py" --target ios
turnip_dylib="$core/build/mesa-tu-ios/src/freedreno/vulkan/libvulkan_freedreno.dylib"
codesign --force --sign - --timestamp=none "$turnip_dylib"

echo "== [5/6] Building Upstream Rust Bridge (m2v@87a869f7 zero-copy) + Linking with ABI-aligned Houji-ref iOS 16 Frontend"
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
cat > "$work/houji_stubs.c" <<'STUBS'
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
double nmb_command_buffer_kernel_time(void *cb, bool end) { (void)cb; (void)end; return 0.0; }
void nmb_command_buffer_trace(void *cb, uint32_t step, uint64_t val) { (void)cb; (void)step; (void)val; }
bool nmb_device_native_astc_copy_check(void *dev) { (void)dev; return true; }
bool nmb_encoder_memory_barrier_scope(void *enc, uint64_t s, uint64_t a, uint64_t b) { (void)enc; (void)s; (void)a; (void)b; return true; }
void nmb_pattern_probe_stats(uint64_t *out) { if (out) { out[0] = 0; out[1] = 0; } }
void nmb_stage_ring_stop(void) {}
void *nmb_texture_new_native_astc4x4(void *buf, const void *desc, uint64_t row) { (void)buf; (void)desc; (void)row; return NULL; }
void nmb_thread_qos_stats(uint64_t *out) { if (out) { for (int i = 0; i < 6; ++i) out[i] = 0; } }
STUBS

xcrun clang "${common[@]}" -c "$houji_ref/graphics/include/AdrenoPM4.c" -o "$work/AdrenoPM4.o"
xcrun clang "${common[@]}" -c "$work/houji_stubs.c" -o "$work/houji_stubs.o"
xcrun clang++ "${common[@]}" -g -fstack-protector-strong -std=c++17 \
    -fobjc-arc -Wno-deprecated-declarations -Wno-unguarded-availability-new -bundle \
    -x objective-c++ \
    "$houji_ref/graphics/metal/AdrenoMetal/NativeAdrenoMetalPlugin.mm" \
    "$houji_ref/graphics/metal/AdrenoMetal/NativeBridgeMetalFrontend.mm" \
    -x none "$work/AdrenoPM4.o" "$work/houji_stubs.o" "$archive" \
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
