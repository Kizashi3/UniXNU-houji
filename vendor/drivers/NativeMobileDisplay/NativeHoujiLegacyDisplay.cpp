// SPDX-License-Identifier: BSD-2-Clause-Patent
// 20H392 (Xiaomi 14 / houji) clean-room backend for the unchanged Apple
// IOMobileFramebufferLegacy class. This first milestone only links the class
// into the kernel and answers the kernel's probe entry point; instantiation is
// gated by the houji-legacy-display boot argument so a default boot is exactly
// the previously verified kernel. Backend overrides are added piecewise.
#include "OriginalHoujiLegacyABI.h"
#include <IOKit/IOLib.h>
#include <pexpert/pexpert.h>

static bool houjiLegacyDisplayEnabled(void)
{
	uint32_t enabled = 0;
	PE_parse_boot_argn("houji-legacy-display", &enabled, sizeof(enabled));
	return enabled == 1;
}

class NativeHoujiLegacyDisplay : public IOMobileFramebufferLegacy {
	OSDeclareDefaultStructors(NativeHoujiLegacyDisplay)
public:
	/*
	 * Every abstract backend leaf the original class leaves pure must be
	 * overridden for the class to be instantiable. This milestone does not
	 * implement them; a call traps loudly instead of running sheng code.
	 */
#define HOUJI_LEGACY_LEAF(slot) \
	void opaque##slot() override { __builtin_trap(); }
	HOUJI_LEGACY_LEAF(211)
	HOUJI_LEGACY_LEAF(212)
	HOUJI_LEGACY_LEAF(242)
	HOUJI_LEGACY_LEAF(243)
	HOUJI_LEGACY_LEAF(292)
	HOUJI_LEGACY_LEAF(293)
	HOUJI_LEGACY_LEAF(321)
	HOUJI_LEGACY_LEAF(322)
	HOUJI_LEGACY_LEAF(329)
#undef HOUJI_LEGACY_LEAF
};

OSDefineMetaClassAndStructors(NativeHoujiLegacyDisplay, IOMobileFramebufferLegacy)

extern "C" void
native_legacy_display_probe(void)
{
	if (!houjiLegacyDisplayEnabled()) {
		return;
	}
	/*
	 * Instantiation is deferred to the next milestone: this build proves the
	 * 338-slot inheritance and original-symbol bindings link and load without
	 * changing a default boot. The probe deliberately allocates nothing yet.
	 */
	IOLog("HOUJI-LEGACY: class linked; instantiation pending next milestone\n");
}
