# P3 first-frame bring-up (2026-11-16)

Device: houji / SM8650. Simulator: none, offline only this round.

## What run419 proved, and what it exposed

`houji-legacy-selftest=1` painted a color-bar image straight into the GOP
scanout from the driver timer. The panel lit up, so the scanout mapping,
stride, pixel format and 60 Hz timer are all good.

The same round died at about 85 s with

    panic(cpu 0 caller ...): "AMFI: No PMGR?\n" @ConfigurationSettings.cpp:152

Disassembly of the site (`__PLK_TEXT_EXEC 0xfffffff004717664`) shows
`if (!pmgr) panic(...)`; the single caller (`0xfffffff0046fe914`) ignores the
result. Run420 therefore returns instead of panicking when the pointer is null.

## P3 work in this round (offline)

The swap never arrives because this XNU instantiates no GPU accelerator, so no
compositor frame is produced. P3 is approached from the pixel side:

1. `presentShadow()` allocates a kernel BGRA buffer with the panel geometry
   (1200x2670, stride 4800), paints it, and copies it into the scanout with the
   very `copyBgra` the swap path uses. `presented` counts it and
   `stage=cpu-present frame=N synthetic=1` records it.
2. The copy is verified by reading sample scanout pixels back and comparing
   them with the source; a store that stayed in cache would show up as
   `verify=mismatch` plus `stage=cpu-present-readback`.
3. `HoujiLegacySwapRequest.h` parses the qualified 1132-byte SwapEnd request:
   sequence at +0x50, per-layer surface id at +0x54 (stride 0x60), rectangles at
   +0x64, mask at +0x104. Short buffers, empty masks, out-of-range mask bits and
   enabled layers with a zero id are refused.
4. `houjiSurfaceById()` resolves an identifier to an IOSurface object by walking
   the published `IOSurface` services and matching the `IOSurfaceID` property.
   This avoids depending on a private lookup symbol.
5. Selector 5 now parses the request, resolves the surface, checks format
   (BGRA, single plane), geometry and mapping bounds, copies the pixels into the
   scanout and counts the frame. Rejections are classified:
   `swap-request-invalid`, `swap-surface-missing`, `cpu-reject reason=...`.

## Tests

`p3-pixels-test` covers the panel geometry extents, padded-stride copies,
overlap refusal and offset overflow. `houji-legacy-swap-request-test` covers the
request layout, mask validation and multi-layer ids. The existing pixels, queue
and request tests still pass. The driver object compiles with the Apple target.

## Still unproven

- No real swap has been submitted yet, so selector 5 has never run on device.
- Selector 3 still reports an empty default surface.
- `validateSwap` continues to require the strict full-frame request; whether the
  compositor would submit in that shape is unknown.