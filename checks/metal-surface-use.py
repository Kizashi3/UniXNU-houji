#!/usr/bin/env python3
"""Actual frontend lifetime methods with real host IOSurface use counts; no GPU."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT/'graphics/metal/AdrenoMetal/NativeBridgeMetalFrontend.mm').read_text()
texture = source[source.index('@implementation NBTexture'):]


def method(signature):
    start = texture.index(signature)
    opened = texture.index('{', start)
    depth = 1
    end = opened + 1
    while depth:
        depth += (texture[end] == '{') - (texture[end] == '}')
        end += 1
    return texture[start:end]


unit = r'''
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <IOSurface/IOSurfaceRef.h>
#include <atomic>
#include <cassert>
#include <cstring>
#include <unistd.h>
#include "bridge/NativeMetalObjects.h"
static bool gCountsSurfaceUse;
static std::atomic<uint64_t> gSurfaceUseAdded,gSurfaceUseRemoved;
static unsigned released;
extern "C" void nmb_texture_release(NmbTexture *p){if(p)++released;}
extern "C" void nmb_texture_describe(const NmbTexture *,NmbTextureDescriptor *out){*out={};}
#define NBLOG(...) do{}while(0)
@interface NBTexture:NSObject
@property(nonatomic) NmbTexture *handle;
@property(nonatomic) NmbTextureDescriptor descriptor;
@property(nonatomic,strong) id buffer;
@property(nonatomic) IOSurfaceRef surface;
@property(nonatomic) NSUInteger offset,rowBytes;
@property(nonatomic,strong) id<MTLTexture> parent;
@property(nonatomic) BOOL counted;
- (void)countUse;
- (id<MTLTexture>)view:(NmbTexture *)handle;
@end
@implementation NBTexture
'''
unit += '\n'.join(method(s) for s in ['- (void)dealloc', '- (void)countUse', '- (id<MTLTexture>)view:'])
unit += r'''
@end
static NBTexture *make(IOSurfaceRef surface){
 NBTexture *t=[NBTexture new];t.handle=(NmbTexture *)1;t.surface=(IOSurfaceRef)CFRetain(surface);[t countUse];return t;
}
int main(){@autoreleasepool{
 IOSurfaceRef surface=IOSurfaceCreate((__bridge CFDictionaryRef)@{
  (id)kIOSurfaceWidth:@32,(id)kIOSurfaceHeight:@32,(id)kIOSurfaceBytesPerElement:@4,
  (id)kIOSurfaceBytesPerRow:@128});
 assert(surface && IOSurfaceGetUseCount(surface)==0);
 gCountsSurfaceUse=false;
 @autoreleasepool{NBTexture *t=make(surface);[t countUse];assert(IOSurfaceGetUseCount(surface)==0);}
 assert(gSurfaceUseAdded==0 && gSurfaceUseRemoved==0);
 gCountsSurfaceUse=true;
 NSMutableArray *pending=[NSMutableArray array];
 @autoreleasepool{
  NBTexture *t=make(surface);[t countUse];assert(IOSurfaceGetUseCount(surface)==1);
  assert([t view:nullptr]==nil && IOSurfaceGetUseCount(surface)==1);
  NBTexture *view=(NBTexture *)[t view:(NmbTexture *)2];[view countUse];
  assert(IOSurfaceGetUseCount(surface)==2 && IOSurfaceIsInUse(surface));
  [pending addObject:view];
 }
 // The view retains its parent; command owners retain the view through completion.
 assert(IOSurfaceGetUseCount(surface)==2 && gSurfaceUseRemoved==0);
 [pending removeAllObjects];
 assert(IOSurfaceGetUseCount(surface)==0 && !IOSurfaceIsInUse(surface));
 assert(gSurfaceUseAdded==2 && gSurfaceUseRemoved==2 && released==3);
 @autoreleasepool{NBTexture *t=[NBTexture new];[t countUse];assert(!t.counted);}
 CFRelease(surface);
}}
'''
# Check the real creation path also enrolls imported textures, not only the test fixture.
assert 'texture.surface=(IOSurfaceRef)CFRetain(surface);[texture countUse];return' in source
with tempfile.TemporaryDirectory(prefix='houji-surface-use-') as directory:
    tmp = Path(directory)
    fixture, binary = tmp/'lifetime.mm', tmp/'lifetime'
    fixture.write_text(unit)
    subprocess.run(['xcrun','clang++','-std=c++17','-fobjc-arc','-O2',
                    '-I',str(ROOT/'graphics/metal/AdrenoMetal'),str(fixture),
                    '-framework','Foundation','-framework','Metal','-framework','IOSurface',
                    '-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=30)
print('PASS: real host IOSurface counts; actual texture/view methods, idempotence, pending owners, failure and balanced release; no GPU or iOS pool emulation')
