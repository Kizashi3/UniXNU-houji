# houji A750：XNU 后端接入边界与复用入口

记录时间：2026-10-25。目标为用户提供的 iOS 16.7.16 / 20H392、Darwin 22。
本次只读核对参考源码并记录实施顺序，没有修改内核、编译上层或访问手机。

r131 已证明本机 **UEFI 下**的 CP_INIT 和两次独立 GPU 写回，尚未证明图形绘制、
CP timestamp fence、XNU GPU 后端或桌面加速。证据为
[结果清单](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r131-result.json)
与 [native 日志](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r131/UniXNU.log:2783)：
`code=0 phase=8 kicks=3 init-idle=1 writebacks=2 C0FFEE00/C0FFEE01 RPTR/WPTR=20 IRQ=0 fault=0`。
native payload 402648 字节，CRC32 `0d60c25c`；XNU committed log 本轮未产生，不能混称。
普通停止的首末采样均 `valid=3f failed=1`：HALT3 后 SQE 读回 1，其他五项静止判据通过；
随后实际 CM3 reset 和 GX/GBIF client/arb ACK `1/3/3` 完成隔离。资源仍保留到平台复位，
没有把普通 HALT3 判据标为通过。

后续 r132 重复通过两次写回及 PAS13 能力查询；r133 已完成本机原始签名 ZAP 的
真实 PAS13 认证，再由 `CP_SET_SECURE_MODE(0)` 完成 idle，实际 `TRUST_CNTL` 1→0。
但固定 32×32 CP_BLIT IB 提交后仍 CP/GPU idle 超时：外层 RPTR/WPTR=16、
`RBBM_STATUS=00800005`、IRQ/CP fault=0，未取得像素读回。外层指针一致不证明 IB
内部完成，真实绘图及 XNU/Metal 加速仍未通过；详见
[r133 结果](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r133-result.json)。

r134 的可选进度 IB 为 287 DW，只有首标记写回，mask=1；实际隔离后红像素为 0，
其他保护内容完整。它只定位到“首标记写后 WAIT_MEM_WRITES → 首次 THREAD_BOTH →
次标记”的区间，不能证明 THREAD_BOTH 已执行或直接认定 BV 等待为根因。
IB1 remaining=`1f` 不是 SQE PC，不能把初始长度与 remaining 相减当作退休指令位置。
两阶段 20 项原始读取均有效，`CP_STATUS_1=8001040a` 保留为未解码原值。
详见[r134 结果](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r134-result.json)。

SMMU FSR=`400` 只有 FORMAT 字段为 2，实际 fault mask `c00001fe` 为零；
固定 [Linux arm-smmu.h:200](https://github.com/torvalds/linux/blob/21a7f44fd0765fcc5194130b28767786eba1d1e7/drivers/iommu/arm/arm-smmu/arm-smmu.h#L200)
分离 FORMAT 与 TF/SS 等故障位，
[fault handler:467](https://github.com/torvalds/linux/blob/21a7f44fd0765fcc5194130b28767786eba1d1e7/drivers/iommu/arm/arm-smmu/arm-smmu.c#L467)
在没有故障位时直接返回 IRQ_NONE。因此本次 FAR/FSYNR 不能解释为新发生的转换故障，
更不能据其原值添加映射。

BV 上下文假说有具体机制支持：固定 Mesa `adreno_pm4.xml:2103–2109` 说明 bit27
改变会隐式同步线程并在 BV 触发 skipsaverestore；`2309/2310` 分别定义 bit27 的
CONCURRENT_BIN_DISABLE 和 bit31 的显式 SYNC_THREADS，二者不能混称。
[Linux a7xx_submit:499](https://github.com/torvalds/linux/blob/21a7f44fd0765fcc5194130b28767786eba1d1e7/drivers/gpu/drm/msm/adreno/a6xx_gpu.c#L499)
在外层先发 SYNC|BR，首次上下文路径还有 BOTH、RESET_CONTEXT_STATE、BOTH、LRZ flush
及 SYNC|BR；当时计划由 r135 独立验证此源支持的外层差异；已完成结果见下一节。

## r135 实际已通过的入口

r135 已补齐固定 Linux 的 25 DW 外层首次上下文初始化；动态根为本轮实际构建、
实时 bank0 TTBR 和固定 ASID `751` 的精确匹配。之后同一 287 DW 进度 IB 实际完成，
全部 1024 个 RGBA8 红像素、CRC `e843b26a`、8 个进度标记和其他保护字节均通过。
CP 共 6 次 kick，最终 RPTR/WPTR=`51`，两次独立 canary 为 `c0ffee00/c0ffee01`。
相同图像 IB 在 r134 仅首 marker 成功，增加外层上下文后通过；这支持首次上下文是
本轮修复，但不把旧 remaining/status 原值当作已经解码的执行 PC。

[独立镜像/源码/像素审计](${HOUJI_ARTIFACTS}/native-port/evidence/gpu-known-image-r135-independent-audit.json)
还从实际 Android image 内解压并提取 FAT 中的 app，逐项匹配 qualified binary 及全部
585 个冻结源码文件；确认 CPU 只初始化输出为 `6d` 并读回，不会填入红色期望值。
这是专用 UEFI 2D 渲染资格，尚未验证 shader、真实 timestamp fence、XNU 或 Metal。
普通停止仍有 SQE exact3 未通过的问题，结束由实际 CM3 reset 与 ACK `1/3/3` 隔离，
资源保留到平台复位。

下一步是 XNU 自有内存及板级 provider；不会以 UEFI 指针作为已完成所有权转移。
当前 XNU 的 16 KiB CPU 页与参考的 4 KiB CPU 页存在确定差异，GPU SMMU 仍用 4 KiB 叶。

## 固定参考与实际实现

| 组件 | 固定提交 | 本文采用范围 |
| --- | --- | --- |
| [Adreno740，原 NativeAdreno](https://github.com/UniXNU/Adreno740/tree/4e0314df8ad29d52f6fa3f9383a540adcd618b87) | `4e0314df8ad29d52f6fa3f9383a540adcd618b87` | BO、4K VM、ring、submit、CP fence、IOKit 用户客户端；板级参考是 sheng/A740 |
| [AdrenoMetal，原 NativeMetal](https://github.com/UniXNU/AdrenoMetal/tree/454ff2ce83766ce7b3e0f355e83f1d72907708b3) | `454ff2ce83766ce7b3e0f355e83f1d72907708b3` | 正式 Objective-C 前端、metal2vulkan 桥、GPU scanout copy；另有离线资格组件 |
| 已有 iOS 16 候选的 NativeAdreno ABI 输入 | `b686b9054f57d393c80195b82568a09f8ca106a2` | 既有构建锁定版本，不能静默改 ABI 后复用旧二进制 |
| 已有候选的 Mesa / Turnip Darwin | `85fda3b36405bcaea8bffc64aa4f2651dc90770d` 加已记录九个补丁 | NativeAdreno ABI v1 transport，设备表含本机 `0x43051401`；设备表存在不等于已运行 |
| GopFramebuffer wire | `8666a9950c9699b368931d18cac92c0fdb2ce9c0` | 固件 scanout 交接协议，不是完整显示控制器或 vblank 驱动 |
| 本地 sheng 板级快照 | `251b291adf941b9953fe3ae66a808b9b626e164d` | iPadOS 17.7.11 / 21H461 的组合配置，不能复制其原始地址/ABI 到 20H392 |

本地参考目录为
`${HOUJI_ARTIFACTS}/native-research/nativeadreno-reference/`
与 `adrenometal-reference-20261025/`。本轮通过 GitHub 固定 ref 再取核心文件核对 blob。
`NativeAdrenoPublish.cpp:47` 的本地快照仍写 `drivers/NativeMobileDisplay`，固定 ref 改为
`drivers/GopFramebuffer`；`NativeAdrenoAccelerator.cpp:4` 的本地注释仍写 `NativeMetal`，
固定 ref 改为 `AdrenoMetal`。这两个文件的差异均仅该条路径注释，行号和实现不变。
下方摘要把本地 SHA-256 与固定 ref 的 Git blob 分开列出。

**真实后端与离线组件必须分别使用。**

- `NativeAdrenoMemory/VM/Ring/Submit/UserClient/Publish` 有真实资源、硬件提交与完成代码，
  可以作为 A750 后端的内核组件。
- `NativeAdrenoService.cpp:65` 的通用服务仍默认 `gpu_context_ready_=false`，
  `:326` 的 ring/fence/SQE/pwrup IOVA 为 0，`:420` 明确拒绝缺 GPU context 的 CP 路径。
  它不是安装后自动工作的 sheng/A750 provider；应实现 houji 板级所有者后接真实组件。
- [NativeOfflineAccelerator.cpp](https://github.com/UniXNU/AdrenoMetal/blob/454ff2ce83766ce7b3e0f355e83f1d72907708b3/NativeOfflineAccelerator.cpp#L1)
  只有原 IOAcceleratorES 基类的未发布生命周期资格；`OfflineMetalWire.h:2` 也明确是离线传输。
  它们不提供 BO、SMMU、CP、fence、Metal device 或硬件加速。
- `OriginalGPUProviderABI.h` 的 opaque IOGPU/slot 声明是 ABI 仪器，不是系统驱动 API，
  不能用其 600 字节占位私有状态拼出可工作的 provider。

## 可复用接口与 A750 适配点

下表行号对应上述本地固定快照；GitHub 链接固定到提交。

| 层 | 入口与源码 | 可复用内容 / houji 必须补齐 |
| --- | --- | --- |
| 生命周期 | [NativeAdrenoGpu.cpp:12](https://github.com/UniXNU/Adreno740/blob/4e0314df8ad29d52f6fa3f9383a540adcd618b87/NativeAdrenoGpu.cpp#L12)，`NativeAdrenoGpuBoard` | 注入 `reserve / bootGmu / programSmmu / quiesce`，失败后保留资源。该类本身不拥有电源/时钟；`Ring::attach` 与 `CpInit::run` 也不能替代本机明确的 SQE1 顺序。 |
| CPU 页与缓存 | `NativeAdrenoCpu.cpp:27/71/110` | `NativeAdrenoQueryCpu4K`、PoC cache maintenance、pmap 页属性；运行中检查 `PAGE_SIZE`、`page_size`、kernel map 和 TG0/TG1 均为 4K。需要在实际 Darwin22 内核验证符号/类型及物理 aperture。 |
| BO | `NativeAdrenoMemory.cpp:97/176/239/275/287` | `allocate/importTask/release/holdForDevice/publishForDevice/acquireDeviceWrites`；以 IOBufferMemoryDescriptor 或调用任务的 IOMemoryDescriptor 真正分配/prepare/pin。先用小 BO，不把 A740 的 1536 MiB pool 默认值搬来。 |
| 4K GPU VM | [NativeAdrenoGpuContext.h:37](https://github.com/UniXNU/Adreno740/blob/4e0314df8ad29d52f6fa3f9383a540adcd618b87/NativeAdrenoGpuContext.h#L37)、`GpuContext.cpp:11/90/105/117`；`NativeAdrenoVm.cpp:92/225/262` | `bringUp`、`NativeAdrenoGpuContextBringup/Buffers/Vm`、`attach/map/unmap`。保留实际 bank/ASID/slot/SID、TTBR 根、全图和 alias 检查；GMU SID5/bank2 与普通 GPU SID0+LPAC SID1/bank0 分离，secure SID2 及其他流保持 FAULT。 |
| VM 可见性 | [NativeAdrenoVm.h:16](https://github.com/UniXNU/Adreno740/blob/4e0314df8ad29d52f6fa3f9383a540adcd618b87/NativeAdrenoVm.h#L16)，`Vm.cpp:321/331/342` | `invalidateTlb/publishMapped/acquireImported`。map/unmap 需要真实主设备静止；引用计数不是 fence。导入 IOSurface 后仍处理实际 cache 属性与 CPU/GPU 交接。 |
| Ring / fence | [NativeAdrenoRing.cpp:124](https://github.com/UniXNU/Adreno740/blob/4e0314df8ad29d52f6fa3f9383a540adcd618b87/NativeAdrenoRing.cpp#L124)，`:167/202/206/250/268` | `attach/submit/submitFramed/observeFence/wait`。ring 发布后再 WPTR，CP event timestamp 写 `memptrs+4`，CPU acquire 后实际观察该值；r131 的 CP_MEM_WRITE canary 还不是这条 fence 的实机验证。用户 IB 使用 BR/BV framing，CP_INIT 用 plain submit。 |
| CP 初始化 | [NativeAdrenoCpInit.cpp:25](https://github.com/UniXNU/Adreno740/blob/4e0314df8ad29d52f6fa3f9383a540adcd618b87/NativeAdrenoCpInit.cpp#L25)，`:29`；`NativeAdrenoPwrup.h:32/35` | 复用包编码和 list pack；A740 `meInitMask=0x14b` 不能覆盖本机 r131 已验证的 `0x94b`。`buildA740` 的寄存器列表、固定 SQE 字节数和 IOVA/GMEM 范围都需要 A750 配置，不能复制常数后宣称兼容。 |
| 提交生命周期 | `NativeAdrenoSubmit.cpp:38/75/155/166/180/211/267` | `attach/submit/wait/retireCompleted`，提交前 cache/TLBI，完成后 retire BO 引用和 acquire 导入缓冲；未知提交结果保持 poison/保留资源，真实 reset 后才能回收。 |
| 内核/用户 ABI | [NativeAdrenoABI.h:13](https://github.com/UniXNU/Adreno740/blob/4e0314df8ad29d52f6fa3f9383a540adcd618b87/NativeAdrenoABI.h#L13)，`NativeAdrenoUserClient.h:64/68/88/104/116` | 固定 ABI v1 方法 1..16：query、BO、map、submit、wait、timestamp、status、queue、CPU view、device info、任务内存导入。`importBo` 必须由 wrapper 传真实调用 task；不是任意 PA 导入。DeviceInfo 的 GMEM/UBWC/VA/芯片事实由 A750 实际来源提供。 |
| 真正服务发布 | [NativeAdrenoPublish.cpp:732](https://github.com/UniXNU/Adreno740/blob/4e0314df8ad29d52f6fa3f9383a540adcd618b87/NativeAdrenoPublish.cpp#L732) | `native_adreno_publish(vm,submit,ring,clock,timer,info,input_bits,output_bits)`，仅在资源和真实提交/fence 已就绪后调用；对象须终身有效，并由驱动 gate 序列化。先用于受限测试任务。 |
| Metal discovery | [NativeAdrenoAccelerator.cpp:16/49](https://github.com/UniXNU/Adreno740/blob/4e0314df8ad29d52f6fa3f9383a540adcd618b87/NativeAdrenoAccelerator.cpp#L16)，`NativeAdrenoMetalPlugin.mm:1/30/51` | `AGXAccelerator : IOAcceleratorES`、`native_adreno_accelerator_allocate()`；在真实 IOGPUFamily metaclass 加载后初始化。原 discovery 查 `MetalPluginName` 并调用 bundle 的 `initWithAcceleratorPort:`，不是注册同名空 service 就能加速。 |
| Turnip transport | `mesa-adrenometal-pin-85fda3b3/src/freedreno/vulkan/tu_knl_darwin.cc:105/136/365/420/482` | 现有 ABI v1 Darwin KMD 的查询、BO/导入/CPU map/提交/fence 可复用；默认 IOAcceleratorES/open type `0x4147`，须验证实际 IOKit 调用与任务权限。无需在底层每次变化后重编前端。 |

GPU context 的 A740 固定配置位于 `NativeAdrenoGpuContext.h:16`：
SQE `0x100000`、ring `0x200000`、memptrs `0x300000`、pwrup `0x301000`、scratch `0x302000`、
aperture 2 GiB、SQE buffer `0x13000`。它们是参考板布局，不是 houji 的既有地址证明。
本机实现应依据自己的固件长度、GMEM/UCHE 和所拥有的 DRAM 建立独立配置。

## 已有显示路径与 Darwin22 缺口

真实桌面链是 **Metal composition → 实际 GPU 提交/完成 → IOSurface / 显示帧交接 → GPU copy 到 scanout**。
前端成功创建 MTLDevice 与最后一帧实际出现在屏幕上，是两个验证点。

可复用的显示协议在
[NativeGOPWire.h](${HOUJI_PORT_ROOT}/out/adrenometal-ios16/source/NativeMobileDisplay/NativeGOPWire.h:4)：
`MODE / PRESENT / WAIT_SWAP / COMPLETE_SWAP`，mode 固定版本、BGRX8888、宽高/字节 stride/范围；
等待返回 frame sequence 与调用任务映射，完成只能在真实 GPU copy 后提交。
`NativeAdrenoPublish.cpp:47` 把它转发为 `0x7000..0x7003`，scanout memory type `0x5343`；
此转发本身不碰 GPU。

[GpuScanoutClient.h:41/69](${HOUJI_PORT_ROOT}/out/adrenometal-ios16/source/AdrenoMetal/GpuScanoutClient.h:41)
通过 `open/serveOne` 获取帧、调用 GPU presenter 并回报 swap；
[GpuScanoutPresenter.h:30/45/52/72](${HOUJI_PORT_ROOT}/out/adrenometal-ios16/source/AdrenoMetal/GpuScanoutPresenter.h:30)
用 `newBufferWithBytesNoCopy` 导入源帧和 scanout，Metal blit 后 `waitUntilCompleted`。
它没有 CPU 像素复制回退，也不替代面板/刷新率驱动。houji 现有显示驱动要提供真实 frame ownership、
stride、可写 scanout 映射与完成交接，不能照抄 sheng 的帧缓冲地址。

Darwin22 仍需逐项完成以下实机/目标 ABI 验证：

1. **内核 ABI 和资源。** 在目标 XNU 头/符号上验证 IOBufferMemoryDescriptor prepare/complete、
   IOMemoryDescriptor task wiring、pmap/cache 接口、4K page ABI。现有 UEFI 实验页没有这些 XNU 所有权。
2. **原基类。** `OriginalAcceleratorABI.h:3/11` 原先只资格化所提供的 iOS17 基类。
   本轮已在 20H392 原始 IOGPUFamily 中独立确认最薄 IOAcceleratorES 的 136 字节/168 槽布局，
   详见下方实际二进制证据；实际重建 prelink 的符号绑定、原 mod_init 的加载顺序和运行实例仍须验证。
   opaque IOGPU 则确有 704/736 字节及 214/215 槽差异，不能沿用 iOS17 声明。
3. **用户态 Metal。** 已有 iOS16 patch 接受 `_MTLDevice` 的 528/536 字节参考布局，
   禁用 iPadOS17 固定 QuartzCore 地址并移除 discovery 的 A740 raw-PM4 自测。
   这仍需要本机 runtime 类布局、selector、bundle discovery 与插件初始化验证。
4. **用户客户端与进程。** query/device-info/BO/import/CPU-map/submit/wait 要在实际任务里运行。
   原参考的 AGX 类名、selector tunnel 和平台 sandbox 适配不是 A750 硬件初始化代码，
   不在 provider 初期引入更宽进程授权；先使用指定探针，后验证 backboardd 自己的调用路径。
5. **图像和持续呈现。** 已有候选的 688 项非可选导入闭包通过，只证明符号可满足。
   还要实际 compute/triangle/IOSurface GPU readback、单帧 scanout copy、持续滑动、上下文丢失和恢复。
   当前 clients 文件只列 `adrenometalprobe`；不能直接把候选当桌面发布版本。

原候选和边界详见 [adrenometal-ios16.md](adrenometal-ios16.md)，不需要为本轮研究重编它。

## 最小 houji provider 实施顺序

1. **完成当前 known-image 资格。** 在 r131 已工作的 UEFI ring 上使用固定的真实 CP_BLIT
   小图命令、不同 CPU 哨兵、逐像素 GPU 输出与边界检查；单独记录图像结果与 fence。
   不用 CP_MEM_WRITE 把期望像素逐个写入后称为图形渲染。r133 超时后，r134 增加实际进度采样，r135 加入固定外层首次上下文并通过了小图资格。
   该项已完成；实际 timestamp fence 仍需独立验证。
2. **XNU 板级所有者与电源。** 新建 houji provider/board ops，独占映射真实 GPU/GMU/SMMU
   窗口，实测 reset/clock/regulator/HFI/OOB 顺序。将 UEFI 已验证的 A750 顺序移植为 XNU 实现；
   不调用失效的 gBS、OEM UEFI protocol 或临时页表函数。先保持服务未发布。
3. **XNU 自有 4K SMMU 与 BO。** 用 XNU descriptor 分配并 pin GMU 固件、SQE、GPU/GMU
   表、ring、memptrs、pwrup 和小图目标。重建 bank2/SID5 与 bank0/SID0+1 的独立所有权和
   native4K 图，保持其余 FAULT；验证真实 TTBR、属性、alias、TLB 与每次映射的静止条件。
4. **Ring / CP / 真 fence。** 接 `NativeAdrenoRingIo/Cache/Clock` 与 A750 CP_INIT profile，
   实际 SQE1→CP_INIT→完成；在 XNU 内重做两 canary、小图和 CP event timestamp fence。
   先可有界 polling，之后接本机真实 GIC/IOWorkLoop fault/completion source；IRQ 不能代替 fence 值。
5. **提交与发布。** 接 `NativeAdrenoVm`、`NativeAdrenoSubmit`、UserClient v1，验证任务内 BO
   生命周期和故障 poison/reset，然后才调用 `native_adreno_publish`。先跑 query/BO/submit/wait
   探针，返回真实 chip ID/GMEM/UBWC/VA 与 status。普通 HALT 的精确读回问题仍独立待适配；
   未证实普通停机前沿用已验证的 reset+三 ACK 故障隔离，资源不能提前回收。
6. **最后接正式前端与显示。** 资格化 Darwin22 原 IOAcceleratorES ABI，再启用已有
   AdrenoMetal/Turnip 候选的指定探针；通过 compute/render/import 后接 houji frame handoff，
   验证实际 GPU scanout copy，再逐步启用 backboardd 和持续桌面测试。

**UEFI 资源不能直接算作 XNU 所有。** r131 中低 RAM、FAT/BootServices 分配、CPU 映射、
device TTBR 和固件协议均属于该次 UEFI 诊断实例；其 CPU/PA/IOVA 数值相等不能证明
XNU VM 已保留、wire、cache 属性一致或可退役。当前实验还在返回 Recovery 前执行真实隔离。
默认方案是在 XNU 自己的资源管理内重新分配和重建；若以后设计保留 handoff，必须另行证明
loader/ADT reserved-memory、XNU VM 排除、物理和缓存视图、设备 pin/所有权转移及 reset 生命周期，
不能只传一个 UEFI 指针或复制 TTBR 后发布服务。

## 核心来源摘要

以下 SHA-256 为本次实际读取的本地文件；Git blob 是固定 GitHub ref 的内容身份。
两处注释差异已经在前文说明，未修改任何参考源码。

| 文件 | 本地 SHA-256 | 固定 ref Git blob SHA-1 |
| --- | --- | --- |
| `NativeAdrenoGpu.cpp` | `2c3e0238a4fd1be2f5a5224b7ad33b385987b437d27f28e8166406948e48f589` | `ba225cf32ad0102a9d8de03782c300a281de45d6` |
| `NativeAdrenoGpuContext.h` | `077bbedefb96f3086047db931f39beb27b5ad0aaa3a110e4c2dc01caa48fa3c0` | `dbe915aeb3dfef1984d0680c95e1c8229c4ff8f1` |
| `NativeAdrenoCpInit.cpp` | `02bb5791a021ae115b430187291a7de30002c069d1924ef69a9c3282633bbe49` | `23759d2719edbc381987a654788b8781b0e10a92` |
| `NativeAdrenoPublish.cpp` | `1c342a0ebcb68678c2d83c7d0627c55f99bd0d230651f7a1f9ca23fe270d9647` | `d8becdffa6d51f247cf114e5ed16906c3103bfb7` |
| `NativeAdrenoAccelerator.cpp` | `0efc3af57940465f8a25cf9d341631bbd2384cd36532606537c64452bd0767d5` | `0c5c2d086f46f8b61d57e1272fa4192792a47635` |
| `NativeAdrenoVm.h` | `da9bfcef9d5b7231d0143b853cf9de4535df0f749bb0023e2f052bb7823db6fa` | `be6820b83c96e36fe9194a622f18a6f29d94cc6b` |
| `NativeAdrenoMemory.h` | `8137491b5ef2657eb362a4f41cf2c2b8d8cb747fc93d7a63e453194d7c3288cc` | `f91b19ec9365d579558a0e9a802a23549891ea91` |
| `NativeAdrenoRing.cpp` | `dc2c71b8225ec034b800e01d107939fa7d8a8b5335a2337323c016c9e5fc083e` | `1711ea19399c7c725c04e9014fcacdeef9fe41c5` |
| `NativeAdrenoABI.h` | `b5574e34ee3a368616f722f9fa40ea2c87bbc5c03989a299d9d4f954c9f8be70` | `3ca23cd84c0cdd547314d720b4846b131d16b633` |
| `OriginalAcceleratorABI.h` | `211e922f9b760ddec2e3453db6584bac57597b3d39e4bf0d013c1b2debd53365` | `a052b099b0186ce8519fb5e912bac30ef249ec29` |
| `NativeOfflineAccelerator.cpp` | `c9afd3dc3b0924370232f9da04273d5aabe0274f5cd624af65882f3fb7cabe33` | `11f1b9d15faf500358df4313a1b46f3575864cef` |
| `GpuScanoutPresenter.h` | `5a3239c15abb20da6301c3f553415e189b85476b67c5186202f8976d96599049` | `9a9e938b59946f95d00ed33f764d21a2c188e3fa` |

## 20H392 原始 IOAcceleratorES 实际二进制资格

本轮没有使用 iOS17 固定偏移推算 iOS16 地址。直接读取用户 IPSW 的
`kernelcache.release.iphone10b`，核对已提取的原始 decompressed cache，解析实际 Mach-O
load commands、239 条 prelink metadata、内核符号与 IOGPUFamily 内完整 vtable/ARM64 指令。
源 kernelcache 是 Darwin 22.6.0 / `xnu-8796.142.1.703.8~1/RELEASE_ARM64_T8015`。
没有单独的 IOAcceleratorFamily prelink 项；原 IOAcceleratorES 位于
`com.apple.iokit.IOGPUFamily` 65.60.1，SDK `iphoneos16.7.internal`。

完整摘要、输入身份、原始指令字节、条目 hash 和静态验证边界保存在
[ios16-accelerator-abi-audit.json](${HOUJI_ARTIFACTS}/native-port/evidence/ios16-accelerator-abi-audit.json)。
报告 SHA-256 为 `64a279dde147d80bc85ad7770add9ec31d0c0e8fdc2e5219b127f6da247edec1`。

| 直接读取的对象 | 实际身份 |
| --- | --- |
| IPSW 内压缩 KernelCache | 18204358 字节；SHA-256 `2d6a13d040aaf87cec09bb6906d43e9bd8cea951e43d1aa1cd62707dfdc5aaec` |
| 原始 decompressed KernelCache | 50937856 字节；SHA-256 `2ec297bac95bcba01046fd0148e97e7e5885c05a6c18827f39f534ba375c1221` |
| IOGPUFamily 完整 `__TEXT_EXEC` | 153788 字节；SHA-256 `34aea2cba7f617ae031c37411027b34380c68bbe1e1a17d6abbf3bbabcc777cf` |
| IOAcceleratorES 168 槽 vtable | SHA-256 `26c39f9ba38d0ef33aafe5c39cc3d41aec6a9e030e17677e58848790bf146664` |

IOAcceleratorES 的静态结论：

- 实际原 metaclass initializer 以 `name="IOAcceleratorES"`、真实
  `IOService::gMetaClass`、`MOV W3,#136` 调用真实 `OSMetaClass::C2`。
  随后的 IOGPU initializer 则以该 metaclass 为父类；没有从零初始化 data 段猜实例大小。
- 完整 168 槽与目标 cache 中 IOService 的对应槽逐项比较，只有 `0/1/7`
  （两个析构与 getMetaClass）不同，后方 24 字节为零；没有额外操作性 override。
- 两个 protected constructor alias 都是实际 8 条指令：保存 FP/LR，调用真正
  `IOService::C2(OSMetaClass const*)`，安装自己的 vptr，恢复并返回。
  非 deleting destructor 是真实 `IOService::D2` 的 tail branch；deleting destructor
  的实际释放尺寸也为 136。不是按类名或 header 大小推断兼容。

以下地址只属于 **未重建、未 slide 的用户原 cache VM**，用于验证身份，不是可以直接
填入 houji 当前内核的部署地址：

| 对象 | 20H392 原 cache VM 地址 |
| --- | --- |
| `IOAcceleratorES::gMetaClass` | `0xfffffff007bb6448` |
| 实例 vptr | `0xfffffff006fc9e78` |
| protected C2-compatible aliases | `0xfffffff006b45228`、`0xfffffff006b45248` |
| nondeleting D2 | `0xfffffff006b4526c` |
| deleting destructor | `0xfffffff006b45270` |
| getMetaClass | `0xfffffff006b452b4` |
| 真实 IOService 父 metaclass | `0xfffffff0078baf08` |
| 真实 IOService C2 / D2 import 目标 | `0xfffffff007755d74` / `0xfffffff007755da4` |

**可实施的适配是沿用最薄 ancestry 声明，重新生成三个目标绑定。**
`__ZN15IOAcceleratorESC2EPK11OSMetaClass`、`__ZN15IOAcceleratorESD2Ev` 和
`__ZN15IOAcceleratorES10gMetaClassE` 应从实际 houji 重建 prelink candidate 的原 IOGPUFamily
extent/relocation/slide 解析，绑定到该 candidate 的原构造、D2 和 metaclass。
不能使用 `scripts/data/ioaccelerator-base-abi.json` 中的 iOS17 地址，也不能直接使用上表的原 cache 地址
覆盖重定位后的地址。原有 `build-native-adreno-accelerator.py` 的 late 初始化机制可以复用：
移除新类的自动 `__mod_init_func`，在原 IOGPUFamily 已执行其 mod_init、父 metaclass 确实存在后
才初始化新类。新 native kernel IOService 的槽序和对象前缀也须在该最终 candidate 中保持一致。
这一步是内核原类的三个符号绑定适配，不要求重编 Metal 前端。

opaque IOGPU 参考则不能复用：

| 项目 | 20H392 真实原 IOGPU | 现有 iOS17 ABI 仪器声明 |
| --- | --- | --- |
| 实例大小 | 704 (`MOV W3,#0x2c0`) | 736（136 字节父类 + 600 字节 opaque state） |
| 非零虚表槽数 | 214（索引 0..213，后 24 字节零） | 215（索引到 214） |
| pure virtual 槽 | `170,174,189,192,194,195,196,199,201,204` | `170,174,189,192,195,196,197,200,202,205` |

这证明“把 iOS17 opaque IOGPU 声明换成 iOS16 最低版本重新编译”不能取得正确 ABI。
最小 native Adreno provider 应继续使用已资格化的 IOAcceleratorES ancestry 和自己的 UserClient，
不继承未知的 IOGPU 操作尾表。若后续需要 IOGPU 的原生方法，必须单独逐项恢复目标原始签名。

以上是原始二进制的静态资格；没有在设备创建新类实例、发布服务或运行 Metal。
当前候选 prelink 的地址解析与运行中 metaclass 就绪检查仍是接入前的具体工作，不能把本文静态通过
记为已完成 XNU A750 后端。

## r133 当前内核页 ABI：16K CPU 与 4K GPU 必须分别处理

2026-10-26 只读核对的完整证据保存为
[kernel-page-abi-r133.json](${HOUJI_ARTIFACTS}/native-port/evidence/kernel-page-abi-r133.json)
（SHA-256 `2ac1e976a1c4a535f5a03204b91c3b403b39f516b86c95f0c5c3c1a87c455f55`）。
当前 `kernel-r133.macho`、其 policy 和实际 `DEVELOPMENT_ARM64_SWEET` 构建输出的 SHA-256
均为 `e1dae8bf777b4dd4466c40dd7fab2d0a5093c3bd5bbe42ada940cf440f4baf2a`；
该候选仍配置 8 GiB、八核，不能把 UEFI 的 4K 页证据算作该 XNU 的页 ABI。

实际源码 `makedefs/MakeInc.def:64` 选择 `ARM64_BOARD_CONFIG_SWEET`，
`pexpert/pexpert/arm64/SWEET.h:29` 定义 `__ARM_16K_PG__=1`，
`osfmk/arm64/proc_reg.h:1157` 因而选择 `ARM_PGSHIFT=14`。
这不只是源码推断：r133 unstripped 内核的 `_vm_set_page_size`（未 slide 地址
`0xfffffe000742c00c`）实际指令把 `0x4000` 写入 `_page_size`，把 `0x3fff` 写入
`_page_mask`，把 `14` 写入 `_page_shift`。它直接证明本份二进制的正常 VM 初始化赋值；
尚未新增运行中的全局变量读回。

已有桌面 r58 的实际日志 `XnuLog.txt:91/160/355` 记录 `page_bytes=16384`，
但采样源码 `bsd/dev/sweet_sample.c:110–112` 打印的是 `PAGE_SIZE` 宏。
因此它证明 r58 运行代码的编译页单位，不能单独冒充当前内核的 `page_size`、
`vm_map_page_size(kernel_map)` 或每核 `TCR_EL1` 读回。
当前源码选择的 TG0=2、TG1=1 是 16K 配置推导；当前 XNU 的这些寄存器尚未采集。

上游 `NativeAdrenoCpu.cpp:27–43` 要求 `PAGE_SIZE/page_size/kernel_map` 全部为 4096，
并要求 TG0=0、TG1=2，因此原版 CPU4K 路径与本候选不兼容。
不能只移除 gate：其 `:128/145` 用 `physical >> 12` 调用 CPU pmap 页属性接口，
而本机 XNU `pmap.c:10077/10550` 经 `ptoa(pn)` 按 `PAGE_SHIFT=14` 解释页号。
可实施的后续方向是保持已工作的 16K CPU VM，单独适配 CPU 内存层：完整分配、wire、
管理 16K CPU 页，再把物理 span 拆为受限的 4K GPU 叶；缓存属性和回收覆盖完整所有权页。
这不要求 GPU SMMU 改成 16K，也不代表该适配已经实现。首个内核诊断应只读采集实际
页变量、kernel map 和八核 TCR/TTBR/SCTLR，再决定 CPU 内存层的具体边界。

本次还逐 blob 比较了旧候选 `b686b905…` 与当前 `4e0314df…`：
`NativeAdrenoABI.h`、`NativeAdrenoCpu.cpp`、`NativeAdrenoMemory.cpp` 和
`NativeAdrenoUserClient.h` 均逐字相同；两处 accelerator/publish 的变化仅为组件路径注释。
ABI v1、方法 1–16 的 header SHA-256 仍为
`b5574e34ee3a368616f722f9fa40ea2c87bbc5c03989a299d9d4f954c9f8be70`，
与已有 iOS16 Turnip 的 `source-identity.json` 一致。因此此处没有用户态 wire ABI 漂移，
无需为它反复重编前端；先补齐真实 XNU 板级所有权、16K CPU 内存适配和实际 ring/fence。
前文的 20H392 原 IOAcceleratorES 静态资格仍可复用，运行中的类加载、provider 和 Metal
提交验证仍独立待做。


## r136 构建事实：当前内核不是原始 239-kext prelink

对实际 r58、r77、r136 的 `.macho` 和 `.unstripped` 共六个文件逐一解析后确认：
本机沿用的是独立源码内核，不是将 20H392 的原始 239 个 kext 合并进来的 kernelcache。
完整 load command、segment、符号和构建日志证据保存于
[xnu-kernel-prelink-state-r136.json](${HOUJI_ARTIFACTS}/native-port/evidence/xnu-kernel-prelink-state-r136.json)
（SHA-256 `2668b62d3ab5a7166c7f79932cb98ed927b6365716c4c72782b8adb302c73b30`）。
本项是构建文件审计，不代替 r136 的启动或运行期诊断结果。

| 实际运行格式文件 | 字节数 | SHA-256 |
| --- | --- | --- |
| `kernel-r58.macho` | 16741048 | `83d004cc3797718dad97a5ba99c918a0fd872759462ded79c0d76139466dcb5e` |
| `kernel-r77.macho` | 16757536 | `e1dae8bf777b4dd4466c40dd7fab2d0a5093c3bd5bbe42ada940cf440f4baf2a` |
| `kernel-r136.macho` | 16757792 | `38b7309637f499277640ddee2be05091b7efe4cbe638e65ce39725ee09e65926` |

六份文件均为 ARM64 subtype 0 的 `MH_EXECUTE`，包含 `LC_UNIXTHREAD`，没有
`LC_DYLD_CHAINED_FIXUPS`。所有 `__PRELINK_TEXT`、`__PRELINK_INFO` 和 `__PLK_*`
段虽然保留在 load commands 中，但 `vmsize/filesize` 均为 0。原 IOGPUFamily 的
bundle identifier 不存在，符号表中也没有前文审计的 IOAcceleratorES 构造、析构和
`gMetaClass` 三个符号。空段名不能作为原始 kext 已链接或已初始化的证据。

既有流水线由 XNU 的 `make install` 自身完成：先从
`kernel.development.sweet.unstripped` 执行 `strip -S`，再 `ctf_insert`，最后安装为
`fakeroot/System/Library/Kernels/kernel.development.sweet`。r58/r77/r136 的实际构建
日志都记录了这两步；当前 obj 产物与 fakeroot 安装文件逐字相同，unstripped 与
`build/xnu.sym/kernel.development.sweet` 逐字相同，且分别与 r136 保存文件相同。
将这两份产物分别保存为 `kernel-r136.macho` 和 `kernel-r136.unstripped` 即沿用原路线，
不需要再对原始 cache 做 merge、重定位或 flatten。r136 不引入新的 prelink 合并流程。

**前文 20H392 IOAcceleratorES ABI 审计仍成立，但其对象仅是原始 cache。**
它没有证明当前独立内核内已存在该 metaclass，也没有提供当前目标可用的三个 imports。
前文“从最终 prelink candidate 的原 IOGPUFamily 解析绑定”是未来选择集成原类时的实施条件，
不能视为当前已完成的步骤。未来真实发布 accelerator 前，必须在实际目标内核中明确接入
相应基类及其依赖，或者采用另行验证的 native provider 路线，再验证类初始化顺序、
IOService ABI 与实际符号绑定。不得把原始 cache VM 地址或 iOS17 shim 地址直接填入
当前独立内核。当前 CPU16K/GPU4K 内存候选和只读页几何诊断均不自动补齐这项类加载前置。
