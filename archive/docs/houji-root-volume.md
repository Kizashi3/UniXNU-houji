# Xiaomi 14 native iOS volume

The phone now uses a **32 GiB HFSX volume** in the prefix of the existing
515465261056-byte userdata partition. r196 booted to the usable iOS desktop,
confirmed by the owner. The authored baseline had 21704261632 free bytes
(about 20.2 GiB). This is disk capacity; managed RAM remains 8 GiB.

## Reference layouts

There is no common fixed system-volume size across the reference projects.
[UniXNU userdata](https://github.com/UniXNU/UniXNU/blob/40d21cc65171c3a24faa130a2a8e899f85790485/docs/guide/userdata.md)
separates the read-only firmware volumes from writable Data. Its
[`seed-data-grow.py`](https://github.com/UniXNU/UniXNU/blob/40d21cc65171c3a24faa130a2a8e899f85790485/scripts/seed-data-grow.py)
supports a specified capacity or sizing to userdata, with guards and a log
reserve. It grows APFS, which cannot be applied directly to our HFSX volume.

The [sheng root image builder](https://github.com/UniXNU/UniXNU-sheng/blob/08cde20edc3254ed6f7df8d0f5384fb887786e8f/scripts/build-userdata-root-image.py)
uses the sizes of the original OS/SystemOS/AppOS images, rather than a fixed
12 GiB. The main project's 32 GiB dual-system example is a **partition example**,
not a requirement for the firmware's system volume.

Houji combines the original iOS16 system and writable files in one HFSX volume.
The former 12 GiB volume had only about 147 MiB available, so it was inadequate
for continued caches, diagnostics and application work. 32 GiB leaves working
space without changing GPT or using the rest of userdata.

## Actual migration

- Immutable complete 12 GiB preimage:
  `phone-after-wallpaper-v7/ios16-phone.hfsx`, SHA256
  `e7828e19dbf5f4531aa8c4e85b234a1684d7125bffb460c46b8784516f3046ad`.
- Replay the HFS journal on a **local clone** and cleanly detach before resizing.
  A preliminary clone resized before journal replay failed fsck and was rejected;
  it was never installed.
- Grow with the macOS HFS-aware image resize tool. The installed candidate passed
  `diskutil verifyVolume`, preserved HFSX/4096-byte blocks and volume UUID
  `1e38300864ba2b7b`.
- Initialize only userdata offsets `[12 GiB,32 GiB)` and update the changed
  128 MiB chunks 0, 1 and 255. This newly exposed range lay outside the old iOS
  volume; the owner previously authorized clearing Android and personal data.
- Direct-read all 256 chunks. Full candidate SHA256:
  `d57293ea39b0d6289df0d77957a879f2adb50aa7bb35787389ecfe48be25dc5d`.
- Verify all five protected boot partitions, all twelve GPT ranges, misc and a
  block immediately beyond 32 GiB before/after. They remain unchanged.

The expanded volume requires the 32 GiB kernel profile: 8388608 4K blocks,
physical LUN 0, first LBA 2260480. `HoujiRootPolicy.h` retains a 12 GiB default
for older build consumers; the frozen r196 kernel explicitly defines
`HOUJI_ROOT_GIB=32`. The header validator and every read/write span use the same
compiled geometry. Both 12/32 GiB transport/RMW boundary tests passed.

The first new readback-helper build had an Android static TLS ABI mismatch and
was rejected before any userdata write. The replacement uses the same dynamic
linker model as the qualified 12 GiB helper, passed actual-phone input-rejection
and edge-chunk checks, and is pinned at SHA256
`bdc1a8de7623d4a6f5cc559bfed20beb9ef5e619df45eecbe706fd9ef30bbc38`.

## Recovery and evidence

Artifacts are under
`${HOUJI_ARTIFACTS}/native-port/`:

- `ios-userland/root32-r196/`: pinned delta, installation journal, verification,
  immutable installed 32 GiB baseline.
- `ios-userland/phone-after-root32-r196/`: complete, stable post-boot 32 GiB
  snapshot, SHA256
  `0ddc284aaf543022c64ab465f6b69df36fd8b06f7b84a206f0049c0e9b84a24c`.
- `evidence/root32-r196-result.json`: committed run identity, protected storage
  checks, actual GPU counters and separate human feedback.
- `native-ios-candidate/r196-source/`: frozen kernel, loader and boot source
  inputs, policy and source hashes.

OrangeFox and the GPT were retained. Do not format data or boot Android.
Older 12 GiB kernels reject the current 32 GiB HFS header; use r196 with the
expanded volume. To revert to the old layout, restore the **entire verified
12 GiB preimage**, verify all 96 chunks, then use its matching r195 image.
Do not apply an old incremental delta after iOS has changed the filesystem.

The geometry migration changes no GPU shader, renderer, clock governor, touch
or SMP implementation. r196 completed 6757 backboardd submissions and 6847 GPU
fences, with no recorded submission errors. This does not establish correct
pixels or panel FPS. Wallpaper blanks and component flicker remain unresolved.
