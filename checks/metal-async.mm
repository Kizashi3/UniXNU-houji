// SPDX-License-Identifier: MIT
// The Python runner inserts the actual frontend asynchronous method bodies.
// The synchronous compiler is gated so inline calls deadlock/fail this check.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <cassert>
#include <pthread.h>
#include "NativeMetalAsync.h"

static dispatch_semaphore_t gate, done;
static unsigned testCase;
static std::atomic<unsigned> compileCalls, callbacks;
static std::atomic<bool> returned;
static void waitFor(dispatch_semaphore_t value) {
    assert(!dispatch_semaphore_wait(value, dispatch_time(DISPATCH_TIME_NOW, 5 * NSEC_PER_SEC)));
}
static void beginCompile() {
    assert(!pthread_main_np());
    ++compileCalls;
    waitFor(gate);
    assert(returned.load());
}

@interface FixtureConstants : NSObject <NSCopying>
@property unsigned value;
@end
@implementation FixtureConstants
- (id)copyWithZone:(NSZone *)zone {
    (void)zone; FixtureConstants *copy = [FixtureConstants new]; copy.value = self.value; return copy;
}
@end

@interface Fixture : NSObject
/* ACTUAL_DECLARATIONS */
- (id<MTLFunction>)newFunctionWithName:(NSString *)name constantValues:(MTLFunctionConstantValues *)values error:(NSError **)error;
- (id<MTLFunction>)newFunctionWithDescriptor:(MTLFunctionDescriptor *)d error:(NSError **)error;
@end

@implementation Fixture
- (id<MTLFunction>)newFunctionWithName:(NSString *)name constantValues:(MTLFunctionConstantValues *)values error:(NSError **)error {
    beginCompile(); assert([name isEqual:@"before"] && ((FixtureConstants *)values).value == 7);
    *error = nil; return (id<MTLFunction>)[NSObject new];
}
- (id<MTLFunction>)newFunctionWithDescriptor:(MTLFunctionDescriptor *)d error:(NSError **)error {
    beginCompile(); assert([d.name isEqual:@"before"] && ((FixtureConstants *)d.constantValues).value == 7);
    *error = nil; return (id<MTLFunction>)[NSObject new];
}
- (id<MTLRenderPipelineState>)newRenderPipelineStateWithDescriptor:(MTLRenderPipelineDescriptor *)d error:(NSError **)error {
    beginCompile(); assert([d.label isEqual:@"before"] && d.colorAttachments[0].pixelFormat == MTLPixelFormatBGRA8Unorm);
    *error = nil; return (id<MTLRenderPipelineState>)[NSObject new];
}
- (id<MTLRenderPipelineState>)newRenderPipelineStateWithDescriptor:(MTLRenderPipelineDescriptor *)d options:(MTLPipelineOption)options reflection:(MTLRenderPipelineReflection **)reflection error:(NSError **)error {
    assert(options == MTLPipelineOptionArgumentInfo && reflection);
    *reflection = (MTLRenderPipelineReflection *)@"reflection";
    return [self newRenderPipelineStateWithDescriptor:d error:error];
}
- (id<MTLComputePipelineState>)newComputePipelineStateWithFunction:(id<MTLFunction>)function error:(NSError **)error {
    beginCompile(); assert([function.label isEqual:@"retained-function"]);
    *error = nil; return (id<MTLComputePipelineState>)[NSObject new];
}
- (id<MTLComputePipelineState>)newComputePipelineStateWithFunction:(id<MTLFunction>)function options:(MTLPipelineOption)options reflection:(MTLComputePipelineReflection **)reflection error:(NSError **)error {
    beginCompile(); assert([function.label isEqual:@"retained-function"]);
    assert(options == MTLPipelineOptionArgumentInfo && reflection);
    *reflection = nil; *error = [NSError errorWithDomain:@"compiler-fixture" code:42 userInfo:nil];
    return nil;
}
- (id<MTLComputePipelineState>)newComputePipelineStateWithDescriptor:(MTLComputePipelineDescriptor *)d options:(MTLPipelineOption)options reflection:(MTLComputePipelineReflection **)reflection error:(NSError **)error {
    beginCompile(); assert([d.label isEqual:@"before"] && d.maxTotalThreadsPerThreadgroup == 64);
    assert(options == MTLPipelineOptionArgumentInfo && reflection);
    *reflection = (MTLComputePipelineReflection *)@"reflection";
    *error = nil; return (id<MTLComputePipelineState>)[NSObject new];
}
/* ACTUAL_METHODS */
@end

@interface FixtureFunction : NSObject
@property NSString *label;
@end
@implementation FixtureFunction
@end

int main() {
    @autoreleasepool {
        Fixture *fixture = [Fixture new];
        gate = dispatch_semaphore_create(0); done = dispatch_semaphore_create(0);
        for (testCase = 0; testCase < 7; ++testCase) {
            returned = false;
            FixtureConstants *constants = [FixtureConstants new]; constants.value = 7;
            NSMutableString *name = [@"before" mutableCopy];
            MTLFunctionDescriptor *functionDescriptor = [MTLFunctionDescriptor new];
            functionDescriptor.name = name; functionDescriptor.constantValues = (id)constants;
            MTLRenderPipelineDescriptor *render = [MTLRenderPipelineDescriptor new];
            render.label = @"before"; render.colorAttachments[0].pixelFormat = MTLPixelFormatBGRA8Unorm;
            MTLComputePipelineDescriptor *compute = [MTLComputePipelineDescriptor new];
            compute.label = @"before"; compute.maxTotalThreadsPerThreadgroup = 64;
            __weak id weakFunction;
            __block void (^check)(id, id, NSError *) = ^(id state, id reflection, NSError *error) {
                assert(!pthread_main_np() && returned.load());
                if (testCase == 5) { assert(!state && error.code == 42 && [error.domain isEqual:@"compiler-fixture"]); }
                else { assert(state && !error); }
                if (testCase == 3 || testCase == 6) assert([reflection isEqual:@"reflection"]);
                else assert(!reflection);
                ++callbacks; dispatch_semaphore_signal(done);
            };
            @autoreleasepool {
                FixtureFunction *function = [FixtureFunction new]; function.label = @"retained-function"; weakFunction = function;
                switch (testCase) {
                case 0: [fixture newFunctionWithName:name constantValues:(id)constants completionHandler:^(id s,NSError *e){check(s,nil,e);}]; break;
                case 1: [fixture newFunctionWithDescriptor:functionDescriptor completionHandler:^(id s,NSError *e){check(s,nil,e);}]; break;
                case 2: [fixture newRenderPipelineStateWithDescriptor:render completionHandler:^(id s,NSError *e){check(s,nil,e);}]; break;
                case 3: [fixture newRenderPipelineStateWithDescriptor:render options:MTLPipelineOptionArgumentInfo completionHandler:check]; break;
                case 4: [fixture newComputePipelineStateWithFunction:(id)function completionHandler:^(id s,NSError *e){check(s,nil,e);}]; break;
                case 5: [fixture newComputePipelineStateWithFunction:(id)function options:MTLPipelineOptionArgumentInfo completionHandler:check]; break;
                case 6: [fixture newComputePipelineStateWithDescriptor:compute options:MTLPipelineOptionArgumentInfo completionHandler:check]; break;
                }
            }
            assert(compileCalls <= testCase + 1 && callbacks == testCase);
            if (testCase == 4 || testCase == 5) assert(weakFunction);
            returned = true;
            [name setString:@"changed"]; constants.value = 9;
            functionDescriptor.name = @"changed";
            render.label = @"changed"; render.colorAttachments[0].pixelFormat = MTLPixelFormatR8Unorm;
            compute.label = @"changed"; compute.maxTotalThreadsPerThreadgroup = 32;
            dispatch_semaphore_signal(gate); waitFor(done);
            assert(callbacks == testCase + 1 && compileCalls == testCase + 1);
            check = nil;
        }
        // A callback can enqueue another compilation and synchronously wait.
        // It must not execute on the serial compiler queue.
        nbCompileAsync(NBCompileKind::Function, ^{
            nbCompleteAsync(^{
                dispatch_semaphore_t nested = dispatch_semaphore_create(0);
                nbCompileAsync(NBCompileKind::Function, ^{ dispatch_semaphore_signal(nested); });
                waitFor(nested); dispatch_semaphore_signal(done);
            });
        });
        waitFor(done);
        assert(gAsyncRequested[0] == 4 && gAsyncRequested[1] == 2 && gAsyncRequested[2] == 3);
    }
    puts("PASS: seven actual async APIs return before gated compilation, snapshot inputs, retain functions, forward errors/reflection and permit callback reentry; no GPU");
}
