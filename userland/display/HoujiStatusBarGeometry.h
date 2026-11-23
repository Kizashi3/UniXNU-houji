// SPDX-License-Identifier: MIT
// Included after the shared ABI checker and bounded geometry-only logger.
namespace houji_status_bar {
using InsetsMethod = Insets (*)(id, SEL);
InsetsMethod originalLeading, originalTrailing;
unsigned reports;

Insets adjust(id provider, Insets original, bool trailing) {
    if (!NSThread.isMainThread) return original;
    Insets result = original;
    @try {
        const auto object = [](id receiver, const char *selector) {
            return ((id (*)(id, SEL))objc_msgSend)(receiver, sel_registerName(selector));
        };
        id bar = object(provider, "statusBar");
        const NSInteger orientation = ((NSInteger (*)(id, SEL))objc_msgSend)(bar, sel_registerName("orientation"));
        const BOOL expanded = ((BOOL (*)(id, SEL))objc_msgSend)(provider, sel_registerName("expanded"));
        if (!bar || orientation != 1 || expanded) return original;
        id main = object(NSClassFromString(@"UIScreen"), "mainScreen");
        id window = object(bar, "window");
        id screen = window ? object(window, "screen") : main;
        if (!screen || screen != main) return original;
        const CGRect native = ((CGRect (*)(id, SEL))objc_msgSend)(screen, sel_registerName("nativeBounds"));
        const CGRect bounds = ((CGRect (*)(id, SEL))objc_msgSend)(screen, sel_registerName("bounds"));
        const CGFloat scale = ((CGFloat (*)(id, SEL))objc_msgSend)(screen, sel_registerName("scale"));
        if (native.size.width != 1200 || native.size.height != 2670 ||
            bounds.size.width != 400 || bounds.size.height != 890 || scale != 3) return original;
        for (CGFloat value : {original.top, original.left, original.bottom, original.right})
            if (!std::isfinite(value) || value < 0 || value > 200) return original;
        const CGFloat height = ((CGFloat (*)(id, SEL))objc_msgSend)(object_getClass(provider), sel_registerName("height"));
        const CGSize notch = ((CGSize (*)(id, SEL))objc_msgSend)(provider, sel_registerName("notchSize"));
        id font = object(provider, "clockFont");
        const CGFloat cap = ((CGFloat (*)(id, SEL))objc_msgSend)(font, sel_registerName("capHeight"));
        if (!std::isfinite(height) || !std::isfinite(notch.height) || !std::isfinite(cap) ||
            height < 30 || height > 60 || notch.height < 20 || notch.height > height || cap < 6 || cap > 25) return original;
        // The houji Android overlay specifies a 124-pixel status-bar band.
        // This is a layout reference, not a measurement of the camera centre.
        const CGFloat centre = 124.0 / (2 * scale);
        const CGFloat bottom = height - centre - cap / 2;
        if (bottom <= 0 || bottom + cap > notch.height) return original;
        result.bottom = bottom;
        result.top = std::min(original.top, notch.height - bottom - cap);
        // Keep each region's width and alignment rules; move it toward its
        // outer edge, retaining at least eight points of corner clearance.
        const CGFloat outer = trailing ? original.right : original.left;
        const CGFloat shift = std::min(CGFloat(8), std::max(CGFloat(0), outer - 8));
        result.left += trailing ? shift : -shift;
        result.right += trailing ? -shift : shift;
        if (reports++ < 12) report(@"HOUJI STATUSBAR v1: %@ %@ original=%.3f,%.3f,%.3f,%.3f result=%.3f,%.3f,%.3f,%.3f height=%.3f cap=%.3f bandCentre=%.3f",
            NSStringFromClass(object_getClass(provider)), trailing ? @"trailing" : @"leading",
            original.top, original.left, original.bottom, original.right,
            result.top, result.left, result.bottom, result.right, height, cap, centre);
    } @catch (NSException *exception) {
        if (reports++ < 12) report(@"HOUJI STATUSBAR v1: original retained after %@", exception.name);
        return original;
    }
    return result;
}

Insets leading(id provider, SEL selector) { return adjust(provider, originalLeading(provider, selector), false); }
Insets trailing(id provider, SEL selector) { return adjust(provider, originalTrailing(provider, selector), true); }

void install() {
    if (![NSProcessInfo.processInfo.operatingSystemVersionString containsString:@"16.7.16"]) return;
    Class cls = NSClassFromString(@"_UIStatusBarVisualProvider_FixedSplit");
    if (!cls || originalLeading) return;
    struct Requirement { Class cls; const char *name; const char *type; bool meta; };
    const Requirement requirements[] = {
        {cls, "leadingEdgeInsets", "{NSDirectionalEdgeInsets=dddd}", false},
        {cls, "trailingEdgeInsets", "{NSDirectionalEdgeInsets=dddd}", false},
        {cls, "statusBar", "@", false}, {cls, "expanded", @encode(BOOL), false},
        {cls, "height", @encode(CGFloat), true}, {cls, "notchSize", @encode(CGSize), false},
        {cls, "clockFont", "@", false},
        {NSClassFromString(@"_UIStatusBar"), "orientation", @encode(NSInteger), false},
        {NSClassFromString(@"UIFont"), "capHeight", @encode(CGFloat), false},
    };
    for (const auto &r : requirements) {
        Method m = r.meta ? class_getClassMethod(r.cls, sel_registerName(r.name))
                          : class_getInstanceMethod(r.cls, sel_registerName(r.name));
        if (!m || method_getNumberOfArguments(m) != 2 || !exactType(m, UINT_MAX, r.type)) {
            report(@"HOUJI STATUSBAR v1: ABI refused for %s", r.name);
            return;
        }
    }
    SEL l = sel_registerName("leadingEdgeInsets"), r = sel_registerName("trailingEdgeInsets");
    Method lm = class_getInstanceMethod(cls, l), rm = class_getInstanceMethod(cls, r);
    originalLeading = (InsetsMethod)method_getImplementation(lm);
    originalTrailing = (InsetsMethod)method_getImplementation(rm);
    class_replaceMethod(cls, l, (IMP)leading, method_getTypeEncoding(lm));
    class_replaceMethod(cls, r, (IMP)trailing, method_getTypeEncoding(rm));
    report(@"HOUJI STATUSBAR v1: portrait split-region geometry installed");
}
}
