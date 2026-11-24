# houji r734 runtime experiments

These are the board input and OLED changes tested on houji on 2026-11-24. The addresses and digests are tied to the exact r734 experiment inputs. The regular repository build does not consume this directory.

- enable-lock.py updates the SpringBoard lock preferences while preserving the plist size.
- keys.c keeps the stock HID event route and reads physical key state. panel.cpp handles display power requests and waits for a post-request frame before turning the OLED back on.
- shorten-touch-waits-v2.py shortens the diagnostic pauses in the touch worker and extends PMIC key sampling to cover the recovery trial.

With a locally prepared kernel-wake-frame.macho matching the script's input digest, run:

    python3 shorten-touch-waits-v2.py kernel-wake-frame.macho kernel-touch-fast-v2.macho

The output digest and device measurements are in the [validation record](../../../docs/validation/houji-2026-11-24.md).

For the earlier wake-frame experiment, build.py assembles the payload with Clang, LLD and LLVM utilities. apply-v103.py and assemble-v107.py record the merge against the locally prepared r734 baseline and v106 lock policy. Those scripts expect the filenames and locations declared in their source. Local prelinked inputs, firmware, boot images and Data seeds are sourced separately.
