# 小米 14 CPU 接入与调度参考

更新日期：2026-10-25。r55 已通过八核内核预检，r56 已运行八核 iOS 桌面；
早期双核诊断保留在下文作为历史记录。

## 八核实机结果

设备树和每核实测相互核对：CPU0/1 为 A520（MIDR `410fd801`），CPU2～6 为
A720（`410fd811`），CPU7 为 X4（`410fd821`）。MPIDR 为 `81000000` 加逻辑编号乘 `100`。
r55 在挂载根卷前完成七颗副核心的绑定任务；每核定时器和 IPI 都有接收计数，
日志明确记录 `HOUJI SMP PREFLIGHT: PASS; 8 cores`。

实现串行化副核心注册/启动，为七颗副核心分别传递 PSCI context；每核检查自己的真实
MIDR，不再把所有核心标记为 A520。ADT 保存当前设备树的 capacity、频率域和缓存元数据。
目前仍采用单个调度 cluster 的保守 Clutch SMP，元数据本身不等于能力感知调度；
没有实现 AMP、EPSS DVFS 或温控策略。r56 用户确认全屏设置列表滚动明显改善，
但“关于本机”存在界面冻结，尚不能视为完整稳定性验证。

当前 Darwin 22 内核日志已经报告 `Scheduler: Default of clutch`。调度器存在；现有 SweetCPU 驱动原先只注册启动核心。要让现有调度器使用更多核心，首先需要接通副核心的物理启动入口、每核定时器与核间中断。

| 参考 | 实现与证据 | 应用于 houji 的部分 |
| --- | --- | --- |
| [UniXNU ArmCpu](https://github.com/UniXNU/ArmCpu/blob/1951cc8444b340d7d8879e9418220cf29eb711d7/ArmCpu.cpp) | PSCI `CPU_ON64`，从 ADT 读取 SMC/HVC conduit；延后副核心注册；独立线程调用 `processor_start`；清理代码和启动数据的缓存；GIC IPI | 保留这些启动顺序和缓存同步原则，适配当前 Darwin 22 的接口。继续使用已在 houji 单核验证的 SGI1，不复制其他机型的 SPI 回退地址 |
| [一加 Ace 5 Pro / hummer](https://github.com/2426120557/UniXNU-hummer/blob/db47684cd099fa026cbd4f8f0bbd37422aba08c6/scripts/build-hummer-armcpu-probe.py) | 记录了高层 affinity 被 XNU 截断后与启动核心重复，以及 ADT 暴露数目与驱动接收数目不一致的问题；该原型只暴露首六颗可识别核心 | ADT、驱动、XNU topology 三方必须一致。先暴露 houji 的 `0` 与 `0x100`，逐一核对，不直接修改 `cpus=8` |
| [Linux arm64 PSCI](https://github.com/torvalds/linux/blob/master/arch/arm64/kernel/psci.c) | 使用逻辑核心到 MPIDR 的映射，以副核心物理入口调用 PSCI | 参考标准固件接口和启动契约，不把 Linux 调度器代码移入 XNU |
| [Linux EAS](https://docs.kernel.org/scheduler/sched-energy.html) | 根据异构核心的 capacity、负载、性能域与能耗模型选择运行位置 | 后续大小核适配必须有真实拓扑与能力信息。EAS 不是可直接装入 XNU 的插件 |
| [XNU Clutch，同版本源码](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/osfmk/kern/sched_clutch.c) | XNU 的原生线程组、QoS bucket、运行队列与负载分配 | 首对同规格核心继续使用现有 Clutch，不同时修改调度算法 |
| [Snapintosh 状态文档](https://github.com/Snapintosh/Snapintosh/blob/main/docs/STATUS.md) | Snapdragon X2 Elite 的 macOS 实验，通过 EL2 平台接口运行多个虚拟 CPU | 可借鉴逐核诊断；它的硬件和虚拟化路线不同，不能替代当前原生 EL1 移植 |

## 首对核心的实机依据

来源为已保存的 Android 运行设备树 `live-fdt.dtb`，SHA-256 为 `04dad3a2a40758525e93109ef17954183500a86c7bdf77973b89e39f97723807`。

- CPU0 与 CPU1 的 `reg` 分别是 `0`、`0x100`，相同 frequency domain 和 capacity，共享所记录的 L2。
- 启动核心实测 MIDR `0x410fd801`，对应 Cortex-A520。r41 副核心实测 MIDR 同为 `0x410fd801`，MPIDR 为 `0x81000100`。
- PSCI method 是 `smc`。
- GICD 为 `0x17100000`，GICR 为 `0x17180000`，redistributor stride 为 `0x40000`。原有通用代码默认 `0x20000`，首核启动不会充分检验这个差异。

原型只允许一核默认配置或显式启用两核配置。Darwin 22 原 reset vector 在当前编译配置下只按 Aff0 查找 CPU，故新增 PSCI 物理入口，以 context 传入对应 `cpu_data` 地址，保留原有启动代码处理页表、栈和 MMU；没有整体改变其他平台的 topology 配置。

## 硬件验证门槛

双核原型的编译和主机测试通过不代表手机双核可用。首次测试需在挂载 HFS 之前停止，记录：

1. 两颗核心完成 `ml_processor_register` / `processor_start`，PSCI 返回成功。
2. 副核心报告正确 MPIDR/MIDR，两个逻辑核心都有定时器和 IPI 接收计数。
3. 绑定 CPU1 的内核任务完成 30 次心跳，CPU0 接收到跨核心 SGI。
4. 将结果写入既有固定日志文件，并返回 OrangeFox；不修改系统卷。

这些通过后再让双核运行 iOS 用户态。随后接入不同规格的核心时，还要处理 XNU 的 cluster/AMP 拓扑、能力描述、跨簇 IPI 与缓存一致性，不能把全部核心一直描述成同规格 A520。

r37 实机已到 CPU0 online，但在请求 CPU1 后 panic。照片中的返回值 `3288334339`
等于调用号 `0xc4000003`。反汇编确认新增封装里的 `dsb sy; smc #0` 被 Darwin
汇编器按注释处理，最终没有 SMC 指令。因此该轮没有真正调用 CPU_ON，不能据此
判定固件拒绝副核心启动。修正版改用换行，并通过独立编译、负例测试和最终链接
内核的机器码检查，确认 DSB 后存在 `d4000003`（SMC #0）。修正后的实机结果另记。

## 自动调频是另一层工作

多核调度决定线程在哪颗核心执行；DVFS 决定对应性能域的频率和电压。当前原型没有写入 EPSS 性能请求、频率、电压或热管理寄存器。CPU 频率必须先由已校验的计数采样确认，ADT 中的静态 `clock-frequency` 不能当作当前频率。

后续自动调频需要连接 Qualcomm EPSS/OPP、负载反馈、限温与电源约束，再验证稳定性；直接固定最高频率不能算作完成自动调频。

## locationd 与启动界面

r34 的完整 stackshot 显示 CoreLocationMigrator 等待超过十分钟，SpringBoard 的 shell check-in 又等待 backboardd 的迁移完成。locationd 中一个相关线程停在无超时的 MIG 调用，消息 ID 为 1203、期望回复为 1303，接收服务尚未证实。

新增的可选被动观察器只记录该请求的目标 PID、端口类型、队列长度和回复计数，定期写入现有日志；不改变消息、超时、返回值、迁移完成标记、Setup 或激活状态。需要新一轮硬件运行才能判定实际等待对象。多核可能缩短初始化时间，但不能作为消除服务互相等待的证明。


## r41 双核预检结果

两颗 A520 均完成启动。CPU1 绑定任务完成 30 次心跳，定时中断计数 609/114，
核间中断计数 40/72；已提交带运行编号及 CRC 的原生日志并自动返回 OrangeFox。
首次通过的版本将启动辅助线程绑定 CPU0，并在副核初始化后发送一次远程 SGI；
尚未单独证明这两项中哪项必需。后续用户态保留两项。

CPU0 的约 100 ms 只读忙碌采样为 1,689,595 kHz（约 1.69 GHz）。这不代表固定、
最高频率或已实现 DVFS，未修改频率、电压、温控或调度算法。

r40 的新增 GICR_IGROUPR0 读取曾在 CPU0 触发 data abort。对应诊断已全部改为
CPU 接口系统寄存器读取，未继续探读 redistributor SGI 内存区。
