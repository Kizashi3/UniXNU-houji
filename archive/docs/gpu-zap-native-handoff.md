本文件保存2026-10-27只读审计，方案尚未在新XNU镜像启用；历史UEFI结果与待验证Native实现分开记录。

# Houji ZAP low-PA metadata / Native handoff audit

2026-10-27. Read-only source and saved-evidence audit. No device commands, target-memory reads, P changes or firmware changes were performed. The sole output of this task is this file.

Paths: P=${HOUJI_PORT_ROOT}; U=${HOUJI_UEFI_ROOT}; N=${HOUJI_ARTIFACTS}/native-port; D=N/DarwinBoot/DarwinBootPkg/Driver; X=P/.cache/ios16-reference/dxb-ios/xnu. All source references below resolve under these absolute roots.

## Conclusions

1. A dedicated low-PA metadata allocation can be made by UEFI and transferred as a retained physical reservation to XNU without expanding XNU managed RAM. Use one complete aligned 16KiB allocation, a dedicated scalar /chosen record, and one exclusive XNU NormalNC mapping. The actual portable PAS metadata capacity remains 4096 bytes, payload 4044 bytes. This is a proposed implementation, not an existing qualified handoff.
2. The complete CPU page [0x9b098000,0x9b09c000) is OEM no-map reserved, but is NOT wholly GPU-owned: first 8192 bytes are the IPA GSI tail, last 8192 bytes are GPU microcode. Mapping the page uniformly NormalNC and accessing only the exact 1072-byte GPU segment is a viable conditional design. It does not need to read/write the IPA half or falsely claim whole-page GPU data ownership.
3. Current sources/evidence prove the old UEFI mapping was NormalNC and the old GPU write range was exact. They do not yet prove the proposed XNU mapping, absence of a second XNU alias/owner, or current-boot raw reservation metadata. These are finite handoff/preflight checks that can be combined with the next full graph trial. No PM4/2D algorithm rediscovery is needed.
4. Neither the 0x420... prefix nor existing <=4GiB allocation proves SCM metadata is architecturally limited to 32-bit addresses. Preserve the original convention, frames and low-PA profile; do not truncate or silently test high-PA metadata.

## Exact existing contract

- P/native/gpu/uefi/GpuZapLoad.h:20-28: target 0x9b09a000, reservation 0x2000, MEM_SETUP span 0x1000, metadata capacity 0x1000, metadata payload 4044, signed segment 1072; metadata physical address is uint64_t.
- Same file:70-81: portable config validation accepts aligned uint64_t PA and checks span overflow/overlap; no 32-bit upper bound.
- Same file:133-176: once-only flow is metadata copy/publish/readback, INIT_IMAGE, MEM_SETUP, exact signed-segment copy, AUTH. Original fixed frames at 161/164/173 are 0x42000201/0x82/PAS13/metadataPA; 0x42000202/3/PAS13/0x9b09a000/0x1000; 0x42000205/1/PAS13. Source metadata CRC C73AEE66 and segment CRC EF6CC69B are checked at 144-146.
- P/native/gpu/uefi/GpuZapLoadNative.h:144-170: old UEFI binding allocates only one 4KiB page via AllocateMaxAddress, maximum 0xffffffff, rejects >0xfffff000, and changes that 4KiB allocation WB->WC. This binding must be replaced for CPU16K ownership; copying it mechanically would be wrong.
- Same file:39-53: old AT and CPU pointer assume UEFI 4KiB TG0 and identity VA=PA. These assumptions cannot be inherited by XNU. Native must use the descriptor mapping VA and verify actual full 64-bit R/W PAR separately.
- Same file:203-214: exact destination==0x9b09a000, source==immutable signed segment, bytes==1072. It closes target access before the first volatile byte store, writes only those 1072 bytes, then DSB SY; no memset, target readback, full-page flush, unmap, PAS shutdown or direct TRUST write.
- Same file:185-192: AUTH/later guards stop querying target translations after software access close; the close is a software permission policy, not a hardware unmap/revoke claim.
- P/native/gpu/uefi/GpuHostRingNative.h:535-560: actual AUTH occurs only after SQE enabled and fixed CP_INIT idle with RPTR=WPTR=10, then fixed CP_SET_SECURE_MODE(0), first context, known image. Do not move AUTH before CP_INIT.
- P/native/gpu/uefi/GpuPower.c:875-892: metadata/reservation preparation occurs before host ring; ordinary host profile -> host preparation -> host ring is the proven path.

## OEM 16KiB target-page coverage: proved from DTB and historical EFI observation

Parsed N/device-baseline/live-fdt.dtb with the existing strict P/scripts/fdt.py parser. SHA256=04dad3a2a40758525e93109ef17954183500a86c7bdf77973b89e39f97723807; file/declared size both 960869. Binary values exactly match the saved DTS (not merely a guessed filename).

| Subrange, half-open | OEM owner and source |
|---|---|
| [0x9b090000,0x9b09a000) | /reserved-memory/ipa_gsi_region@9b090000, no-map; N/device-baseline/live-fdt.dts:200-204, reg at 202 = 0x9b090000 +0xa000 |
| [0x9b098000,0x9b09a000) | Last 8KiB of that IPA GSI reservation; first half of the CPU16K page |
| [0x9b09a000,0x9b09c000) | /reserved-memory/gpu_microcode_region@9b09a000, no-map; same DTS:242-246, reg at 244 = 0x9b09a000 +0x2000 |
| [0x9b09c000,0x9b0a0000) | next separate lost_reg_mem no-map reservation, DTS:248-251; must not be included |

Parent reserved-memory uses 2 address and 2 size cells (DTS:58-61). Union of the first two relevant owners covers every byte of [0x9b098000,0x9b09c000), with no gap or normal RAM. This proves OEM reservation coverage, NOT an exclusive GPU lease, secure-world ownership, or IPA inactivity.

U/Platforms/Xiaomi/houjiPkg/Library/MemoryMapLib/MemoryMapLib.c:17 derives PIL_Reserved=[0x8bc00000,0xa2b80000) from captured xbl_config and maps it UNCACHED_UNBUFFERED_XN. It contains all 16KiB. Historical actual r135 evidence N/evidence/logfs-recovery-r135/UniXNU.log:3600-3608 reports EFI type0 reserved, broad PIL descriptor, GCD reserved/no image or device allocation, and target R/W PAR Attr44 at both GPU4K pages. This corroborates reserved/NormalNC mapping, but the old observer only targets 0x9b09a000/0x9b09b000, not the whole CPU16K page. New current-boot handoff must explicitly cover 0x9b098000 through 0x9b09bfff using metadata/AT only.

Historical r135 log:3609-3621 records exact successful INIT/MEM_SETUP/AUTH, metadataPA=D1CE4000, target-copy completed and access-closed. MEM_SETUP x3=9B09A000/x4=1000; no target readback. This is sufficient to reuse the known segment/order/SCM path, not a reason to repeat those algorithms.

## Current loader and managed-memory boundary

- D/DarwinBoot.c:54-73 verifies ordinary EFI allocations remain <4GiB while the XNU contiguous window is 2 or 8GiB in [0x8c0000000,0xbea400000). U/Platforms/Xiaomi/houjiPkg/Include/Protocol/HoujiRootRAM.h:6-10 defines these bounds and CPU16KiB alignment.
- D/DarwinBoot.c:442-476 scans genuine EfiConventionalMemory and reserves the kernel window using AllocateAddress/EfiLoaderCode. It does not synthesize RAM.
- Same file:620-653 allocates the window, lays out Args/ADT and payload, and sets boot_args PhysicalBase/MemorySize/MemorySizeActual plus ADT DRAM base/size to that exact high window.
- Same file:698-707 gets the final map key, calls ExitBootServices and jumps to DarwinEnter.
- D/Entry.S:26-51 cleans the owned high window, then disables old EL1 MMU/D/I-cache and invalidates EL1 TLB before kernel entry. EFI low identity mappings are not a usable Native pointer after this transition. It does not flush a newly allocated low metadata range automatically: that range must be explicitly prepared before EBS.
- U/Mu_Basecore/MdeModulePkg/Core/Dxe/Mem/Page.c:1095-1101 caps automatic EFI search at 4GiB in this build. This helps allocation availability but is not a proof of 16KiB alignment or success.
- P/native/gpu/xnu/Adreno740/NativeAdrenoMemory.cpp:45-64 allocates from managed IOKit RAM and checks actual PA. Requesting bits=32 cannot create low pages when XNU only manages the high window. Do not use this allocation path for the imported low reservation.

## Minimum implementable metadata handoff

### Preferred insertion: loader-owned allocation, no extra Main GUID required

Add a separate opt-in /chosen/houji,gpu-zap-reservation fixed-size scalar slot to the generated ADT. After existing AdtNode validation and AllocateWindow success, before copying Tree at D/DarwinBoot.c:650, loader allocates/qualifies the reservation and fills that slot in the validated private Tree buffer. Main need not publish a new configuration table. Main's present XNU path only powers/clocks the GPU (U/.../HoujiStorageProbe.c:1019-1027); stock execution starts later in XNU, so loader allocation still precedes first GMU/SQE/SCM publication of this new resource.

If Main must own allocation instead, use a separate GUID and reuse the exact scalar-copy pattern of P/native/gpu/handoff/DarwinBootGpuHandoff.h:50-98: one unique GUID + one canonical all-zero ADT slot, strict length/placement/CRC validation, copy scalars before EBS. Do not extend the old power-only schema to mean inherited BO ownership; it currently explicitly transfers no resources/pointers.

Allocation choices, with preferred exact-owned implementation:

1. Reuse the loader's bounded GetMap/raw-descriptor checks. Choose a real conventional-memory candidate <=0xffffc000 and aligned 0x4000, covered by one conventional run, then AllocatePages(AllocateAddress,EfiLoaderData,4,&candidate). Verify returned exact PA, (PA&0x3fff)==0, span16KiB below4GiB and outside target page/high window/loader buffers/other retained resources. Four arbitrary AllocateMaxAddress pages alone do NOT guarantee alignment.
2. An alternative is AllocateMaxAddress 7 EFI pages, select the contained aligned16KiB, retain the entire raw allocation and record both raw and selected spans; never return edge pages on unknown paths. This is slightly larger bookkeeping and is unnecessary if exact aligned AllocateAddress succeeds. Generic AllocateAlignedPages(4,0x4000) is usable only if its actual return PA<=0xffffc000 is checked, including correct failure retention.
3. Record immutable owner/boot epoch, allocation attempted/returned and raw EFI/GCD provenance. Before attribute mutation verify the entire16KiB is SystemMemory allocated to this owner, WB, no RO/RP and WC-capable, no overlaps. Initialize/clean the full exclusively owned16KiB while WB, perform full-owned WB->WC transition once via EFI CPU/GCD service, DSB, then prove R/W PAR Attr44 and correct output PA at all four4KiB offsets. CPU pointers are only UEFI-valid until EBS.
4. Native PAS config remains metadata_capacity=4096, metadata_cpu=NativeVA, metadata_physical=lowPA; actual owned bytes=16384 is separate. The payload4044 plus zero padding may be read back only within this exclusively owned allocation. Native can copy the already pinned source into it at the original hzl_run stage; never take ownership of the source file/EFI pointer.
5. Keep allocation retained on every later error, success and unknown return. Neither loader Fail cleanup nor XNU teardown may FreePages/recycle/relabel it after handoff started. No XNU managed-memory expansion: boot_args and ADT DRAM base/size stay high-window-only. A dedicated /chosen reservation record is explicit ownership transport for an outside-window region; do not insert arbitrary low DRAM into generic /memory reg or blindly depend on EFI type alone after EBS.

Minimum record semantics (fixed typed scalars, no callable pointers): magic/version/bytes/CRC; current trial UUID/epoch; source/ready/retained/attempted/returned; metadata physical base, owned16KiB, logical4KiB, payload4044, expected NC; raw allocation/map/GCD type/ranges/attributes/capabilities and four R/W PAR snapshots; target container base16KiB, IPA8KiB exclusion, GPU8KiB reservation, allowed copy base/1072B, fixed MEM_SETUP span4KiB; current-boot raw reservation coverage; pinned baseline DTB hash/profile ID. A CRC detects corruption, not secure ownership attestation. A missing/malformed/duplicate/wrong-epoch record must fail closed before mapping or SCM.

XNU import:

- Read/copy the unique /chosen scalar property as in P/native/gpu/xnu/HoujiGpuHandoffProbe.inc:142-156, but use an independent one-shot resource owner and schema. Verify all overflow/alignment/type/scope fields and both PA spans remain disjoint from gPhysBase..gPhysBase+gPhysSize and every BO/VM/display/UFS ledger range.
- Make one physical IOMemoryDescriptor for metadataPA/16384, using task=nullptr and kIOMemoryMapperNone, then map(kIOMapAnywhere|kIOMapWriteCombineCache). Actual X/iokit/Kernel/IOMemoryDescriptor.cpp:1744-1769 converts task=nullptr address ranges to physical64. Descriptor map does not allocate or acquire ordinary VM pages and does not authorize access without the handoff record. Retain descriptor/map for the owner until platform reset.
- Do NOT use kIOMapInhibitCache for this RAM metadata: same file:360-365 maps write-combine to VM_WIMG_WCOMB and inhibit to VM_WIMG_IO; X/osfmk/arm/pmap/pmap.c:5687-5689 and arm64/proc_reg.h:1123 identify WCOMB as normal non-cacheable/buffered, NX. Nevertheless actual PAR Attr44/PA for full Native mapping must be verified before the first data access; requested flags are not sufficient proof.
- A fresh Native R/W full-PAR check at all four4K offsets must report expected lowPA and NormalNC. Use descriptor VA only, no phystokv or inherited identity pointer. Include imported full16KiB in the common graph ledger and owner/ref retention; expose only typed metadata copy/publish callbacks, not arbitrary physical writes.

## Target mapping with split data owners: precise allowed plan

1. Before EBS record complete current EFI-map + GCD coverage for [0x9b098000,0x9b09c000), without reading its data. Require reserved/no ordinary allocation and the fixed same NormalNC PIL profile. Baseline DT supplies the IPA/GPU division, not a reclaim permission.
2. XNU excludes the entire page from ordinary RAM (already true if the high-only boot window remains), does not create another mapping/IPA driver/resource owner for it, and establishes exactly one dedicated 16KiB physical NC/NX map. Verify mapping VA16K alignment, exact length, all actual output PAs, all full R/W PAR; AT is translation-only. Existing UEFI identity map is gone at XNU entry. Do not silently create a WB physical-aperture alias below gPhysBase.
3. Label this object as `reserved container mapping / GPU exact subrange lease`, not a NativeAdrenoMemory fully GPU-owned BO. The IPA portion remains excluded and untouched. A single CPU PTE's uniform NC attribute does not transfer data ownership. Keeping the same NC attributes as the old PIL map and doing no CPU data access to IPA is compatible in principle with possible IPA DMA; do not claim IPA DMA stopped merely because no IPA driver is linked.
4. Fixed store callback accepts ONLY Destination=0x9b09a000, immutable source mHoujiZapSegment, Bytes=1072, exact expected phase/once/current owner/CP_INIT-idle/power/SCM guards. Effective Native pointer is containerVA+0x2000. Maximum CPU-written byte is0x9b09a42f. It must never memset/copy16KiB, read/compare target data, inspect IPA data, flush/invalidate the container, use pooled allocator cleanup, or touch [0x9b09a430,0x9b09c000).
5. Close this adapter's target-access authority before the first potentially partial store and DSB SY afterward, mirroring the proven code. AUTH is then allowed only with exact segment-published state; after close no target AT, data load/store, remap, cache operation or restore. Keep map/ref/bookkeeping retained on failure; no claim of hardware revoke.
6. Partial stores, non-returning SMC or unknown DMA stay retained/noFS and use prearmed recovery. Metadata remains retained too. Do not turn reset1 into a drain claim.

This plan is conditionally implementable even though the CPU page contains two OEM owners. It is blocked only if current reservation/NC mapping/exclusive CPU alias policy cannot be established, or if another CPU driver actually needs the same physical16KiB under incompatible attributes. Mere presence of an unrelated IPA reservation is not proof of such conflict.

## IPA/GSI activity: what inspection does and does not show

- U/.../Application/HoujiStorageProbe/OemServices.inc:26-43 lists all16 explicitly loaded OEM services (SMEM, DAL/HWIO/chip/platform/log/SCM, power/clock, HALIOMMU/ICB). No IPA/GSI driver is listed.
- U/.../Include/DXE.inc:1-31 and APRIORI.inc:1-18 contain no IPA/GSI module; houji.fdf:85-87 includes that module inventory. The storage app explicitly loads UFSDxe separately; current inspected path has no IPA init API.
- Actual X/iokit/conf/files:152-166 lists houji root + limited Adreno CPU/memory/firmware/SMMU/stock files. Inspected houji root/Sweet platform source has no IPA/GSI owner. This supports a software configuration invariant that this port does not start an IPA CPU driver.
- This source inventory cannot prove bootloader/secure-world/remote firmware left no IPA DMA running, nor that a hidden OEM service never touched IPA. No current device register evidence was acquired. Such possible device DMA is not itself a reason to read or reset IPA: the proposed CPU mapping preserves NC and never accesses its data. The ledger must preserve its subrange rather than reclaim it.

## Minimum combined acceptance before authenticated copy

- Offline: actual record parser roundtrip/reject duplicates/overflow/wrong epoch, aligned allocator boundary cases, full imported-span ledger, task-null physical descriptor path, full4xR/W PAR verification, exact subrange/store guard, terminal noFS and retention. Pin source/asset hashes and actual linked ARM store/barrier/SMC frames.
- Next full graph device run: before first GMU release, combine metadata allocation/handoff/import and target reservation/AT-only map checks with full graph memory diagnostics. If they pass, continue unchanged bank0/GX/CP_INIT sequence, exact authenticated copy, mode/context/known-image; if not, fail at a named boundary with no target access. This need not be a separate standalone reboot just to reprove old PAS packets.
- Still unproved: success of this new16KiB low allocation at runtime; import/cache requested flags actually produce proper Attr44 on this low reserved mapping; complete current-boot graph/container overlap policy; Native exact copy/SCM/close integration. High-PA metadata support is intentionally outside this profile. DT/EFI type does not establish secure-world ownership; authenticated-load success must come from real PAS returns and the original phase/owner guards, and is not a general ownership attestation.
