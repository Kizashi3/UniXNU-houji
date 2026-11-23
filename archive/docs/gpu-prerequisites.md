# 小米 14 GPU 前置条件与验证边界

核对日期：2026-10-25；目标为 houji / SM8650 / Adreno 750、iOS 16.7.16
20H392 / Darwin 22。本文记录已有证据及缺口，不表示 GPU 加速已经成功。

当前根因仍未知。r125 在实际 SQE 启动写入 `0x03d02020 = 1` 前留下
`step 0x5004`，没有取得该调用返回、CP 执行或 GPU 写回的证据。r126 关闭普通
framebuffer/ConOut 跟踪后，也没有取得后续检查点。r127 则停在基础服务
`starting ScmDxeCompat`，尚未到 GPU 测试；这轮不能用于判断新增 SID1 映射是否有效。

本次按上游[平台与内存](https://unixnu.com/zh/porting/platform)、
[驱动接入](https://unixnu.com/zh/porting/drivers)、
[启动验证](https://unixnu.com/zh/porting/bring-up)、
[设备树](https://unixnu.com/zh/porting/device-tree)及
[GPU 与 Metal](https://unixnu.com/zh/porting/gpu)逐项核对。
网页会更新，下面涉及源码的比较使用固定版本。

## 实机已经通过

| 能力 | 已取得的证明 | 尚不能据此声称 |
| --- | --- | --- |
| 八核、GIC、IPI、定时器 | r55 在挂根卷前通过八核 MIDR/MPIDR、绑定任务、每核 timer/IPI；r56 用户态期间八核计数继续增长 | 异构能力调度、DVFS、温控、挂起恢复完整可用 |
| 8 GiB XNU 内存 | 加载器先以 `AllocateAddress` 独占完整窗口，再做两轮地址相关写/PoC flush/读；XNU 报告 `0x8c0000000` 起的 8 GiB | 任意物理 RAM 都可使用，或 UEFI GPU 分配已经交接给 XNU |
| UFS 根卷与持久日志 | XNU 原生 UFS DMA、HFS 根卷挂载、固定日志重启后回收 | UFS 与 GPU 使用同一 SMMU/stream/缓存模型 |
| 显示、触控 | 1200×2670、stride4800 的继承 framebuffer；r52 物理触点进入 HID，r56 全屏触控，r58 最近任务手势 | GPU 合成、面板时序/亮度完整驱动已完成 |
| GMU 有界 DMA | UEFI CM3 程序向拥有的缓冲写回；越界负例产生对应故障，随后恢复 | GPU SQE 已取指，或 XNU 已有可提交工作的 GPU 驱动 |
| GMU 固件、HFI、OOB | r126 五个 host profile 请求完成；GX/OOB、SQE/AQE 基址读回、Gen7 配置完成，SQE 当时仍为 0 | HFI ACK 等于 CP/fence 完成，或配置值等于当前运行频率 |

对应证据：

- [CPU 预检实现](${HOUJI_PORT_ROOT}/native/smp/SweetCPU.cpp:303)、
  [r55 八核 PASS](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r55/XnuLog.txt:408)、
  [r56 每核计数](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r56/XnuLog.txt:99)。
  GICD/GICR 为 `0x17100000/0x17180000`，redistributor stride 为 `0x40000`；
  PSCI 使用 SMC，虚拟定时器 INTID27、参考时钟 19.2 MHz。
- [加载器分配](${HOUJI_ARTIFACTS}/native-port/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c:474)、
  [窗口验证](${HOUJI_ARTIFACTS}/native-port/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c:48)、
  [r35 XNU 内存](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r35/XnuLog.txt:185)。
  [UEFI 内存表](${HOUJI_UEFI_ROOT}/Platforms/Xiaomi/houjiPkg/Library/MemoryMapLib/MemoryMapLib.c:17)
  分开保留 PIL、TZ、显示和固件资源，普通 UEFI 自动分配限制在低 4 GiB。
- [r56 根卷挂载](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r56/XnuLog.txt:39)、
  [framebuffer 几何门](${HOUJI_PORT_ROOT}/native/display/SweetFramebuffer.cpp:152)、
  [触控硬件记录](${HOUJI_PORT_ROOT}/native/touch/board.json)。
- [r126 GMU DMA 正负例](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r126/UniXNU.log:462)、
  [HFI 完成](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r126/UniXNU.log:572)、
  [OOB/代码/配置](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r126/UniXNU.log:594)。

硬件 RTC 仍未实现；XNU 日历使用 host 提供的 UTC seed。定时中断已工作与硬件 RTC
缺失是两件事，见 [r55 时钟记录](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r55/XnuLog.txt:137)。

## DMA 所有权与缓存：逐设备核对

| 消费端 | 地址、stream/context | 缓存和生命周期 | 验证级别 |
| --- | --- | --- | --- |
| XNU UFS | 控制器 `0x01d80000`；系统 SMMU `0x15000000`、SID `0x60`；连续 139264 B DMA，检查控制器地址宽度 | 专用 stream takeover；提交前 clean/invalidate，设备结果仅 invalidate；先停队列再改配置 | 实机读根卷及日志通过 |
| 触控 | GPIO 48–51/161/162，TouchCom；当前不是 GENI/GPI DMA | 固定缓冲、GPIO SPI；没有建立或提交 SPI DMA | 实机触控通过；无需虚构 SPI stream 证明 |
| 显示扫描 | 固定保留区 `0xfc400000`，4800×2670 B 画布 | 当前 CPU 复制至继承的扫描缓冲；不通过 GPU BO | 实机全屏；GPU 呈现未验证 |
| UEFI GMU | GPU SMMU `0x03da0000`；SID5→bank2/ASID750；有界自有 IOVA、32位输入/36位 PA | 表/固件按用途 WB 或 Normal-NC，逐页 CPU 属性检查、PoC 发布，资源保持到平台复位 | 实机 DMA 正负例、固件/HFI 通过 |
| UEFI GPU | 同一 SMMU，SID0→bank0/ASID751；SQE `0x63001000`、AQE `0x63021000`、ring `0x620c0000`、record `0x6303f000` | 代码 RO/X，ring/record 为固定权限 RW/NX；表与设备可写区分离，CPU Normal-NC；故障后不能仅凭 CM3 reset 放开文件系统 | SID0 配置实机读回；SQE 执行/写回缺失 |
| UEFI LPAC 对照 | 新增固定 SID1→同一拥有的 normal bank0；secure SID2 与其他 stream 仍 FAULT | 同一现有图，不扩展物理范围或权限；逐流读回后完整24槽/22bank审计才设置 attached | r127 源码/主机测试通过，尚未实机运行到此 |

实现入口：[UFS DMA/cache](${HOUJI_PORT_ROOT}/native/ufs-root/HoujiUfsRead.cpp:176)、
[触控传输](${HOUJI_PORT_ROOT}/native/touch/HoujiTouchDriver.inc:2)、
[固件 CPU 属性与发布](${HOUJI_PORT_ROOT}/native/gpu/uefi/GpuFirmwarePrepare.h:28)、
[GPU 实际图审计](${HOUJI_PORT_ROOT}/native/gpu/uefi/GpuScratchNative.h:26)、
[固定双流策略](${HOUJI_PORT_ROOT}/native/gpu/uefi/GpuScratchContext.h:44)。
GMU 的已知写回不能替代 GPU bank0/SID0 或 SID1 的实际访问证明；当前没有观察到
SQE 首次取指使用的真实 SID，新增 SID1 是对照实验，不是已确认的修复。

## 源码与主机测试已完成，但前置证明仍不足

**时钟请求与运行频率须分开。**
[GpuPowerPolicy.h](${HOUJI_PORT_ROOT}/native/gpu/uefi/GpuPowerPolicy.h:194)
会在 GMU 分支已启用时提前拒绝冷配置，625 MHz 的 GMU 请求位于该门之后。
r126 [实际日志](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r126/UniXNU.log:383)
显示 `code=4 phase=8 resource=4`，因此不能声称该次执行了 625 MHz 请求。
后续独立 HUB 冷配置记录 200 MHz 返回值；GMU/HUB 最初配置查询均为 `Not started`。
这些 API 返回的是配置状态，未形成运行时测频证明；HFI ACK 也不能补上这个证明。

**live command database 仍未闭合。**
[HFI 表清单](${HOUJI_PORT_ROOT}/native/gpu/hfi-tables.json)
明确 `live_command_db_verified=false`。当前 rail/BCM/BW 数据由本机 AOP 镜像和捕获
设备树生成，[GpuHfiTables.h](${HOUJI_PORT_ROOT}/native/gpu/uefi/GpuHfiTables.h:1)
不是对当前活动 command DB 的读取或频率测量。仍需逐项核对活动资源地址、unit、width、
VCD、实际 OPP/带宽投票及可观测结果。该缺口值得检查，尚不能当作 SQE 卡点根因。

**固件内容、页表和 MMIO 属性通过不等于设备执行通过。** SQE/AQE 原文件有固定摘要，
剥离首4字节后复制/读回，代码图和权限已有主机审计；r125 CPU 的 CP 页 nGnRE
转换检查通过。但 [r125 结果](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r125-result.json)
仍明确 `GPU_CP_execution_proven=false`、`GPU_writeback_proven=false`；
[r126 结果](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r126-result.json)
没有 SQE 后的检查点。

## 仍缺的 GPU 交付条件

1. **先恢复到同一轮可重复的 GPU 入口。** r127 的 ScmDxeCompat 停点发生在 GPU
   应用之前。先保存前置失败证据并恢复已验证基础服务，不能把这轮计为 SID1 失败。
2. **闭合 A750 的实际启动调用。** 保留首个未返回调用和受限恢复路径，区分 CPU MMIO
   完成、SQE 首取指、实际 stream/context、CP_INIT、RPTR/WPTR 推进。当前卡点根因未知。
3. **证明 GPU 结果。** 有界任务必须产生 CPU 未预填的设备写回，fence 实际推进；再渲染
   已知图像并校验像素。故障/超时先证明 DMA 已停止，之后才能回收映射或恢复文件系统。
4. **建立 XNU 后端。** 现有 [XNU GPU 调用](${HOUJI_PORT_ROOT}/native/ufs-root/HoujiUfsRead.cpp:568)
   仅进入 [只读观察器](${HOUJI_PORT_ROOT}/native/gpu/HoujiGpuProbe.inc:49)，
   没有完整 A750 IOAccelerator/NativeAdreno transport、BO/VM 生命周期、提交/完成或重置。
   UEFI 分配和驱动状态不会自动变成 XNU 的所有权；需要明确接管或重新初始化契约。
5. **完成构建/设备树集成。** 当前旧格式 [board.toml](${HOUJI_PORT_ROOT}/board.toml)
   尚无新 feeds/SoC/porting 解析链；[旧 ADT 生成器](${HOUJI_PORT_ROOT}/scripts/make-houji-adt.py:129)
   仍拒绝导出 GPU 节点。须补全实际消费端的属性或主动初始化、OS ABI、归档和链接证明。
   格式1仍有文档支持；新格式集成缺口不能直接解释 UEFI 中的 SQE 写入停点。
6. **最后接 AdrenoMetal 与桌面。** [候选资格记录](${HOUJI_PORT_ROOT}/out/adrenometal-ios16-candidate-v1/qualification.json)
   只有构建/签名检查，`device_tested=false`、`gpu_acceleration_verified=false`。
   [用户态探针](${HOUJI_PORT_ROOT}/native/gpu/metal/AdrenoMetalProbe.mm:95)
   要求真实后端，不能用空 IOAccelerator 服务代替。小图通过后还需桌面合成、输入、持续
   工作负载与客户端退出验证。

## 固定参考版本

| 参考 | 固定提交 | 本次采用的证据 |
| --- | --- | --- |
| [Linux SM8650 DTS](https://github.com/torvalds/linux/blob/21a7f44fd0765fcc5194130b28767786eba1d1e7/arch/arm64/boot/dts/qcom/sm8650.dtsi) | `21a7f44fd0765fcc5194130b28767786eba1d1e7` | GPU 正常设备列 SID0+SID1，GMU 列 SID5；不是本机 SQE SID 观测 |
| [OnePlus SM8650 KGSL](https://github.com/OnePlusOSS/android_kernel_modules_and_devicetree_oneplus_sm8650/blob/453d8875f815bf9dfad9035982861226a4823a6c/vendor/qcom/opensource/graphics-kernel/kgsl_iommu.c) | `453d8875f815bf9dfad9035982861226a4823a6c` | user/LPAC/secure 分离；普通对象映射 user 与 LPAC，secure 对象另走 secure domain |
| [UniXNU ArmCpu](https://github.com/UniXNU/ArmCpu/blob/1951cc8444b340d7d8879e9418220cf29eb711d7/ArmCpu.cpp) | `1951cc8444b340d7d8879e9418220cf29eb711d7` | PSCI、次级核注册/入口、IPI 和缓存发布顺序；本机另做 Darwin22 适配 |
| [UniXNU ArmSmmu4K](https://github.com/UniXNU/ArmSmmu4K/tree/8bb168ad058c28d5c04f179ba407875eacba7ef3) | `8bb168ad058c28d5c04f179ba407875eacba7ef3` | 表构建、实际描述符审计、context 编码；组件通过不代表 GPU 执行通过 |
| [Ace5 参考](https://github.com/tycykp/UniXNU-OnePlus-Ace5/tree/aaa100d19f6fb14e5897a7e496edf7838d4d4e9f) | `aaa100d19f6fb14e5897a7e496edf7838d4d4e9f` | TouchCom 与 HFI/投票算法参考；本机地址、固件、电源及结果独立核对 |

CPU 调度细节见 [cpu-scheduling.md](cpu-scheduling.md)，前端构建边界见
[adrenometal-ios16.md](adrenometal-ios16.md)。本文件不更新这些既有文档中的历史轮次。
