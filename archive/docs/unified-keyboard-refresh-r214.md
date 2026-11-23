# Unified keyboard and asynchronous display follow-up

Owner verification: App Library search, Home pull-down search and Settings
search keyboards are all complete with the shared v18 library. The owner
reported a small scrolling improvement, but still poor frame rate. These are
manual observations, not a measured 120 fps result.

The purple Reachability upper background and app-switcher card shadows predate
r214. They must not be classified as a new r214 colour regression. r215 retained
only the latest twelve sparse colour samples, so switching back to Settings
could overwrite the relevant scene; a negative final sample does not exclude a
rendered-source colour error.

r213 fixed the tested Settings and Home pull-down search keyboards. The owner
found the App Library keyboard still clipped and requested one rule across the
system image, then requested open-source refresh/performance comparisons.

## Shared keyboard rule

`UnifiedKeyboardGeometry.mm` is installed once as
`/usr/lib/HoujiKeyboardGeometry.dylib`. The image builder automatically discovers
157 system APPL bundles, including SpringBoard, and binds them through an
absolute weak dependency. The rule has no process-name allowlist; it checks the
actual iOS version, native 1200×2670 pixels and 400×890 logical geometry before
adjusting portrait keyboard width. It preserves UIKit's height and padding.

Each main executable's original code/data are compared before signing, and
each original entitlement dictionary is preserved. The same build step enables
`CADisableMinimumFrameDurationOnPhone` in the discovered app plists. All 157
app signatures pass locally, as does the shared library; all 55 nonoptional
library imports resolve against the owner's iOS 16 cache. The existing private
Preferences/Spotlight libraries remain as unused originals for recovery; their
load commands now point to the shared implementation. This builder covers the
system apps in this image; newly installed apps would need to pass through the
same image preparation workflow.

Shared resource envelopes are separated before writing. Numeric ownership is
verified after local finalization through an owners-enabled read-only mount.
The staged image changes five 128 MiB chunks (0, 1, 96, 99, 100). All 256 phone
chunks matched after installation, with protected boot/GPT/misc unchanged.
Candidate root: `d72abe5b45adce58d40d9487d89b06089865941c7c25e1b2e4f90a2923fcba73`.
Shared library: `48f6beda187f66e8711abfb2bf7571ba040cad5e854dd97b99d623e9bdaf70d1`.

The terminal collector records the fixed Preferences, Spotlight and SpringBoard
v18 geometry logs after actual GPU isolation. Each file includes process load,
method installation and geometry; the library also reports the app's observed
maximum frame-rate capability and opt-in. These are app/API values, not panel
measurements. Append history must be distinguished using process IDs.

Reference: [ReScale2 UIKit filter](https://github.com/SniperGER/ReScale2/blob/29c36d25716ed9372da3d2447f2546d45fd44353/ReScaleKB/ReScaleKB.plist)
and [width correction](https://github.com/SniperGER/ReScale2/blob/29c36d25716ed9372da3d2447f2546d45fd44353/ReScaleKB/Tweak.xm).

## Refresh and performance experiment

The old framebuffer's notification callback also synchronously acquired the GPU
issuer mutex and copied the next frame. r213 recorded waits up to 58.863 ms in
the presentation mutex path; blocking the timer in that path can delay later
notifications. r214 moves presentation to one event-driven copy workloop.
The notification callback neither waits on the GPU issuer gate nor copies the
frame. The same FIFO, actual submitted fence, cache acquisition, completion
barrier and retained surface references remain. A frame retires only after its
real copy completes; idle periods do not poll a second worker.

The test requests a fixed 120 Hz software notification mode and publishes one
matching TimingElements/IOMFBDisplayRefresh configuration. Rates use 16.16 Hz;
intervals use 32.32 seconds and separate mach-time values. No variable-refresh
support is declared. Native pixel copying and DPU/DSI registers are unchanged.
Recovery reports a 1200×2670 120 Hz mode for the actual n3 panel, but the physical
rate inherited during iOS boot is not measured by this test. It must not be
described as proven 120 fps presentation.

The iOS 16.7.16 QuartzCore reader at unslid `0x1884cbc94` was checked directly:
it reads `CADisableMinimumFrameDurationOnPhone` from the main bundle. No iOS 18
binary address is applied to iOS 16.

References: [Ishtar refresh investigation](https://github.com/markakash/UniXNU-ishtar-old/blob/79ddf4578db06c3738dd5b56a49434270ee260b1/docs/REFRESH-RATE.md)
and [DPU/refresh implementation](https://github.com/markakash/UniXNU-ishtar-old/blob/79ddf4578db06c3738dd5b56a49434270ee260b1/xnu/patches-ishtar/2025-ishtar-dpu-sm8550-flip.patch).
That project's observed 120 display-link callbacks do not establish sustained
120 rendered/presented frames; it separately records 39–41 and 62–65 swaps/s
under different GPU profiles. Its SM8550 panel writes are not copied to SM8650.

## r214 trial

Fresh run ID: `bfe3c414153f46ec87ef06d6ce5353ca`.
Temporary boot image SHA-256:
`da31dcfbe5ef731012849b6203a6e69cbaf80495dc2c0c532e4a606b8e100fa7`.
The frozen build verifies 435 files. Core GPU/CPU inputs remain those of r213;
runtime changes are framebuffer pacing and the three fixed keyboard log paths.
The sole changed boot argument is `sweetfb_hz=60` to `sweetfb_hz=120`.
Booting OKAY and the background recovery listener are recorded in the r214 boot
journal. Owner feedback, actual callback/copy counts, geometry logs and protected
storage checks are pending this physical test.
