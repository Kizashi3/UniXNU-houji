# Night session 2026-11-18

## Fixed

`HOUJI-PERSONA: system proxy id=501 err=0` — a PERSONA_SYSTEM_PROXY is now
created for uid 501 in `kern_persona.c` at boot. launchd's repeated
`Unable to find persona with type 6` dropped from 366 to 0 in run 502.

## SpringBoard

It still restarts about 13 times a run and always leaves through `exit(255)`,
not a signal. The syscall ring (`HOUJI-SYSRING`) shows its last 32 calls

    bsdthread_ctl / kevent_id / proc_info / madvise ... 

all with errno 0, ending in the malloc teardown pattern. So it decides to exit
from user space; no failing syscall is visible at that layer.

## Next lead: IOHIDSystem is absent

`llvm-nm` on the kernel finds zero IOHIDSystem or IOHIDFamily symbols, the boot
log prints `IOHIDSystem services=0` and `IOHIDSystem alloc failed`, and the
class cannot be allocated by name. SpringBoard needs the HID system; this is now
the most concrete missing dependency.

Questions to settle next:

- whether IOHIDFamily.kext exists on the merged root at all (roottree copy has
  no System/Library/Extensions listing),
- whether the kernel build has to prelink IOHIDFamily (board.toml prelink roots),
- whether IOService::publishResource("IOBSD") still happens before IOHIDFamily's
  personality is probed.

## Infrastructure

- `wait-run.sh` and `ci-watch.sh` watch a build by commit; the first one reads
  run status from the API, the second reads the branch the workflow publishes.
  Both replace the earlier "wait for a new kernel" loop that could not see
  failures.
- ArmCpu is pinned to a823383 because upstream main references
  `arm64_platform_sleep_hook`, which this kernel does not provide.
- `wdt=-1 wdt_test=no_user_checkin` do not stop watchdogd's own assertion exit.

## 2026-11-18 evening: UFS Data window, ownership

* A 2 GiB RAM Data seed cannot boot: `HOUJI XNU: Load failed: Out of Resources`
  (the DXE unpack needs one 2.2 GiB contiguous allocation and the memory map is
  fragmented at ~760 MiB). The RAM seed stays at 512 MiB or below.
* The Data volume now lives in the flashed image as a second SHNGROOT window
  named `Data` (2 GiB). `IOKitBSDInit` publishes it as md3, `memdev` writes
  through to the userdata range via `native_ufs_md_write`, and the mount helper
  tries `/dev/md3` before the RAM block. Run 520 boot: `HOUJI-RD2: mounted
  /dev/md3 on /private/var`, spaceman scanned the container, no data abort.
* The full SystemOS rsync produced a root whose files are owned by 99:99: the
  writable sparse image was attached with owners off, so `hdiutil` stored the
  anonymous owner. launchd then refused every daemon with error 122 ("bad
  ownership/permissions") and nothing started. The merge now attaches with
  `-owners on` and asserts 0:0 on SpringBoard.plist and the LaunchDaemons dir.
* QEMU cannot host this root: the houji kernel has no virtio-blk driver and the
  10.5 GiB container exceeds the VM's 9 GiB of RAM, so the image is verified by
  hash against the CI report instead.

## 2026-11-19 small hours: first swaps, black content

* Root ownership: the merged root carries 99:99 and is mounted read-only, so
  chown and the MNT_UPDATE remount both fail.  `patches/xnu/houji-owner-override.patch`
  rewrites va_uid/va_gid from 99 to 0 in `vn_stat_noauth` for the root mount.
  Result: launchd error 122 dropped from 1066 to 0 and 121 jobs spawned,
  including SpringBoard and backboardd.
* Data volume: the flashed image now carries a second SHNGROOT window named
  Data (2 GiB).  `IOKitBSDInit` publishes it as md3, `memdev` writes through
  with `native_ufs_md_write`, and the mount helper mounts `/dev/md3` on
  `/private/var` before the RAM block.
* Display: with `/chosen/display-scale = 3` backboardd creates a 1200x2670
  display surface and a 1125x2436 layer surface, `sel 3` returns the layer
  surface and SwapEnd records real frames (first at ~250 s).
* Console: `houji_console_muted` was set but never read; `vcputc` now returns
  early after the first present, so the panel keeps the GUI.
* Boot: `houji-autoreboot` compared an absolute deadline against
  mach_absolute_time, which counts from power-on, so a device that sat in the
  bootloader expired at once.  The deadline is relative now.  A 150 s boot
  guard flushes the log and resets into recovery when init never reports.
* Wall: the presented frames are all zeros (probe nonzero=0/3150).  CA has a
  surface but nothing composited into it - SpringBoard runs (pid 5, idle after
  its first transactions) yet never builds its UI.  Same wall ios-sweet hit
  before their HID/work-interval/system-shell-check-in patches.
* Note: the compiled driver is the copy inside `patches/xnu/sweet-display.patch`;
  `vendor/drivers/SweetDisplay/*` is a stale mirror, so edits belong in the patch.
