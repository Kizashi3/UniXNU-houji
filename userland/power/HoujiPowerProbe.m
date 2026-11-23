// SPDX-License-Identifier: BSD-2-Clause-Patent
// Bounded, read-only power diagnostics. Never sets battery values or power mode.
#import <Foundation/Foundation.h>
#include <CoreFoundation/CoreFoundation.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <errno.h>

typedef uint32_t IoObject;
typedef int32_t IoResult;
typedef CFMutableDictionaryRef (*MatchFn)(const char *);
typedef IoResult (*ServicesFn)(uint32_t, CFDictionaryRef, IoObject *);
typedef IoObject (*NextFn)(IoObject);
typedef IoResult (*ReleaseFn)(IoObject);
typedef IoResult (*PropertiesFn)(IoObject, CFMutableDictionaryRef *, CFAllocatorRef, uint32_t);
typedef CFTypeRef (*SourcesInfoFn)(void);
typedef CFArrayRef (*SourcesListFn)(CFTypeRef);
typedef CFDictionaryRef (*SourceDescriptionFn)(CFTypeRef, CFTypeRef);

static NSDictionary *selected(NSDictionary *source) {
    // No serials, identifiers, process inventory or arbitrary registry content.
    NSArray *keys = @[@"CurrentCapacity", @"MaxCapacity", @"BatteryInstalled", @"IsCharging",
        @"ExternalConnected", @"ExternalChargeCapable", @"AtCriticalLevel", @"FullyCharged",
        @"Voltage", @"Amperage", @"InstantAmperage", @"Temperature", @"TimeRemaining",
        @"Current Capacity", @"Max Capacity", @"Is Present", @"Is Charging", @"Power Source State",
        @"Type", @"Transport Type"];
    NSMutableDictionary *result = [NSMutableDictionary dictionary];
    for (NSString *key in keys) {
        id value = source[key];
        if ([value isKindOfClass:NSNumber.class] || [value isKindOfClass:NSString.class]) result[key] = value;
    }
    return result;
}

static NSDictionary *snapshot(void *io) {
    NSProcessInfo *process = NSProcessInfo.processInfo;
    NSMutableDictionary *result = [@{@"uptime_s": @(process.systemUptime),
        @"low_power_mode": @(process.lowPowerModeEnabled), @"thermal_state": @(process.thermalState),
        @"writes_power_policy": @NO} mutableCopy];
    MatchFn match = io ? (MatchFn)dlsym(io, "IOServiceMatching") : NULL;
    ServicesFn services = io ? (ServicesFn)dlsym(io, "IOServiceGetMatchingServices") : NULL;
    NextFn next = io ? (NextFn)dlsym(io, "IOIteratorNext") : NULL;
    ReleaseFn release = io ? (ReleaseFn)dlsym(io, "IOObjectRelease") : NULL;
    PropertiesFn properties = io ? (PropertiesFn)dlsym(io, "IORegistryEntryCreateCFProperties") : NULL;
    NSMutableArray *registry = [NSMutableArray array];
    if (match && services && next && release && properties) {
        IoObject iterator = 0;
        CFMutableDictionaryRef query = match("IOPMPowerSource");
        // IOServiceGetMatchingServices consumes query even on failure.
        IoResult status = query ? services(0, query, &iterator) : -1;
        result[@"registry_status"] = @(status);
        if (!status && iterator) {
            IoObject entry;
            while (registry.count < 8 && (entry = next(iterator))) {
                CFMutableDictionaryRef values = NULL;
                IoResult rc = properties(entry, &values, kCFAllocatorDefault, 0);
                NSDictionary *filtered = values && CFGetTypeID(values) == CFDictionaryGetTypeID()
                    ? selected((__bridge NSDictionary *)values) : @{};
                [registry addObject:@{@"status": @(rc), @"properties": filtered}];
                if (values) CFRelease(values);
                release(entry);
            }
            release(iterator);
        }
    } else result[@"registry_unavailable"] = @YES;
    result[@"registry_sources"] = registry;

    SourcesInfoFn infoFn = io ? (SourcesInfoFn)dlsym(io, "IOPSCopyPowerSourcesInfo") : NULL;
    SourcesListFn listFn = io ? (SourcesListFn)dlsym(io, "IOPSCopyPowerSourcesList") : NULL;
    SourceDescriptionFn descriptionFn = io ? (SourceDescriptionFn)dlsym(io, "IOPSGetPowerSourceDescription") : NULL;
    NSMutableArray *sources = [NSMutableArray array];
    if (infoFn && listFn && descriptionFn) {
        CFTypeRef info = infoFn();
        CFArrayRef list = info ? listFn(info) : NULL;
        result[@"power_sources_info_available"] = @(info != NULL);
        if (list && CFGetTypeID(list) == CFArrayGetTypeID()) {
            for (CFIndex i = 0; i < CFArrayGetCount(list) && i < 8; ++i) {
                CFDictionaryRef values = descriptionFn(info, CFArrayGetValueAtIndex(list, i));
                if (values && CFGetTypeID(values) == CFDictionaryGetTypeID())
                    [sources addObject:selected((__bridge NSDictionary *)values)];
            }
        }
        if (list) CFRelease(list);
        if (info) CFRelease(info);
    } else result[@"power_sources_api_unavailable"] = @YES;
    result[@"power_sources"] = sources;
    return result;
}

int main(void) {
    @autoreleasepool {
        const char *path = "/private/var/log/houji-power.jsonl";
        int fd = open(path, O_WRONLY | O_CREAT | O_NOFOLLOW, 0600);
        if (fd < 0) return 1;
        struct stat st;
        if (fstat(fd, &st) || !S_ISREG(st.st_mode) || st.st_nlink != 1 ||
            fchmod(fd, 0600) || ftruncate(fd, 0)) {close(fd); return 2;}
        void *io = dlopen("/System/Library/Frameworks/IOKit.framework/IOKit", RTLD_LAZY | RTLD_LOCAL);
        for (unsigned i = 0; i < 25; ++i) {
            @autoreleasepool {
                NSMutableDictionary *row = [snapshot(io) mutableCopy];
                row[@"sample"] = @(i);
                NSData *encoded = [NSJSONSerialization dataWithJSONObject:row options:NSJSONWritingSortedKeys error:NULL];
                if (!encoded || encoded.length > 16384) {close(fd); return 3;}
                NSMutableData *line = [encoded mutableCopy];
                [line appendBytes:"\n" length:1];
                size_t done = 0;
                while (done < line.length) {
                    ssize_t n = write(fd, (const uint8_t *)line.bytes + done, line.length - done);
                    if (n < 0 && errno == EINTR) continue;
                    if (n <= 0) {close(fd); return 4;}
                    done += (size_t)n;
                }
                if (fsync(fd)) {close(fd); return 5;}
            }
            if (i != 24) [NSThread sleepForTimeInterval:5.0];
        }
        if (io) dlclose(io);
        close(fd);
        return 0;
    }
}
