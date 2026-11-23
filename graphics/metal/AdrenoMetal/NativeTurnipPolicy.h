// SPDX-License-Identifier: MIT
#pragma once
#include <cstdlib>

// Keep the established path unless a comparison build explicitly selects the
// policy used by AdrenoMetal 461a8421. Concurrent binning remains disabled.
#ifndef HOUJI_TURNIP_RENDER_AUTOTUNE
#define HOUJI_TURNIP_RENDER_AUTOTUNE 0
#endif
#if HOUJI_TURNIP_RENDER_AUTOTUNE != 0 && HOUJI_TURNIP_RENDER_AUTOTUNE != 1
#error HOUJI_TURNIP_RENDER_AUTOTUNE must be zero or one
#endif

namespace houji_turnip {
inline const char *renderMode() {
    return HOUJI_TURNIP_RENDER_AUTOTUNE ? "autotune" : "sysmem";
}
inline const char *defaultDebugFlags() {
    return HOUJI_TURNIP_RENDER_AUTOTUNE ? "nocb" : "sysmem,nocb";
}
inline void configure() {
    // Preserve an explicit process environment, as the existing plugin does.
    setenv("TU_DEBUG", defaultDebugFlags(), 0);
}
}
