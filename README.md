# UniXNU-houji — Xiaomi 14 iOS 16 Port

[简体中文](#简体中文) | [English](#english)

> **项目状态 / Project status:** 实验性开发，不是日常可用系统。  
> **Experimental development — not a daily-driver operating system.**
>
> 本文状态更新于 **2026-11-24**。  
> Status updated on **2026-11-24**.

## 简体中文

### 项目简介

**UniXNU-houji** 是一个基于 [UniXNU](https://github.com/UniXNU/UniXNU) 的**小米 14 社区设备移植项目**，目标是在非 Apple ARM64 硬件上启动并运行 iOS 16。项目以小米 14 的设备代号 **`houji`**、SoC **Qualcomm Snapdragon 8 Gen 3（SM8650）** 和 **Adreno 750** GPU 为硬件基础，围绕 UEFI 启动、XNU 内核适配、存储与显示、触控输入和电源管理开展移植。

目前已在真机上进入并操作 **iOS 16.7.16（Build 20H392，Darwin 23.6）** 的锁屏与 SpringBoard 主屏，显示分辨率为 **1200 × 2670**。当前桌面基线使用 **CPU 合成**，不代表 GPU 加速已经完成。

这是一个独立的社区移植项目，**不由 UniXNU 组织官方维护**。

### 硬件与系统目标

| 项目 | 配置 |
| --- | --- |
| 设备 | Xiaomi 14 |
| 设备代号 | `houji` |
| SoC | Qualcomm SM8650 / Snapdragon 8 Gen 3 |
| CPU | 1 × Cortex-X4 + 5 × Cortex-A720 + 2 × Cortex-A520 |
| GPU | Qualcomm Adreno 750 |
| 内存 | 12 GiB |
| 面板 | 1200 × 2670 OLED |
| 存储 | UFS |
| 目标系统 | iOS 16.7.16 / Build 20H392 / Darwin 23.6 |
| 兼容性用户态身份 | iPhone X（`d22ap` / `iPhone10,3`） |
| 渲染方式 | CPU 合成；Adreno 750 加速正在开发 |

> 这里的 iPhone X 身份是移植环境使用的兼容性配置，并不表示小米 14 使用 iPhone X 的硬件，也不表示完整的 iPhone 功能兼容。

### 当前进展

以下功能已在真机上验证，记录日期为 2026-11-23 至 2026-11-24。

| 功能 | 当前状态 |
| --- | --- |
| XNU 启动 | 可启动 XNU 并进入用户态 |
| CPU / SMP | 八核在线；已记录各核用户态运行时间与跨核中断 |
| 存储与根卷 | 原生 UFS、APFS 系统根卷和可写 Data 卷可完成启动 |
| 桌面 | 可进入并操作锁屏与 SpringBoard 主屏 |
| 显示 | 1200 × 2670 全屏显示；当前由 CPU 合成 |
| 触控与手势 | 点按、底部上划回桌面、上划停顿进入多任务、左缘返回已通过真机验证 |
| 音量键 | 物理音量加、音量减可用 |
| 电池 | 启动后可读取实时电量与充电状态 |
| 电源键 | 短按锁屏并关闭 OLED，再次短按可唤醒 |
| 唤醒画面 | 已改为等待新画面写入后再点亮面板，减少上一帧闪现 |
| 开机触控 | 驱动注册与首个触控数据包的等待时间已显著缩短 |
| 诊断与恢复 | 支持启动轮次标识、日志保留和自动返回 Recovery |

### 技术路线

项目采用 UniXNU 的分层结构，将通用启动能力与设备适配分离：

```text
设备 UEFI
   ↓
UniXNU / DarwinBoot
   ↓
针对 SM8650 与 houji 适配的 XNU
   ↓
原生 UFS + APFS 系统根卷 / Data 卷
   ↓
显示、触控、输入与电源管理驱动
   ↓
iOS 16 用户态 / SpringBoard
```

主要工作包括：

- **UEFI 与启动链：** 完成设备固件适配、启动载荷传递和 XNU 启动。
- **平台与 SMP：** 适配 CPU、GIC、定时器、中断和跨核唤醒。
- **存储：** 通过 NativeUfs 提供系统与 Data 存储窗口，并挂载 APFS 根卷。
- **显示：** 实现 framebuffer / surface 服务和 CPU 合成上屏，保持面板原始分辨率。
- **输入：** 适配触控控制器、手势坐标和物理按键。
- **电源与续航信息：** 处理 OLED 开关、锁屏唤醒和电池状态读取。
- **GPU：** 正在推进 Metal → `metal2vulkan` → Turnip Darwin → NativeAdreno 的 A750 用户态加速路线。

### 尚未完成与限制

| 方向 | 当前状态 |
| --- | --- |
| A750 GPU 加速 | 已开展 GMU、SMMU 与固件启动诊断；命令提交、fence 和 Metal UI 加速尚未完成 |
| 预置应用恢复 | 尚未完成 |
| 持续负载温控 | 仍需验证 iOS 运行中的峰值温度、动态调频和长期稳定性 |
| 无线与外设 | Wi‑Fi、蜂窝网络、蓝牙、音频、相机和传感器等未纳入当前桌面基线的验证范围 |
| 系统兼容性 | 以启动和核心交互为目标，不保证完整 iPhone 应用、服务或硬件兼容 |
| 安装体验 | 没有通用的一键安装器；系统镜像、Data 和分区布局需要按开发记录准备 |

因此，**“能够进入桌面”不等于“已经可以作为主力系统使用”**。当前成果应理解为设备移植和硬件适配的阶段性进展。

### 仓库与资料

| 仓库 / 资料 | 用途 |
| --- | --- |
| [Kizashi3/UniXNU-houji](https://github.com/Kizashi3/UniXNU-houji) | 本项目的小米 14 设备仓库：板级配置、XNU 补丁、设备驱动、诊断与构建脚本 |
| [UniXNU/UniXNU](https://github.com/UniXNU/UniXNU) | 上游通用构建工具、UEFI 包、OS profile 与可复用组件 |
| [UniXNU 设备列表](https://github.com/UniXNU/UniXNU/blob/main/docs/devices/index.md) | 查看官方与社区设备移植条目 |
| [UniXNU 文档](https://unixnu.com/) | 构建、启动、移植与日志采集指南 |

### 开发与风险声明

- 项目面向**研究、学习和硬件移植验证**，不对刷写造成的分区损坏、数据丢失或设备故障负责。
- 安装或测试前应备份重要数据，并保留可恢复的固件与 Recovery。
- 系统根卷、Data 种子、内核与启动参数必须互相匹配；不要混用不同测试轮的产物。
- Apple 系统文件、固件及供应商二进制文件不随本介绍提供，也不应被随意重新分发。
- 具体构建输入、固定提交和镜像校验值以对应测试轮的记录为准。
- 欢迎提交设备日志、复现步骤、问题报告和经过真机验证的改进；请勿将未上机的结果描述为已支持功能。

---

## English

### Overview

**UniXNU-houji** is an independent community device port built on [UniXNU](https://github.com/UniXNU/UniXNU). Its goal is to boot and run iOS 16 on non-Apple ARM64 hardware, specifically the **Xiaomi 14** with codename **`houji`**, **Qualcomm Snapdragon 8 Gen 3 (SM8650)** and **Adreno 750** GPU.

The project covers UEFI boot, XNU adaptation, storage and display, touch input, and power management. On physical hardware, it has reached an operable lock screen and SpringBoard home screen on **iOS 16.7.16 (Build 20H392, Darwin 23.6)** at the panel's native **1200 × 2670** resolution.

The current desktop baseline uses **CPU composition**. This does **not** mean that GPU acceleration is complete.

This is an independent community port and is **not officially maintained by the UniXNU organization**.

### Hardware and Target System

| Item | Configuration |
| --- | --- |
| Device | Xiaomi 14 |
| Codename | `houji` |
| SoC | Qualcomm SM8650 / Snapdragon 8 Gen 3 |
| CPU | 1 × Cortex-X4 + 5 × Cortex-A720 + 2 × Cortex-A520 |
| GPU | Qualcomm Adreno 750 |
| Memory | 12 GiB |
| Panel | 1200 × 2670 OLED |
| Storage | UFS |
| Target OS | iOS 16.7.16 / Build 20H392 / Darwin 23.6 |
| Compatibility userland identity | iPhone X (`d22ap` / `iPhone10,3`) |
| Rendering | CPU composition; Adreno 750 acceleration is in development |

> The iPhone X identity is a compatibility configuration used by the porting environment. It does not mean the Xiaomi 14 uses iPhone X hardware or guarantees full iPhone feature compatibility.

### Current Progress

The following features were verified on physical hardware in records dated 2026-11-23 to 2026-11-24.

| Feature | Current State |
| --- | --- |
| XNU boot | XNU starts and enters userland |
| CPU / SMP | Eight cores online; per-core user time and cross-core interrupts recorded |
| Storage and root | Native UFS, APFS system root and writable Data volume support startup |
| Desktop | Lock screen and SpringBoard home screen are accessible and operable |
| Display | Full-screen 1200 × 2670 output; CPU-composited |
| Touch and gestures | Taps, bottom swipe home, swipe-and-hold for multitasking, and left-edge back verified on hardware |
| Volume buttons | Physical volume up and volume down work |
| Battery | Live charge level and charging state are readable after startup |
| Power button | Short press locks the screen and turns off the OLED; another short press wakes it |
| Wake display | Panel activation waits for a new frame, reducing stale-frame flashes |
| Early-boot touch | Driver registration and first touch-packet delays have been substantially shortened |
| Diagnostics and recovery | Run identification, retained logs and automatic return to Recovery are supported |

### Technical Approach

The project follows UniXNU's layered design, separating reusable boot infrastructure from device-specific integration:

```text
Device UEFI
   ↓
UniXNU / DarwinBoot
   ↓
XNU adapted for SM8650 and houji
   ↓
Native UFS + APFS system root / Data volume
   ↓
Display, touch, input and power-management drivers
   ↓
iOS 16 userland / SpringBoard
```

Major work areas include:

- **UEFI and boot chain:** device firmware adaptation, boot payload handoff and XNU startup.
- **Platform and SMP:** CPU, GIC, timers, interrupts and secondary-core wake-up.
- **Storage:** NativeUfs-backed system and Data windows, with an APFS root volume.
- **Display:** framebuffer/surface services and CPU-composited scanout at native panel resolution.
- **Input:** touch-controller integration, gesture coordinates and physical buttons.
- **Power and battery information:** OLED power control, lock-screen wake-up and battery-state reporting.
- **GPU:** development of the Metal → `metal2vulkan` → Turnip Darwin → NativeAdreno route for Adreno 750 acceleration.

### Work in Progress and Limitations

| Area | Current State |
| --- | --- |
| A750 GPU acceleration | GMU, SMMU and firmware-start diagnostics are underway; command submission, fences and Metal UI acceleration are not complete |
| Bundled application restoration | Not complete |
| Sustained-load thermal management | Peak temperature, dynamic frequency scaling and long-term stability under iOS workloads still require validation |
| Wireless and peripherals | Wi‑Fi, cellular, Bluetooth, audio, camera and sensors are outside the verified desktop baseline |
| OS compatibility | Targets boot and core interactions; full iPhone application, service and hardware compatibility is not guaranteed |
| Installation experience | No universal one-click installer; system images, Data and partition layout must follow the relevant development records |

Reaching the desktop is a porting milestone, not a daily-driver release.

### Repositories and Documentation

| Repository / Resource | Purpose |
| --- | --- |
| [Kizashi3/UniXNU-houji](https://github.com/Kizashi3/UniXNU-houji) | Xiaomi 14 board configuration, XNU patches, device drivers, diagnostics and build scripts |
| [UniXNU/UniXNU](https://github.com/UniXNU/UniXNU) | Upstream build driver, UEFI package, OS profiles and reusable components |
| [UniXNU device list](https://github.com/UniXNU/UniXNU/blob/main/docs/devices/index.md) | Official and community device-port entries |
| [UniXNU documentation](https://unixnu.com/) | Build, boot, porting and log-capture guides |

### Development and Risk Notice

- This project is intended for **research, education and hardware-porting validation**. It is not responsible for damaged partitions, lost data or device failure caused by flashing or testing.
- Back up important data and preserve a recoverable firmware and Recovery environment before installation or testing.
- The system root, Data seed, kernel and boot arguments must match. Do not mix artifacts from different test rounds.
- Apple system files, firmware and vendor binaries are not distributed with this introduction and must not be redistributed casually.
- Build inputs, pinned revisions and image checksums are defined by the corresponding test records.
- Hardware logs, reproducible steps, issue reports and device-verified improvements are welcome. Do not describe untested results as supported features.
