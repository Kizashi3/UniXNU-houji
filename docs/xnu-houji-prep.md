# Xiaomi 14 houji XNU preparation

Completed on Ubuntu:

- `houji_defconfig` selected in `UniXNU/out/houji/.config`.
- XNU and supporting Apple sources fetched at the commits recorded in `unixnu.lock`.
- `UniXNU/out/houji/tree` assembled.
- houji ADT generated with a 256 MiB first-entry probe window, CPU0 only, PSCI SMC.
- Offline board/FV/ShmBridge/UFSDxe validation passed.

The Ubuntu stage stops before `unixnu build kernel`: the kernel recipe requires macOS and Xcode. The board now points to the matching iOS 16.7.16 / build 20H392 IPSW for `iPhone10,3` (`d22ap`, chip `0x8015`, board `6`). The raw `kernelcache.release.iphone10b` member is pinned; the decoded kernelcache hash remains unset until macOS `compression_tool` verifies it.

The first device test remains `fastboot boot` only. Do not use `fastboot flash`, `erase`, or `format`.
