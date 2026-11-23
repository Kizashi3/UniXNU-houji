/* SPDX-License-Identifier: MIT */
/* Exercise the production retained-owner seal, without firmware or hardware.
 * Only the envelope is a peer. The hash, failure and sticky-lost logic are real. */
#include "houji_full_host_runtime.c"

static struct FhgState sealed_graph;
static struct FhrState sealed_runtime;

void houji_test_seal_arena(const ArmSmmu4KLiveArena *arena)
{
    memset(&sealed_graph,0,sizeof(sealed_graph));
    memset(&sealed_runtime,0,sizeof(sealed_runtime));
    sealed_graph.magic=FHG_MAGIC;sealed_graph.inverse=~FHG_MAGIC;
    sealed_graph.self=(uintptr_t)&sealed_graph;
    sealed_graph.config.abi_version=FHG_ABI_VERSION;
    sealed_graph.busy=sealed_graph.ready=1;
    sealed_graph.phase=FHG_PREPARED;sealed_graph.allocated=FHG_ALL;
    sealed_graph.gpu_arena=*arena;
    sealed_runtime.magic=FHR_MAGIC;sealed_runtime.inverse=~FHR_MAGIC;
    sealed_runtime.self=(uintptr_t)&sealed_runtime;
    sealed_runtime.ops.abi_version=FHR_ABI_VERSION;
    sealed_runtime.busy=sealed_runtime.sealed=1;
    sealed_runtime.stage=FHR_RETAINED_LIVE;
    sealed_runtime.graph=&sealed_graph;
    sealed_runtime.graph_hash=rt_hash_graph(&sealed_graph);
}

int houji_test_check_sealed_arena(const ArmSmmu4KLiveArena *arena)
{
    sealed_graph.gpu_arena=*arena;
    return rt_begin(&sealed_runtime);
}

unsigned houji_test_seal_failure(void)
{
    return sealed_runtime.code==FHR_BINDING && sealed_runtime.lost &&
        sealed_runtime.first.kind==13 &&
        sealed_runtime.first.stage==FHR_RETAINED_LIVE;
}
