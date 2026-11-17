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
