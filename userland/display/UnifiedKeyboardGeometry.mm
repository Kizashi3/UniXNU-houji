// SPDX-License-Identifier: MIT
// Board-local iOS 16 keyboard layout compatibility. Reference behavior:
// SniperGER/ReScale2, 29c36d25, ReScaleKB/Tweak.xm (screen width minus padding).
// The original UIKit computes the height and layout. No display resampling.
#import <Foundation/Foundation.h>
#import <CoreGraphics/CGGeometry.h>
#import <objc/message.h>
#import <objc/runtime.h>
#include <cmath>
#include <algorithm>
#include <initializer_list>
#include <cstdlib>
#include <cstring>
#include <cstdarg>
#include <cstdio>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>


namespace {
struct Insets { CGFloat top, left, bottom, right; };
using SizeMethod = CGSize (*)(id, SEL, NSInteger);
using PaddingMethod = Insets (*)(id, SEL, NSInteger, id);
struct Entry { const char *name; SEL selector; SizeMethod original; };
Entry entries[] = {
    {"defaultSizeForInterfaceOrientation:", nullptr, nullptr},
    {"keyboardSizeForInterfaceOrientation:", nullptr, nullptr},
    {"sizeForInterfaceOrientation:", nullptr, nullptr},
};
PaddingMethod padding;
SEL paddingSelector;
unsigned reportCount;
thread_local bool inGeometry;

void report(NSString *format, ...) {
    va_list arguments;
    va_start(arguments, format);
    NSString *line = [[NSString alloc] initWithFormat:format arguments:arguments];
    va_end(arguments);
    NSLog(@"%@", line);
    // Geometry only: no typed characters, field text, or screenshots. A small
    // ordinary file survives a recovery reboot independently of unified logs.
    const char *name = getprogname();
    if (!name || !*name || strlen(name) > 63) return;
    for (const char *c = name; *c; ++c)
        if (!( (*c >= 'a' && *c <= 'z') || (*c >= 'A' && *c <= 'Z') ||
               (*c >= '0' && *c <= '9') || *c == '_' || *c == '-' || *c == '.' )) return;
    char path[192];
    snprintf(path, sizeof(path), "/private/var/mobile/Library/Logs/HoujiKeyboard-v18-%s.log", name);
    const int fd = open(path,
                        O_WRONLY | O_APPEND | O_CREAT | O_NOFOLLOW, 0600);
    if (fd < 0) return;
    struct stat st = {};
    if (!fstat(fd, &st) && S_ISREG(st.st_mode) && st.st_uid == getuid() &&
        !(st.st_mode & 0077) && st.st_size < 32768) {
        NSData *data = [[line stringByAppendingString:@"\n"] dataUsingEncoding:NSUTF8StringEncoding];
        if (data.length < 2048) (void)write(fd, data.bytes, data.length);
    }
    close(fd);
}

bool exactType(Method method, unsigned argument, const char *expected) {
    char *type = argument == UINT_MAX ? method_copyReturnType(method)
                                     : method_copyArgumentType(method, argument);
    const bool same = type && !strcmp(type, expected);
    free(type);
    return same;
}

#include "HoujiStatusBarGeometry.h"

CGSize adjusted(id receiver, SEL selector, NSInteger orientation, CGSize original) {
    // Restrict the correction to portrait on this board. All system APPL bundles share this library.
    // Other displays, orientations, invalid geometry and non-UI callers retain
    // the original result. In particular this never resizes a UIWindow.
    if (inGeometry || !NSThread.isMainThread || (orientation != 1 && orientation != 2)) return original;
    inGeometry = true;
    CGSize result = original;
    @try {
        Class screenClass = NSClassFromString(@"UIScreen");
        Class deviceClass = NSClassFromString(@"UIDevice");
        id screen = ((id (*)(id, SEL))objc_msgSend)(screenClass, sel_registerName("mainScreen"));
        id device = ((id (*)(id, SEL))objc_msgSend)(deviceClass, sel_registerName("currentDevice"));
        const NSInteger idiom = ((NSInteger (*)(id, SEL))objc_msgSend)(device, sel_registerName("userInterfaceIdiom"));
        const CGRect bounds = ((CGRect (*)(id, SEL))objc_msgSend)(screen, sel_registerName("bounds"));
        const CGRect native = ((CGRect (*)(id, SEL))objc_msgSend)(screen, sel_registerName("nativeBounds"));
        const CGFloat scale = ((CGFloat (*)(id, SEL))objc_msgSend)(screen, sel_registerName("scale"));
        const Insets pad = padding(receiver, paddingSelector, orientation, nil);
        const CGFloat width = bounds.size.width - pad.left - pad.right;
        const bool target = screen && device && idiom == 0 && scale == 3 &&
            native.size.width == 1200 && native.size.height == 2670 &&
            bounds.size.width == 400 && bounds.size.height == 890;
        if (target && std::isfinite(width) && std::isfinite(original.width) &&
            std::isfinite(original.height) && original.height > 0 && original.height < 890 &&
            std::isfinite(pad.left) && std::isfinite(pad.right) && pad.left >= 0 && pad.right >= 0 &&
            width >= 300 && width <= 400) result.width = width;
        if (reportCount++ < 24) {
            report(@"HOUJI KEYBOARD v18: %s original=%.3fx%.3f result=%.3fx%.3f screen=%.3fx%.3f native=%.0fx%.0f scale=%.3f padding=%.3f,%.3f target=%d",
                sel_getName(selector), original.width, original.height, result.width, result.height,
                bounds.size.width, bounds.size.height, native.size.width, native.size.height, scale,
                pad.left, pad.right, target);
        }
    } @catch (NSException *exception) {
        result = original;
        if (reportCount++ < 24) report(@"HOUJI KEYBOARD v18: original retained after %@", exception.name);
    }
    inGeometry = false;
    return result;
}

CGSize replacement(id receiver, SEL selector, NSInteger orientation) {
    for (const auto &entry : entries) {
        if (entry.selector == selector && entry.original) {
            return adjusted(receiver, selector, orientation, entry.original(receiver, selector, orientation));
        }
    }
    // All replacements are installed only after the three original IMPs exist.
    __builtin_trap();
}

void install() {
    if (![NSProcessInfo.processInfo.operatingSystemVersionString containsString:@"16.7.16"]) {
        report(@"HOUJI KEYBOARD v18: OS gate refused");
        return;
    }
    Class cls = NSClassFromString(@"UIKeyboardImpl");
    Class meta = object_getClass(cls);
    if (!cls || !meta || !NSClassFromString(@"UIScreen") || !NSClassFromString(@"UIDevice")) {
        report(@"HOUJI KEYBOARD v18: UIKit classes unavailable");
        return;
    }
    Method methods[3] = {};
    for (unsigned i = 0; i < 3; ++i) {
        entries[i].selector = sel_registerName(entries[i].name);
        methods[i] = class_getClassMethod(cls, entries[i].selector);
        if (!methods[i] || method_getNumberOfArguments(methods[i]) != 3 ||
            !exactType(methods[i], UINT_MAX, @encode(CGSize)) ||
            !exactType(methods[i], 2, @encode(NSInteger))) {
            report(@"HOUJI KEYBOARD v18: size ABI refused for %s", entries[i].name);
            return;
        }
        entries[i].original = (SizeMethod)method_getImplementation(methods[i]);
    }
    paddingSelector = sel_registerName("deviceSpecificPaddingForInterfaceOrientation:inputMode:");
    Method pad = class_getClassMethod(cls, paddingSelector);
    if (!pad || method_getNumberOfArguments(pad) != 4 ||
        !exactType(pad, UINT_MAX, "{UIEdgeInsets=dddd}") ||
        !exactType(pad, 2, @encode(NSInteger)) || !exactType(pad, 3, "@")) {
        report(@"HOUJI KEYBOARD v18: padding ABI refused");
        return;
    }
    padding = (PaddingMethod)method_getImplementation(pad);
    for (unsigned i = 0; i < 3; ++i) {
        class_replaceMethod(meta, entries[i].selector, (IMP)replacement, method_getTypeEncoding(methods[i]));
    }
    report(@"HOUJI KEYBOARD v18: three size methods installed in %s; native pixels unchanged", getprogname());
    @try {
        id screen = ((id (*)(id, SEL))objc_msgSend)(NSClassFromString(@"UIScreen"), sel_registerName("mainScreen"));
        const NSInteger fps = ((NSInteger (*)(id, SEL))objc_msgSend)(screen, sel_registerName("maximumFramesPerSecond"));
        report(@"HOUJI UI PACING v18: process=%s maximumFramesPerSecond=%ld highRateOptIn=%@; advertised app capability only", getprogname(), (long)fps, [NSBundle.mainBundle objectForInfoDictionaryKey:@"CADisableMinimumFrameDurationOnPhone"]);
    } @catch (NSException *e) { report(@"HOUJI UI PACING v18: getter exception %@", e.name); }
}

__attribute__((constructor)) void start() {
    const char *process = getprogname();
    if (!process) return;
    @autoreleasepool {
        report(@"HOUJI KEYBOARD v18: loaded in %s pid=%d", process, getpid());
        houji_status_bar::install();
    }
    dispatch_async(dispatch_get_main_queue(), ^{ install(); });
}
}
