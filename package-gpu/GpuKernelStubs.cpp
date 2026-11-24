// SPDX-License-Identifier: BSD-2-Clause-Patent
// Board hooks the UniXNU Adreno740 sources expect from the sheng board and its other drivers, answered for NX769J. None of
// them carries a feature this board has yet; each answer is the "not available" the caller already handles.
#include <IOKit/IOLib.h>
#include <IOKit/IOMemoryDescriptor.h>

extern "C" {
// NativeAdrenoMemory::release(): which user maps still hold a page (sheng's iPadOS patch zzzz-sheng-ipados27-bringup); a
// diagnostic only. None reported.
__attribute__((weak)) unsigned int
native_pmap_user_mappings(unsigned int, void **, uint64_t *, char *)
{
	return 0;
}

// NativeAdrenoPublish: the GOP framebuffer hand-off of GopFramebuffer (scanout straight from GPU buffers). This board's
// display is package/display (SweetFramebuffer); the plugin falls back to its own present path.
IOReturn
native_gop_handoff_call(uint32_t, task_t, const void *, size_t, void *, size_t)
{
	return kIOReturnUnsupported;
}

IOMemoryDescriptor *
native_gop_handoff_memory(void)
{
	return nullptr;
}

// NativeAdrenoPublish: sheng's persistent boot log export. Not on this board: refused.
int
boot_log_export_put(uint32_t, uint32_t, uint32_t, const void *, uint32_t)
{
	return -1;
}

// NativeAdrenoSubmit: sheng's GPU DCVS state ([1] is the current level). No GPU governor yet: level 0.
volatile uint32_t native_gpu_dcvs[15];
}
