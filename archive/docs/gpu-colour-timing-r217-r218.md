# Colour and submission timing follow-up

The owner reports purple in Reachability's upper background and app-switcher
shadows, slow scrolling and occasional garbled text. The purple predates r214.
All three tested keyboard hosts remain fixed by the shared v18 library.

## r217 result

r217 tested the rounded sRGB extended-range blend and two-plane shadow creation
patches from rootstockos/AdrenoMetal at
`16e8125525a64d34439ef924213a6fea4530e239`, on the existing metal2vulkan
`0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35` plus the retained board adapters.
The blend fallback has a typed precision note; its results are compared against
the independently measured safe table, without changing the fast table's data.
The 36 arithmetic checks and the fragment lowering/precision-note check passed.
These are host checks, not GPU execution evidence.

The owner saw no improvement. Runtime evidence:

- `pf553 pipelines=0`: the new blend path was not exercised by this desktop.
- Ten two-plane surfaces exercised the texture creation path.
- No Vulkan pipeline creation failed in the recorded final counters.
- Mean commit-to-callback time was 27,352 microseconds. This is not GPU time.
- Active display-copy windows averaged about 1.4 ms per copy, not panel FPS.
- Submit ABI method 5 took 19,867,626 microseconds across 2,570 calls while
  holding the kernel lock, about 7.7 ms per call.
- The retained source-surface observation contained purple candidates, but its
  broad hue test also counts intentional wallpaper colours and does not prove
  which shader is wrong.

Automatic recovery capture was committed and CRC-valid for run
`f4dcb2f0511c4df09b69c326d5d3ff62`. The boot partitions, twelve GPT ranges and
reserved misc bytes were unchanged.

## r218 observation scope

The timing v15 frontend reuses the exact r217 translation runtime and cache
namespace. It reads the existing completed command buffer GPU timestamp
interface, adds submission-span and CPU API wall-time observations, and initially exported WorkCounts for host imports, copied pages and shadow textures.
The later audit found that `work_counts()` calls `deferred.lower_all()`, so this
getter is not read-only and has been removed from v16.
Unavailable GPU times remain unavailable; callback latency is not substituted.

The kernel additionally measures submission, write-combine reassertion,
mapping publication and cache-audit phases using its existing board clock.
It retains validation, references, memory bounds, cache operations and policy.
The cached coherence flags and audit counters are reported with the timings.
No new GPU register reads or clock/voltage writes are introduced.

The latest stable upstream tip checked was `219f01365dc4c8eb346816c405b5b17403793764`
on `master`. Its `ed837440` gated-copy ordering fix addresses a newer path absent
from the deployed `0dfdbcd` runtime; it has not been represented as an applied
fix here. A later full update needs its own adapter and device validation.

The immutable pre-r218 32 GiB snapshot is
`phone-after-native-r217/ios16-phone.hfsx`, SHA-256
`d96a1c3b56f9aa8bee5a74900a3839580ba3928fef1636b84896d6b777a8f994`.
The timing candidate modifies only the existing renderer and signature files.
All 256 device chunks and protected partitions were checked after installation.
r218 reached the desktop and the owner completed scrolling. Its CRC-valid
committed capture ends in a periodic snapshot around 164 seconds and does not
contain the new terminal timings. No CPU/GPU split was inferred from it.
r219 returned early; its last valid snapshot is around 42 seconds during the
GPU/UFS preflight, without desktop timing evidence.

v16 removes the mutating getter and retains the same translation runtime.
The next kernel formats cached RAM timings directly into each committed
snapshot before the kernel-message tail, with a strong linked call.
The 12-OPP factory governor and broader comparison are described in
`upstream-porting-comparison-20261030.md`; hardware results remain separate.
