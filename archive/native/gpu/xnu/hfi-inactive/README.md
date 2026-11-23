# Offline houji inactive firmware/HFI bridge candidate

This directory is an isolated candidate. It reads the existing UniXNU-houji
sources at compile time. It does not modify that checkout, the XNU build tree,
firmware dependencies, Git state, or any device.

`houji_hfi_inactive.h` is a standalone C11/C++14 POD header. The C implementation
sets `HFM_WITH_SCRATCH=0`, includes the existing `GpuFirmwareMemory.h`, and calls
its original `hfm_prepare()` / `hfm_release()`. No planner, copy, HFI initializer,
table builder or physical-table audit is reimplemented in the bridge.

The wrapper has no SMC/MMIO/TTBR/stream/firmware-execution interface. Its trusted
callbacks must preserve that CPU-only scope. In particular **publish means CPU
cache publication to PoC plus ordering, not publication of a TTBR to a device**.
The upstream `published` bit is copied unchanged and has only that meaning here.
`hfi_initialized` means queue structures were initialized in RAM, not HFI ready,
an ACK, firmware execution, DMA completion, or desktop acceleration.

## Caller contract

1. Own one `HhiStorage`, initially `={0}` in C or `{}` in C++14. It is a fixed
   4096-byte, 16-byte-aligned envelope. Current internal state is 992 bytes,
   alignment 16; exported runtime queries report those values. Do not allocate
   only the internal size: every API checks the full fixed envelope exactly.
2. Keep the storage at one address, externally serialize calls, and keep callback
   code/cookie resources alive. A copied or moved state fails its self-address
   check. Never manually clear an initialized resource owner.
3. Call `hhi_init()` with exact `sizeof(HhiCallbacks)`, ABI version 1, reserved 0,
   and all four callbacks. The callback struct itself is copied.
4. Validate firmware identity in the caller, before `hhi_prepare()`: exact 78588
   bytes and SHA-256
   `9685f62c42543befcaee68d25355e16bf55cdb0d573bddcc9f6633f59eec3f72`.
   The bridge repeats length validation, not hashing. A caller can use the
   existing `NativeAdrenoFirmware::validate` with houji-specific rules; the
   generic Sheng service path is not used by this candidate.
5. Call `hhi_prepare()`, then read `HhiSummary` and rows 0 through 8. The return
   value reports API validation; `out_hfm_code` and summary report the original
   upstream operation result. `HHI_OK` alone does not mean preparation succeeded.
   After successful preparation and independent CPU-backing qualification, call
   `hhi_verify_contents()` to verify the retained buffers without changing them.
6. One prepare attempt per initialized lifecycle, including failure. A repeated
   prepare cannot clear the upstream result or ownership ledger. Callback reentry
   into init/prepare/release/summary/row/verify is rejected as busy. This is a single-owner
   reentry guard, not an inter-thread synchronization primitive.

The callback `publish` allocation pointer is a temporary POD valid for that call.
Store its values in the adapter's ledger if needed; do not retain its address.

## Exact inactive profile

The actual firmware's five metadata reservations occupy GPU4K pages
`19,27,19,37,2`, at IOVAs `0x4000,0x100000,0x200000,0x300000,0x60000000`.
HFI is 18 pages / `0x12000` bytes at `0x60010000`; log is 16 pages at
`0x60030000`; VRB is one page at `0x60040000`. The ninth BO is a ten-page
table pool and is never itself mapped into the GMU aperture.

This is eight ranges and nine BOs: logical 596 KiB, separately rounded CPU16K
backing 656 KiB. HFI is 72 KiB logical / 80 KiB backing, not 128 KiB.
The original prepare builds six used tables / 139 leaves and independently
audits 3072 actual descriptors. Four spare logical table pages and the rounded
CPU tail must remain zero and unmapped. The host adapter checks these facts.

The bridge reports logical GPU4K pages. The Native adapter must independently
own and validate complete CPU16K backing; logical length must not be used for
partial-page cache attributes or release. The callbacks receive raw PA, never
an EFI pointer or an IOMMU-translated address. All eight ranges keep upstream
RW+Privileged; only the first four ICACHE ranges execute at the device stage.
HFI/log/VRB require actual Normal NC, the other buffers/tables WB. These flags
describe the descriptor view and are not a request to change CPU execution
permissions. The Native adapter qualifies the known physical-aperture aliases
with AT only: they must resolve to the same PA and may report WB or NC. It does
not read or write data through those aliases. A descriptor NC view plus an
inactive WB aperture alias is reported as such; this CPU-only preparation does
not qualify alias/cache ownership for firmware execution or DMA. A later
execution stage requires its own ownership/cache gate. CPU PoC publication
never grants device access.

## Read-only content verification

`hhi_verify_contents(storage, storage_bytes, firmware, firmware_bytes, &code)`
requires one successful prepare, all nine rows allocated/validated/retained,
no released row, no uncertain allocation output and no release attempt. The
caller keeps all backing alive and exclusively accessible, with no device
references, DMA or concurrent access, and revalidates the firmware's pinned
identity before calling. The bridge repeats the exact length check and reruns
the existing independent `AdrenoFirmwarePlanGmu`, `gg_fw_plan` and
`gg_memory_plan`; it does not authenticate the input itself.

The verifier compares every byte of the five firmware logical reservations
against the original planned payload or zero for holes. It uses the existing
`ggh_queue` validator on all 17 queues, requires empty cursors and zero rings,
checks all reserved header fields and both logical padding areas, and requires
the complete log and VRB logical buffers to be zero. It invokes no adapter
callback, changes no content or ownership/result field, and does not qualify
CPU attributes, rounded CPU tails or the table graph; those remain independent
adapter/audit checks.

The API return uses the existing `HhiStatus`. An API/state rejection leaves
`code` unchanged. With `HHI_OK`, `code` is 0 for a match, 1 for a planner/profile
mismatch, 2 for a firmware payload mismatch, 3 for a nonzero firmware hole,
4 for an HFI header/cursor/ring/logical-padding mismatch, 5 for a nonzero log,
or 6 for a nonzero VRB. Inputs and the output must not alias the opaque storage
or any logical BO, and the output must not alias the firmware input. A mismatch
does not clear preparation bits or automatically release a resource; callers
must keep/quarantine the owner under their existing failure policy.

## Ownership and failure reporting

The raw `allocated/validated/released/retained` masks and original allocation
metadata are copied verbatim. Releasing a row leaves stale CPU/PA metadata;
never dereference a row after its released bit is set. The bridge adds historical
per-callback attempted/success/failure masks and call counts so a partially
completed cache publication is visible even when total `published` is zero.

`hfm_prepare` automatically attempts cleanup on failure. A callback must return
release success only after the underlying owner actually restored/verified CPU
attributes and released the resource. Returning failure retains the original
upstream row; a Native adapter that keeps resources until platform reset can
intentionally refuse cleanup and quarantine its own backing. The bridge does
not fabricate a successful release. It separately preserves the first prepare
error before upstream release failure can overwrite `hfm_code` with HFM_RELEASE.

On explicit `hhi_release`, only `allocated && !released` rows are passed to
upstream cleanup, in reverse order. Retrying cleanup calls only the remaining
rows; the upstream error code intentionally remains sticky even after all rows
are released. Per-row callback traces use row identity and the upstream cleanup
cursor, not potentially duplicate PA/CPU tuples.

An allocate callback returning failure must transfer no resource and leave both
outputs zero; it owns/quarantines any uncertain partial descriptor in its separate
ledger. If it returns failure with nonzero outputs, the bridge records
`uncertain_allocate_outputs` and blocks reinitialization. It does not invent
upstream allocated/retained/released bits for that unaccepted transfer, and does
not automatically free it. The caller must retain that independent partial owner.
Validate failures after partial cache changes likewise remain the adapter's
restore/quarantine responsibility.

Clean reinitialization is permitted only after the prior prepare attempt has no
remaining upstream owner and no uncertain allocation outputs. The API cannot
protect against a caller deliberately overwriting its own storage or callbacks.

## Host validation

Run `python3 /tmp/houji-hfi-inactive-candidate/run_tests.py`. Optional `--repo`
and `--firmware` select existing local inputs; no download path exists. Build
outputs and the source/digest/command manifest go only into this directory's
`build/` folder.

The runner validates caller-side firmware length/hash, including changed-byte
and truncated identity refusals, before executing tests. It compiles the original
source dependencies unchanged with Clang C11, ASan and UBSan; then compiles and
links the separate C++14 consumer against the C object. A final isolated
`-std=c++14 -pedantic-errors` header check has no upstream include directories.

The current C suite passes over 105000 assertions, including exact real-firmware layout,
padding and all 17 HFI rings; every allocation/validation/publication failure;
single and multiple release failures, retained masks and retry order; partial
attribute/allocation ownership; duplicate/overlapping/zero/unaligned/out-of-range
successful allocation outputs; strict argument lengths/alignments/ABI; reentry;
copied-state rejection; repeated-prepare refusal; verification guards; and
data corruption at each of the nine publication boundaries. Every HFI header
word, all 17 ring boundaries, both logical padding areas, firmware payload and
holes, log and VRB are checked by negative cases. Verification is repeatable and
preserves opaque state, contents and callback counts. These are host results,
not XNU integration or hardware evidence.
