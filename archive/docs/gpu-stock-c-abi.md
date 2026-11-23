当前实现已落地 `native/gpu/xnu/hfi-inactive/houji_stock_native.{c,h}` 与 `native/gpu/xnu/HoujiGpuStockFirmwareProbe.inc`。r152 实际XNU内核已通过原厂固件FWready/HFIready/属性查询ACK，证据见 bringup.md/r152；无CP/图形/桌面加速。原始设计正文保留在下方，设计阶段的“no implementation”描述仅反映当时状态。

原HHI 105724检查和Native2743 profile、新Cbridge93 profile、Native整体29 profile、MMIO policy19435检查分别离线通过。实际ARM64链接和真实照片/CRC各自独立绑定，不把host结果当硬件结果。stage1为执行前最后可保存检查点，stage2及之后只RAM；reset1并不授权FS或释放资源。

# Stock GMU C ABI: implementation and original design

This candidate contains a proposed POD header and an executed host layout probe. It contains **no stock-run implementation** and has not called `hhi_prepare`, `hgf_run`, a Native operation, MMIO, SMC or a device. P, actual XNU, drivers and dependencies were not changed. Root's next step remains the Native owner/secure-CX/storage-exit review, not stock firmware execution.

## Interface and measured storage

`houji_stock_native.proposed.h` is standalone C11/C++14 POD, including only the unchanged HHI public header and standard integer/size types. Proposed entry points are `hsn_init`, one-shot `hsn_run`, and read-only summary/failure/TCM-word/RX/memory-summary/memory-row getters. Native supplies typed read32/read64/write32/write64/barrier/delay/prerequisite/publish/checkpoint/stopped callbacks. Normal operations return 0 on success; upstream prerequisite uniquely requires exactly 1. The initial scope fixes `hgf_io.bootstrap=NULL`: real stock boot, HFI readiness and the existing property query; no additional HWSCHED/resource/PAS/ZAP/CP scope.

| Actual host layout | Bytes | Alignment |
|---|---:|---:|
| Unchanged `HhiStorage` | 4096 | 16 |
| Real private `HhiState` | 992 | 16 |
| Real `hfm_result` | 800 | 8 |
| Real `hgf_result` | 78168 | 8 |
| Included real `hhb_result` | 44008 | 4 |
| Proposed callbacks | 96 | 8 |
| One proposed RX record (255 words) | 1036 | 4 |
| Proposed stock state, 34 RX records | 113760 | 16 |
| Proposed opaque envelope | 131072 | 16 |

The 78 KiB upstream result includes 8192 actual TCM backup words and the full bootstrap subtree even when bootstrap is disabled. Do not replace it with a shortened imitation. The 128 KiB envelope is design-stage sizing, not an existing implemented ABI. `build/layout.json` contains measurements and original HHI offsets: callbacks 72, traces 120, actual result 184. The probe includes the actual existing HHI C implementation to measure its real private type; `main` only prints layout values.

## Binding the real HHI graph

Do not construct `hfm_result` from `HhiSummary` or `HhiRow`, and do not accept an arbitrary `hfm_result*` in the public API. The proposed bridge accepts the existing self-bound `HhiStorage*` plus exact size and, inside its private C TU, passes **`&real_hhi_state->result` directly** to the untouched upstream `hgf_run`.

For an eventual implementation, move the original complete `HhiState` definition and constants into a private C-only header shared by the original HHI implementation and the new stock implementation. Keep every field, order, offset, alignment and public HHI signature unchanged. Do not expose that header to C++ or Native callers, and do not add an exported raw-state pointer getter. A single C TU including the existing HHI C implementation would also avoid a copied layout, as this layout probe demonstrates; the private-header extraction is cleaner for normal build inputs.

Before binding: validate both envelopes, magic/inverse/self/version, HHI not busy, exactly one successful prepare, no release attempt, no uncertain allocation outputs, all 9 allocated/validated/retained and none released, exact profile/build/audit/HFI state, and disjoint output/firmware/storage intervals. Call the real `hhi_verify_contents` while the allocator remains inactive. Native remains responsible for pinned FW hash, original 78588 bytes, actual BO/ref/CPU-page/NC/WB/alias/cache/secure-CX ownership, and a separate qualified PRR-zero BO.

Then seal the real HHI busy word before any Native callback, record the exact HHI storage address in the stock state's own address-bound identity, and never unseal it in this one-shot experiment, including early failure. Existing HHI APIs already reject nonzero busy, so release/reinit/prepare/verify cannot race or reuse the graph. No HHI fields need to be added or repurposed, and the original lifecycle is unchanged for callers that never bind stock. Read-only stock memory getters can use shared private snapshot helpers to report the sealed original metadata; the snapshots must never become executable input.

`hgf_run` itself has no once/reentry guard and clears its entire result at entry. The bridge needs a separate one-attempt flag, address identity, mutation busy guard and externally serialized lifetime. The two opaque storages, original firmware bytes, Native BOs/maps and references remain alive until platform reset. There is deliberately no release, unbind, retry, cleanup or restore-to-inactive API.

## Exact receive and failure records

Upstream stock phase9 calls `ggh_send/ggh_receive` directly on the actual HFI row5 CPU pointer; it does not invoke a receive callback. Its result retains only the last `reply[255]`, `reply_count` and `debug_count`. Reporting that as a complete RX log would be false.

The minimal proposed instrumentation is a C-TU call-binding tap: first include the real `giulia_gpu_hfi.h`, declare the tap, temporarily bind only `ggh_receive` while including the real unmodified `GpuStockGmu.h`, then undefine the binding. The tap calls the original `ggh_receive` once with identical arguments, logs its unchanged status/count/output, and returns the identical status. It obtains the bridge identity through the real typed `hgf_queue_cookie -> hgf_io.cookie`, not a global current-instance variable or a fabricated struct layout. No table, HFI contents, upstream result, MMIO or callback behavior is changed by the tap.

Keep each nonempty receive and receive error in original order; count empty receives by queue separately. With bootstrap fixed NULL, the actual stock loop stops after at most 32 debug messages plus one ACK, or at the first additional debug/error. 34 fixed slots conservatively cover this bounded transcript. Record overflow explicitly; never claim a complete log if anything was dropped. A future bootstrap extension needs a separate bound and design review.

The failure getter reports raw upstream code/failed_phase/address/value/operation/observed_valid, plus the first wrapper callback error with its original status. Never normalize failed callback outputs into valid observations. TCM getters return only indices strictly below actual `tcm_backup_words`; a failed/unfinished read does not become a valid backup merely because its array slot exists. No public getter returns an executable `hfm_result` or writable upstream pointer.

## Native owner and filesystem boundary

The bridge adds no MMIO or SMC implementation. Real `hgf_run` performs the existing fixed protocol through Native callbacks, including context/stream installation, TCM writes, reset release and later reset attempts. These are substantial future actions, not authorized by compiling this interface.

Every upstream outcome retains resources. Reset1 is explicitly not a DMA-drain proof; no stream/table/TCM/backing/reference is revoked. `hgf_result` has no `safe_to_save` contract. Its checkpoints at stage1 and stage2 are progress boundaries, not storage authorization. Native must separately prove whether a checkpoint is legal; after possible firmware execution, a reset/stopped callback or raw success code must never create an FS or release permission. Read-only CPU diagnostics and the existing direct platform-reset exit remain separate from filesystem operations.

## Dependencies and verification scope

The actual layout compiler recorded 21 inputs: 19 P source/header files, this probe, and SDK metadata. Project dependencies are:

- HHI: `native/gpu/xnu/hfi-inactive/houji_hfi_inactive.{c,h}`.
- UEFI: `GpuStockGmu.h`, `GpuFirmwareMemory.h`, `GpuSmmuContext.h`, `GpuSmmuPrepare.h`, `GpuSmmuProfile.h`, `GpuSharedMemory.h`, `GpuCodeMemory.h`, `GpuHfiBootstrap.h`, `GpuHfiTables.h`.
- Vendor: `AdrenoFirmware.h`; `giulia_gpu_memory.h`, `giulia_gpu_firmware.h`, `giulia_gpu_hfi.h`; `ArmSmmu4K.h`, `ArmSmmu4KContext.h`, `ArmSmmu4KProgram.h`, `ArmSmmu4KAudit.h`.
- Link inputs for the layout probe/eventual bridge: real `AdrenoFirmware.c` and `ArmSmmu4K{,Context,Program,Audit}.c`; no IOKit or UEFI services are compiled into the bridge. Native callbacks remain external.

`build/design-verification.json` binds every transitive input SHA and the C11/C++14 public-header syntax commands. `build/layout-commands.json` binds the real compile/link/layout invocation. All actual flow functions are dormant in the host layout run.

The old 105724 HHI and 2743 Native host regressions have **not been rerun for a new stock implementation**, because none exists and no old source was refactored. Existing corresponding evidence is hash-bound in `baseline-evidence.json`; those prior results are historical, not new stock validation. Any private-header extraction or implementation must rerun the original suites unchanged, verify all original HHI ABI sizes/offsets, and add stock bad-input/once/reentry/binding/retention/tap-equivalence tests before integration.
