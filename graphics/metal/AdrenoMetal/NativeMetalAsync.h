// SPDX-License-Identifier: MIT
// Shared by the frontend and the host contract check. A bounded compiler queue
// keeps asynchronous API calls off the UI thread without multiplying compiler
// memory. User callbacks run separately: they may enqueue and wait for another
// compilation without blocking the compiler queue itself.
#pragma once
#import <Foundation/Foundation.h>
#include <atomic>
#include <time.h>

enum class NBCompileKind : unsigned { Function, Render, Compute };
static std::atomic<uint64_t> gAsyncRequested[3], gAsyncCompiled, gAsyncCallbacks;
static std::atomic<uint64_t> gAsyncQueueWaitUs, gAsyncQueueWaitMaxUs;

static void nbCompileAsync(NBCompileKind kind, dispatch_block_t work) {
    static dispatch_queue_t queue;
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        queue = dispatch_queue_create("org.unixnu.houji.metal.compile",
            dispatch_queue_attr_make_with_qos_class(DISPATCH_QUEUE_SERIAL, QOS_CLASS_USER_INITIATED, 0));
    });
    gAsyncRequested[(unsigned)kind]++;
    const uint64_t enqueued = clock_gettime_nsec_np(CLOCK_UPTIME_RAW) / 1000;
    dispatch_async(queue, ^{
        @autoreleasepool {
            const uint64_t waited = clock_gettime_nsec_np(CLOCK_UPTIME_RAW) / 1000 - enqueued;
            gAsyncQueueWaitUs += waited;
            uint64_t previous = gAsyncQueueWaitMaxUs.load();
            while (waited > previous && !gAsyncQueueWaitMaxUs.compare_exchange_weak(previous, waited)) {}
            work();
            gAsyncCompiled++;
        }
    });
}

static void nbCompleteAsync(dispatch_block_t callback) {
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        @autoreleasepool {
            callback();
            gAsyncCallbacks++;
        }
    });
}
