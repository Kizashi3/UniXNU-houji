# Adreno 750 移植调研

2026-10-25 核对各仓库默认分支 HEAD；固定记录在仓库外的
`native-research/latest-heads-20261025.json`。本文中的其他机型结果来自作者记录，
不是小米 14 的硬件验证。当前 houji 仍为 CPU 渲染；r79 已实机通过原厂 GMU/HFI，尚无 A750 GPU 命令提交。

## 最新代码可复用的部分

| 项目与固定版本 | 已有工作 | houji 的边界 |
| --- | --- | --- |
| [Ace 5 / aaa100d1](https://github.com/tycykp/UniXNU-OnePlus-Ace5/blob/aaa100d19f6fb14e5897a7e496edf7838d4d4e9f/docs/GPU_TERMINAL_BRINGUP.md) | 同 SM8650/A750 v2，GPU/GMU/SMMU/HFI 部分实机预检；AQE/HWSCHED 涉及安全上下文分配 | 最接近的平台参考，尚未证明完整 CP 提交、fence、Metal 桌面，不能当作现成驱动 |
| [Adreno740 / 4e0314df](https://github.com/UniXNU/Adreno740/commit/4e0314df8ad29d52f6fa3f9383a540adcd618b87) | 原 NativeAdreno；b686b905 修正 GPU 写入导入缓冲的缓存属性，后续至本次 HEAD 只有文档、注释和路径调整 | README 明确 A740/SM8550 范围；板级 MMIO、供电、GMU 固件、SMMU 和安全初始化需要 A750 适配 |
| [AdrenoMetal / 454ff2ce](https://github.com/UniXNU/AdrenoMetal/commit/454ff2ce83766ce7b3e0f355e83f1d72907708b3) | 原 NativeMetal；通过 metal2vulkan、Turnip 和内核 GPU 接口实现前端；最新改动统一组件路径 | 官方验证范围为 sheng/A740；可在 A750 提交/fence 工作后复用前端 |
| [AdrenoFirmware / 20ad3d7a](https://github.com/UniXNU/AdrenoFirmware/commit/20ad3d7aca14bd46aecab6335c780f5413fa054b) | GMU 固件段规划、HFI 传输、初始化消息和电压/带宽表编码；A6xx/A7xx wire profile | 平台仍须提供真实的已就绪 GMU、独占队列、有效 SMMU 映射，以及本机时钟/命令数据库投票；只能以真实 ACK 推进 |
| [AdrenoPM4 / 282606b5](https://github.com/UniXNU/AdrenoPM4/commit/282606b528b2595bc4274ea7490b62b323f35a5f) | 独立的 Adreno PM4 命令组件 | 待 GMU/HFI 与 CP 基础路径可用后核对 A750 packet 与初始化差异 |
| [GopFramebuffer / 8666a995](https://github.com/UniXNU/GopFramebuffer/commit/8666a9950c9699b368931d18cac92c0fdb2ce9c0) | 原 NativeMobileDisplay；GPU copy 接受后提前 retire，使渲染和复制重叠 | 需要可用 GPU copy/fence，当前软件复制通路不具备此契约 |
| [Pandora / 4aea93cd](https://github.com/ShueiTsuki/data-a-live/blob/4aea93cdf5b5daf8ec1215e37bdfae2c17fe0fdc/docs/GPU_PLAN.md) | 原 ios-pandora；A840 已记录 iOS16 GPU 合成桌面；新记录称128个IB一批已修复快速交互hang，并补齐部分IOSurface格式 | 可参考主机命令环、iOS16 Metal ABI、IOSurface和故障记录；gen8寄存器及票据不能直接套用到A750 |
| [ios-sailfish / 6f27e41f](https://github.com/joranv1/ios-sailfish/blob/6f27e41ff249f2680540ebe8ee5ab982c5e641c9/README.md) | A530 + Freedreno/EAGL + CoreAnimation OpenGLES，在 iOS 16.7.16 渲染界面 | 是另一个用户态渲染路线；不能替代 A750 内核 GPU 驱动 |
| [ios-sweet / 45263bee](https://github.com/dipa-studio/ios-sweet/blob/45263bee51df4a0f55cdf9c649af886399488ddb/README.md) | 同 iOS 版本、CPU 渲染，部分设置页面有限制 | 可借鉴系统兼容与诊断，未提供 A750 GPU 实现 |

在本轮核对的仓库中，尚未找到已验证完整 A750 原生 iOS 桌面加速的实现。
Linux/Mesa 对 A750 的支持证明硬件有公开驱动基础，但 Linux DRM/KGSL 接口不能直接
装入 XNU。不能仅复制 Metal 插件，或将设备 ID 改成 750 就声明完成。

## 本机已采集输入

`native/gpu/captured-board.json` 固定当前手机的 FDT 来源和类型校验结果：

- 芯片 ID `0x43051401`，compatible gen7-9-1。
- GPU `0x03d00000/0x40000`，GMU `0x03d68000/0x37000`，
  SMMU `0x03da0000/0x40000`，GPUCC `0x03d90000/0x9800`。
- 只读取得本机 vendor_a 的 `gmu_gen70900.bin`、`gen70900_sqe.fw`、
  `gen70900_aqe.fw`，各文件与手机 SHA-256 一致，副本存放仓库外。
- 已在本机只读挂载的 odm_a 找到 `/firmware/gen70900_zap.mbn`，12088 字节，
  SHA-256 `ab6035deaf3df20b52f1fc0b27b10f2ad392398e2eb802b68746d5511981931e`，
  前后设备读值与本地副本一致。保存在仓库外，没有执行，也未调用 SCM/PAS。
  FDT `zap-shader` 引用本机 `gpu_microcode_region@9b09a000`，大小 8192 字节。
  此前 vendor/modem 及本地 vendor_boot 检索未命中，不能据此推断 odm 缺失。

以上是早期采集输入。后续 r79 已执行并验收 GMU/HFI；SQE/AQE/ZAP 尚未执行，
也未申请安全上下文。各阶段结果记录在下文；提交、fence 和绘图仍须先完成，
随后才能接入 Metal 或 OpenGLES 桌面合成。

## 本机只读预检结果

r59 已临时启动并自动返回 OrangeFox。固定运行编号/CRC 的日志记录：

| 地址/项目 | 值 | 结论 |
| --- | --- | --- |
| GCC CFG `0x171004` | `80000003` | 配置使能位存在，GPUCC 可读 |
| GCC MEMNOC `0x171010` | `80000003` | 当前时钟未报告运行 |
| GCC DVM `0x171018` | `80000001` | 当前时钟未报告运行 |
| CX GDSCR `0x3d99108` | `0022f801` | CX 关闭 |
| CX HW control `0x3d99168` | `2800010a` | 电源就绪位未置位 |

预检只执行上述五次 MMIO 读取；后续 GPU 分支与 SMMU 读取被条件检查阻止，
没有把未读取字段的零初始化值当作硬件结果。未挂载 HFS、未启动 iOS 用户态。

r60 进一步实测原厂 Clock 1.0.a：9 个时钟与 `gpu_cc_cx_gdsc` 均解析成功。
AOP 描述符 magic=`4d41494c`、version=1；remote=`c0/68`、host=`128/2d8`，
链路 UP、主机通道 DOWN、待处理长度均为 0。只观察，没有打开通道或写门铃。

r61 已准备原生 CX/时钟初始化试验：采用同芯片参考的电源策略，经本机 FDT 和
r59/r60 状态核对后，通过原厂接口请求资源；AOP 事务仅使用关闭且空闲的主机通道。
GMU 保持复位，不加载固件、不调用 SCM/PAS、不改 SMMU。主机策略 102 项、
实际固件 QMP 算法 86 项、12 种内存映射组合通过检查；原有区域及属性保持一致。
原厂时钟接口内部等待不可抢占，不能把这些调用描述为已验证有界。
r61 已自动返回恢复环境，CX 仍关闭；单独源码文件使用的标准打印没有进入应用日志，
尚不能判断原厂接口的失败位置。r62 将该模块接入同一个日志缓冲后，确认是
调用方提前封装了请求 CRC，被严格的原始请求检查拒绝，未进入硬件准备。

r63 修正请求初始化后，AOP `acd=0` 消息已消费、通道正常关闭，原厂接口开启
CX，独立回读 `GDSCR=f822f800`、`HW=80000202`。随后因继承的 GMU 分支
`2001`，按策略在 phase 8 停止；没有直接重设已有时钟。

r64 继续只读确认 `CM3_SYSRESET=1`，GMU/HUB 的 RCG CMD/CFG 均为 0，
原厂 `GetClockFreqHz` 均返回 `EFI_NOT_STARTED`，输出值 0 不代表实测频率。
因此当前只能证明分支 enabled，不能证明 GMU 已有有效的 625 MHz 时钟。
SMMU 时钟 `80000000` 仍关闭；固件未执行，没有 GPU 加速。

r65 实机通过独立的总线访问探测：只接受本次原厂准备生成且 CRC 有效的
`attempted=confirmed=1002` 部分结果；确认 CX、AHB、DVM 和 CM3 保持复位后，
临时清 GCC CFG/MEMNOC 的 HWCG 位、开启 GPUCC SMMU 时钟投票位，
读取 SMMU ID/控制/故障信息，再按相反顺序恢复这三个字段。
不修改 SMMU stream/context、PLL/RCG 或复位，不上传固件。
读到 `ID0=4c017e18`、`ID1=40000016`、`ID2=5511`、全局 fault=0，
三个时钟字段 `attempted=restored=7`，没有修改 SMMU 控制寄存器。

r66 追加全部 24 组 SMR/S2CR 和 22 个 bank SCTLR 观察：SMR 均为 0，
S2CR 均为 FAULT 类型，SCTLR.M 均为 0。其他 SCTLR 字段存在未初始化值，
不能称其为“全部寄存器清零”。FWINIT=0、GXPOWER=3，访问结束恢复时钟字段。

r67 尝试只使用内部 TCM 的 CM3 诊断程序，返回恢复环境时尚无提交的 XNU 日志，
UEFI 最后保存点也未到达；无法据此确认 CM3 执行或具体重启位置。

r68 调整日志保存顺序，在 GPU 操作之前建立经 GPT 校验的 logfs 快照，
并增加原厂电源调用、TCM 映射/备份/装载和复位释放前的落盘点。
每次文件 Flush/Close、设备 Flush 后独立读回并校验 CRC；写入只在已有 logfs
边界内放行，返回硬件操作前关闭写门。文件系统在 application TPL 执行，
CM3 保持复位；返回 notify TPL 后重查全部访问条件。
实机已保存电源调用前后、TCM 映射前和最终检查点，并提交有效 XNU 日志。
本轮在 HUB `0x3d993e8=0` 的新条件检查处停止，没有读取/写入 TCM 或解除复位。

本机原厂 ClockDxe 的静态节点表已与 r60 返回的 ID 对应：GMU `10159`、
HUB `10164`、CXO `1016a` 的 CBCR/RCG 地址与 Linux 来源一致；
HUB 原厂频率表含 200 MHz。绑定证据记录于 `native/gpu/clock-provider.json`。
r69 实机通过原厂接口设置、读回 HUB 200 MHz，Enable 返回成功，IsOn=true。
CBCR=0、RCG CMD=0、CFG=0x505；原厂 IsEnabled=false，因此不能用分支 bit0
解释 AON 时钟是否运行。只对本次冷启动、未配置的 HUB 做准备，不重调继承的
GMU 时钟或 CPU 频率。配置频率不等于实测频率。原厂接口内部等待仍不可抢占。
TCM 备份、程序装载和读回通过；最后有效落盘点为解除 CM3 复位之前，
XNU 日志尚未提交。手动返回恢复环境后，保护分区、GPT 和 misc 保留区校验通过。

r70 按固定版本 Qualcomm gen7 驱动补齐 9 个 CM3 启动控制寄存器：
BOOT/CM3 配置、内部缓存与总线配置、FAL 控制和两组中断屏蔽。
所有原值先备份；确认重新复位后恢复前 7 个字段，两组中断保持屏蔽直到整机重启。
诊断程序改用 ITCM 内部循环，避免未经验证的 WFI 路径；不访问外部内存。
复位写入后、完成邮箱验证后各增加独立落盘点。主机用例覆盖写入失败前后
两种硬件副作用、逐次读取失败、恢复失败、超时和复位状态被改变；实际编译指令模拟通过。
落盘与原厂接口不可抢占，只有轮询次数有界，不能据此保证整个硬件调用会按时返回。

r70 自动返回恢复环境，UEFI CRC 快照有效；9 项配置均尝试写入，最后一项
AO 中断屏蔽的全位相等检查拒绝继续，尚未解除 CM3 复位。58/58 个 TCM 字、
前 7 项启动配置和三个临时时钟字段全部恢复。该版清理过程覆盖了失败读值，
不能从最后一次 MMIO 地址推断失败位置；r71 保留独立的失败地址/原值/期望/掩码。
同芯片固定参考 [gpu-native-hwsched.py](https://github.com/tycykp/UniXNU-OnePlus-Ace5/blob/aaa100d19f6fb14e5897a7e496edf7838d4d4e9f/scripts/gpu-native-hwsched.py)
对 AO mask 写 UINT_MAX 后只验证低 0x7f；r71 采用相同读回契约，低位缺失仍拒绝释放复位。
新增缺失低位的故障用例后，共 536 个策略用例通过。

r71 实机确认内部 CM3 程序执行完成：邮箱为 `a7500002/750c0de0/128`，
SMMU 全局故障为 0；随后重新保持 CM3 复位，58/58 个 TCM 字、7/7 项启动配置
和三个临时时钟字段全部恢复。两组 GPU 外设中断保持屏蔽直到重启。
这不等于原厂 GMU/HFI 固件已经启动，也不等于 GPU 命令或绘图可用。

r72 引入未修改的 [ArmSmmu4K / 8bb168ad](https://github.com/UniXNU/ArmSmmu4K/commit/8bb168ad058c28d5c04f179ba407875eacba7ef3)
页表构建与审计组件。实机复核 CM3 成功后，分配 3 页页表和 1 页测试数据，
CPU AT 读/写翻译逐页确认真实 PA、WB 与 inner-shareable；当前 EL=1。
32 位 IOVA、36 位 PA、4 KiB 页表包含唯一的 RW 非执行映射 `0x60000000`，
全量遍历 1536 个描述符通过，所有内存已释放。本轮没有写 TTBR、上下文或 stream，
尚未验证设备可见性或 DMA；UEFI 和 XNU 两份日志均通过运行编号与 CRC 校验。

r73 使用同一构建/审计结果，在 CM3 保持复位、所有 stream 为 FAULT、
所有 bank 的 M 位为 0 时，仅配置禁用的 bank 0。配置读回成功：SCTLR=0、
CBA2R=1、CBAR=1f300、TCR2=38071、TCR=80802020，TTBR 为本轮实际页表 PA。
随后重放初始 CBAR 值时发生同步外部异常：原图 FAR=03da1000，PC/LR 与
实际编译的 `MmioWrite32` / `ContextWrite32` 两个 RVA 同时匹配，定位于 CBAR0 写入。
异常处理器沿用了 STORAGE 名称，PC 并不在受限 UFS 驱动内，不能称为 UFS 写坏。
手动回到恢复环境后，UEFI CRC 快照有效，五个启动分区、12 组 GPT 和 misc 保留区
均未变化。配置阶段通过，清理阶段失败，尚未验收完整流程；没有启用翻译或设备 DMA。

r74 已在实机修正这一点：初始寄存器值只保存作证据，不重放不确定配置。
结束时保持 SCTLR=0，留下已知有效的禁用格式，清零 TTBR0/1，并完成 bank 内
TLBIALL/TLBSYNC；独立落盘后再次检查所有权与两份空表根，才允许释放测试页。
559 个策略用例覆盖不允许重放旧 CBAR、逐次 I/O 故障、超时和回调期间的所有权变化。
调用层另有 11 项检查：任何上下文错误均保留总线和内存，停止进入 XNU。
实机日志确认 retirement mask=1ff、两份 TTBR 均为 0、bank TLB 同步完成；
随后四个测试页均已释放，三个临时时钟字段均恢复，未再次出现 CBAR 写回异常。
UEFI CRC 快照有效，五个启动分区、12 组 GPT 和 misc 保留区再次校验一致。
从不写 M=1，不改 stream、全局控制或故障状态；尚未验收 DMA 或 GPU 绘图。

r75 已实机通过 CPU 缓存发布和平台只读检查。使用 `CTR_EL0.DminLine` 的实际
缓存行长度，仅对当前分配的 3 页表和 1 页数据逐行执行 `DC CVAC`，随后
`DSB SY`；发布前后均遍历 1536 个描述符并检查整个数据页。主机测试覆盖逐次
cache 操作失败、错误几何、越界元数据与发布过程中的内容变化。CPU 清缓存成功
不等于设备已访问这些页，仍需后续真实 GMU 事务来验收设备可见性。

本机运行设备树 `kgsl-smmu@3da0000` 的 `qcom,actlr=<0 0x3ff 0x32b>`
与 [小米 qsmmuv500 的三元组解析](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/shennong-u-oss/drivers/iommu/arm/arm-smmu/arm-smmu-qcom.c)
对应 SID、mask、ACTLR。源码要求修改 ACTLR 后清除 bank 的旧 TLB 状态。
[固定 SM8650 KGSL 源码](https://github.com/OnePlusOSS/android_kernel_modules_and_devicetree_oneplus_sm8650/blob/453d8875f815bf9dfad9035982861226a4823a6c/vendor/qcom/opensource/graphics-kernel/kgsl_iommu.c)
还在设置 ACTLR.PRR bit 5 前写入真实零页的物理地址，不能单独照抄 `0x32b`。
r75 在冷态所有权检查之间两次读取 ACTLR0、PRR low/high 并检查一致性，
不写这些平台寄存器，不启用 stream 或翻译。源码 blob 和 DT 摘要单独固定。
实机结果为 line=64、cleaned-lines=256、DSB=1、audits=2、descriptors=3072；
ACTLR0=3，PRR low/high 均为 0，228 次只读检查一致。禁用上下文清理、
CM3 诊断恢复及测试页释放再次通过。UEFI 与 XNU 日志均有效，已自动回到恢复环境。
1,313 项缓存发布测试和 237 项平台观察测试均通过 ASan/UBSan；最终链接产物
还独立核对了 owned-line `DC CVAC` 和循环结束后的 `DSB SY`。

下一阶段是受限 GMU 外部内存事务，而非直接启动原厂固件。需要先分配并发布
真实 PRR 零页，按本机 DT 配置平台字段；持有唯一 bank0/SID5/ASID 的所有权，
让其他 stream 保持 FAULT，使用明确屏蔽故障 IRQ 的有界轮询诊断。必须同时验证
设备读回已知数据、设备写入经 CPU invalidate 后可见，以及未映射地址被拒绝。
CM3 复位、stream 分离、bank 禁用、TLB 同步和空 TTBR 独立读回后才允许释放资源；
任一步不确定则保留内存与时钟并停止进入 XNU。当前 r75 尚未执行这些事务。

r76 候选实现以上内存诊断：唯一映射 `0x60000000/4096`，真实 PRR 零页，
bank0/ASID750/slot0/SID5；其他 stream 保持 invalid/FAULT。使用 `SCTLR=0x1027`
（允许硬件 ASIDPNE 读零），明确屏蔽 context fault IRQ 且不启用 fault stall。
CM3 只向映射页偏移 8 写入 `0xa750cafe`，随后读取未映射的 `0x60002000`。
必须同时取得已知读取值、该地址的 read translation fault，以及 CPU `DC IVAC`
之后可见的设备标记，才认为 DMA 诊断通过。只清除精确匹配的本轮 TF bit，
不清除未知或全局 fault。成功后复位 CM3、断开 SID、关闭 bank、同步 TLB、
恢复已知 ACTLR=3/PRR=0、恢复 TCM、修复数据并清缓存，再由外层清零两份 TTBR。
失败仅在必要时尝试确认 CM3 复位，保留所有资源直至重启。

CM3 诊断源码仅访问内部 ITCM/DTCM，实际编译指令已通过 Cortex-M3 模拟器验证，
内部执行已由 r71/r72 实机验收。策略测试覆盖逐次 I/O 失败、超时、恢复和复位不确定时保留资源。
**尚未实现 GPU 加速。**

当前优先级：GPU 上电/时钟 → GMU 与隔离页表 → 提交/fence → 绘制/桌面合成；
关于本机等待和 WCN7850 Wi-Fi 已保留诊断，待 GPU 主线推进后继续。

## r76 实机结果与 r77 合并诊断

r76 的 GMU 外部内存诊断已在小米 14 通过：读取已知两字、写入标记、
未映射读取均取得真实硬件结果；FSR=0x402、FAR=0x60002000、FSYNR=0x170023。
CPU invalidate 后实际观察到 0xa750cafe，整页完整性检查并恢复成功。
TCM 68/68、配置 7/7、ACTLR=3、PRR=0、SID 分离、bank 禁用及两份空 TTBR
均已回读，再释放全部五页，三个总线字段也已恢复。UEFI 日志 CRC 有效。
XNU 文件仍是未提交初始记录，不能据此断言内核 panic，亦不算 GPU 绘图通过。
五个启动分区、12 组 GPT 与 misc 保留区在恢复后校验一致。

r77 将以下工作放进一个 UEFI 镜像，按依赖推进，同时记录每阶段耗时：

1. 固定本机 GMU 文件通过长度和 CRC 检查后，交叉调用 UniXNU AdrenoFirmware
   和固定 Ace 5 的布局规划；创建真实固件/BSS、17 队列 HFI、log、VRB 内存。
   HFI 使用 Normal NC（本 UEFI 的 WC），实际 CPU AT 验证 PA 和缓存属性。
   构建并审计全部实际 native4K 描述符，仅为未激活的准备。
2. 沿用已验证的 CX/HUB、内部 CM3 检查，把详细记录留在 RAM，关键边界统一落盘，
   不逐步骤重复 FAT 文件写入。
3. 使用正式 GMU bank 2 运行完整 DMA 正反例、缓存可见性和清理；bank 0/1 保留给 GPU。
   即使正例失败也先记录 FSR/FAR/FSYNR 和完整八字邮箱。
4. 在独占、CM3 复位、所有 stream FAULT 和 bank M=0 时，执行固定 secure-CX
   convention/availability/INIT_REGS 请求，保存真实 x0..x7、重试和耗时。
   不调用 PAS/ZAP，不分配安全内存，不提交 GPU 命令。未知安全状态立即隔离。
5. 记录 CX/GMU/SMMU 的 fault、IRQ mask/status、TTBR 和 stream 快照。
   全部结果持久化后直接冷重启到恢复环境，省去与本轮无关的 8 GiB loader 检查
   和 XNU/用户态启动。UEFI 只读校验 misc 中精确的无 wipe 恢复请求；不写 misc。

主机先完整备份 4 MiB misc，仅在其前 864 字节没有其他待处理请求时写入
`boot-recovery` / `recovery\n`；全分区回读确认其余字节完全相同。
UEFI 只有在该请求和结果文件均校验通过时才自动重启，失败后持有的资源直到平台重置。
监听脚本持续轮询已有 ADB 服务，设备恢复即抓取 CRC/运行编号绑定的日志；不固定等待，
不重启 ADB 服务、不自动继续启动下一个未经检查的镜像。

r77 主机检查与构建属于候选验证，以上新路径仍须实机记录验收。
原厂 GMU/HFI 尚未执行，CP/fence 和 Metal 接入仍在后续依赖链上。

### r77 已实机验收

完整合并流程自动返回 OrangeFox，监听器在恢复设备出现后立即开始读取，
本次观察到完成抓取用时 11.486 秒（从监听器启动算起，并非整机启动耗时）。
固件准备耗时约 0.991 秒；实际页表为 6 表、139 个 4K 叶、3072 个描述符，
17 个 HFI 队列和三个共享区的 Normal NC CPU AT 检查通过，9 项内存全部释放。
bank 2 正反 DMA 和缓存可见性通过，FSR=0x402/FAR=0x60002000；两份 TTBR
清零、SID 分离，所有五页均已释放。secure-CX 真实三个 SMC 返回 a0=0，
初始化 request=0x0b 成功，没有 busy/interrupted 或隔离状态。前后 fault/IRQ
快照未出现新有效故障。最后阶段时间戳约 7.09 秒；后面仅有结果打印、文件校验
和恢复重启。保护分区、12 组 GPT、misc 保留区均再次校验一致。
本轮明确没有启动 XNU，初始 XnuLog 未提交是预期，不再作为缺失内核日志的错误。

### r78 候选：一轮覆盖原厂固件与 HFI

延续已验收前置流程，在同一镜像保留 8 段真实 GMU 内存和 6 表/139 叶的根，
核对本机 PDC/RSCC 设备树窗口并配置固定 gen7-9-1 启动值，备份整个 32 KiB TCM，
装载并回读原厂固件的 540 字节 TCM 段，其余内容由实际 RAM 和页表提供。
依次验证新的 firmware-ready、HFI-ready、真实 id12/property125 查询的匹配 ACK。
逐阶段记录 phase、地址/读值有效位、返回错误、故障、IRQ、时钟计数器和完整响应。
所有页面、PRR 和 gate 引用在成功/失败后均保留至平台重置，不宣称复位读回代表
已排空 DMA；只在确认 CM3 停止后写结果文件。不调用 HWSCHED START，不提交 CP/PM4。

此 UEFI 专项复用 r77 的相同未执行内核文件和初始 XNU 标记；本轮由新的 UEFI
日志版本、镜像 SHA 和冻结源码标识，省去重复编译 XNU。该内核没有生成新版本。
869 项状态机与故障注入检查、65929 项实际 native writer 检查通过；实机结果待记录。

### r78 实机停止点与 r79 权限验证

r78 已自动返回 OrangeFox，UEFI 日志 CRC 和本轮版本有效；保护分区、12 组 GPT
及 misc 保留区一致。实际固件 RAM、17 队列 HFI、bank 2 DMA 和 secure-CX 前置
检查再次通过。整个 32 KiB TCM 已备份（8192 字，CRC fba23565），540 字节原厂
TCM 内容已写入并回读，19 项 RSC/PDC 和 19 项 boot 配置完成。

释放 CM3 后固件尚未 ready，停止在 phase 7，FSR=0x408、FAR=0x4000、
FSYNR=0x1f0063：对应取指权限错误，且 PNU 指示特权事务。CM3 重新复位已确认，
所有资源保留到平台重启。没有执行 HFI 查询、HWSCHED START、CP 或 PM4。

固定 [Ace 5 同芯片实现](https://github.com/tycykp/UniXNU-OnePlus-Ace5/blob/aaa100d19f6fb14e5897a7e496edf7838d4d4e9f/ios16/GiuliaGPU.cpp)
为所有 GMU 固件/HFI 范围设置 `Read|Write|Privileged`，只对 ICACHE 加 Execute。
r78 缺少 Privileged，r79 仅修正此权限差异并记录每段真实页表的 raw/AP/PXN/UXN；
保持缓存和共享属性不变，以实机结果判断该差异是否解释 0x4000 的错误。
r79 仍合并固件 ready、HFI ready、匹配 property ACK，并自动返回和即时抓取日志。

### r79 已实机验收：原厂 GMU 与 HFI

修正权限后，实际 ICACHE 叶描述符 AP=0/PXN=0/UXN=0；全部八段页表已逐级记录。
原厂 firmware-ready=1（0x100），HFI-ready=1（0x1），property125 的 ACK
回显完整原请求 0x0010030c，value=1、status=0。stock 流程约 1.042 秒，phase=10
完成，CM3 复位确认，所有页面保留至平台重启。FSR=0x400 不含有效故障位；
FAR/FSYNR 是同轮负向 DMA 实验的旧值，不作为新故障。

设备自动回到 OrangeFox，监听器取得本轮有效 CRC 快照；五个启动分区、12 组 GPT
和 misc 保留区校验一致。尚未发送 HWSCHED START、CP/PM4 或绘图命令，
这只证明原厂 GMU/HFI 已通，不是 GPU 加速验收。

### r80 合并调度初始化候选

在 r79 的同一条原厂 GMU/HFI 路径后，追加九条有界消息：本机性能表、带宽表、
HWSCHED、KPROF、CORE_FW_START、CONTEXT_QUEUE 查询、关闭抢占、启用 AQE、START。
每条消息核对完整原请求回显、ACK 类型和 ID，以及对应消息协议的 value/status。
收到任何资源请求只保存完整原文，不发送未经实现的成功分配应答。没有 GPU stream、
GX MMIO、CP/PM4、OOB、PAS 或安全所有权操作；CM3 复位后保存合并结果并返回恢复环境。

表来自本机只读提取的 aop_a（SHA c572b184827e4a6fac8f87318da81b36e0e8056d87025ac8ae40e764d4129f8c）
和原始 live-fdt.dts。两套 ARC 表一致；解析本机 BCM 地址、unit/width/VCD 和 DDR 档位，
只公布所有 speed-bin 共有的最低 GPU 档 231MHz。此为静态原厂表，不声称已读实时 command-DB
或频率已经生效。源码参考固定 OnePlus 453d8875 与 Ace5 aaa100d1；不使用 Ace5 的 AOP 内容。

新增 102 项检查使用真实 17 队列环，验证九条消息顺序、匹配/伪造/拒绝/不完整应答、
每次健康/传输回调失败、超时、debug 泛滥和资源请求不应答。原厂生命周期检查扩至 871 项，
覆盖 bootstrap 成功/失败后复位和内存保持；65929 项实际 native writer 检查通过。
运行后额外保存 17 个队列索引和最前 256 个固件 log 字，实机结果另记。

### r80 实机结果与 r81 协议修正

r80 原厂 GMU/HFI/property125 再次通过；性能表请求 0x0020130f 得到
`[0x0011030f,0x0020130f,0]`。它按上游 `gen7_hfi_send_generic_req` 的表提交
协议是完整三字成功应答，原实现统一要求四字导致本轮主动停止，并非固件 panic
或 SMMU 故障。CM3 复位、日志 CRC、自动返回和保护分区检查均通过。

r81 按固定 vendor 的实际调用区分协议：TABLE、BW、CORE_FW_START 和 START
允许三字 ACK，以 word2=0 判成功；v5 FEATURE_CTRL 与 GET_VALUE 仍要求四字及
word3 状态。每条记录单独输出 status-present 和 legacy-contract，绝不补造状态字。
九条合并消息、首个资源请求停止策略不变。

### r81 实机：八条初始化通过，已取得资源请求

PERF、BW、HWSCHED、KPROF、CORE_FW_START、CONTEXT_QUEUE（value=1）、
PREEMPTION disable、AQE enable 全部成功。前三字协议仅用于表和 CORE；实际
FEATURE/GET_VALUE 均收到完整四字成功状态。START 的首个报文为 v1 MEM_ALLOC，
kind=2/SCRATCH、flags=0x33f、bytes=4096、align=0、gmu_handle=2；GPU/GMU
地址尚为 0。这需要真实、生命周期受控的 GPU+GMU+CPU 共享可写 scratch，不能
直接把 CPU PA 填成 IOVA，也不能伪造 ACK。当前只有 GMU bank2 的有效映射，
GPU bank0 尚未建立；故记录请求后主动停止，没有应答分配或提交 CP。

整轮 stock/HWSCHED 约 1.045 秒，CM3 重新复位确认，SMMU FSR=0x400 无有效
故障，自动回 OrangeFox，UEFI 59909 字节快照 CRC 有效，所有保护分区/GPT/misc
保留区一致。设备仍在恢复模式，GPU 桌面加速尚未完成。

### r82 共享 scratch 候选

在原八段 GMU 资源外添加一段真实 4KiB Normal NC 共享页，IOVA=0x61000000，
完整 GMU 图成为 7 表/140 叶。另分配独立的三页 GPU 页表，仅映射这同一物理页，
属性为 privileged RW、NX、Normal NC。两份图均通过实际物理描述符审计，
CPU AT 确认内存属性；所有内存先于原厂 CM3 释放准备和发布。

只在完整匹配 r81 的首个 v1 kind2/flags33f/4096/align0/handle2 请求时，
配置独立 bank0/ASID751/slot1/SID0；保留运行中的 GMU bank2/ASID750/slot0/SID5。
编程前后核对全部 stream 和 bank；只写 bank0 的精确编码值、TLB 同步和 SID0
路由，不写 SMMU 全局/PRR/故障清除/IRQ 或 GX/CP。已验证的全局 PRR 零页保持。
确认实际图、bank 回读和活动 root 后，才以真实两侧 IOVA 应答，保留原 flags、
kind、逻辑大小、alignment 和 GMU handle，host handle 按 vendor 等于 GMU handle。
第二个资源请求完整保存后停止，不伪造任意地址或映射，不应答未知资源。

643 项 bank0 状态检查覆盖每次读写故障和副作用、其他 bank/stream 占用及 TLB
超时；65568 项实际 native writer 检查拒绝 bank2、全局、故障清除、IRQ、CP 和
错误表根。共享内存配置 78630 项和旧配置 78626 项检查均通过，原厂生命周期两种
配置各 871 项；HFI 流程 107 项覆盖真实 resource ACK、第二请求停止、提供方失败
和应答语义被修改的拒绝。新路径仍待实机验证，不是 GPU 绘图验收。

### r82 实机：共享映射和首个应答通过

实际 GMU 图 7 表/140 叶、GPU 图 3 表/1 叶，CPU/GMU/GPU 同一页 PA=d27c0000，
GPU root=d27bd000（仅本轮有效）。bank0/ASID751/SID0 编程、回读、全部 stream/bank
核对通过，code=0/phase5。按真实地址返回首个 SCRATCH 的 11 字 ACK 后，固件继续
请求 v1 PROFILE（kind14/handle14），同为 flags33f、4096、align0，证明已消费首个
分配应答。GPU 和 GMU FSR 都是 0x400，不含有效故障；GPU FAR/FSYNR 的旧/
未初始化值不能解释成新故障。没有 CP 或 fence 验证。

完整日志 CRC 有效，自动返回 OrangeFox，启动分区、12 组 GPT 和 misc 保留区
一致。下一步把相同普通共享权限的请求放入有界预分配池，在一轮内处理，遇到
安全/特殊资源或池容量不足立即停止并完整记录。

### r83 批量普通共享资源候选

把 r82 的单页扩为预先分配并清零的 1 MiB Normal NC 开发池：GPU 图 3 表/256 叶，
GMU 图 7 表/395 叶。运行中不编辑活动描述符、不分配新页；每条 flags33f 普通
共享数据请求从单调游标取得互不重叠的页范围，核对实际 CPU 属性、全图和 live root
后才返回两侧真实 IOVA。逻辑 size 保持原值（例如 24 字节），底层范围按页及请求的
packed size/VA alignment 向上取整。以 kind+GMUhandle 区分身份，重复请求停止。

上限 32 条请求，ACK 主机序号连续且每个回显对应当前请求；完整保存原报文和
应答。安全/特殊 MMIO、IPC、独立 memstore/fence、未知 flags、超过池或对齐能力
的请求均不应答并结束。整个池都是本轮专用预映射零页，这是单一所有者开发诊断，
不声称已实现生产应用的逐任务隔离。没有新 GX/CP、IRQ 或 SCM 操作。

811 项逻辑大小/对齐/边界检查、109 项真实环队列消息检查（含多资源后最终 START
应答、32 条上限、提供方拒绝/失败和篡改）通过；上下文 643、实际 writer 65568、
固件内存 78630、生命周期 871 项检查通过。实机结果另记。

### r83 实机：两块分配连续消费，取得不同权限请求

实际 GPU 图 3 表/256 叶、GMU 图 7 表/395 叶，1MiB Normal NC 开发池准备和
bank0/2 核对通过。SCRATCH 和 PROFILE 的两个应答均被固件继续处理，消耗 8192
字节。第三个请求是 v1 kind15/handle15 USER_PROFILE_IBS，flags=0x339、4096、
align0：GPU 侧 read-only/unprivileged，GMU 侧仍 privileged RW。当前全部 GFX
映射是 privileged RW，不能用现有权限直接回应；本轮保存请求后停止。

两侧 FSR=0x400 无有效 fault，完整 65184 字节日志 CRC 有效，自动返回 OrangeFox，
保护分区/GPT/misc 保留区一致。后续预建四种 GFX 读写/特权组合区域，避免逐种权限
重启，仍不修改活动页表。没有 CP、fence 或 Metal 通过的结论。

### r84 实机与 r85 GMU 专用资源

r84 的四种 GFX AP 权限图核对通过，SCRATCH、PROFILE 和 USER_PROFILE_IBS
三条应答连续消费；第三条 flags339 已使用 read-only/unprivileged 区域。
下个请求为 kind16/handle16 CMD_BUFFER，flags178、32768 字节、align0：
只有 GMU 访问，CPU host access，不请求 GFX 地址。日志 67121 字节 CRC 有效，
两侧 FSR400 无有效 fault，自动返回和保护分区校验通过。

r85 为这类普通 GMU-only bufferable privileged RW 请求预建独立 1MiB Normal NC
区域，IOVA61100000；GPU 图中无该地址，响应 GPU address=0。GMU 图扩为 10 段、
7 表/651 叶，实际分配 11 项。按固定 OnePlus453d8875 的 `get_attrs` 与 Ace5
`ggm_attributes`（未加 IOMMU_NOEXEC），该专用 GMU 区使用 R/W/Privileged/Execute
设备权限；没有请求修改 CPU 可执行属性，GFX 数据仍全部 NX。
只支持已知普通 kind 与同类 flags78/178/278/378，保留 host bits、逻辑大小及对齐，
不为 secure/MMIO/memstore/fence 合成普通地址。实际表和 CPU 属性核对后才回应。

另将监听器启动移入 host boot 工具：确认 Fastboot `Booting OKAY` 后立即创建
独立 session 的轮询进程，输出/PID/状态均落本地文件，镜像名和运行标签绑定，
已有 capture/watcher 在手机写入之前拒绝。无需模型再手工发起监听；无固定宽限等待。
853 项分配/编码、78634 项固件内存、871 项生命周期及后台启动检查通过；
新硬件结果另记。

### r85 实机：GMU-only 应答与自动监听验收

第四块 CMD_BUFFER 的真实 GMU-only 32KiB 分配已消费，GPU address=0、GMU
address=0x61100000，没有 GPU 别名。实际 GMU 图 7 表/651 叶、11 项资源保持，
GPU 图仍为 3 表/256 叶；两侧 FSR400 无有效 fault。第五个请求 kind1/handle26
RB 为 flags37b、32768 字节、align0：GFX privileged read-only，与既有只读类
相比只多 GMU_BUFFERABLE bit6。上游 `get_attrs` 只解释 GMU PRIV/WRITE，
VMA 按 CACHE bit7 选择；bit6 描述非缓存 bufferable VA，既有61000000区域满足。
r86 允许该已解释的 bit6，保留完整原 flags，不修改 PTE 权限或缓存属性。

后台进程在 Fastboot 完成记录后 0.043602 秒开始，自动处理一次传输中断、保留
partial 后从另一 ADB 服务抓到本轮 69616 字节有效 CRC 日志，不需要模型另行
启动监听。保护分区/GPT/misc 保留区一致，设备在 OrangeFox。没有 CP/fence/
Metal 成功结论。


### r86–r88 实机：七块普通资源连续消费，捕获 secure CONTEXT

r86 接受 flags37b 的 RB；r87 接受 flags17f 的 SMMU 记录，logical24 字节保持，
独立 backing 按4096字节使用。r88 新增独立4MiB共享上下文区61200000，CPU
NormalNC、GPU/GMU privileged RW NX，保留原四类和 GMU-only 区，不改活动页表。
实际 GPU 图5表/1280叶，GMU图9表/1675叶、12项资源保留。

原厂固件已连续消费七条分配应答，包括 kind4/handle4 flags37f 的0x37d000字节
非安全上下文。第八条实际请求为 kind5/handle5 flags1007、同为0x37d000、align0；
没有 GMU/HOST 访问权限，是独立 secure GPU context，未用普通池应答。两侧FSR400
没有有效fault，原始 FAR/FSYNR 不解释为新fault。75131字节完整日志CRC有效，
自动回OrangeFox并抓取；启动分区、12组GPT及misc保留区一致。

r88 的 1935 项分配/编码、1674 项上下文（含完整1024页大区raw AP/NX/PA遍历和
GMU-only/尾部空洞）、78638 项固件内存故障路径、871项GMU生命周期、实际writer
检查通过；实际装载EFI与已验证二进制一致。没有CP/PM4、fence或Metal验收。


### r89 安全内存所有权候选（实机结果另记）

原厂依据为 OnePlus 内核d763ed47的qcom_scm.c `__qcom_scm_assign_mem`
七参数ABI及qcom_scm.h常量，graphics453d8875的`kgsl_lock_sgt`，以及
Ace5 aaa100d1平台实现。只调用6个固定INFO可用性查询，MP_ASSIGN、
CP_SMMU_APERTURE和PAS四接口；不调用PAS本身。确认ASSIGN可用后，
预分配独立4MiB、64KiB对齐、低4GiB候选内存及独立16KiB NormalNC控制区。

候选数据不进入普通GPU/GMU图，不按HOST_INIT为其清零或读取内容；转移前
clean-invalidate已属HLOS的缓存行，用UEFI RP+XP撤销CPU访问，1024页逐页实际
AT读写均fault才允许SCM。控制区按固定region/source/dest、7参数extended frame
发布；HLOS3转CP_PIXEL10、RW6，要求真实a0=0与服务a1=0。未知/失败均隔离
资源至平台cold reset，不回收、不回读数据。转移前后独立落盘。

这轮只验收物理所有权，尚不配置bank3、不向HFI回应secure地址、不运行CP/PAS。
成功后仍在同轮复跑既有原厂GMU/HFI普通请求批次，再自动回恢复并抓日志。
79项独立描述符与各阶段/调用/guard故障检查通过；不把候选或INFO可用当成
安全DMA、绘图或Metal成功。


### r89 实机与 r90 checkpoint 级别修正

实机六个INFO返回a0=0/a1=1，queried/available均3F。独立候选PA=d1ab0000、
控制区d1a9c000（仅该轮有效），NormalNC控制与WB数据初始identity核验通过。
RP+XP设置成功，1024页读写AT均返回PAR817 fault；未读取或初始化数据内容。

随后新callback直接从TPL_NOTIFY调用ProbeCheckpoint，被其现有TPL检查拒绝，
HSM code7/phase3、attempted0/owned0：本轮没有执行MP_ASSIGN，也未运行后续
stock批次。最终主程序在应用级保存了有效CRC日志、自动返回OrangeFox，保护
分区/GPT/misc一致。这不是所有权转换失败或成功的证据。

r90 adapter按现有GmuCheckpoint的约定，先在NOTIFY核对CM3 reset和独占状态，
仅落盘时降到APPLICATION，所有返回路径恢复NOTIFY并打印实际EFI状态。实际
adapter的52项TPL/故障状态检查与79项ownership模型通过；原始SMC结果另标
result-valid，回调transport失败不当作真实返回寄存器。r90结果另记。


### r90 实机：独立安全数据所有权通过

6个INFO仍全部可用，1024页CPU RP+XP与AT fault复核通过。修正的native
TPL adapter在转移前后均保存Success；真实MP_ASSIGN函数42000c16/arginfo1117
于972微秒返回a0=0/a1=0，HLOS3到CP_PIXEL10的4MiB RW所有权诊断通过。
此后同一轮原厂GMU/HFI和七条普通应答复跑通过，secure kind5仍明确拒绝。
没有secure bank、CP或Metal通过的结论。完整CRC日志已自动取回，恢复环境可用，
启动分区、12组GPT、misc保留区一致。

### r91 独立安全页表与上下文候选

按固定内核d763ed47的`qcom-io-pgtable-alloc.c::io_pgtable_hyp_assign_page`，
页表需要HLOS RW与CP_PIXEL R共同所有权。r91在原厂固件启动前预建4页/893叶
独立图，仅覆盖已捕获的F0000000/0x37d000安全请求，尾部和普通映射为空；
软件实际图审计、CPU WB发布及第二次真实MP_ASSIGN share均需通过。

只在完全匹配kind5/handle5/flags1007/size37d000/align0时，配置独立
bank3/ASID753/slot2 SID2，逐字段回读、bank TLB sync有界等待，保留bank0/2。
在同轮物理所有权和页表共享证明、实际图、live root检查后才返回GPU F0000000、
GMU0；不读取安全数据，不建立普通别名，不修改活动页表，不调用CP/PAS/IRQ。
未知/重复资源拒绝，所有相关资源保留至cold reset。

1555项图/893页/边界/request/上下文故障路径及65569项实际native writer检查
通过。未执行ATOS硬件翻译操作；上下文回读与HFI接受本身不是GPU DMA、fence
或Metal绘图证明。实机结果另记。


### r91 实机：页表构建前的 MS ABI 常量问题

数据所有权再次实际成功，4页WB表区CPU identity检查通过，之后在table share前
停止，未调用第二次MP_ASSIGN、未写secure bank/未运行stock。已保存49954字节
CRC有效日志，自动回恢复并校验保护分区一致。

离线重现定位到Windows ARM64 MS ABI的enum语义：即便枚举初始化写成
`0xf0000000u`，升为64位仍为fffffffff0000000。实际r91 DLL c79c是
`mov x8,-0x10000000`，c7a4将它写入range.iova，因而32位页表规划器拒绝。
普通macOS ABI的单元检查未复现此差异。

r92改用UINT32_C宏；针对真实aarch64-unknown-windows-msvc的完整当前header
生成LLVM，要求返回4026531840，并保留旧enum返回-268435456的拒绝fixture。
新增实际range/build/audit/publication/descriptor阶段日志，不改变硬件权限或操作。
实机结果另记。


### r92 实机：安全页表共享与 bank3 应答通过

实际高地址F0000000正确，4表/893叶构建、完整实际图、CPU发布、描述符编码
均通过。第二次真实MP_ASSIGN以a0=0/a1=0共享页表HLOS RW/CP_PIXEL R。
在固件发出准确kind5请求后，bank3/ASID753/slot2 SID2配置及回读code0/phase5，
240读、15写、TLB无忙等待；FSR400没有有效fault。第八条secure应答已消费，
返回GPU F0000000、GMU0，保留逻辑大小与所有权边界。下一条实际请求为
kind7/handle7 flags147、4096、align0，仅GPU访问的preemption counter。
85237字节CRC有效日志自动取回，保护分区/GPT/misc一致，手机在OrangeFox。
没有GPU数据DMA、CP/fence/Metal通过的结论。

### r93 GPU-only 普通资源候选

为GPU-only的四种GFX权限预建独立1MiB NormalNC池62000000，每类256KiB；
不进入GMU图，物理上也不与GMU/安全数据共享。普通GPU图增为6表/1536叶/9段，
GMU仍9表/1675叶/11段、12项原资源，secure图仍4表/893叶。所有图在固件启动
前发布，运行中不改叶。原生属性记录明确扩至13项，额外1项只归GFX后端，
保留到cold reset；完整检查分配失败和越界不调用分配器。

支持已知普通kind的GFX_ACC及四种PRIV/WRITE组合，保留HOST/BUFFERABLE位，
不接受GMU_ACC/PRIV/WRITE、CACHE、secure或特殊MMIO/memstore/fence。
应答GPU62000000+准确类内偏移、GMU0、逻辑大小原样。2245项planner/编码、
1931项三/五/六表上下文与全部GPU-only raw AP/NX/PA叶检查、107项实际allocator
边界，以及normal/secure实际writer检查通过。实机结果另记。


### r93 实机：完整 HWSCHED START 通过

普通GPU6表/1536叶、GMU9表/1675叶及独立secure4表/893叶均核对通过。
GPU-only kind7/flags147 counter使用GPU620c0000、GMU0；随后shared kind24/flags33f
PREEMPT_SCRATCH也在同轮应答。全部10条资源应答被消费，最终START已回复：
stock result0，HWSCHED result0、completed9/9。87930字节完整CRC日志自动取回，
保护分区/GPT/misc一致。未执行GPU OOB、CP/fence/Metal。

### r94 最低DCVS、GPU OOB与GX只读候选

按固定OnePlus453d8875 `gen7_gmu_dcvs_set`/`gen7_gmu_oob_set`/
`gen7_gmu_gx_is_on`及Ace5同芯片流程，完整START后发HFI30 blocking
ACK类型1、freq index1、BW index1（本机已验证table最低非零档）。匹配完整
header与真实legacy ACK后，仅发GPU OOB bit30，等新ACK31，再只W1C该bit31。
初始IRQ/host OOB若已占用则拒绝；不启用中断、不清其他位、不自动释放OOB租约，
所有资源随外层CM3 reset确认及cold recovery reset保持。

CPU先以AT确认三个目标页是identity Device，不读取GX。实际GPU电源/时钟
状态低2位为0、AHB fence=0、CX busy bit23clear、normal/secure图和live root
及三个SMMU无有效fault，才读RBBM_STATUS(3d00840)、STATUS3(3d0084c)、
CP_SQE_CNTL(3d02020)。每次gated read前重新核对条件；没有CP/GX配置写、
PM4、PAS或XNU。HFI/OOB/GX ready均有策略轮询上限；单次MMIO不可抢占。

46项状态机/故障/部分副作用及295011项实际native读写门检查通过。运行原厂
固件期间只记RAM，CM3 reset确认后保存完整vote回复、有效位/状态及last operation，
自动返回OrangeFox。实机结果另记。


### r94 实机：最低 DCVS、GPU OOB 和 GX 读取通过

CPU Device AT检查通过。HFI30 header150041e收到匹配legacy3字ACK、value0，
没有捏造不存在的status字。初始IRQ1/host0，发bit30后新ACK80000001，
只清31后IRQ仍1。GX状态3→0、AHB fence0、CX busy71000000（bit23clear），
门内实际读RBBM_STATUS1、STATUS3=0、CP_SQE_CNTL0。GX code0/phase6，
21读/2写，3个SMMU仍FSR400无有效fault。88728字节CRC日志自动取回，
保护分区、12组GPT、misc保留区一致；没有CP执行或Metal结论。

### r95 原厂 SQE/AQE 稀疏代码内存与地址绑定候选

只用本机提取的85300字节SQE、33176字节AQE，RAM镜像构建逐文件SHA256和
读回核验；引导时严格长度/CRC、零4字节header、跳过header后整份payload及
padding读回。额外独立256KiB NormalNC分配不进入GMU图。GPU只映射
63001000/21页SQE和63021000/9页AQE为RO/unprivileged/executable；
6303f000一页record为RW/privileged/NX，所有间隔/尾部保持无效。普通GPU
图7表/1567叶/12段，GMU与secure图不变；14项lifetime ledger保持至cold reset。

完整HWSCHED和GX/OOB后，仅写/回读四个SQE/AQE instruction-base低/高寄存器，
每步重新验证图/根/电源/时钟/fence及SQE_CNTL=0，结束仍为0。无SQE enable、
RAW/PM4、信任状态修改或PAS。118666项实际文件/拷贝/图检查、27项binding
状态机、65673项实际native whitelist、122项allocator、1932项四类图配置通过。
实机结果另记。

### r95/r96 实机：代码绑定与完整 Gen7 配置通过

r95 实际文件校验和稀疏图通过，四个 SQE/AQE 地址寄存器写入/读回 verified=F，
SQE control 前后均为0；10个 HFI 资源请求全部接受。89342字节 native CRC 有效。

r96 在同一轮完成101/101配置步骤，100次写入、178次读取；48个保护跨度、
本机UBWC4/MAL32/HBB16、GBIF、UCHE、TSB和APRIV逐项验证。TXDONE实际读到3，
bit0置位，首轮poll即成功；75/75实际寄存器对进入独立6303f000恢复表，完整
CPU读回/发布，整页CRC=3ec14bba。SQE仍为0。无CP命令、PAS或Metal证明。
保护的五个启动分区、12组GPT、misc保留区一致。

101步及58个IFPC+17个preemption记录的寄存器事实来自固定OnePlus
453d8875 gen7_9_1；生成器绑定四份原厂源码SHA和本机FDT参数，算法独立实现。
源码事实和逐步有效位/原始值保留在native/gpu/uefi及实机capture中。
USB在抓取时切换ADB端口，后台监听自动重试成功，没有固定宽限等待。

### r97 首个 CP_INIT 候选

接在完整HWSCHED/OOB/代码绑定/Gen7配置之后，只执行固定bank0 CP aperture
SCM和原厂第一组RAW：CP_THREAD_CONTROL、CP_ME_INIT，使用已验证6303f000
恢复表。无预先NOP、PAS/ZAP、退出secure或fence命令，不启动XNU或HFS。
SCM采用同一已验证调用约定，仅允许固定4个立即数及合法的中断恢复cookie；
INFO可用性已在同一boot验证。原厂qcom_scm_kgsl_set_smmu_aperture传NULL结果，
成功按真实a0定义，a1只留原始数据，不误认为所有权status。

异步RAW的原厂check_ack_failure只以结果word2=ffffffff为失败；其他回复字保存，
不解释成不存在的status。固定完整首包、ACK发送者/header/count/type检查、
有限等待和前8条debug消息保留；之后验证CX idle并记录RBBM、SQE、IRQ状态。
此轮即便ACK/idle通过，也不是实际fence写入或桌面GPU加速的证据。
实机结果另记。参考原厂gen7_hwsched_gpu_boot、gen7_hwsched_cp_init、
gen7_cp_init_cmds和qcom_scm_kgsl_set_smmu_aperture；Ace5已记录900E的RAW试验
未被当成可用驱动直接复用。

### r97 实机结果：CP 阶段尚不能定位

本轮自动返回OrangeFox，取回52169字节、CRC86498324的有效native日志；最后
落盘点为before-stock-GMU-reset-release。后续RAM内的aperture/CP报告未提交。
这只是较早的有效检查点，不能说CP_INIT通过，也不能断言复位发生在该检查点。
保护的启动分区、12组GPT和misc保留区一致。

### r98 日志单项验证候选

为避免CP阶段复位后所有新信息丢失，新增独立canary：完成与r96相同的全部
前置步骤后，确认所有17队列为空、SQE0、IRQ mask0、本次尚未进行aperture/RAW，
验证GPU/GMU/secure完整图与CPU实际映射，保持OOB及所有分配，再短暂降到
APPLICATION TPL，对既有UniXNU.log执行Flush/读回/CRC；无论文件结果均恢复
NOTIFY TPL并重新检查。此轮随后先reset CM3，再正常保存报告/返回恢复。
该候选明确放宽了原先“GMU运行期间不做文件I/O”的范围，但仅限无CP的隔离
canary；不允许在CP命令提交后套用。是否兼容仍须实机验证。

日志缓冲从128KiB扩到512KiB，避免重复/组合行和debug数据导致截断。
77项TPL/失败恢复测试、81项实际native队列/映射/IRQ拒绝测试通过。
真实目标二进制验证：TPL4快照及恢复TPL16确实位于StockBootstrap中；
CP aperture/RAW回调被链接器移除。实机结果另记。

### r98 实机：运行中的 GMU 前置日志保存通过

live-GMU-pre-CP-canary实际写入/Flush/读回78848字节，status0；三个guard
全部通过，TPL16→4→16恢复，stock result0并确认reset-held1。
本轮未执行aperture或RAW。末次native文件139530字节，payload139463，
CRC17a3cb0d一致。原Mac解析器仍限128KiB，因此最初误判并反复抓取；
已停止该任务的监听进程，保留原始记录。解析器改为设备相同512KiB上限后
只读重抓同一SHA7b3f66fc…的数据通过，无设备重启或写入。

监听器同时要求native/XNU传输稳定；三次相同稳定但无效的快照会保留证据
并停止，避免类似问题反复消耗时间。快照边界、CRC、大小、旧版本拒绝和
监听的立即抓取/端口迁移/稳定错误停止测试通过。启动分区/GPT/misc保留区一致。

### r99 固定 CP_INIT 与双检查点候选

沿用r97固定scalar aperture/第一组RAW，不扩大CP命令范围。先使用r98已实测
前置快照；aperture真实a0成功且无quarantine后，再保存after-aperture-before-RAW。
第二个快照额外要求同boot首个快照成功/恢复、phase2 aperture_attempted、
实际调用与原始返回有效、尚无RAW；同样验证队列/页表/CPU属性/IRQ/OOB。
第二个点不能在RAW发出后复用。新版实际native拒绝/门控测试91项，SCM测试
262699项；CP初始化异步ACK/故障82项。实机结果另记。


r99 实机：aperture 真实调用一次，raw-valid=1、a0=0/a1=0；第二个
before-RAW 检查点83846字节，payload83780，CRC33513187一致。
随后自动返回恢复。由于没有提交CP结果，不能把最后的检查点当作已经执行
RAW或已经定位到具体复位指令的证据。启动分区、12段GPT与misc保留区一致。

### r100 CP 短轮询候选

首次固定CP命令和aperture不变。发命令前保留完整的CPU属性、三个图、
所有权、队列和GX校验；等待期间不修改图/分配/文件系统。每次短轮询仍
检查全部保留/附着/quarantine标记，先读7个常开供电与时钟寄存器，失败
便不读门控窗口。通过后读取其余12个故障/电源/固件/SCTLR寄存器和
6个精确TTBR。保留首次失败与末次样本及有效位；不清除故障。
发命令前的持久检查点保存16次短检查与一次完整guard的实际耗时，
CP返回后先由外层确认CM3复位再输出完整诊断。尚未实测，不声称提速或CP成功。
实际函数的各寄存器/根每个位变更、失去所有权、门控读取顺序和首错保留
测试263749项通过；CP协议82项和日志/TPL路径91/77项通过。


r100 实机：467µs完成16次短检查（约29µs/次），完整guard721µs；
当前六个TTBR通过。aperture仍a0/a1为0。末次快照84124字节，
payload84058、CRC9d3e80d0一致，之后自动恢复，未提交CP结果。
缩短轮询未解决这个现象；不能据此声称CP执行失败或成功。
本轮protected state验证通过，未启动XNU或修改系统卷。

### r101 提前保存 CP 结果与复位状态

命令、地址空间和本轮硬件写入范围沿用r100。新增两处窄检查点：
只有实际ACK成功/phase6/idle/CXbusy0/RBBM0/IRQstatus0/IRQmask0、
完整图与当前所有权有效、全部17队列空时才允许成功结果快照；
另在CM3复位真实读回1之后、任何后续fault MMIO之前保存RAM结果。
复位不确认时不调用第二处；全部资源和门控保持保留。
两处均沿用已验证的TPL16→4→16与Flush/readback/CRC，不在RAW在途时写文件。
这轮用于区分CP、复位和之后的诊断阶段，尚未声称硬件成功。
57项实际门控测试、872项stock状态机/副作用/失读/复位回调测试、
65929项实际native writer测试通过，原CP和TPL测试继续通过。

参考原厂hwsched初始化与adreno_gen7.h，硬件调度IRQ mask仅五个错误位，
与普通GEN7/A7XX mask不同；本轮未启用任何新中断或照搬普通mask。


r101 实机：75.5s自动回到恢复；84124字节native快照CRC57bdeebf有效。
末次仍为before-RAW，新增的ACK/idle与确认CM3复位检查点均未提交。
完整保护区验证通过。尚不能从这个结果确认RAW发送或断言已在某条指令失败。

### r102 发 CP 前完整边界验证

暂不发RAW，走相同aperture与两处完整快照/恢复guard，再重复初始已实测
GET_VALUE125查询并严格核对ACK/实际status。当前phase2、无RAW且队列空，
完整guard通过时才保存第三个检查点，证明前一个文件操作已经返回。
同时按原厂gen7_gmu_version_info读取DTCM固定五字，不从文件名猜版本。
随后继续真实CM3复位与早期结果快照。此profile不引入任何新CP或中断写入。
9项实际完整路径测试覆盖每个门控、ACK与文件错误；尚未实测。

本轮再次查询了Adreno740、AdrenoMetal和OnePlus-Ace5的GitHub最新提交，
仍分别为4e0314df、454ff2ce、aaa100d1，与当前固定参考一致。
[Adreno740](https://github.com/UniXNU/Adreno740/commit/4e0314df8ad29d52f6fa3f9383a540adcd618b87)、
[AdrenoMetal](https://github.com/UniXNU/AdrenoMetal/commit/454ff2ce83766ce7b3e0f355e83f1d72907708b3)、
[Ace5](https://github.com/tycykp/UniXNU-OnePlus-Ace5/commit/aaa100d19f6fb14e5897a7e496edf7838d4d4e9f)。
普通/硬件调度mask区别依据
[原厂adreno_gen7.h](https://github.com/OnePlusOSS/android_kernel_modules_and_devicetree_oneplus_sm8650/blob/453d8875f815bf9dfad9035982861226a4823a6c/vendor/qcom/opensource/graphics-kernel/adreno_gen7.h)。


r102 实机PASS：aperture之后再次GET_VALUE125实际ACK，value1/status0；
五个原始版本字为40020014/ffffffff/40020010/00000000/20060001，
core4.2.20。第三快照89649字节，全部三个guard、TPL恢复通过；
确认CM3复位后的早期结果95377字节，最终156884字节、payload156817、
CRC4f245d48一致。stockresult0、reset-held1，自动恢复、保护区相同。
本轮明确无RAW。因此相同aperture/完整快照返回/普通HFI/CM3退出路径可通，
先前失败范围收窄到增加的首次CP执行路径，仍不声称知道具体失败指令。

### r103 原厂 HWSCHED 本地错误掩码候选

沿用完整r102边界/版本/查询，在同一boot之后补上原厂hwsched的五位
错误掩码03400042（AHB/ATB async/ATB bus/UCHE OOB/TRAP），不复制普通
A7XX掩码。设备树GPU SPI300对应GIC INTID332：先用AT核实GICD页为
identity Device，实际IGROUPR10bit12须为1、ISENABLER10bit12须为0。
任何一项不满足都不写GPU mask，更不发RAW；没有任何GIC写入。
只允许3d000e0写入唯一固定值并回读相同，保存新检查点后才发原先相同CP_INIT。

复用本轮已经真实成功的一次aperture；独立adapter检查其真实返回、未quarantine、
边界与IRQ日志guard/TPL都完整，hci_run仍按原先固定10字PM4和11字HFI执行。
每次RAW健康检查还要求GIC NS组别/CPU禁用和GPU本地掩码不变。
只在真实ACK+idle或确认CM3复位后保存结果；不清故障，不执行PAS/unsecure/fence。
65624项实际mask写白名单、部分写回读失败、所有权与GIC门控测试通过；
原有CP/边界/快照测试通过。此差异尚未证明是根因，实机结果待记。

### r103/r104 实机结果与 r105 发送前路径验证

r103 已保存新的本地 IRQ 检查点：GIC PAR17100b00、NS groupffffffff、
CPU enable0；GPU 本地 mask0→03400042 回读成功。94856字节快照有效，
随后79.3s自动恢复，没有 CP 返回或确认 CM3 复位后的结果。

r104 只增加受限 GPU 读取异常处理：仅精确同步 external read abort、
已武装的自有单条 LDR+RET、精确 PC/X0/FAR/指令及地址白名单；失败向上传播，
不把占位零值当成有效读取，不处理 SError/写入/OEM 指令，异常内不访问磁盘。
524723项处理器策略与6项输出有效性测试，以及现有实际 CP/IRQ/DMA 测试通过。
实机80.675s自动恢复；最后有效快照94857字节，payload94791、CRC D68072DD。
没有提交读取异常、CP 返回或确认复位的结果，故不能宣称具体出错读指令已定位。
用户 IMG_0740 的 PA D2459000、D272A000、D2447000、D2437000、D2729000、
D2337000、D2237000、D1E37000、D1E2D000、D1CC6000、D1D26000、D1E26000
与本轮页账本一致；画面没有 exception/panic。五个启动分区、十二段 GPT 和
misc 保留字节均已重新核对，XNU 未执行、初始日志标记未变。

r105 在同一轮实际发送前，先运行同一个 hci_run 和 ready/aperture/health
适配器，以只复制11字命令包并拒绝的 send 替身，在发布队列前主动停止。
必须恰好 HCI_EXCHANGE/HHB_IO、phase3、一次 send、未 sent/ACK/idle、
命令包逐字正确、真实序列号不变；否则不进入真实 CP。
完整 guard/TPL16→4→16 在新检查点保存后，才继续原来的同一固定 CP_INIT。
替身不写 HFI 队列、不响 doorbell、不增加 SCM；原始序列只由真实发送消费。
274项实际预检函数/完整 hci+hll 路径及逐点 guard 故障测试通过。
这是确定发送入口是否到达的诊断，尚不代表 CP 成功或 GPU 加速可用。

r105 实机：预检 PASS，真实 hci_run 的 ready/aperture/health/包生成全部
走到替身 send；逐字保存01700B83、70970001、08000000、70C80007、
0000094B、3、20000000、2、6303F000、0、80000000。
真实序列号仍23，未发布队列/响 doorbell。新快照102025字节、
payload101958、CRC4A69CB27有效；82.578s自动恢复，仍无真实 CP 返回。
因此停止区间进一步收窄到实际发布之后，尚不能证明硬件已接收 CP。

### r106 先只收实际 HFI 回复

继承 r105 同轮预检和所有实际硬件/页表/内存属性/本地 IRQ guard。
真实发布开始前保守标记 published，即便发送部分失败，也不再做 GPU、
SMMU、GIC 的状态读取；持有全部页表/分配/时钟直到平台复位。
发布后健康检查仅检查 CPU RAM 中的保留所有权和 pin 状态；收取原有
Normal-NC HFI 消息/调试队列，保留原来的包与 ACK 合同、20000×10us上限，
同一 AO doorbell 写入。无新增寄存器值、无额外 SCM、无正在执行时的磁盘操作。
本轮只做 hci_exchange，不读取 idle/RBBM/SQE 状态；确认 CM3 复位后的已有
回调才保存回复。即使 ACK 成功，也不能称 CP idle、fence 或 GPU 加速成功。
30项实际函数故障/ACK/拒绝/坏包/超时/部分发送/发布后禁读测试和现有82项
固定 CP 合同、274项实际预检全部通过；实机结果另记。

r106 实机：86.655s自动恢复，最后有效快照102026字节、payload101959、
CRC43482F7B。没有提交 transport return 或确认复位结果，故仅取消发布后
的 GPU/SMMU/GIC 轮询尚不足以取得回复。最后快照是 save 前缀，尚不能
据此证明其最后 post-file guard 已完成，不能直接断言已执行 RAW。

### r107 最后检查点的无 RAW 对照

保留本地 IRQ mask、完整 r105 预检与最后一次文件操作/三次 guard/TPL恢复。
随后只发送已有普通 GET_VALUE125，检查 ACK/value1/status0，并通过原有
确认 CM3 复位回调保存结果。没有新的 live 文件操作，不调用真实 RAW 路径。
编译出的 EFI 保留 NO-RAW EXIT marker、LTO 移除真实 transport marker；
19项实际查询/部分失败/前置条件测试通过。此轮只用于判断停止是否发生在
最后检查点收尾或后面的真实发布区间，结果待记。

r107 实机 PASS：最后一次 preflight 文件操作的三个 guard/TPL恢复全部返回，
其后 seq23 普通 GET_VALUE125 的 ACK/value1/status0 正确；phase8、RAW-attempted0。
CM3 reset-held1、stockresult0，早期及最终结果都保存；最终171582字节、
payload171515、CRC D7E4B1E6有效，85.292s主动返回恢复。41397次受限读取
在早期复位结果中无异常。五个启动分区、十二段GPT和misc保留字节不变。
这排除了本地 IRQ mask 与最后检查点完整返回/普通传输/退出组合导致停止。
真实 RAW 发布/通知/执行区间仍需分辨，不能将对照 PASS 称为 GPU 加速。

### r108 保持发布，抑制通知

沿用 r106 的原始固定11字 RAW，正常发布 HFI 队列；通知回调在实际 AO
写入之前主动返回1，预期 HCI_EXCHANGE4/HHB_IO2，立即进入已有外层
CM3 复位与保存路径，不等待 ACK、不读 GPU/SMMU/GIC、不增加 live 文件操作。
已发布的队列可能被 GMU 自行轮询消费，故不能宣称完全没有 GPU 执行。
30项原始传输和8项抑制通知的实际函数测试通过；actual EFI 中 callback
反汇编证明没有调用 StockBootstrapDoorbell/MMIO。此轮仅隔离发布与通知。

r108 实机对照 PASS：真实队列 published1、send-code0，actual-doorbell-writes0、
receives0；预期的 HCI4/HHB2（主动中止）已保存，CM3 reset-held1，
最终171685字节、payload171618、CRC32AF0960完整。82.666s主动回恢复，
启动分区/GPT/misc保留区不变。这证明写入/发布队列并立即退出本身能完成。

### r109 实际通知后立即退出

只将 r108 的通知抑制改为调用同一个真实 AO doorbell，再立即主动返回失败，
不等 ACK、不轮询 GPU/SMMU/GIC。9项 actual callback 测试通过；编译出的
镜像使用 RETURN CONTROL marker，排除抑制通知版本。仍未取得通知后的
提交结果：85.506s自动恢复，最后有效快照102025字节、payload101958、
CRC DA531B29；没有 DOORBELL RETURN、transport return 或确认复位结果。
五个启动分区、十二段 GPT 和 misc 保留区核对不变；没有 XNU/HFS 执行。
停止区间已收窄到真实通知及紧接的固件执行/退出，不能断言具体故障指令。
异常处理器不在未知硬件状态下执行文件系统 I/O；自动读取的是最后已校验
的持久快照。下一次重复同镜像需捕捉屏幕最后异常 PC/ESR/FAR，以区分
精确 MMIO 写入 abort、SError 与后续硬件复位。当前镜像、冻结源和策略
保留原样可重用，没有再次刷写/启动。


### r110 精确通知写异常和同轮快照

所有 HFI 通知经过本应用独立的 STR/RET 叶函数，精确同 EL 同步外部写
abort 才保留失败上下文并禁止后续通知；不恢复 SError 或其他指令。
19 个通知前寄存器、19 项电源/故障租约、6 个表根以及 3 个队列游标合并到
最后一次已有 preflight 快照，没有新增等待或文件操作。
实际22次普通通知完成 STR/DSB 返回，stage3/faults0。SCACHE0/1=0、
SQEctl0、本机 SQE/AQE 基址63001000/63021000、trust1、RBBM1、IRQ0、
本地mask03400042；bank0/3 SCTLR27、FSR400。84.956s自动恢复，最终有效
快照105886字节、payload105819、CRC FEABE0B7；没有取得 RAW 后结果。
五个启动分区、十二段GPT和misc保留字节核对不变。此结果不是精确写故障
已触发的证据；它只证明普通通知在该包装中正常。

### r111 将原有两个 PM4 包分开发送

诊断版将 vendor 原有10个PM4字分为 THREAD_CONTROL 两字、ME_INIT八字，
分别组成3/9字HFI消息。正常vendor一次发11字；拆分不声称与其冷启动等价。
第一段必须取得匹配真实ACK、CX idle、RBBM0/IRQ0、17空队列、全图/CPU属性
复核及三次guard/TPL恢复快照，才能发第二段；没有新opcode或NOP。
737项实际native路径/逐位报文/故障阻断测试及82项原有整包合同通过。
编译EFI精确STR/RET在RVA6dac，真实一条SMC；源、RAM中应用和镜像已冻结。
实机83.749s自动恢复，最后快照105887字节、payload105820、CRC E0FD2F6A。
没有 prefix ACK/return 或确认复位结果，因此不能断言第一段已发送或执行，
也不能断言最后执行的指令；本轮没有功能性GPU突破。启动/GPT/misc保留区
及原有XNU日志初始标记核对不变。

### 2026-10-25 重新比较同芯片与已工作的移植

- [Ace5 aaa100d1](https://github.com/tycykp/UniXNU-OnePlus-Ace5/blob/aaa100d19f6fb14e5897a7e496edf7838d4d4e9f/docs/GPU_TERMINAL_BRINGUP.md)
  默认分支本轮查询仍是此提交。同SM8650/A750v2是板级主参考，但作者记录
  自己的RAW/NOP也未取得ACK，不能把这条路径视作已有成功实现。
- [Adreno740 4e0314df CP](https://github.com/UniXNU/Adreno740/blob/4e0314df8ad29d52f6fa3f9383a540adcd618b87/NativeAdrenoCpInit.cpp)
  和 [Ring](https://github.com/UniXNU/Adreno740/blob/4e0314df8ad29d52f6fa3f9383a540adcd618b87/NativeAdrenoRing.cpp)
  默认分支未变化。实际由主机写命令环/WPTR，显式配置ring/SQE并等待fence；
  不能把HWSCHED消息路径简单替换为该类名或把A740常量用于A750。
- [Pandora4aea93cd](https://github.com/ShueiTsuki/data-a-live/blob/4aea93cdf5b5daf8ec1215e37bdfae2c17fe0fdc/wsl/pandora_gpu.c)
  原ios-pandora API返回迁移，跟随后确认新名data-a-live。UniXNU设备页的GPU
  状态已经落后。作者GPU_PLAN记录CP、Vulkan、Metal、GPU桌面通过；新计划还
  记录128IB修复和图像格式修复，README的快速交互hang说明自身也较旧。
  实际代码采用Linux式主机ring/SQE启动，CP idle后再做PAS；没有把PAS提前。
  这些是作者记录，未由本机复现。A840的gen8寄存器/UBWC6/票据不能照搬。
- [Linux同A750v2表项](https://github.com/torvalds/linux/blob/21a7f44fd0765fcc5194130b28767786eba1d1e7/drivers/gpu/drm/msm/adreno/a7xx_catalog.c)
  包含本机chipID43051401、GMU7090100和本机同名SQE/GMU文件；
  [a7xx_cp_init](https://github.com/torvalds/linux/blob/21a7f44fd0765fcc5194130b28767786eba1d1e7/drivers/gpu/drm/msm/adreno/a6xx_gpu.c)
  提供主机ring路线。其ME_INIT mask为14b；当前vendor HWSCHED用94b。
  ring、BR/BV读指针影子、SQE启动和HFI初始化模式必须成套核对，不能混合。

### r112 主机命令环路线的 GMU 协议兼容验证

依据固定Linux21a7f44的a6xx_hfi.h/c重新编码PERF_TABLE4：body58字，
16组GX(vote/acd/freq)、4组CX(vote/freq)及两个计数字。本机已验证票据中
2个GPU档、3个GMU档写入对应位置，其余项全零。BW3沿用本机表。
同轮按序发送PERF4、BW3、CORE14、START10、GET_VALUE12/property125；
不发送HWSCHED/AQE/KPROF/IFPC/ACD feature enable，不发RAW、不触发CP、
不做GX/OOB或Gen7配置/PAS/secure内存分配。17队列传输保持原样，只用0/1/2；
不宣称它与Linux3队列布局等价，也不把没有feature enable当作模式读回。
任何意外MEM_ALLOC停止且不应答。仅确认CM3复位后保存CPU结果，自动返回恢复。
62项实际native调用、真实17队列RAM、每次传输失败/坏ACK/拒绝/查询缺状态/
意外资源请求阻断检查通过。真实EFI排除CP拆分、aperture、GX及资源回调，
保留一条原有SMC和AT/cache指令。编译/打包、59项元数据篡改检查及463源文件
冻结通过；kernel字节未变化。实机结果另记，尚不能称主机ring或GPU成功。


r112 实机：5/5消息均有真实匹配ACK，PERF4/BW3/CORE14/START10均为三字
通用回复value0；查询125为四字value1/status0；resource_count=0。
CM3确认复位，stockresult0；57.400s自动恢复，最终payload83994、
CRC BC4985DF有效，启动/GPT/misc保留区不变。
**范围更正**：以上是host bootstrap内部的行为；外层仍继承了旧路径的
RunSecureMemoryBatch/RunSecureDomainPrepare，所以本轮在START之前仍做了
secure data/table的两次MP_ASSIGN。早期候选scope将“无分配”写成全程范围
不准确；原始日志和镜像保留，后续版本按实测纠正，不改写冻结历史。

### r113 普通GPU准备的检查阻断

新host准备先要求r112完整5ACK、无资源请求、query125value1/status0，
才允许普通bank0/SID0挂接。host分支用普通/GMU上下文检查，不要求激活
HWSCHED secure bank3，但严格拒绝任何意外已owned/attached的secure状态；
原有HWSCHED检查保留。79项实际native编排、63项协议、295020项实际GX
门控/写入、1932项真实SMMU图与故障阻断、46项DCVS/OOB策略检查通过。

实机5ACK和普通bank0挂接通过；后面的GX phase1/code2资格检查正确拒绝，
尚未发送DCVS vote或OOB，GX reads0/writes0。日志明确显示外层在此前已经
转移secure data/table所有权，和新分支的严格前置条件冲突，并非GPU再次
异常复位。正常CM3reset-held1，55.669s返回恢复；最终payload84796、
CRC6976F157有效，五启动分区/十二段GPT/misc保留区不变。无CP/code/config
成功结论；phase0报告的零值代表未执行，不能当成功。

### r114 移除host路径外层的旧HWSCHED分配

从RunGmuProbe中移除RunSecureMemoryBatch/RunSecureDomainPrepare实际调用，
保留原有GMU所需secure-CX服务。旧函数仅地址引用以供编译检查，LTO应删除
分配/MP_ASSIGN调用；资格门控保持严格，不接受意外的secure ownership。
同轮仍完成5条HFI、普通GPU挂接、minimum vote/OOB、固件地址、Gen7配置与
三guard/TPL快照，然后确认CM3复位、自动恢复。SQE维持0；不启动ring/CP，
不调用aperture/PAS。没有新的用户数据或系统卷写入。

后续host-ring实现需核对普通环/BR与BV读指针影子、CP_SQE_CNTL启动与停止、
有界fenced-WPTR写、idle/实际写回验证和发生超时时的日志许可，不能只复制
一个原始提交。Linux adreno_hw_init仍会对bank0调用SMMU aperture服务，
需要保留实际参数与返回值验收。vendor的ME_INIT bit11表示禁用DMS（不是
SMMU信息开关）；原HWSCHED94b和Linux14b差异需要按功能选择核对。


r114 实机完整准备 PASS：5/5普通HFI ACK、resources0；普通bank0/SID0挂接、
最低档vote及OOB唤醒全部通过。四个SQE/AQE地址读回一致；101/101寄存器操作、
75/75恢复记录对、CRC3EC14BBA。完整host guard/TPL快照完成并恢复，随后
实际CM3reset-held1、stockresult0。日志没有secure ownership/table-share记录。
71.910s自动恢复；最终native 124215字节、payload124148、CRC165F262C有效。
五启动分区、十二段GPT、misc保留区核对不变，XNU初始标记未变。
这是主机ring路线的准备基线；SQE仍0，未编程/敲响ring，未证明CP、fence或Metal。
当前镜像/源码/策略保留冻结状态，实测更新在evidence/native-ios-r114-result.json，
新一轮准备尚未执行。


### r115–r118 主机环与 AdrenoMetal 接口边界

r115–r118 已加入固定主机环、独立 GPU-only 写回区、CP_INIT 与两次独立
CP_MEM_WRITE 的实际 native 实现，以及停止/总线隔离和精确同步写异常诊断。
这些版本的最后有效持久化快照仍在 SQE 启动之前；不能由该快照中尚为零的
计数推断后面的 STR 没有执行，也不能报告 CP、canary 或停止路径已实机通过。

r118 自动返回 OrangeFox 后在 84.481 秒取回本轮 native 快照，payload101371、
CRC09BCDE53 与独立计算一致。XNU 文件只有本轮初始标记，尚未提交。
五启动分区、十二段 GPT 与 misc 保留区只读复核不变。当前没有新一轮正在启动。

用户指定主线为 AdrenoMetal。已新增 [iOS 16 前端构建与合并探针](adrenometal-ios16.md)，
固定它配套的 metal2vulkan 和 Turnip，保留正式类/ABI，取消 A740 默认自测及
固定 iPadOS17 QuartzCore 地址。插件、桥接、Turnip 和 iOS 探针编译及签名结果
单独保存在本地 out/ 和 native-port/；不据此报告 GPU 或桌面加速成功。
下一次有可执行的 A750 XNU 后端后，用同轮计算、绘图和 IOSurface 读回判定真实结果。
