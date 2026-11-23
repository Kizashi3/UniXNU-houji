# Houji CPU/GPU governor and wallpaper bootstrap

This is a development port. Compiling or receiving a firmware ACK is not a
temperature, power, panel-FPS or visual correctness measurement.

## CPU

`houji_dvfs=1` enables the four SM8650 EPSS policies found in this phone's live
FDT and recovery cpufreq inventory. Bit 2 separately enables the GPU governor.

| EPSS domain | Logical CPUs | Factory non-boost cap, kHz |
|---|---|---:|
| 0 | 0, 1 | 2265600 |
| 1 | 5, 6 | 2956800 |
| 2 | 7 | 3052800 |
| 3 | 2, 3, 4 | 3148800 |

All four enable bits and hardware LUTs are validated before any vote. Initial
inherited requests are clamped to the qualified non-boost table. The governor
samples the busiest core's actual scheduler idle accounting every 20 ms,
raises immediately, and requires four consecutive low samples before lowering.
Touch reports hold a 75% floor for one second. EPSS retains voltage selection;
the code does not program voltages or PLLs. Requested LUT index and hardware
domain-state samples are logged separately.

The governor starts after all eight cores pass the existing bound-task/timer/SGI
preflight. Preserve the prior `houji_publish_secondary_state` publication of
`sysreg_restore` and `cpu_ttep`; the portable SMP base is not the full current
linked source. Apply `native/power/manifest.json` after the earlier overlays.

## GPU

The initial governor uses only already advertised own-board HFI levels:
231 MHz / BW index 1 and 500 MHz / BW index 5. These are nominal requests,
not independently measured core clocks. The already configured GMU XO counter
0, countable 5, supplies busy time against its 19.2 MHz reference. Invalid or
backward counter samples are rejected. Polling is 16 ms; touch/queued work
raises the vote, and idle/hysteresis lowers it.

HFI30 uses the published provider's existing issuer mutex and a fresh live
transport lease. It must not reuse the intentionally retired cold-boot callback
owner. Actual queue publication, firmware ACK/error and the requested table/BW
indices are distinct from completed rendering fences. Failure requests live
worker isolation; filesystem log commits remain after actual GPU reset/halt.

## Serial input

The port uses `serial=1` for output only. `fbcon_probe` returns after a successful
map so the same static backend cannot register twice and link itself into a
cycle. Failed maps can still retry. This preserves normal output and eliminates
the unused serial keyboard reader. Thermal reduction is not inferred from it.

References: [sheng governor](https://github.com/UniXNU/UniXNU-sheng/blob/08cde20edc3254ed6f7df8d0f5384fb887786e8f/package/CpuFreqProbe.cpp),
[ishtar investigation and hardware observations](https://github.com/markakash/UniXNU-ishtar/blob/901611d6e51b2f84f7755f72ba3762c816727395/docs/HEATING.md).
The local repeated-probe check is adapted from that project's `check-fbcon.py`.

The first r195 hardware capture qualified actual CPU up/down transitions on all
four domains, including readbacks at 364800/499200/480000/499200 kHz. The GPU
completed 31 acknowledged nominal level changes without vote failures or invalid
busy-counter samples. The same run completed 2854 backboardd submissions and
2938 total GPU fences (including kernel qualification jobs). These establish
governor operation, not panel frame rate or complete visual correctness. The user
still observed component flicker and only a modest responsiveness improvement.

## Wallpaper

The existing iOS16 PosterBoard crash is in first switcher configuration setup.
Original wallpaper assets exist, but the observed poster extension store is
empty. A complete immutable 12 GiB root snapshot precedes the repair attempt.

`native/wallpaper/WallpaperBootstrap.m` uses this iOS16 PlugInKit's verified
`PKManager registerPlugInAtURL:result:` API for seven original poster providers.
It queries the resulting registry records separately from asynchronous callback
completion. It does not suppress PosterBoard assertions, replace services or
modify Setup/activation. Only three new files were installed; all 96 root chunks,
boot partitions, GPT and misc readbacks were verified. Its bounded log is read
after GPU isolation from `/private/var/mobile/Library/Logs/UniXNU-wallpaper.log`.

The first three bootstrap attempts did not repair wallpaper. Full offline iOS
unified logs were recovered using `log show --directory <root>/private/var/db/diagnostics`.
They identify the chain: ExtensionFoundation cannot find AMFI to verify the
original extension-point cache, MobileInstallation consequently treats
`com.apple.posterkit.provider` as unknown, and the providers are omitted from LS.
The generic PKManager registration call separately fails because it supplies no
MobileInstallation installation dictionary on this iOS build.

The fourth trial changes only the existing ExtensionKit feature default
`enforce_xpc_cache_code_signing` to false and updates our helper. This is a
development compatibility setting for the cache, not a complete AMFI driver.
The original `extensions.plist` and `.sig` are unchanged and byte-compared to
the owner's original iOS image before installation. Their SHA256 values are
`e92ee2b85cea78e17f951169c674a55d717be53e331a4b0a5a26de8221c095a4` and
`39a894877f31d01815758184317b90d21ad30791ec0d818c78d00a74d870ad73`.
No activation settings or signature enforcement for executable code are changed.

The helper observes cache enforcement and extension definitions, then uses
the original OS `rebuildDatabaseContentForFrameworkAtURL:completionHandler:`
for the six specific wallpaper frameworks. Its actual iOS16 callback ABI
`(BOOL, NSError *)` and required database-update entitlement were verified in
the owner's dyld cache. It records localized errors and resulting PK records.
This trial reuses the byte-identical r195 firmware/kernel and preserves numeric
owners and inodes on both edited files. Each preceding full 12 GiB snapshot is
immutable and every installation validates all 96 root chunks.

Actual registration and visible wallpaper require hardware confirmation. Sensor
feedback and automatic thermal protection are also not qualified: keep trials
supervised and return to recovery if the device heats noticeably.

The fourth trial has visual evidence of partial progress: the user now sees
wallpaper options, while previews remain blank, cannot be selected and the
default wallpaper is absent. Component flicker persists. The automatic recovery
capture has a valid committed CRC, but stops at the pre-isolation checkpoint;
its per-client desktop observation reports `e00002d5` and is unavailable. Do not
interpret the zeroed per-client counters as zero GPU execution: the separate
present synchronization path observed completed fence 4650. A fresh complete
root snapshot is being read for the original helper and service logs.

The complete fourth-trial snapshot confirms 139 extension definitions with one
poster type. Its unified log boot UUID is `1E6D5C8D-E4F6-494F-A716-2405D3DE8377`.
The remaining preview crash is now concrete: `_imageForView:` creates a Metal
device and queue, then inserts a nil queue at object index 1 of an NSDictionary.
The original frontend's external clients file contains only `backboardd`, and
`clientDevice()` explicitly returns nil for any other process. AegirPoster also
inserts a nil uniform buffer after a 432-byte `newBufferWithLength:options:1`.
These are distinct from GPU command completion errors.

The fifth trial only adds `PosterBoard`, `CollectionsPoster` and `AegirPoster`
to that existing clients file. It uses the original bundle and kernel, with no
recompilation or wildcard. The four existing client windows are retained, so
this test limits itself to four named processes. Other provider compatibility,
actual preview rendering and persistent wallpaper remain to be verified.

The fifth trial still showed blank previews. Its final committed capture now
includes the precise next refusal: `PosterBoard: no-cachedir` and
`AegirPoster: no-cachedir`. Neither process opened a GPU client. The existing
client path only tries `confstr(_CS_DARWIN_USER_CACHE_DIR)` and the corresponding
temporary directory, which are unavailable in this development root.

`native/gpu/metal/adrenometal-wallpaper-cache.patch` adds a third fallback only
for explicitly listed uid-501 processes: an individually named directory under
the verified mobile-owned 0700 `/private/var/mobile/Library/Caches`. Both the
parent and final directory are checked for owner, mode and non-symlink type.
Normal Darwin locations retain priority. A successful device and its first
bridge problem are recorded in that process's existing kernel diagnostic row.

This sixth trial rebuilds only the Objective-C++ plugin with the original
Rust archive and Turnip. Its 398 nonoptional imports are identical to r178 and
verified against the owner's iOS16 cache; bundle signature and in-image numeric
owners/inodes are also checked. A failed local candidate that accidentally
sealed generated dSYM files was rejected before any delta or phone write, then
retained separately. Debug symbols are kept outside the corrected bundle.

The seventh trial compared current main/sheng/ishtar configuration. The ishtar
allowlist also uses a bounded four-client kernel; a list of allowed names is not
a promise that all providers can run at once. Twelve verified iOS16 process
names were selected (eleven compatible reference entries plus the reported
MobileSlideShow app); iOS18-only entries and WidgetRenderer_Default were omitted.
Main UniXNU's HEIC-to-PNG wallpaper overlay was adapted to all 48 original iOS16
layers in 18 animations, including percent-encoded filenames. All references
were checked and originals retained. Only 166139184 bytes of already-snapshotted
historical tracev3 files were cleared for capacity; their full preimage remains.

Actual v7 results still show blank wallpapers/Photos and flicker. Complete
per-process initialization logs establish device creation, followed by
`texture: OutOfMemory(Device)` for PridePosterExtension. AegirPoster initially
opens a device, then repeatedly exits; later attempts fail with Vulkan result
-3. PosterBoard calls the unimplemented `newTextureLayoutWithDescriptor:` path.
The full source and observation must distinguish these failures from shader
compile failure, unsupported registration and filesystem capacity.

The owner's later observation narrows most flickering components to blurred
backgrounds. Historical backboardd pipeline logs contain 308 blur-related
creation records (downsample/narrow/variable blur), none with `ok=0`.
Compilation success does not validate shader arithmetic, intermediate texture
contents or synchronization. A same-image r196 replay compares Reduce
Transparency off/on in one boot; it makes no GPU-code change.

The owner's original 20H392 cache supplied all seven required and one optional
`MTLTextureLayout` method encodings. A CPU-linear layout prototype is staged in
`native/gpu/metal/NativeLinearTextureLayout.h`, with checked row/region helpers
in `LinearTextureMemory.h`. Its address/undefined-sanitized CPU copy check
passes. **It is not yet integrated, compiled into a phone plugin or qualified
on GPU.** It must use this device's measured row alignment and its own cache
watermark, retain proper backing lifetime, and reject unsupported layouts.

See [the 32 GiB migration](houji-root-volume.md) for the current disk geometry,
readback proofs and recovery boundary. Increasing disk capacity does not enlarge
the separate GPU virtual-address windows.


The Reduce Transparency r196 replay produced no reported improvement, but the
owner did not observe whether blur actually became opaque. Treat this as an
**unconfirmed intervention**, not evidence excluding the Gaussian path.

A more concrete gap was then found by comparing ishtar's `2027` surface patch:
both current `trapUseCount` handlers were still no-ops. The owner's iOS16
`IOSurfaceClientIsInUse` disassembly independently confirms a 64-bit state-page
load at `+0x18`, and its count APIs use traps 0/1. `surface-use-runtime` adds
real checked atomic increments/decrements there, separates the two handlers,
and cleans/invalidates fresh zeroed buffers before publication. It does not
change shaders, the Metal plugin, GPU windows or the 32 GiB volume.

`SurfaceUseCount.h` is shared by the production kernel and the small concurrent
host check; eight threads perform 80000 inc/dec pairs, checking underflow,
overflow and adjacent state preservation. r197's linked kernel contains both
new trap methods and the cached-count reporter. A hardware run is in progress;
`HOUJI SURFACE USE` will distinguish actual calls from an unused patch. The
reference-style aggregate counter has no per-client crash cleanup yet, so
possible leaked holds after process death remain a limitation to investigate.


r197 completed the actual count traps: terminal diagnostics show inc=105,
dec=88, underflow=0, missing=0 and overflow=0, with 1014628352 bytes of fresh
zeros cleaned. The owner still reports flicker and slow interaction. This fixes
a concrete missing lifetime operation but **does not resolve the visual issue**.
The owner later clarified that the Reduce Transparency option was not available,
so the earlier test cannot exclude blur. New reported geometry issue: the
keyboard opened from Settings search extends beyond the right screen edge.
The next diagnostics need logical UIScreen bounds/scale and actual framebuffer
geometry, alongside intermediate-image/native Metal behavior.


r198 integrates the linear-layout prototype in the Objective-C++ frontend only;
the original Rust static archive and Turnip remain unchanged. The matching
`MTLTextureLayout` ABI was decoded from the owner's original protocol metadata:
size/alignment are Q, granularity is three Qs, watermark is two Qs, and both
region copy methods return void. Layout rows come from the runtime's actual
linear-row query. The implementation supports selected uncompressed 2D formats,
retains normal no-copy backing/deallocator lifetime, and rejects unsupported
heap/array/mip/multisample shapes. CPU copy tests pass with address/undefined
sanitizers, and all 399 plugin imports exist in this iOS16 cache.

The existing wallpaper helper now records UIScreen logical/native bounds and
both scales, plus physical surface dimensions. It takes at most three local
1200x2670 physical-display CPU snapshots for the owner's Settings search
keyboard crop. Captures are not atomic panel scanout; they diagnose stable
geometry. No user photo is required. The helper's 88 imports are separately
verified against the same cache. The three edited files retain their numeric
root owner, permissions and inodes, and all 256 device chunks match the new
candidate `547a556ba8684c5175d4d5dfdd53500fe8e9de72fef52f3799598faa757dcd12`.
The complete immutable immediate preimage is `phone-after-surface-r197`, hash
`fa62f98e916a603ca2b800be5a121a8a6000d213e06c16d1dbad0234793d5399`.

The kernel also retains identical full-byte IEEE CRC32 checks but dispatches to
CPU CRC instructions only for the architectural CRC32 feature encoding 1.
Unknown/absent features retain the previous slicing-by-eight implementation.
A RAM-only executable on this phone matched 16448 short/unaligned inputs and
24 full-4MiB inputs against the existing implementation, at roughly tenfold
checksum throughput. The linked kernel contains CRC32x and CRC32b, and cached
hardware/software call counters distinguish actual use. This is CPU checksum
qualification, not GPU rendering or FPS evidence.

The first r198 packaging attempt selected the previous FAT payload, and the
embedded size/CRC check rejected it before any boot. After correcting the final
payload selection, actual firmware/driver/payload identity and policy binding
passed. r198 has now been temporarily booted; visual feedback, linear texture
execution, screen geometry and actual checksum costs remain pending.
