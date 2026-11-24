/* SPDX-License-Identifier: MIT
 * One-shot system-app registration after offline staged-bundle migration.
 * Uses the OS rebuild API also called by Procursus uicache -a -f. It leaves
 * user registrations, data, icon layout, capability tags and signatures alone.
 */
#import <Foundation/Foundation.h>
#import <objc/message.h>
#include <dlfcn.h>
#include <stdio.h>
#include <unistd.h>
#include <notify.h>
#include "SystemAppsManifest.h"

static FILE *logFile;
static void note(NSString *text) {
    flockfile(logFile);
    fprintf(logFile, "%.3f %s\n", NSProcessInfo.processInfo.systemUptime, text.UTF8String);
    fflush(logFile); fsync(fileno(logFile)); funlockfile(logFile);
}
static id send0(id object, NSString *name) {
    return ((id(*)(id,SEL))objc_msgSend)(object, NSSelectorFromString(name));
}
static id send1(id object, NSString *name, id argument) {
    return ((id(*)(id,SEL,id))objc_msgSend)(object, NSSelectorFromString(name), argument);
}

int main(void) { @autoreleasepool {
    NSString *stamp = @"/private/var/mobile/Library/Preferences/moe.houji.system-apps.plist";
    NSDictionary *prior = [NSDictionary dictionaryWithContentsOfFile:stamp];
    if ([prior[@"manifest"] isEqual:kSystemAppsManifest] && [prior[@"complete"] boolValue]) return 0;
    logFile = fopen("/private/var/mobile/Library/Logs/UniXNU-system-apps.log", "w");
    if (!logFile) return 1;
    note([NSString stringWithFormat:@"START manifest=%@ uid=%u", kSystemAppsManifest, getuid()]);
    // A stalled system service cannot leave a new permanent startup worker.
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 90ll*NSEC_PER_SEC),
                   dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
        note(@"TIMEOUT: system registration did not finish within 90 seconds"); _exit(7);
    });
    sleep(8);
    NSDictionary *expected = expectedSystemApps();
    for (NSString *name in expected) {
        NSString *path = [@"/Applications" stringByAppendingPathComponent:name];
        NSDictionary *info = [NSDictionary dictionaryWithContentsOfFile:[path stringByAppendingPathComponent:@"Info.plist"]];
        if (![info[@"CFBundleIdentifier"] isEqual:expected[name]]) {
            note([@"REFUSED bundle identity: " stringByAppendingString:name]); return 2;
        }
    }
    if (!dlopen("/System/Library/Frameworks/CoreServices.framework/CoreServices", RTLD_NOW)) {
        note(@"ERROR CoreServices unavailable"); return 3;
    }
    @try {
        Class cls = NSClassFromString(@"LSApplicationWorkspace");
        id workspace = [cls respondsToSelector:NSSelectorFromString(@"defaultWorkspace")] ? send0(cls,@"defaultWorkspace") : nil;
        SEL rebuild = NSSelectorFromString(@"_LSPrivateRebuildApplicationDatabasesForSystemApps:internal:user:");
        if (![workspace respondsToSelector:rebuild]) { note(@"ERROR system rebuild API unavailable"); return 4; }
        note(@"REBUILD system=YES internal=YES user=NO");
        BOOL success = ((BOOL(*)(id,SEL,BOOL,BOOL,BOOL))objc_msgSend)(workspace,rebuild,YES,YES,NO);
        note([NSString stringWithFormat:@"REBUILD returned=%d",success]);
        if (!success) return 5;
        unsigned verified = 0;
        Class proxyClass = NSClassFromString(@"LSApplicationProxy");
        SEL lookup = NSSelectorFromString(@"applicationProxyForIdentifier:");
        if (![proxyClass respondsToSelector:lookup]) { note(@"ERROR registration lookup unavailable"); return 6; }
        for (NSString *name in [[expected allKeys] sortedArrayUsingSelector:@selector(compare:)]) {
            NSString *identifier = expected[name];
            id proxy = send1(proxyClass,@"applicationProxyForIdentifier:",identifier);
            NSURL *url = [proxy respondsToSelector:NSSelectorFromString(@"bundleURL")] ? send0(proxy,@"bundleURL") : nil;
            NSString *path = [@"/Applications" stringByAppendingPathComponent:name];
            id state = [proxy respondsToSelector:NSSelectorFromString(@"appState")] ? send0(proxy,@"appState") : nil;
            BOOL valid = [state respondsToSelector:NSSelectorFromString(@"isValid")] &&
                ((BOOL(*)(id,SEL))objc_msgSend)(state,NSSelectorFromString(@"isValid"));
            BOOL matches = [url isKindOfClass:NSURL.class] && [url.path isEqual:path] && valid;
            if (matches) ++verified;
            note([NSString stringWithFormat:@"APP %@ registered=%d valid=%d path=%@",identifier,matches,valid,url.path]);
        }
        note([NSString stringWithFormat:@"FINISHED registered=%u expected=%lu; launches not tested",verified,(unsigned long)expected.count]);
        if (verified != expected.count) return 6;
        NSDictionary *done = @{@"manifest":kSystemAppsManifest,@"complete":@YES,@"registered":@(verified)};
        if (![done writeToFile:stamp atomically:YES]) { note(@"ERROR writing completion marker"); return 8; }
        notify_post("com.apple.mobile.application_installed");
    } @catch (NSException *exception) {
        note([NSString stringWithFormat:@"EXCEPTION %@ %@",exception.name,exception.reason]); return 9;
    }
    return 0;
}}
