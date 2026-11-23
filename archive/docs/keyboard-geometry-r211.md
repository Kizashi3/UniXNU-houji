# Settings keyboard geometry trial

The owner still observes a clipped right keyboard edge at the accepted native
1200×2670 output. CPU-resampled 375-point canvases were rejected because of text
quality; this trial retains the native framebuffer and owned presentation buffer.

## Open-source reference

[ReScale2's ReScaleKB](https://github.com/SniperGER/ReScale2/blob/29c36d25716ed9372da3d2447f2546d45fd44353/ReScaleKB/Tweak.xm)
adjusts three `UIKeyboardImpl` class-method results to the actual screen width
minus device padding, retaining UIKit's original height. Its older implementation
is a reference, not evidence of iOS 16 or houji qualification. Bounded searches of
the UniXNU organization and ishtar repositories did not locate an equivalent
onscreen keyboard clipping fix. The ishtar serial-input-thread fix is unrelated.

Disassembly of the owner's 20H392 UIKitCore confirms these three methods and the
padding method still exist:

- `defaultSizeForInterfaceOrientation:`
- `keyboardSizeForInterfaceOrientation:`
- `sizeForInterfaceOrientation:`
- `deviceSpecificPaddingForInterfaceOrientation:inputMode:`

The persistent UIKit logs contain a 375-point `UIKeyboardAutomatic` inside a
400-point host; the native screen reports 400×890 points at scale 3. This mismatch
supports testing a geometry correction, but does not alone explain the visible
key clipping. Internal keyboard resource selection could still require work.

## Scoped implementation

`native/display/KeyboardGeometry.mm` independently replaces the three methods
after checking their Objective-C ABIs. It acts only in Preferences, on the main
thread, in portrait, on iOS 16.7.16, with exactly the observed 1200×2670 native
and 400×890 logical geometry. Other inputs retain the original return value.
It changes width only, using the actual left/right device padding, and does not
change any window frame, scale, transform, GPU setting, or display property.

A private dylib is loaded by a new `LC_LOAD_DYLIB` in the existing unused Mach-O
header padding of Preferences. Original executable code/data are compared before
resigning, and the original entitlement dictionary is preserved exactly. The
candidate app and library both pass strict signature verification. Its 50
nonoptional imports resolve in the owner's iOS 16 dyld cache; this is a static
check, not proof of runtime selector execution.

The first prototype embedded the constructor in the Metal plugin. It was built
but never installed: Preferences is absent from the GPU client list, and its
captured crash image list does not contain that plugin. The standalone app-local
library provides an explicit load path without changing the GPU client list.

The library logs its load, installation status, and the first 24 size calls to
unified logging and a bounded `HoujiKeyboard-v15.log` in the mobile Logs folder.
Only geometry is recorded, never typed text. The file distinguishes a refused
ABI/geometry gate from a correction that ran but did not solve the clipping.

## Recovery and validation

The complete immutable 32 GiB r210 preimage has SHA-256
`2e391762dfb8e9fd78c902c5f245a8595ecf81ca0ab091e11924e205a5cd4ec7`.
The local candidate modifies the Settings executable and its signature resource
and adds one library; all other app resources and the installed Metal, Turnip,
client list and display helper hashes are retained. The original app's numeric
ownership is root:80, with 0775 executable and 0664 signature metadata; the new
library is root:80, 0755. This was verified through an owners-enabled read-only
remount after local finalization.

The delta touches four 128 MiB chunks: 0, 1, 90, 91. The installer checks all 256
phone chunks before and after writing, and verifies protected boot partitions,
GPT ranges and misc. Kernel/UEFI changes for r211 are limited to the new trial
label and log identity. The existing timed return and recovery watcher remain.

The owner reported that the keyboard remains clipped, Settings now exits when
opened, and lag is unchanged. The compatibility trial FAILED acceptance and must
not be treated as a retained fix. The next step is to preserve its crash/geometry
records and restore the original Settings executable/signature, with the GPU and
native output unchanged. The new code must not be redeployed until the concrete
crash has been identified. This trial does not solve desktop performance.

The actual installation completed with all 256 chunk readbacks matching, and
unchanged protected storage. Fastboot accepted the temporary r211 image at
2026-10-30 02:17:17 +08:00. Image SHA-256:
`a68ed7693517feae19e2352b3f8554483b532502e72040641ddfacf16846a763`;
run ID: `91f56e9e60d94849b557f1f9c9c6b4eb`. The background recovery watcher started
immediately. Comparing frozen runtime inputs against r210 found only the new log
allocation/UUID headers changed in XNU/DarwinBoot; no GPU or frequency source was
changed for this trial.

## r211 failure diagnosis and r212 correction

The post-r211 root snapshot was verified against all 256 device chunks and has
SHA-256 `7217b5fd251523580e0e9379c6675708b8c47dd9b991a80eb2ee594f7d6eec86`.
Eight new Preferences crash reports agree on a DYLD launch termination:
`Library not loaded: @executable_path/HoujiKeyboardGeometry.dylib`, with
`security policy does not allow @ path expansion`. No keyboard log file or loaded
keyboard image is present. Thus the geometry correction did not execute; r211
does not establish whether that correction can solve the layout problem.

v16 replaces the load command and library ID with the fixed absolute path
`/Applications/Preferences.app/HoujiKeyboardGeometry.dylib`. It retains the same
geometry logic and all original entitlements; it does not change dyld policy.
Diagnostic messages and the bounded log filename now identify v16. The already
existing root:80 inodes are overwritten in place, so no new privileged local
ownership operation is required. The dylib passes all 50 iOS 16 import checks,
and the complete app and library pass strict signature verification.

An alternative original-app restoration candidate was also prepared locally and
was not installed. The original Apple resource envelope uses obsolete omit rules
that current macOS codesign rejects even on the untouched preimage. Restoration
therefore verifies original code pages separately and compares every app file
byte-for-byte with the immutable preimage; it does not replace Apple's original
signature. Both the failure and this verifier distinction are retained in local
evidence.

The owner confirmed in r212 that Settings opens normally and its search keyboard
is no longer clipped. The home-screen pull-down search keyboard remains clipped.
This is scoped success for the Preferences-only hook, not a system-wide fix.
Its CPU, GPU and display behavior remains r210's; only keyboard loading and
diagnostic identity changed.

v16 installation passed all 256 device chunk comparisons. Its root image digest
is `8464be4858c64c92db666fb13eff4cf21646d5d141f9248230b4b89444f0f205`.
Fastboot accepted r212 at 2026-10-30 02:35:39 +08:00; its image SHA-256 is
`96de1c5bc62cefc958b9c68b6acf2b3d7c978fb98dfca7aceb78f7765be49359` and run ID is
`5a941d3ad32a4ece9a4b943600f69a35`. No new Mac ownership prompt was needed.

The owner requested that the next change be prepared offline and not tested until
tomorrow. No further device writes, log allocation, reboot or test are authorized
tonight by this continuation. The already running read-only post-r212 snapshot
and log inspection may finish. Identify the actual home-search keyboard host from
UIKit logs, then prepare a narrowly scoped extension of the proven geometry fix.

## Offline Spotlight follow-up (v17, not installed)

The post-r212 immutable root was read back successfully, SHA-256
`c5be3bdf2720de8d3aa81199bbc3811f688b922200cbee96d66c312563603878`.
Its Preferences geometry log confirms all three hooked size methods returning
400×233 points from the original 375×233, with screen bounds 400×890, native
pixels 1200×2670 and scale 3. This corroborates the owner's successful Settings
test. The accepted Settings library remains v16.

Captured UIKit window records identify Spotlight as the home-search keyboard
host (36 of the 40 inspected automatic-keyboard window records, with four from
SpringBoard). The v17 candidate uses the same correction and gates its
constructor to `Spotlight`. It loads through the explicit absolute path
`/Applications/Spotlight.app/HoujiKeyboardGeometry.dylib`, retaining the r212
resolution of the restricted `@executable_path` failure.

The three-file overlay and original-file rollback archive are prepared under
`out/keyboard-home-v17/`. Strict signatures, original entitlements, all 50
nonoptional iOS 16 imports and numeric archive metadata pass local checks. The
Spotlight constructor macro was also checked through the compiler preprocessor.
The new library SHA-256 is
`2d79fbf242756d664e9ea2df75f48dcdf24dbabb305c6e1cdca40764a6017884`.

The optional terminal collector now reads the two fixed, mobile-owned geometry
logs only after actual GPU isolation and after an already committed terminal
checkpoint. Each file is bounded to a 32 KiB read and at most 8 KiB printed. No
typed text is collected. Existing wallpaper diagnostics retain their preceding
checkpoint. The XNU build passes and the compiled kernel contains the new reader;
only `HoujiGpuProbeLog.inc` and `HoujiGpuNativeLive.inc` differ from r212's frozen
UFS runtime sources. Append history is explicitly labelled as potentially from
earlier boots rather than treated as proof of this run.

No Spotlight overlay was installed and no device test, reboot, write or new log
allocation was performed after the owner's request to defer. The offline kernel
still has r212's identity and is not a deployable next-trial image. Next session
must perform normal fresh-root verification, local staging/ownership finalization,
fresh log identity and packaging before a physical keyboard test. Performance,
Photos and GPU-clock qualification remain unresolved by this keyboard change.
