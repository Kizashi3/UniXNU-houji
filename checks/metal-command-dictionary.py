#!/usr/bin/env python3
"""Run the actual command-buffer initializer and dictionary property on the host."""
from pathlib import Path
import re, subprocess, tempfile
ROOT=Path(__file__).resolve().parents[1]
text=(ROOT/'graphics/metal/AdrenoMetal/NativeBridgeMetalFrontend.mm').read_text()
interface=text.split('@interface NBCommandBuffer : NBObject {',1)[1].split('@end',1)[0]
properties='\n'.join(line for line in interface.splitlines() if line.startswith('@property') and not any(word in line for word in ['NmbCommandBuffer','NBQueue']))
method=re.search(r'@implementation NBCommandBuffer\n(- \(instancetype\)init \{[\s\S]+?\n})',text)[1]
unit='''#import <Foundation/Foundation.h>
#include <cassert>
static uint64_t nowUs(){return 1;}
@interface Fixture:NSObject {uint64_t createdUs;}
'''+properties+'''\n@end
@implementation Fixture
'''+method+'''\n@end
int main(){@autoreleasepool {
 Fixture *a=[Fixture new],*b=[Fixture new];
 assert(a.userDictionary && b.userDictionary && a.userDictionary!=b.userDictionary);
 NSMutableDictionary *saved=a.userDictionary;
 __weak NSObject *value;
 @autoreleasepool {NSObject *object=[NSObject new];value=object;a.userDictionary[@"owner"]=object;}
 assert(value && saved==a.userDictionary && !b.userDictionary[@"owner"]);
 a.userDictionary[@"counter"]=@42;assert([saved[@"counter"] isEqual:@42]);
 [a.userDictionary removeObjectForKey:@"owner"];assert(!value);
 assert(![a respondsToSelector:NSSelectorFromString(@"setUserDictionary:")]);
 }puts("PASS: actual command-buffer initializer retains an independent mutable SPI dictionary, stable identity, retained/released values and readonly property; no GPU");}
'''
with tempfile.TemporaryDirectory(prefix='houji-command-dictionary-') as directory:
    source,binary=Path(directory)/'check.mm',Path(directory)/'check';source.write_text(unit)
    subprocess.run(['xcrun','clang++','-std=c++17','-fobjc-arc','-fblocks','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-framework','Foundation',str(source),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
