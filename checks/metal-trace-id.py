#!/usr/bin/env python3
"""Exercise the actual Objective-C base object and inherited trace selector."""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
frontend = (ROOT / 'graphics/metal/AdrenoMetal/NativeBridgeMetalFrontend.mm').read_text()
start = frontend.index('static std::atomic<uint64_t> gTraceObjectSequence')
end = frontend.index('// ---- resources ----', start)
actual = frontend[start:end]
# Preserve the production superclass chain, without linking unrelated GPU methods.
classes = ['NBEncoder', 'NBComputeEncoder', 'NBRenderEncoder', 'NBBlitEncoder', 'NBCommandBuffer', 'NBQueue']
for name in classes:
    parent = re.search(r'@interface ' + name + r' : (\w+)', frontend)[1]
    actual += f'\n@interface {name} : {parent}\n@end\n@implementation {name}\n@end\n'
source = r'''
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <objc/runtime.h>
#include <atomic>
#include <cassert>
#include <cstring>
#include <set>
#include <unistd.h>
static id gDeviceObject;
static void (*gMissing)(const char *, const char *);
static unsigned missing;
static void noteProblem(NSString *message) { assert([message containsString:@"missing"]); ++missing; }
'''
source += actual
source += r'''
int main() {
 @autoreleasepool {
  NSArray *types=@[[NBComputeEncoder class],[NBRenderEncoder class],[NBBlitEncoder class],[NBCommandBuffer class],[NBQueue class]];
  NSMutableArray *objects=[NSMutableArray new];
  std::set<uint64_t> identities;
  for(Class type in types) {
   Method method=class_getInstanceMethod(type,@selector(globalTraceObjectID));
   char result[16]={};method_getReturnType(method,result,sizeof result);
   assert(strcmp(result,"Q")==0 && method_getNumberOfArguments(method)==2);
   for(unsigned i=0;i<1000;++i) {
    NBObject *object=[type new];
    const uint64_t identity=object.globalTraceObjectID;
    assert(identity && (identity>>32)==(uint32_t)getpid());
    assert(identities.insert(identity).second);
    object.label=@"changed label";assert(object.globalTraceObjectID==identity);
    [objects addObject:object];
   }
  }
  // Concurrent reads must return one identity, and concurrent allocations must
  // not duplicate IDs even when Objective-C reuses an object's address.
  NBObject *shared=objects[0];const uint64_t sharedID=shared.globalTraceObjectID;
  uint64_t *concurrent=(uint64_t *)calloc(8192,sizeof(uint64_t));assert(concurrent);
  dispatch_apply(8192,dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^(size_t i){
   @autoreleasepool {
    assert(shared.globalTraceObjectID==sharedID);
    NBObject *encoder=[NBComputeEncoder new];concurrent[i]=encoder.globalTraceObjectID;
   }
  });
  for(size_t i=0;i<8192;++i)assert(identities.insert(concurrent[i]).second);
  free(concurrent);
  BOOL raised=NO;
  @try { [shared doesNotRecognizeSelector:sel_registerName("unsupportedTraceFixture")]; }
  @catch(NSException *e) { raised=[e.name isEqual:NSInvalidArgumentException]; }
  assert(raised && missing==1);
  gTraceObjectSequence=UINT32_MAX;
  assert(([NBObject new].globalTraceObjectID&UINT32_MAX)==UINT32_MAX);
  raised=NO;
  @try { (void)[NBObject new]; }
  @catch(NSException *e) { raised=[e.name isEqual:NSInternalInconsistencyException]; }
  assert(raised);
 }
 puts("PASS: actual Metal object selector ABI, encoder inheritance, stable concurrent identities, no address-reuse collisions, exhaustion and strict unknown-selector failure; no GPU");
}
'''
with tempfile.TemporaryDirectory(prefix='houji-metal-trace-') as directory:
    unit, binary = Path(directory) / 'check.mm', Path(directory) / 'check'
    unit.write_text(source)
    subprocess.run(['xcrun', 'clang++', '-std=c++17', '-fobjc-arc', '-fblocks',
                    '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-framework', 'Foundation', '-framework', 'Metal', str(unit), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=20)
