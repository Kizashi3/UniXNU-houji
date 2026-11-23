# r198 video and native ASTC follow-up

The owner video IMG_0858.MOV shows the wallpaper gallery and blank preview cards, plus discontinuous component updates during gestures. It does not show the Settings-search keyboard. HDR-derived frame extraction is for timing/geometry, not colour validation.

## Confirmed r198 evidence

- Current run ID: 99614b428b36427db15cec7ea3f025af; committed XNU log and automatic OrangeFox recovery captured.
- PosterBoard requests MTLTextureLayout fmt204 (ASTC4x4_LDR),216x216,one mip and slice. Backboardd also requests raw49152-byte textures of this format. The v8 path rejects compressed formats.
- Seven wallpaper-provider records and six successful framework callbacks now exist. Registration success does not imply preview rendering success.
- UIScreen is400x890 points@3, native1200x2670. This is a helper-process observation, not a measurement of the remote keyboard frame. The physical-display PNG path stops after surface metadata; no PNG was saved. Fresh r198 bootUUID DBEBCACC-DCDB-4B49-96E7-70AFA042D8CC is absent from the immutable pre-run log store. In this boot Preferences PID253 reports a400x278 remote-keyboard region, with375x233 keyboard at x12.5 and a400x45 assistant view. Thus these UIKit frame logs do not show an oversized keyboard; cropping/rendering still needs visual measurement.
- Hardware CRC ran6442 times with zero software calls. Full-range CRC set/check totals are approximately0.56s each, against roughly10s each previously. User still reports sluggishness/flicker; no FPS claim.
- Full immutable32GiB post-run image: phone-after-linear-r198/ios16-phone.hfsx, SHA256 6f3b3fcb877be570c330458363678e1d07f02f85351f8432b02527a3578acbd0. All256 chunks independently match stable device indices.

## r199 candidate, not yet visually qualified

The native-only ASTC4x4 raw-memory creator uses our MTLTextureLayout's explicit16-byte block rows and a distinct watermark. It does not loosen public Metal buffer-texture restrictions or infer Apple tiling from byte length. The source Buffer and its release callback survive GPU uses; existing shadow hazards copy updates between submissions. Compressed images use actual pixel extents for Vulkan image copies, including partial blocks at image boundaries. CPU region calls use block units.

At native Metal device initialization, backboardd will make216x216 and217x215 images and verify two generations of CPU updates through GPU image-copy/readback. This qualifies compressed transfer and refresh only, not shader sampling or visual correctness. The normal desktop is then the sampling/rendering test.

Display diagnostics use a read-only AvoidSync lock with stage markers, and discard unused scanout alpha when making PNGs. These are non-atomic CPU display snapshots for geometry; they are not panel FPS or direct GPU scanout evidence.

The signed/import-checked v9 plugin and v6 helper overwrite only three existing HFSX inodes with verified root numeric ownership. Same Turnip, display dimensions, CPU/GPU DVFS and32GiB geometry. Kernel rebuild changes the run/log allocation binding. Protected boot/GPT/misc checks and256-chunk readback remain required before a temporary boot.

## Remaining

- ASTC sampling and rendered pixels must be checked on the phone.
- Poster extension device/VA exhaustion and repeated restarts remain separate failure modes.
- Keyboard right-edge crop and component flicker are unresolved. Do not change global scale solely from the video.

## r199 hardware result

Temporary boot returned automatically to OrangeFox after242.594s; fixed log CRC and runID match. Full post-run32GiB SHA25652e5b1b41daef63f9aac4dbc15ae307908e51405847311c5fd376e9d24dd1ec3 matches every stable device chunk. Userland bootUUID F2E99584-3A06-4F3C-A19E-9E3B28E6DB09 recorded the ASTC GPU copy/CPU-update check PASS for both extents and both generations. A real raw ASTC texture1200x2670,row4800,3211264bytes was created. This is transfer/refresh qualification, not shader sampling or visual correctness.

CoreUI now rejects pre-existing zero-watermark ASTC image payloads against the distinct native layout watermark. Preserve that check: do not pretend a platform-specific payload has our block-row layout. Asset regeneration/portable decoding must be investigated. PosterBoard no longer records its prior unimplemented-layout error, but AegirPoster device creation and PridePosterExtension image allocation still fail.

ReadOnly|AvoidSync lock returned0 and base lookup succeeded. The helper still stops before the CPU-copy completion marker, so no PNG capture is claimed. An archived helper XPC crash report is unbound/historical and is not evidence of this current stop. Human visual feedback for r199 is pending.
