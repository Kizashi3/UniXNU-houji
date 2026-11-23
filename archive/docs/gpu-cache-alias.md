# r149 CPU16K alias / DMA qualification notes

只读研究，2026-10-26。没有修改 P、actual XNU 或设备，没有运行测试、改变 cache 属性或页表，也没有设计新的 firmware 执行流程。当前源与已有 r148 持久日志是本报告的事实依据；文中的下一层条件是建议，不是已取得的硬件资格。

## 结论

当前 SWEET non-PPL XNU 的 `pmap_set_cache_attributes()` 更新 managed-page 元数据及登记在 PV 列表的 CPU PTE，**不保证更新独立的 `phystokv` aperture**。`pmap_cache_attributes()==WCOMB` 也只是元数据读回。因此 r149 的 HFI/log/VRB descriptor 为 Normal NC，不能推出所有别名已经 NC，或已能安全 live DMA。

另一方面，“存在 dormant WB alias”不能直接判为 DMA 必然错误。Linux arm64 的 noncoherent coherent-remap 实现也保留 kernel alias，先做缓存准备，再返回 NC view。正确问题是：旧 WB cache 状态是否完全交接、DMA 期间是否能保证只通过已资格化的 NC view 访问、是否控制其他别名和并发、是否保持正确内存顺序。当前 r149 只做 inactive CPU preparation 和 bounded alias AT 观察，尚未建立这份跨 DMA 生命周期的契约，`DMA-eligible=0` 必须保持。

新增已持久化的 r149 真机事实：[result.json](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r149-result.json) 明确 `PASS_CPU_INACTIVE_FIRMWARE_HFI_MEMORY`、hardware_tested=true，但 DMA_eligible=false／HFI_device_publication=false。[XnuLog.txt:466](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r149/XnuLog.txt:466) 为 complete1、content verified1、9BO／17HFI／AT2624／table6/139/3072；474–476 行三个 NC descriptor 的全部 aperture rows 分别 WB20/WB16/WB4，NC0，refs0。因此“descriptorNC／apertureWB”已是本轮 CPU-only 实测结果，不只是源码预期。

最小建议是先做**纯 CPU alias/cache 生命周期资格层**：在完整 CPU16K owned backing 上建立明确的 NC-only access lease，并审计已知 dormant WB alias。如果不能证明这个 lease，采用更强的、由内核管理的 aperture 同属性方案；不能通过换一个 IOBuffer flag、重复设置 WCOMB 或给 32 MiB block 整块改属性来跳过它。

## actual XNU 与 Native 调用链

本地 actual XNU 根目录：

`${HOUJI_PORT_ROOT}/.cache/ios16-reference/dxb-ios/xnu`

| 位置 | 实际行为与边界 |
| --- | --- |
| [SWEET.h:15](${HOUJI_PORT_ROOT}/.cache/ios16-reference/dxb-ios/xnu/pexpert/pexpert/arm64/SWEET.h:15) | `NO_MONITOR=1`；29 行选择 CPU16K。`__ARM_COHERENT_CACHE__` 是 CPU cache 配置，不能解释成 GPU coherent I/O。 |
| [proc_reg.h:2650](${HOUJI_PORT_ROOT}/.cache/ios16-reference/dxb-ios/xnu/osfmk/arm64/proc_reg.h:2650) | 只有 `XNU_MONITOR` 定义 `__ARM_PTE_PHYSMAP__`。 |
| [pmap.c:10539](${HOUJI_PORT_ROOT}/.cache/ios16-reference/dxb-ios/xnu/osfmk/arm/pmap/pmap.c:10539) | `pmap_set_cache_attributes_priv` 对非 managed PA 直接 void return；在 PVH lock 下更新 `pp_attr_table`，只有新旧 WIMG 不同才更新 PTE，随后 `pmap_sync_wimg`。 |
| [pmap.c:10090](${HOUJI_PORT_ROOT}/.cache/ios16-reference/dxb-ios/xnu/osfmk/arm/pmap/pmap.c:10090) | `pmap_cache_attributes` 读 `pp_attr_table`，不是硬件 AT 或页表完整性证明。重复同值 setter 也不能保证修复已漂移 PTE。 |
| [pmap.c:10673](${HOUJI_PORT_ROOT}/.cache/ios16-reference/dxb-ios/xnu/osfmk/arm/pmap/pmap.c:10673) | aperture 的 `phystokv` PTE 更新、TLBI 受 `__ARM_PTE_PHYSMAP__` 保护；当前 SWEET 路径没有这一段。 |
| [pmap.c:10700](${HOUJI_PORT_ROOT}/.cache/ios16-reference/dxb-ios/xnu/osfmk/arm/pmap/pmap.c:10700) | 遍历 PV 的 CPU PTE，替换 AttrIdx/SH，flush 对应 VA 并同步 TLB；10723 行显式跳过 IOMMU PTE。CPU cache setter 不会配置 GPU SMMU。 |
| [pmap.c:6106](${HOUJI_PORT_ROOT}/.cache/ios16-reference/dxb-ios/xnu/osfmk/arm/pmap/pmap.c:6106) | 后续 CPU mapping 可用显式 WIMG flags 覆盖默认页面属性；不能推导任意未来别名都保持同属性。6156 行是普通映射 PV 注册路径。 |
| [arm_vm_init.c:1603](${HOUJI_PORT_ROOT}/.cache/ios16-reference/dxb-ios/xnu/osfmk/arm64/arm_vm_init.c:1603) | 普通 DRAM aperture 初建允许 block/hint，直接写启动表，不经普通 PV 注册。1121–1124 行 L2 block 明确 WB，1038–1039 行边界页为默认属性。CPU16K L2 block 是 32 MiB。 |
| [NativeAdrenoMemory.cpp:160](${HOUJI_PORT_ROOT}/native/gpu/xnu/Adreno740/NativeAdrenoMemory.cpp:160) | `makeWriteCombined` 先对 `mapping_,owned_bytes_` 做真实 CleanInvalidate，再标 `write_combined_`，调用完整 owned spans 的 `NativeAdrenoSetPagesCacheMode`；属性部分失败则 quarantine。 |
| [NativeAdrenoCpu.cpp:139](${HOUJI_PORT_ROOT}/native/gpu/xnu/Adreno740/NativeAdrenoCpu.cpp:139) | 对完整 CPU pages 校验 exclusive spans、PA/aperture/ppnum 边界，每 CPU page 调 setter 并读回元数据。它不是 all-alias PTE 遍历接口。 |

`pmap_sync_wimg` 在 WB→NC 时调用 `pmap_sync_page_attributes_phys`。本地 [pmap.c:6886](${HOUJI_PORT_ROOT}/.cache/ios16-reference/dxb-ios/xnu/osfmk/arm/pmap/pmap.c:6886) 已先扩为 `vm_offset_t` 再左移，避免 32-bit ppnum 高 PA 截断。actual [caches.c:61](${HOUJI_PORT_ROOT}/.cache/ios16-reference/dxb-ios/xnu/osfmk/arm/caches.c:61) 的非 coherent-I/O 路径把 PA 转为 `phystokv_range` 并做 PoC maintenance。Native 自身的直接 `DC CVAC/CIVAC/IVAC` 与 DSB 则没有假定 Apple coherent-I/O shortcut。

另外，actual [pmap.c:5687](${HOUJI_PORT_ROOT}/.cache/ios16-reference/dxb-ios/xnu/osfmk/arm/pmap/pmap.c:5687) 的 WCOMB 生成 Normal NC AttrIdx 与 XN，不 OR 入 SH；WB/default 分支明确 OR `SH_OUTER_MEMORY`。这是**编码差异，不是已成立的有效 shareability 冲突**：Arm 官方 [EffectiveShareability](https://support.arm.com/documentation/111108/2026-09/Shared-Pseudocode/shared-translation-attrs) 对 Device 与 Normal inner-NC/outer-NC 强制有效 Outer Shareable。因此不能要求 NC PTE 的原始 SH bits 必须等于 WB PTE 才算正确。正式资格应结合有效 PAR/PTE/MAIR、CPU 配置及 barrier scope解释属性，当前 host AT peer 固定的低位值不能替代真机证据。

## IOBuffer cache flag 不能自动填补 aperture 缺口

[IOBufferMemoryDescriptor.cpp:176](${HOUJI_PORT_ROOT}/.cache/ios16-reference/dxb-ios/xnu/iokit/Kernel/IOBufferMemoryDescriptor.cpp:176) 的 `initWithPhysicalMask` 将物理 mask/alignment 提升到 CPU page，contiguous/physical-restricted 路径分配 wired kernel backing。Native 当前使用 `kIOMemoryMapperNone|kIOMemoryPhysicallyContiguous`，不使用 constructor cache flag，随后显式 `makeWriteCombined`。

该构造器约 294 行把 `kIOMapCacheMask` 转成 memory-entry cache mode；约 392 行对带 cache flag 的 buffer 逐 CPU page 预触。随后 IOMemoryDescriptor 的 `vmProtForCacheMode`／memory entry 路径进入 VM 属性更新：

1. [IOMemoryDescriptor.cpp:360](${HOUJI_PORT_ROOT}/.cache/ios16-reference/dxb-ios/xnu/iokit/Kernel/IOMemoryDescriptor.cpp:360)：WriteCombine 对应 `VM_WIMG_WCOMB/MAP_MEM_WCOMB`；InhibitCache 对应 `VM_WIMG_IO/MAP_MEM_IO`，后者不是所需 Normal NC。
2. [vm_user.c:2661](${HOUJI_PORT_ROOT}/.cache/ios16-reference/dxb-ios/xnu/osfmk/vm/vm_user.c:2661)：`MAP_MEM_ONLY` 转 WIMG 并调用 `vm_object_change_wimg_mode`。
3. [vm_object.c:7247](${HOUJI_PORT_ROOT}/.cache/ios16-reference/dxb-ios/xnu/osfmk/vm/vm_object.c:7247)：逐非 fictitious object page 调同一个 `pmap_set_cache_attributes`。

因此“改成 constructor WC”可以改变 VM object/view 属性管理方式，**没有证据说明它会新增 SWEET 缺失的 aperture 更新**。也不能把 InhibitCache 当作 Normal NC 的同义词。

[NativeAdrenoMemory.h:83](${HOUJI_PORT_ROOT}/native/gpu/xnu/Adreno740/NativeAdrenoMemory.h:83) 仍写“every CPU mapping”以及后续 maintenance 不需工作，字面上比实际实现宽；应理解为受管理映射和 caller alias 契约，而不是当前已证明 all aliases NC。`.cpp` 的 aperture 注释更准确。

## 3 个 NC BO 的 CPU16K 边界

| BO | GPU logical | CPU owned | CPU pages | GPU4K logical pages |
| --- | ---: | ---: | ---: | ---: |
| HFI | 73728 | 81920 | 5 | 18 |
| log | 65536 | 65536 | 4 | 16 |
| VRB | 4096 | 16384 | 1 | 1 |
| 合计 | 143360 (140 KiB) | 163840 (160 KiB) | 10 | 35 |

cache 属性、CPU ownership、初始 cache handoff 与最终恢复都必须覆盖这 **10 个完整 CPU16K 页面**；不能只覆盖 35 个 logical GPU4K leaves。HFI 的 8192-byte CPU padding、VRB 的 12288-byte CPU padding仍属独占 owned backing。GPU 映射范围继续只能由 logical range 决定，不能顺带映射 rounded tail。

## 最小下一层：先建立 CPU alias lease，不执行 firmware

以下是资格条件建议，当前 r149 没有因此获得 DMA-ready：

1. **固定资源身份与拥有权。** 保持独立 backing／完整 CPU16K span，PA36/full-owned 边界和不重叠校验；不导入用户内存、不暴露 client map、不复用 r148 或已有 quarantine BO。把 descriptor、known aperture 和其他允许访问的 alias 放进同一生命周期 ledger；未知 alias/access owner 就保持 inactive。
2. **显式完成旧 WB→NC 交接。** 在设备引用为 0、无 CPU 并发写、旧 WB view 仍有效时，对完整 owned backing 做真实 PoC CleanInvalidate 与完成屏障；调用合法 pmap/VM 属性路径，验证元数据及每 GPU4K 的实际 descriptor R/W AT/PA/有效属性。确认实际 XNU 的 high-PA pmap cache 同步也指向原物理页，而不是只相信返回码。
3. **若保留 dormant WB aperture，禁止 DMA lease 期间的 WB 数据访问。** NC descriptor 是唯一 payload/header/log/VRB 访问 view；禁止通过 phystokv 的 memcpy、zero、dump、poll/readback 或另建 WB view。AT 观察不是数据解引用；cache maintenance 也不能用作“已经允许 WB 数据访问”的理由。所有可能访问者、后续 map 创建和属性改变必须受同一拥有权控制。仅 `deviceReferences()` 或一次 AT 不能证明整个 lease 无旁路访问。
4. **保持 NC 也需要的顺序。** volatile 只约束编译器访问，不建立 DMA 可见顺序；NC 不自动提供 packet payload→write index、read index→CPU消费 的发布／获取契约。只能接受实际源码和目标平台支持的 cache/barrier domain，记录有效 SH/NS/权限/MAIR。这里只界定 RAM 资格，不在此增加 doorbell、IRQ、SCM、TTBR 或 firmware 执行。
5. **退出必须是真实 quiescence 后恢复。** 所有设备访问结束且引用退役、CPU 访问仍被控制后，才允许恢复默认属性与完整相关 cache/TLB 状态；再次验证实际映射再交还 VM。属性或 owner 不确定就保留 quarantine，不能把 failed release 记成已释放。

这条 mixed-alias lease 路线的优势是无需先改变全局 aperture；缺点是当前 Native API 没有证据表明它控制了所有别名访问者。它是可进一步做 CPU-only 架构资格研究的最小候选，**不是批准当前对象 DMA 的快捷检查**。如果无法让调用范围和 VM 生命周期共同保证这份 lease，应使用下面更强的方案。

若无法证明访问 lease，更强的备选才是为确实拥有的完整 CPU16K pages 建立受内核管理、可安全逐页更新的 aperture，并保证所有可访问 CPU aliases 有兼容属性及完整 cache/TLB 生命周期；**本报告不建议现在盲改全局 pmap/physmap**。当前 non-PPL aperture 可为 32 MiB block 或 hint group：不能只 define `__ARM_PTE_PHYSMAP__`，因为 [pmap_pt_geometry.h:546](${HOUJI_PORT_ROOT}/.cache/ios16-reference/dxb-ios/xnu/osfmk/arm/pmap/pmap_pt_geometry.h:546) 的 `pmap_pte` 不接受 block，aperture 更新还拒绝 hint；也不能改整 32 MiB block 影响其他 VM 页。任何可用方案都需要合法 split／hint处理、架构规定的属性转换与 TLBI、邻页不变、失败保留和释放恢复。这里不写实现，不声称已有支持。

## 上游原始依据，以及不能直接移植的部分

- Arm 的 [Armv8-A memory model，section13](https://developer.arm.com/-/media/Arm%20Developer%20Community/PDF/Learn%20the%20Architecture/Armv8-A%20memory%20model%20guide.pdf?revision=58b1dd0a-3800-4218-b21a-f95a0332034c) 建议同 PA 的虚拟别名具有兼容 memory type/cacheability/shareability；不兼容属性会影响 coherency/性能。这支持审计有效属性，不支持从一次 AT 推导 DMA 协议正确。
- Arm 的 [EffectiveShareability 原始伪代码](https://support.arm.com/documentation/111108/2026-09/Shared-Pseudocode/shared-translation-attrs) 对 iNC/oNC 返回 OSH，补足上面原始 SH 编码与有效属性的区别；不会把 NC memory 变成硬件 cache-coherent DMA。
- Linux v6.6 [dma_direct_alloc](https://github.com/torvalds/linux/blob/v6.6/kernel/dma/direct.c#L281-L305) 的 noncoherent remap 路径先清理 kernel alias，再 [vmap remap](https://github.com/torvalds/linux/blob/v6.6/kernel/dma/remap.c#L22-L60)，返回新 view；该路径并没有一并改掉全部 linear aliases。这说明 dormant WB mapping 的存在本身不能直接判死。
- Linux arm64 [arch_dma_prep_coherent](https://github.com/torvalds/linux/blob/v6.6/arch/arm64/mm/dma-mapping.c#L35-L40) 使用 kernel page address 做 PoC cache clean；[pgprot_dmacoherent](https://github.com/torvalds/linux/blob/v6.6/arch/arm64/include/asm/pgtable.h#L573-L582) 选择 Normal NC；[dma_pgprot](https://github.com/torvalds/linux/blob/v6.6/kernel/dma/mapping.c#L419-L427) 根据设备 coherency/属性选择。这是完整内核 DMA 分配契约的一部分，不能只复制某条 clean 指令给当前 XNU 宣告相同保证。
- Linux [DMA mapping guide](https://docs.kernel.org/core-api/dma-api-howto.html#types-of-dma-mappings) 区分可并行访问的 coherent memory 与需要显式 ownership/sync 的 streaming memory；coherent memory 仍需要 barriers，混用 CPU/device writer 的 cache line 需要额外控制。[memory barriers 的 DMA/cache 章节](https://docs.kernel.org/core-api/wrappers/memory-barriers.html#the-effects-of-the-cpu-cache) 说明普通顺序屏障不能替代非一致 DMA 所需的 cache maintenance。
- Apple [IOBufferMemoryDescriptor 原始源码](https://github.com/apple-oss-distributions/xnu/blob/xnu-8792.81.2/iokit/Kernel/IOBufferMemoryDescriptor.cpp) 可作接口实现对照；本报告针对实际 local tree 逐行检查，不假定这个 Apple tag 与本地修改树逐字节相同。

## 为什么 r148 的 WB 写回成功不能直接推广到 HFI live

实际记录：[native-ios-r148-result.json](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r148-result.json:9)，其 30–83 行明确限制为有限 CM3 程序、单个 GPU4K 映射、CPU16K backing 和实际隔离后 CPU readback。原始 [XnuLog.txt:569](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r148/XnuLog.txt:569) 为 complete1/safe1/positive1/negative1，577 行 data BO PA `8c5cf0000`、logical4096/owned16384、PAR Attr FF；575 行观测 `a750cafe`、checked1024/padding1。

证据链是：CPU 独占 WB backing → 发布前 data full-owned CleanInvalidate、table/zero Clean → device references 持有 → 有限 GMU 访问与真实 precise negative fault → reset/context/stream/TLB/fault 完整退役和 TCM/control恢复 → **此后** CPU full-owned Invalidate → volatile 验证 1024 words、padding/zero/table tail → 恢复 CPU marker并 Clean。对应 Native 发布在 [ExternalCanaryProbe.inc:237](${HOUJI_PORT_ROOT}/native/gpu/xnu/HoujiGpuExternalCanaryProbe.inc:237)，CPU finish 在 [293 行](${HOUJI_PORT_ROOT}/native/gpu/xnu/HoujiGpuExternalCanaryProbe.inc:293)。

这是一条明确分阶段 ownership 的有限 streaming writeback 证据，不要求 CPU 与 GMU 同时修改共享 cache line；也没有验证 NC descriptor 与 WB alias 并用。它证明这次单4K高PA读写／fault／退役／invalidate后的正确值，不能证明 stock firmware、17 个 HFI queue、持续 log/VRB、异步 producer/consumer、IRQ 或 CP/图形路径正确。

当前 [giulia_gpu_hfi.h:35](${HOUJI_PORT_ROOT}/native/gpu/vendor/Ace5Gmu/giulia_gpu_hfi.h:35) 的队列读写只使用 volatile 和 barrier callback，没有 WB cache sync；header 为 48 bytes、read/write index 为相邻 h[10]/h[11]，ring 起点848也不是通常64B line边界。以64B cache line为例，多处 queue/header/ring 会共享 line，两个主体更新不同 DWORD 不等于缓存独占；实际 line size仍须现场CTR确认。简单把HFI全改WB再周期 Clean/Invalidate，可能把对端的新字段覆盖或消费旧内容。不能把 r148 的“device完全隔离后才 invalidate”套到持续 live HFI 中，更不能把DSB当作cache清理。

同理，后续若独立的有限 NormalNC canary 对 fresh data/zero full-owned16K 完成 CIVAC/DSB、仅访问 NC descriptor、table 保持 WB、aperture 仅 AT、持有 backing 到 reset，它所能取得的仍是**该有限 NormalNC ownership/cache 路径的资格**。没有执行 HFI 或证明异步队列，不能把该结果重新命名为 live HFI 正确；本报告不安排或新增这类执行。

## 本轮关键输入 SHA-256

```text
actual pmap.c                    d7beb9d9d95fce0b5e5f2b504c8f9d63481f20e52dbc5ca5277a7e24d58af204
actual arm64/proc_reg.h          d1ee94a900c134ebcc2bb12f3e1a6b6a9dfbbf6a543bfb71a812f8b16cf50116
actual arm_vm_init.c             5e49cc32de4b60922ac23171027343839f1f9e386eceaa0f127538facd5c71ef
actual IOBufferMemoryDescriptor  606d18527db26310912b88d8c1ce29cfa853d9b7e6914c837a8c5ecdcd5869a4
actual IOMemoryDescriptor        9963ef1a82cfe5e1bfca797c17c686c54eeea6e631ed349babfc80ac8c824379
actual vm_object.c              7fad002b17eb966e476d5a9361b2cbbcf4ef310299da83970092b732874a77a1
actual SWEET.h                  248c4180d0ba6ef834c00f660269e9f2ea6bdb27f69e4e20f73cf947aaf1c8a2
NativeAdrenoMemory.cpp           d78c51e6e465289c8e5957a2d9a8266445502a7801be9b2a42cd892a4ff82fc1
NativeAdrenoCpu.cpp              55a5d49eb20c62d4f7da0d87dcc5dc117021965845b35ef8873189099c99aa94
HoujiGpuFirmwareMemoryProbe.inc  7b7a537ae7b84850ba7993d7e4b24a854d8ed867515a164b288080805082da05
giulia_gpu_hfi.h                 26683bb33cb70fc05a877f2cff41956e46e5dddc87ad94a88e091c4b34f323ce
r148 result JSON                daf843a53c53d2659f55c073e4fcff389711cfc74385268d4720b1aee356be1f
r148 XnuLog.txt                 ab08520557e01caedb9227f345e521f6bfd4c387df903e15a9899af05df24980
r149 result JSON                db8a54c47d9eb9a80e322cf9dece72c689e683bbd02c46839e412925c14f5813
r149 XnuLog.txt                 28cbc5efec5eafffd1117fa67165ed1f672dc6b9137315063d6056cb3b0af961
```

旧 memory 条目停在 r146/r147，未用来推导本次硬件结果；r148 和新增 r149 CPU-only 结论已用上述持久结果和日志重新核实。
