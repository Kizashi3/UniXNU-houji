# GPU 地址窗口与共享内存

2026-10-31 核对。下面的 GiB/MiB 均为二进制单位。GPU 虚拟地址窗口、物理 RAM、片上 GMEM 和预留页池是不同资源。

## 其他项目的配置

| 源码 | 配置 | 含义 |
| --- | --- | --- |
| [UniXNU/Adreno740 `5c8c1453`](https://github.com/UniXNU/Adreno740/blob/5c8c1453c67d6ef6b10ec43ab1f8fc570a2f33e1/NativeAdrenoPublish.cpp) | 主渲染进程 1 GiB，其他三个窗口各 `0x0AAA9000` 字节，约 170.66 MiB | 四个客户端共享页表，驱动检查窗口；不是每个进程独立的 SMMU 地址空间 |
| [UniXNU-sheng `08cde20e`](https://github.com/UniXNU/UniXNU-sheng/blob/08cde20edc3254ed6f7df8d0f5384fb887786e8f/package/GpuPowerProbe.cpp) | 板级输入地址 32 位，设备信息声明从 `0x20000000` 起的 3.5 GiB 范围 | 设备范围和上述客户端窗口是两层限制，不能把 3.5 GiB 当成每个应用的显存额度 |
| [高通 KGSL `2b2d762c`](https://github.com/qualcomm-linux/kgsl/blob/2b2d762c0b843c560d2ae2203f6b3cfe1474fb3f/kgsl_iommu.h) | 64 位路径的普通 GPU VA：`0x4000000000..0x8000000000`，共 256 GiB；SVM 另有范围 | 大虚拟空间按需映射 RAM，不会预留等量物理内存；这是高通参考驱动配置，不是本机 Darwin 已实现的能力 |
| [Linux DRM/MSM](https://linux.googlesource.com/linux/kernel/git/torvalds/linux/+/1f57f68c4dd101e5e8ffc9ffa6428f45bcdd776a/drivers/gpu/drm/msm/adreno/adreno_gpu.c) | 按 IOMMU geometry/设备特性建立 VM，支持进程地址空间 | 需要完整的页表、上下文、映射和回收机制，不能只移植一个容量常量 |

## 小米 14 设备树核对

对照小米官方 houji/SM8650 基础树、[SM8650 GPU 公开设备树](https://github.com/onelots/android_kernel_xiaomi_sm8650-devicetrees/blob/d9d0fc2cd8138d3fa0523e226ea5460380c4d240/qcom/graphics/gpu/pineapple-gpu.dtsi)，并核对本机保存的 live FDT：

- GPU 用户、LPAC、安全通道分别使用 SMMU stream 0、1、2。GPU 节点中没有本仓库主渲染进程的 1 GiB 限制。
- 六个 `qcom,gpu-mempools` 项的块大小/预留数量为 4 KiB × 2048、8 KiB × 1024、64 KiB × 256、128 KiB × 128、256 KiB × 80、1 MiB × 32，合计 100 MiB。
- [KGSL 页池实现](https://github.com/qualcomm-linux/kgsl/blob/2b2d762c0b843c560d2ae2203f6b3cfe1474fb3f/kgsl_pool.c) 把这些数用于预分配，并包含从系统分配页面和收缩页池的路径。它们不是 GPU 总内存上限。
- GMEM 是片上分块渲染存储；当前平台信息中的 3 MiB 不能当成共享 RAM 的上限，也不能靠设备树扩成数 GiB。

因此，修改 Android DTS 的页池大小不会改变 Darwin 驱动中的客户端分区。GPU 可以通过 SMMU 将较小的虚拟窗口映射到不同物理地址；本机现有输出地址宽度为 36 位，不意味着只能访问 RAM 的前 4 GiB。让 GPU 使用更多共享内存仍须留出内核、应用和显示所需的 RAM。

## 本次扩容候选

`HoujiGpuAddressLayout.h` 统一约束页表所有者、启动检查、客户端窗口、提交地址及 TLB 刷新范围：

- 总页表覆盖从 2 GiB 扩至 4 GiB；保持 32 位输入、36 位物理输出和关闭 TTBR1 的配置。
- 主渲染窗口从旧的 `0x20000000..0x60000000` 移至 `0x80000000..0x100000000`，容量从 1 GiB 增至 2 GiB。
- r231 已验证的三个其他窗口为 256/192/192 MiB；启动固件、GMEM 和 ring 映射保持原位置，该轮客户端数量为四个。后续 Preferences 候选见下表。
- 页表从 1027 个有效 4 KiB 页面增至 2053 个；为 CPU16K 所有权对齐，实际分配 2056 页，约 8.03 MiB。三个尾部填充页都必须为零。增加的内存约 4.02 MiB，并非预分配 4 GiB RAM。
- 发布用户客户端之前，在 `0x40000000`、`0x80000000`、`0xc0000000`、`0xfffff000` 分别完成八次 GPU 图案写入与核对，每轮取消映射并恢复原始页表 CRC。

主机 ASAN/UBSAN 检查覆盖实际 VM/SMMU 代码的高地址映射、解除映射、4 GiB 边界及整数溢出拒绝。主机检查不等于真机渲染验证。扩容仍需检查实际启动结果、分配错误及更大页表带来的校验成本。

### 启动对照与修正

- r228 使用上述 2 GiB 窗口和高地址自检，用户确认未进入桌面。校验有效的日志记录到 2053 个有效页表页已准备完毕；没有保存高地址自检完成记录。
- r229 保留 4 GiB 页表覆盖，仅恢复旧 1 GiB 客户端窗口与低地址自检。用户确认进入系统、亮度可调，但文字乱码、粉色区域和低帧率仍存在；日志仍有纹理 OOM。这个对照不能证明高地址 GPU 访问已可用。
- 排查发现启动自检把新映射固定置于列表首位；当测试地址高于启动映射时，违反 `ArmSmmu4KLiveAudit` 要求的地址排序。修正为按 IOVA 插入，在映射前准备完整列表。使用实际 SMMU 更新/审计代码的 CPU4K/CPU16K 主机回归重现旧列表的拒绝，并验证新列表在高地址及最后 4 KiB 页的映射、取消映射和原表恢复。
- r230 保持旧客户端窗口，仅运行修正后的启动自检，预期不进入桌面。真机在 `0x40000000`、`0x80000000`、`0xc0000000`、`0xfffff000` 各完成八次图案写入，CRC 均为 `e843b26a`，四次映射/取消映射均成功，原始页表恢复；Native 提交共 80/80 次完成。
- r231 恢复 2 GiB 高地址主窗口，用户确认进入桌面；回收日志确认 backboardd 的窗口为 `0x80000000..0x100000000`。乱码、粉色和卡顿仍在。保留的 backboardd 统计没有分配错误，但它在本轮重新打开过客户端，不能推断整轮没有 OOM；PridePoster 仍报纹理内存不足，AegirPoster 仍被槽位限制拒绝 20 次。窗口扩容已在桌面路径生效，渲染正确性和流畅性没有通过。

进一步超过 4 GiB，需要扩展输入地址位宽、所有映射/命令边界和测试，并考虑按需分配页表与独立进程 VM。当前全表审计方案不宜直接铺满高通参考驱动的 256 GiB 范围。

## Preferences 客户端（r239 已验证接入）

r238 的通知页面仍因没有 Metal 设备而进入未完成的 GL 路径。`HoujiGpuClientLayout.h` 为该进程保留第五个槽位；通用进程不能占用它。新增范围位于原 1 GiB 渲染窗口已经移走的部分。

| 槽位 | 地址范围（末端不包含） | 容量 |
| --- | --- | --- |
| 0：render server | `0x80000000..0x100000000` | 2 GiB，保持不变 |
| 1：通用 | `0x10000000..0x20000000` | 256 MiB，保持不变 |
| 2：通用 | `0x64000000..0x70000000` | 192 MiB，保持不变 |
| 3：通用 | `0x70000000..0x7c000000` | 192 MiB，保持不变 |
| 4：Preferences | `0x20000000..0x30000000` | 新增 256 MiB VA |

每个窗口仍须通过实际启动映射的冲突检查；任何重叠都会拒绝发布。32 位输入、36 位输出、页表覆盖和物理 RAM 保持不变；窗口仅限定可映射地址。计数数组扩为五个用户槽位加独立内核行，生命周期仍由原 issuer 锁、fence 和失败隔离管理。进程名分配是接入策略，不是硬件安全隔离。主机检查覆盖所有 32 种占用状态、地址冲突拒绝和计数边界，不能代替设备打开/退出/渲染验证。

r239 的 Preferences 已连接槽位 4（基址 512 MiB、窗口 256 MiB），拒绝次数为 0；用户确认通知页可打开，启动前后日志比较没有新增 Preferences IPS。它验证了接入前提，不代表所有 CoreImage/shader 路径已完成，也未解决“关于本机”等待、粉色和乱码。
