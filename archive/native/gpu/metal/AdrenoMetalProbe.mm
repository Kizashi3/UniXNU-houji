// SPDX-License-Identifier: MIT
// One iOS process collects loader/ABI/backend, shader results and IOSurface results.
// Read-only discovery is the default. Real GPU work requires --execute.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <IOSurface/IOSurfaceRef.h>
#include <objc/runtime.h>
#include <dlfcn.h>
#include <mach/mach.h>
#include <signal.h>
#include <unistd.h>
#include <sys/stat.h>
#include <time.h>
#include <cstring>
#include "NativeAdrenoABI.h"
#include "NativeMetalBridge.h"

@interface NSObject (HoujiAdrenoPluginInit)
- (id)initWithAcceleratorPort:(unsigned)port;
@end

static uint32_t gSteps;
static unsigned gMarkerService;
static int (*gMarkerOpen)(unsigned, unsigned, uint32_t, unsigned *);
static int (*gMarkerClose)(unsigned);
static unsigned gStageMarker;
static void report(NSString *stage, NSDictionary *values) {
    NSMutableDictionary *row = [values mutableCopy];
    row[@"stage"] = stage;
    row[@"component"] = @"AdrenoMetal";
    row[@"uptime_ns"] = @(clock_gettime_nsec_np(CLOCK_UPTIME_RAW));
    if (gMarkerService && gMarkerOpen && gMarkerClose) {
        unsigned marker = 0x6600 + (++gStageMarker % 0xfd);
        if ([stage isEqualToString:@"complete"]) marker = 0x66fe;
        if (values[@"pass"] && ![values[@"pass"] boolValue]) marker = 0x66ff;
        unsigned connection = 0;
        (void)gMarkerOpen(gMarkerService, mach_task_self(), 0x41470000u | marker, &connection);
        if (connection) (void)gMarkerClose(connection);
    }
    NSData *data = [NSJSONSerialization dataWithJSONObject:row options:NSJSONWritingSortedKeys error:nil];
    if (data) {
        fwrite(data.bytes, 1, data.length, stdout); fputc('\n', stdout); fflush(stdout);
        struct stat st{};
        if (fstat(STDOUT_FILENO, &st) == 0 && S_ISREG(st.st_mode)) fsync(STDOUT_FILENO);
    }
}
static void mark(uint32_t value) {
    if (value >= 0x6501 && value <= 0x6505) gSteps |= 1u << (value - 0x6501);
    if (value == 0x650f) gSteps |= 1u << 5;
    report(@"bridge-progress", @{@"marker": @(value)});
}
static int fail(NSString *stage, NSString *why) {
    report(stage, @{@"pass": @NO, @"reason": why ?: @"unknown", @"gpu_acceleration_verified": @NO});
    return 1;
}
static void expired(int) {
    static const char text[] = "{\"stage\":\"process-watchdog\",\"pass\":false,\"reason\":\"timeout\"}\n";
    write(STDOUT_FILENO, text, sizeof text - 1);
    _exit(124);
}

int main(int argc, char **argv) {
    @autoreleasepool {
        if (argc != 4 && argc != 5) {
            fprintf(stderr, "usage: adrenometalprobe BUNDLE TURNIP CACHE [--execute|--frontend-only]\n");
            return 2;
        }
        const bool frontendOnly = argc == 5 && !strcmp(argv[4], "--frontend-only");
        const bool execute = argc == 5 && (!strcmp(argv[4], "--execute") || frontendOnly);
        if (argc == 5 && !execute) return 2;
        signal(SIGALRM, expired);
        struct stat outputStat{};
        if (!fstat(STDOUT_FILENO, &outputStat) && S_ISREG(outputStat.st_mode)) {
            if (ftruncate(STDOUT_FILENO, 0)) return 2;
        }
        alarm(90); // A process watchdog cannot recover an uninterruptible kernel fault.
        Class base = objc_getClass("_MTLDevice");
        const size_t size = base ? class_getInstanceSize(base) : 0;
        report(@"objc-abi", @{@"base_bytes": @(size), @"execute_requested": @(execute),
                             @"frontend_only": @(frontendOnly),
                             @"os": NSProcessInfo.processInfo.operatingSystemVersionString});
        if (!base || (size != 528 && size != 536)) return fail(@"objc-abi", @"unsupported _MTLDevice layout");

        NSString *path = [NSString stringWithUTF8String:argv[1]];
        NSBundle *bundle = [NSBundle bundleWithPath:path];
        NSError *error = nil;
        if (!bundle || ![bundle loadAndReturnError:&error]) return fail(@"plugin-load", error.localizedDescription);
        Class principal = bundle.principalClass;
        report(@"plugin-load", @{@"principal_class": principal ? NSStringFromClass(principal) : @"missing"});
        if (!principal || ![NSStringFromClass(principal) isEqualToString:@"NativeAdrenoMetalDevice"])
            return fail(@"plugin-load", @"unexpected principal class");
        void *image = dlopen(bundle.executablePath.fileSystemRepresentation, RTLD_NOW | RTLD_LOCAL);
        if (!image) return fail(@"plugin-link", [NSString stringWithUTF8String:dlerror()]);
        auto selftest = reinterpret_cast<decltype(&nmb_selftest)>(dlsym(image, "nmb_selftest"));
        using Open = id (*)(const char *, const char *, uint64_t, void (*)(const char *, const char *));
        auto frontend = reinterpret_cast<Open>(dlsym(image, "native_bridge_metal_open"));
        if (!selftest || !frontend) return fail(@"plugin-link", @"required AdrenoMetal bridge exports missing");
        setenv("TU_DEBUG", "sysmem,nocb", 0);
        void *turnip = dlopen(argv[2], RTLD_NOW | RTLD_LOCAL);
        if (!turnip) return fail(@"turnip-load", [NSString stringWithUTF8String:dlerror()]);
        if (!dlsym(turnip, "vkGetInstanceProcAddr")) return fail(@"turnip-load", @"Vulkan entrypoint missing");
        report(@"turnip-load", @{@"pass": @YES});

        void *io = dlopen("/System/Library/Frameworks/IOKit.framework/IOKit", RTLD_NOW | RTLD_LOCAL);
        if (!io) return fail(@"backend-discovery", @"IOKit could not be loaded");
        auto matching = reinterpret_cast<CFMutableDictionaryRef (*)(const char *)>(dlsym(io, "IOServiceMatching"));
        auto service = reinterpret_cast<unsigned (*)(unsigned, CFDictionaryRef)>(dlsym(io, "IOServiceGetMatchingService"));
        auto release = reinterpret_cast<int (*)(unsigned)>(dlsym(io, "IOObjectRelease"));
        auto entryID = reinterpret_cast<int (*)(unsigned, uint64_t *)>(dlsym(io, "IORegistryEntryGetRegistryEntryID"));
        auto open = reinterpret_cast<int (*)(unsigned, unsigned, uint32_t, unsigned *)>(dlsym(io, "IOServiceOpen"));
        auto close = reinterpret_cast<int (*)(unsigned)>(dlsym(io, "IOServiceClose"));
        auto call = reinterpret_cast<int (*)(unsigned, uint32_t, const void *, size_t, void *, size_t *)>(dlsym(io, "IOConnectCallStructMethod"));
        if (!matching || !service || !release || !entryID || !open || !close || !call)
            return fail(@"backend-discovery", @"IOKit entrypoints missing");
        const unsigned accelerator = service(0, matching("IOAcceleratorES"));
        if (!accelerator) return fail(@"backend-discovery", @"no IOAcceleratorES service; kernel backend required");
        gMarkerService = accelerator; gMarkerOpen = open; gMarkerClose = close;
        uint64_t registryID = 0;
        const int idResult = entryID(accelerator, &registryID);
        unsigned connection = 0;
        const int opened = open(accelerator, mach_task_self(), 0x4147, &connection);
        if (idResult || !registryID || opened || !connection)
            return fail(@"backend-open", [NSString stringWithFormat:@"registry=%d open=%x connection=%u", idResult, opened, connection]);
        NativeAdrenoAbiParams params{};
        size_t paramsBytes = sizeof params;
        const int queried = call(connection, NativeAdrenoMethodQuery, nullptr, 0, &params, &paramsBytes);
        NativeAdrenoAbiDeviceInfo info{};
        size_t infoBytes = sizeof info;
        const int informed = call(connection, NativeAdrenoMethodGetDeviceInfo, nullptr, 0, &info, &infoBytes);
        close(connection);
        report(@"backend-abi", @{@"query_status": @(queried), @"info_status": @(informed),
                                  @"abi_version": @(params.abi_version), @"chip_id": @(info.chip_id),
                                  @"params_bytes": @(paramsBytes), @"info_bytes": @(infoBytes)});
        if (queried || informed || paramsBytes != sizeof params || infoBytes != sizeof info ||
            params.abi_version != NativeAdrenoAbiVersion || info.chip_id != 0x43051401 || info.reserved)
            return fail(@"backend-abi", @"requires the real houji A750 backend with the recorded ABI");
        if (!execute) {
            report(@"discovery-complete", @{@"pass": @YES, @"gpu_work_submitted": @NO,
                                           @"gpu_acceleration_verified": @NO});
            return 0;
        }
        if (mkdir(argv[3], 0700) && access(argv[3], W_OK)) return fail(@"cache", @"cache directory is not writable");
        if (!frontendOnly) {
        NmbSelftest result{};
        const uint32_t code = selftest(argv[2], argv[3], nullptr, 0, mark, &result);
        report(@"bridge-results", @{@"return_code": @(code), @"failed_stage": @(result.stage),
                                     @"seen_steps": @(gSteps), @"compute_bad_of_1000": @(result.compute_bad),
                                     @"render_bad_of_64": @(result.render_bad), @"import_bad_of_4096": @(result.import_bad),
                                     @"message": [[NSString alloc] initWithBytes:result.message length:strnlen(result.message, sizeof result.message) encoding:NSUTF8StringEncoding] ?: @"invalid UTF-8"});
        if (code || result.stage || gSteps != 0x3f || result.compute_bad || result.render_bad || result.import_bad)
            return fail(@"bridge-results", @"shader execution or GPU writeback did not match");
        }

        // The plugin calls this same exported frontend. Use the already verified
        // cache explicitly so runtime/IOSurface and discovery helpers are separable.
        report(@"frontend-open-begin", @{@"registry_id": @(registryID)});
        id<MTLDevice> device = (id<MTLDevice>)frontend(argv[2], argv[3], registryID, nullptr);
        if (!device) return fail(@"frontend-open", @"AdrenoMetal did not create its Objective-C device");
        report(@"frontend-open", @{@"pass": @YES, @"class": NSStringFromClass([device class])});
        report(@"iosurface-begin", @{});
        NSDictionary *properties = @{(__bridge NSString *)kIOSurfaceWidth: @64,
            (__bridge NSString *)kIOSurfaceHeight: @64, (__bridge NSString *)kIOSurfaceBytesPerRow: @256,
            (__bridge NSString *)kIOSurfaceBytesPerElement: @4, (__bridge NSString *)kIOSurfaceAllocSize: @16384,
            (__bridge NSString *)kIOSurfacePixelFormat: @(0x42475241)};
        IOSurfaceRef surface = IOSurfaceCreate((__bridge CFDictionaryRef)properties);
        if (!surface) return fail(@"iosurface", @"allocation failed");
        uint32_t seed = 0;
        if (IOSurfaceLock(surface, 0, &seed) || !IOSurfaceGetBaseAddress(surface))
            return fail(@"iosurface", @"initial CPU lock failed");
        memset(IOSurfaceGetBaseAddress(surface), 0xa5, IOSurfaceGetAllocSize(surface));
        IOSurfaceUnlock(surface, 0, &seed);
        MTLTextureDescriptor *desc = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm width:64 height:64 mipmapped:NO];
        desc.usage = MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead;
        desc.storageMode = MTLStorageModeShared;
        id<MTLTexture> texture = [device newTextureWithDescriptor:desc iosurface:surface plane:0];
        id<MTLCommandQueue> queue = [device newCommandQueue];
        id<MTLCommandBuffer> command = [queue commandBuffer];
        if (!texture || !queue || !command) return fail(@"iosurface", @"Metal texture or command creation failed");
        MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
        pass.colorAttachments[0].texture = texture;
        pass.colorAttachments[0].loadAction = MTLLoadActionClear;
        pass.colorAttachments[0].storeAction = MTLStoreActionStore;
        pass.colorAttachments[0].clearColor = MTLClearColorMake(0.25, 0.5, 0.75, 1);
        id<MTLRenderCommandEncoder> encoder = [command renderCommandEncoderWithDescriptor:pass];
        if (!encoder) return fail(@"iosurface", @"render encoder was refused");
        [encoder endEncoding]; [command commit]; [command waitUntilCompleted];
        if (command.status != MTLCommandBufferStatusCompleted || command.error)
            return fail(@"iosurface", command.error.localizedDescription ?: @"command did not complete");
        if (IOSurfaceLock(surface, kIOSurfaceLockReadOnly, &seed)) return fail(@"iosurface", @"readback lock failed");
        const uint8_t *pixels = static_cast<const uint8_t *>(IOSurfaceGetBaseAddress(surface));
        const size_t stride = IOSurfaceGetBytesPerRow(surface);
        uint32_t bad = 0;
        for (unsigned y = 0; y < 64; ++y) for (unsigned x = 0; x < 64; ++x) {
            const uint8_t *p = pixels + y * stride + x * 4;
            if (abs(int(p[0])-191)>1 || abs(int(p[1])-128)>1 || abs(int(p[2])-64)>1 || p[3]!=255) ++bad;
        }
        IOSurfaceUnlock(surface, kIOSurfaceLockReadOnly, &seed);
        CFRelease(surface);
        report(@"iosurface-results", @{@"bad_pixels_of_4096": @(bad), @"pass": @(bad == 0)});
        if (bad) return fail(@"iosurface-results", @"GPU IOSurface writeback differs from the expected colour");

        // These are the exact helpers before native_bridge_metal_open in the
        // upstream clientDevice path. Record each call, then exercise discovery.
        report(@"plugin-preferences-begin", @{});
        CFPreferencesSetAppValue(CFSTR("CAEnableIOSurfaceCompression"), kCFBooleanFalse, kCFPreferencesCurrentApplication);
        report(@"plugin-preferences-end", @{});
        char directory[512] = {};
        report(@"plugin-cache-directory-begin", @{});
        const size_t cacheBytes = confstr(_CS_DARWIN_USER_CACHE_DIR, directory, sizeof directory);
        report(@"plugin-cache-directory-end", @{@"bytes": @(cacheBytes)});
        report(@"plugin-temp-directory-begin", @{});
        const size_t tempBytes = confstr(_CS_DARWIN_USER_TEMP_DIR, directory, sizeof directory);
        report(@"plugin-temp-directory-end", @{@"bytes": @(tempBytes)});
        report(@"plugin-initializer-begin", @{});
        id pluginDevice = [[principal alloc] initWithAcceleratorPort:accelerator];
        if (!pluginDevice) return fail(@"plugin-initializer", @"Metal discovery returned no device");
        report(@"plugin-initializer-end", @{@"pass": @YES});
        report(@"complete", @{@"pass": @YES, @"gpu_shader_tests_run": @(!frontendOnly),
                              @"gpu_surface_test_verified": @YES,
                              @"desktop_acceleration_verified": @NO});
        release(accelerator); gMarkerService = 0;
        return 0;
    }
}
