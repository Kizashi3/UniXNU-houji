#!/usr/bin/env python3
"""Exercise the actual status-bar adapter with host UIKit peers; no visual claim."""
from pathlib import Path
import subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
s=(ROOT/'userland/display/UnifiedKeyboardGeometry.mm').read_text()
exact=s[s.index('bool exactType('):s.index('\n#include "HoujiStatusBarGeometry.h"')]
unit=r'''
#import <Foundation/Foundation.h>
#import <CoreGraphics/CGGeometry.h>
#import <objc/message.h>
#import <objc/runtime.h>
#include <algorithm>
#include <initializer_list>
#include <cmath>
#include <cstring>
#include <cassert>
struct Insets {CGFloat top,left,bottom,right;};
struct NSDirectionalEdgeInsets {CGFloat top,leading,bottom,trailing;};
static void report(NSString *format,...) {va_list ap;va_start(ap,format);NSString *line=[[NSString alloc] initWithFormat:format arguments:ap];va_end(ap);fprintf(stderr,"%s\n",line.UTF8String);}
static bool target=true,expanded=false,external=false;
static NSInteger orientation=1;
static CGFloat fontCap=12;
@interface UIScreen:NSObject
+ (id)mainScreen;
- (CGRect)nativeBounds;
- (CGRect)bounds;
- (CGFloat)scale;
@end
@implementation UIScreen
+ (id)mainScreen {static id s=[UIScreen new];return s;}
- (CGRect)nativeBounds {return CGRectMake(0,0,target?1200:1170,2670);}
- (CGRect)bounds {return CGRectMake(0,0,400,890);}
- (CGFloat)scale {return 3;}
@end
@interface Window:NSObject
- (id)screen;
@end
@implementation Window
- (id)screen {return external?[UIScreen new]:[UIScreen mainScreen];}
@end
@interface UIFont:NSObject
- (CGFloat)capHeight;
@end
@implementation UIFont
- (CGFloat)capHeight {return fontCap;}
@end
@interface _UIStatusBar:NSObject
- (NSInteger)orientation;
- (id)window;
@end
@implementation _UIStatusBar
- (NSInteger)orientation {return orientation;}
- (id)window {return [Window new];}
@end
@interface _UIStatusBarVisualProvider_FixedSplit:NSObject
+ (CGFloat)height;
- (CGSize)notchSize;
- (id)statusBar;
- (BOOL)expanded;
- (id)clockFont;
- (NSDirectionalEdgeInsets)leadingEdgeInsets;
- (NSDirectionalEdgeInsets)trailingEdgeInsets;
@end
@implementation _UIStatusBarVisualProvider_FixedSplit
+ (CGFloat)height {return 44;}
- (CGSize)notchSize {return CGSizeMake(209,30);}
- (id)statusBar {return [_UIStatusBar new];}
- (BOOL)expanded {return expanded;}
- (id)clockFont {return [UIFont new];}
- (NSDirectionalEdgeInsets)leadingEdgeInsets {return {1,26,8,20};}
- (NSDirectionalEdgeInsets)trailingEdgeInsets {return {1,20,8,26};}
@end
static NSString *version(id,SEL) {return @"Version 16.7.16";}
'''  + exact + '\n#include "HoujiStatusBarGeometry.h"\n' + r'''

int main(){@autoreleasepool {
 Method versionMethod=class_getInstanceMethod(object_getClass(NSProcessInfo.processInfo),@selector(operatingSystemVersionString));
 IMP previous=method_setImplementation(versionMethod,(IMP)version);
 houji_status_bar::install();
 method_setImplementation(versionMethod,previous);
 assert(houji_status_bar::originalLeading && houji_status_bar::originalTrailing);
 id p=[_UIStatusBarVisualProvider_FixedSplit new];
 auto l=[p leadingEdgeInsets],r=[p trailingEdgeInsets];
 assert(l.leading==18 && l.trailing==28 && r.leading==28 && r.trailing==18);
 assert(l.top>=0 && std::abs(44-l.bottom-fontCap/2-124.0/6)<1e-9);
 assert(l.bottom==r.bottom && 30-l.top-l.bottom>=fontCap-1e-9);
 assert(l.leading+l.trailing==46 && r.leading+r.trailing==46);
 expanded=true;assert([p leadingEdgeInsets].leading==26);expanded=false;
 orientation=3;assert([p leadingEdgeInsets].bottom==8);orientation=1;
 external=true;assert([p trailingEdgeInsets].trailing==26);external=false;
 target=false;assert([p leadingEdgeInsets].bottom==8);target=true;
 fontCap=NAN;assert([p leadingEdgeInsets].bottom==8);fontCap=12;
 auto saved=houji_status_bar::originalLeading;houji_status_bar::install();assert(saved==houji_status_bar::originalLeading);
 }puts("PASS: actual status-bar hook installation, region width/baseline, portrait/screen/expanded guards and invalid geometry; no iOS visual claim");}
'''
with tempfile.TemporaryDirectory(prefix='houji-statusbar-') as tmp:
    source,binary=Path(tmp)/'check.mm',Path(tmp)/'check';source.write_text(unit)
    subprocess.run(['xcrun','clang++','-std=c++17','-fobjc-arc','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-framework','Foundation','-framework','CoreGraphics','-I'+str(ROOT/'userland/display'),str(source),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
