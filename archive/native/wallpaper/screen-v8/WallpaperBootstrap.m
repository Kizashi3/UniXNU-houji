/* SPDX-License-Identifier: MIT
 * Recover system poster-provider registration using the OS's framework refresh.
 * Does not replace wallpaper services, suppress assertions or change Setup.
 * Methods verified in this owner's iOS16.7.16 PlugInKit Objective-C metadata.
 */
#import <Foundation/Foundation.h>
#import <objc/message.h>
#import <dlfcn.h>
#import <unistd.h>
#import <stdio.h>
#import <stdarg.h>
static FILE *logFile;
static void note(NSString *format,...) {
 va_list ap;va_start(ap,format);NSString *s=[[NSString alloc] initWithFormat:format arguments:ap];va_end(ap);
 fprintf(logFile,"%s\n",s.UTF8String);fflush(logFile);fsync(fileno(logFile));
}
static id send0(id obj,NSString *sel) {return ((id(*)(id,SEL))objc_msgSend)(obj,NSSelectorFromString(sel));}
static id send1(id obj,NSString *sel,id arg) {return ((id(*)(id,SEL,id))objc_msgSend)(obj,NSSelectorFromString(sel),arg);}
static void errorNote(NSString *name,NSError *error) {
 note(@"CALLBACK %@ domain=%@ code=%ld",name,error.domain,(long)error.code);
 for(NSString *key in @[NSLocalizedDescriptionKey,NSLocalizedFailureReasonErrorKey,NSDebugDescriptionErrorKey,NSFilePathErrorKey]){
  id value=error.userInfo[key];if([value isKindOfClass:[NSString class]])note(@"DETAIL %@ %@=%@",name,key,value);
 }
 NSError *underlying=error.userInfo[NSUnderlyingErrorKey];
 if([underlying isKindOfClass:[NSError class]])note(@"UNDERLYING %@ domain=%@ code=%ld description=%@",name,underlying.domain,(long)underlying.code,underlying.localizedDescription);
}
#include "DisplayDiagnostics.h"
int main(void) {@autoreleasepool {
 logFile=fopen("/private/var/mobile/Library/Logs/UniXNU-wallpaper.log","w");if(!logFile)return 1;
 note(@"WallpaperBootstrap version8, display metrics only, no physical scanout read, uid=%u",getuid());
 void *exLib=dlopen("/System/Library/Frameworks/ExtensionFoundation.framework/ExtensionFoundation",RTLD_NOW);
 id defaults=send0(NSClassFromString(@"_EXDefaults"),@"sharedInstance");
 BOOL enforce=YES;
 if([defaults respondsToSelector:NSSelectorFromString(@"enforceXPCCacheCodeSigning")])
  enforce=((BOOL(*)(id,SEL))objc_msgSend)(defaults,NSSelectorFromString(@"enforceXPCCacheCodeSigning"));
 note(@"EXTENSION CACHE library=%p enforceXPCCacheCodeSigning=%d",exLib,enforce);
 @try {
  id enumerator=send0(NSClassFromString(@"EXEnumerator"),@"extensionPointDefinitionEnumerator");
  unsigned points=0,posters=0;id point;
  while(points<1024 && (point=send0(enumerator,@"nextObject"))){
   ++points;
   if([point respondsToSelector:NSSelectorFromString(@"identifier")]){
    id identifier=send0(point,@"identifier");
    if([identifier isEqual:@"com.apple.posterkit.provider"])++posters;
   }
  }
  note(@"EXTENSION CACHE definitions=%u posterDefinitions=%u",points,posters);
 }@catch(NSException *e){note(@"CACHE EXCEPTION %@ %@",e.name,e.reason);}
 note(@"STEP before PlugInKit dlopen");
 void *lib=dlopen("/System/Library/PrivateFrameworks/PlugInKit.framework/PlugInKit",RTLD_NOW);
 const char *loadError=dlerror();note(@"STEP after PlugInKit dlopen handle=%p error=%s",lib,loadError?loadError:"none");
 Class cls=NSClassFromString(@"PKManager");
 note(@"STEP class lookup=%p",(__bridge void*)cls);
 if(!lib || !cls || ![cls respondsToSelector:NSSelectorFromString(@"defaultManager")]){note(@"PKManager unavailable");return 2;}
 note(@"STEP before defaultManager");
 id manager=send0(cls,@"defaultManager");
 note(@"STEP after defaultManager=%p",(__bridge void*)manager);
 NSArray *paths=@[@"/System/Library/PrivateFrameworks/WallpaperKit.framework/PlugIns/CollectionsPoster.appex",
  @"/System/Library/PrivateFrameworks/GradientPoster.framework/PlugIns/GradientPosterExtension.appex",
  @"/System/Library/PrivateFrameworks/EmojiPoster.framework/PlugIns/EmojiPosterExtension.appex",
  @"/System/Library/PrivateFrameworks/PhotosUIPrivate.framework/PlugIns/PhotosPosterProvider.appex",
  @"/System/Library/PrivateFrameworks/PridePoster.framework/PlugIns/PridePosterExtension.appex",
  @"/System/Library/PrivateFrameworks/UnityPoster.framework/PlugIns/UnityPosterExtension.appex",
  @"/Applications/PaperBoard.app/PlugIns/LegacyPoster.appex"];
 unsigned found=0,records=0,refreshes=0;__block unsigned callbacks=0;
 dlopen("/System/Library/Frameworks/CoreServices.framework/CoreServices",RTLD_NOW);
 id workspace=send0(NSClassFromString(@"LSApplicationWorkspace"),@"defaultWorkspace");
 SEL refresh=NSSelectorFromString(@"rebuildDatabaseContentForFrameworkAtURL:completionHandler:");
 // The generic PKManager API failed on iOS with missing MobileInstallation
 // dictionaries. This API lets the OS gather those dictionaries itself.
 // Actual iOS16 IMP 0x181c4fd4c; callback at 0x181c4fe54 is (BOOL,NSError*).
 if(!enforce && [workspace respondsToSelector:refresh]){
  for(NSString *path in paths){
   NSString *framework=[[path stringByDeletingLastPathComponent] stringByDeletingLastPathComponent];
   if(![framework.pathExtension isEqual:@"framework"])continue;
   ++refreshes;note(@"REFRESH %@",framework.lastPathComponent);
   void (^completion)(BOOL,NSError*)=^(BOOL success,NSError *error){
    note(@"REFRESH RESULT %@ success=%d",framework.lastPathComponent,success);
    if(error)errorNote(framework.lastPathComponent,error);
    __atomic_fetch_add(&callbacks,1,__ATOMIC_RELEASE);
   };
   ((void(*)(id,SEL,id,id))objc_msgSend)(workspace,refresh,[NSURL fileURLWithPath:framework],completion);
  }
 }else note(@"REFRESH refused: cache enforcement=%d or verified OS API absent",enforce);
 NSDate *deadline=[NSDate dateWithTimeIntervalSinceNow:60];
 while(__atomic_load_n(&callbacks,__ATOMIC_ACQUIRE)<refreshes && deadline.timeIntervalSinceNow>0)[[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.05]];
 for(NSString *path in paths){@try{
  NSDictionary *info=[NSDictionary dictionaryWithContentsOfFile:[path stringByAppendingPathComponent:@"Info.plist"]];NSString *identifier=info[@"CFBundleIdentifier"];
  if(identifier)++found;
  note(@"STEP before record %@",identifier);
  id factory=send0(manager,@"proxyFactory"),record=nil;
  if([factory respondsToSelector:NSSelectorFromString(@"plugInRecordForIdentifier:")])record=send1(factory,@"plugInRecordForIdentifier:",identifier);
  if(record)++records;note(@"RECORD %@ = %p",identifier,(__bridge void*)record);
 }@catch(NSException *e){note(@"QUERY EXCEPTION %@ %@",e.name,e.reason);}}
 note(@"FINISHED found=%u refreshes=%u callbacks=%u records=%u. PosterBoard rendering requires separate observation.",found,refreshes,__atomic_load_n(&callbacks,__ATOMIC_ACQUIRE),records);
 for(unsigned sample=1;sample<=3;sample++){@autoreleasepool{displayDiagnostics(sample);if(sample<3)[[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:25]];}}
 return records==paths.count?0:4;
}}
