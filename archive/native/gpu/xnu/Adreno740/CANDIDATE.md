# XNU CPU 页适配候选

此目录是未集成、未经真机验证的内存层候选。从 `UniXNU/Adreno740` 的固定提交
`b686b9054f57d393c80195b82568a09f8ca106a2` 复制；原始文件 SHA-256 记录于
`source-manifest.json`。原始参考目录未修改。这里的上游 A740 平台地址、硬件初始化
和 README 中的历史实测结果，不代表小米 14 的 XNU 后端已实现或可直接加载。

## 本候选改变的边界

- CPU VM 支持两种严格一致的配置：编译页、运行时 `page_size`、kernel map 页大小均为
  4096，且 TG0/TG1 为 0/2；或三者均为 16384，且 TG0/TG1 为 2/1。MMU 必须启用，
  TTBR1 根必须非零。`NativeAdrenoQueryCpu4K` 继续保留旧的严格 4 KiB 查询语义。
  不接受尚未验证的混合页配置；资格失败不会继续分配。
- `NativeAdrenoMemory::bytes()/spans()` 是 GPU 逻辑范围，保留 4 KiB 单位。
  `ownedBytes()/ownedSpans()/cpuPageBytes()` 描述完整 CPU backing。独占分配显式请求
  向上圆整的 backing，逐 CPU 页检查原始物理段，清零并发布整个 backing，再把 GPU
  span 截到逻辑长度。没有把 CPU 页号当作物理字节地址，也没有把 GPU 叶改为 16 KiB。
- `allocate` 的 budget 限制实际 backing；调用者通过 `backingBudget(logical_bytes)`
  显式计算运行时圆整预算。单 BO 的实际 backing 仍不超过 256 MiB。
- 第一版禁用池化。即使 `pooled=true`，每个 BO 也采用独占分配；保留的 pool API
  返回 Unsupported／0，不会把一个 CPU 页切给相邻 BO。
- CPU pmap 页号来自已经验证的运行时 CPU shift。页属性检查、写入、读回和默认属性恢复
  均覆盖完整 CPU 页；先验证原属性为已知默认值，避免声称能够恢复未知模式。pmap 写入
  没有返回状态，因此读回不符视为失败，BO 留在 quarantine 中，不能回收或创建新 CPU view。
- `cpuView()` 只允许正常持有的独占分配；`NativeAdrenoPublish.cpp` 仅用其完整 backing
  物理段创建用户 CPU view。`BoCpuMap` 回复完整 backing 长度。GPU 逻辑长度和 ABI wire
  结构、版本及方法编号不变；向上圆整的尾部属于本 BO，已清零，不映射到 GPU。
- 导入只接受完整 CPU 页对齐的 task 地址和长度，先 prepare/wire，再逐 CPU 页验证原始物理段、
  宽度与长度并留存。导入不会改变 pmap 属性，也不能创建第二个 CPU view。
  只读 pin 的 GPU 权限限制、持久 memory entry 和设备引用生命周期保留。
- cache-line PoC 维护仍可在独占 backing 内处理 4 KiB 对齐的 GPU 子范围；页属性操作
  则始终采用完整 CPU 页。物理 aperture、CPU／GPU 排他和缓存别名仍须实际 XNU 资格验证。
- 提交前的 pmap 属性重检是强制步骤。无论返回 Unsupported、IOError 或其他错误，VM
  都隔离失败的 BO；Submit 保留已经 hold 的 IB 引用并进入 poisoned 状态，返回原始错误，
  不执行 sample、publish、TLB 更新或 GPU kick。失败对象即使不属于当前 IB 列表也会留存。
  可选 cache-line 审计缺少 board hook 时的 Unsupported 与此错误分开处理。
- descriptor complete 失败，或属性写入／恢复结果不确定时，完整 backing、两组 span
  和 descriptor 留存。设备引用未退休前不能释放；本候选不会自动重置或强行释放。

## 未完成的验证

host fixtures 只能验证控制流、地址计算、范围、保留语义和实际源码的 IOKit/pmap 调用边界。
它们不会证明当前 XNU 每核 TCR／TTBR、实际物理 aperture、pmap 属性、用户映射隔离、DMA
一致性、A750 SMMU／ring／fence 或 Metal 桌面加速已经可用。尚未编译上层插件、加载驱动、
更换运行内核或操作手机。后续必须先只读采集实际 XNU 页几何，再测试一个由 XNU 自己
分配并 pin 的完整 CPU backing 和对应四个 4 KiB GPU 叶。

## 实际内核头 object 资格

沿 `r136-kernel-build.log:1257` 的真实 HoujiUfsRead.cpp 编译 argv，在原 iokit build
目录使用同一套 XNU 源／导出头、KERNEL/KERNEL_PRIVATE、ARM64、SWEET、PAGE_SIZE_FIXED
与 SDK 参数，只替换输入、object／依赖输出路径并增加本候选及固定依赖的 include 路径。
`NativeAdrenoCpu.cpp`、`NativeAdrenoMemory.cpp`、`NativeAdrenoVm.cpp` 与
`NativeAdrenoSubmit.cpp` 均生成 ARM64 Mach-O OBJECT，零编译错误。原命令的
`-Weverything` 仍产生真实内核头／宏告警，并非零告警构建；没有为通过资格放宽宏或屏蔽它们。
具体 argv、source/object SHA 和结果见 `validation-result.json`。

这是 object 类型/API 资格，未链接内核或 kext，也没有加载或执行这些 object。
主机回归为 CPU4K 121／CPU16K 125 个页边界场景，以及每种 CPU 页各 7 个真实
Submit/VM/Ring 失败传播场景，均使用 ASAN、UBSAN 与 `-Werror`；原内存回归
18 个分配、16 个失败和 20 个参数场景保持通过。
