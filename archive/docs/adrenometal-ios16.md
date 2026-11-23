# houji 的 AdrenoMetal iOS 16 候选构建

主线采用 [AdrenoMetal](https://github.com/UniXNU/AdrenoMetal)：Metal Objective-C
前端 → 固定版本 metal2vulkan → Turnip Darwin 后端 → XNU 的实际 GPU 接口。
前端可编译不等于 A750 已能执行，也不代表 iOS 桌面已经加速。

## 固定输入

| 输入 | 提交 |
| --- | --- |
| AdrenoMetal | `454ff2ce83766ce7b3e0f355e83f1d72907708b3` |
| metal2vulkan | `720ef1ce9ae2a2068999a8675717418b9416283e`，加 AdrenoMetal 记录的七个补丁 |
| NativeAdreno ABI | `b686b9054f57d393c80195b82568a09f8ca106a2` |
| AdrenoPM4 | `445f8fe6d115738352b9d78dc70af6d61aa7f62f` |
| GopFramebuffer wire | `8666a9950c9699b368931d18cac92c0fdb2ce9c0` |
| Mesa | `85fda3b36405bcaea8bffc64aa4f2651dc90770d`，加主仓库记录的九个补丁 |

Mesa 使用 `adreno-compiler-inputs.json` 的实际构建输入，不能误用另一份研究清单中
`c823a83e` 的源码再标成同一构建。此版本设备表包含本机 chip ID `43051401`／FD750；
这仅证明存在相应的编译配置。未取得本机 GPU 输出前，不报告其运行成功。

## iOS 16 调整

`native/gpu/metal/adrenometal-ios16.patch` 只应用于构建输出的源码副本：

- 移除默认 discovery 中 A740 专用的 raw-PM4 自测；保留正式 AdrenoMetal 前端。
- 禁用固定 iPadOS 17 QuartzCore 地址的读写，不把这些偏移用于 iOS 16。
- 接受参考实现记录的 `_MTLDevice` 528/536 字节布局，其余布局拒绝；实际布局须由手机探针记录。
- 保留原运行时类、bundle、桥接符号和 ABI；Turnip 从 bundle 同目录或 `/usr/lib` 加载。
- 保留上游 clients 白名单。当前候选仅列 `adrenometalprobe`，尚未选择 backboardd。

参考 iOS 16 用户态适配来自 `ShueiTsuki/data-a-live` 的
`tools/metal/build_plugin.sh` 和 `adapt_ios16.py`。没有复制 A840 寄存器、内存票据，
也没有把其他机型的硬件验证算作本机结果。

## 构建与检查

`scripts/build-adreno-metal-plugin.py --help` 给出完整路径参数。依赖 Xcode iPhoneOS SDK、
本地 Rust 1.98/aarch64-apple-ios、LLVM 21 llvm-as、glslc、spirv-val、Vulkan 头。
用 LLVM 组装上游自有 IR fixture，不需要下载 Metal Toolchain；输出仍为 iOS ARM64。
安装本地依赖无需改动系统默认 Rust 或 shell 配置。签名产物应放在本地仓库的 `out/`，
避免云盘自动添加的 Finder 元数据干扰 bundle 签名。

`scripts/build-adreno-turnip-ios16.py --help` 给出 Mesa、ABI、Meson 和本地工具路径。
使用 iOS 16.0 最低版本、release/NDEBUG、Darwin KMD、不嵌入任何未知来源的 shader pack。
脚本检查并反向重构全部记录的补丁，生成精确 source ID、ABI 摘要和签名结果。

`scripts/check-adreno-metal-ios16.py` 使用 PyYAML 和本地 `ipsw`，从用户提供的
20H392 dyld cache 生成导出 stub 并检查所需符号及 re-export 闭包，另行记录可选的
weak import。它不证明 Objective-C selector、动态加载或 GPU 兼容性。

`scripts/assemble-adreno-metal-candidate.py` 只打包检查过的本地产物，不访问手机。
加入 Turnip 后重新签名并记录额外 owner trust CDHash；不改动原有 Apple 信任模块。
没有对应的 A750 XNU 后端时，候选明确标为不可安装运行 GPU。

## 合并实机探针

`native/gpu/metal/AdrenoMetalProbe.mm` 编译为 `adrenometalprobe`。默认只检查
ABI、plugin/Turnip 加载和真实驱动接口；没有服务或 chip ID 不符时直接报告失败。
传入 `--execute` 后才执行实际工作：

1. 上游桥接自测：1000 个计算结果、64 个绘图 texel、4096 个导入缓冲 texel。
2. 要求全部进度标记实际到达、返回无错且错误输出数均为零。
3. 调用 Metal discovery 使用的真实插件初始化方法，创建 Objective-C Metal device。
4. 把 IOSurface 预填为不同的 CPU 哨兵值，再用 GPU 清屏，检查 4096 个像素实际写回。

每个阶段输出独立 JSON 行；stdout 是普通文件时立即 fsync，便于重启后取回。
120 秒进程 watchdog 不能恢复不可中断的内核或总线故障。通过探针仍需另做桌面
合成、持续交互和稳定性验证，不能把这个小图测试称作完整桌面加速。

当前本机尚无 CP 实际执行、GPU 写回或 fence 完成的可靠证据，不能发布假的
IOAccelerator 服务来绕过它。r118 的最后有效 UEFI 检查点仍在 SQE 启动之前；
前端/Turnip 构建与此硬件问题分开记录。手机保持 OrangeFox，未为这些本地构建刷写。

## 本地检查结果（2026-10-25）

- iOS ARM64 Rust 静态桥、AdrenoMetal bundle、Turnip dylib 和合并探针均编译成功。
- 三个上游自有 smoke shader 经 glslc 编译，并通过外部 spirv-val 校验。
- 插件 366、探针 74、Turnip 248 项非可选导入／coalesced binding，共 688 项，
  在 20H392 cache 的 43 个导出/re-export 镜像中检查通过。Turnip 另有 5574 个
  可选 weak import，未把它们当作运行时可用功能。
- `out/adrenometal-ios16-candidate-v1/` 已生成，三个 Mach-O 的 iOS 16.0 最低版本、
  4 KiB 签名、文件摘要和重签名前后 import 表检查通过。
- `manifest.json`、`qualification.json` 与 `out/adrenometal-ios16/target-import-audit/result.json`
  保存实际结果；没有执行 iOS 动态加载、GPU 测试或桌面加速验证。
