# 开发指南

## 环境与输入

已使用的主机环境是 Apple Silicon macOS、Xcode 27.2、Python 3.12 或更新版本、Clang，以及 Rust 1.98.0 的 `aarch64-apple-ios` 目标。UEFI 使用 Linux 容器构建。Mesa 还需要 Meson、Ninja、支持 `-Wcounterexamples` 的 Bison 3.8 或更新版，以及 Mako/PyYAML 等 Python 构建依赖；不要让 macOS 自带旧 Bison 遮盖它。

下列输入需在本地自行取得，不能提交到 Git：

- iPhone X 的 iOS 16.7.16 / 20H392 IPSW，以及从中提取的用户空间、设备树和所需文件。成员校验值见 `board.toml`。
- 对应的 XNU 构建工具、KDK 和 Xcode SDK；本仓库不重新分发 Apple 的二进制输入。
- 自有设备匹配版本的 Qualcomm / OEM 固件、UEFI 二进制依赖和 GPU 固件。
- 设备的 GPT、引导链、校准、通信和恢复分区备份。

本仓库保存的是实机开发源码，尚未验证在全新电脑上一次性构建全部组件。以下流程分别验证源码组装和组件，不应将组装成功等同于可刷写镜像。

## 离线检查

```bash
python3 tools/check-source-tree.py
python3 tools/run-host-checks.py
```

检查需要 arm64 主机、Python 3.12+、Clang（含 ASan/UBSan/TSan 运行库）及 Rust 1.98.0。
默认在 Apple Silicon macOS 执行全部检查，Linux arm64 执行可移植检查并明确报告未覆盖的项目。
SMMU 检查会编译 AArch64 绑定，因此不能在 x86 主机直接运行完整套件。
可用 `--suite portable` 单独检查公共逻辑，或在 Apple Silicon macOS 使用 `--suite apple`
检查 Foundation、Metal、IOSurface、Mach 采样及 Darwin 日志线程。
CI 分别运行 Ubuntu 24.04 arm64 的可移植检查和 macOS 15 的完整检查；不会以 Linux 通过代替
Apple 接口验证。这里的 macOS 检查仍不执行手机 GPU。

检查覆盖 GPU 的 12 个频点、上限取整、突发负载与空闲降频、HFI 表一致性、CPU 交互升降频和 Turnip BO 复用回归；另外编译有效 Submit/VM/SMMU 源码，在 4 KiB/16 KiB CPU 页的主机替身上验证缓存维护、TLB 同步、地址复用及失败隔离。板级提交门、显示队列和 shader 预热检查也执行有效源码中的函数。另测 TSENS 有效位/有符号温度/滞后与丢失读数，以及亮度范围、渐变和 DSI FIFO 的忙碌/超时/恢复。BO 检查会在同一线程交错条件下验证旧函数失败、修复函数通过。ASAN/UBSAN 检查不仿真 GPU 命令执行或证明实际 FPS。

GPU 参数、显示/预热行为和实机对照流程见 [性能修复](performance.md)。

## 组装固定版本源码

先取得 `sources.lock.json` 中对应仓库及提交，再从一个已有 Git 仓库向**全新输出目录**组装：

```bash
python3 tools/prepare-sources.py kernel \
  --upstream /path/to/xnu --output .deps/kernel
python3 tools/prepare-sources.py bootloader \
  --upstream /path/to/DarwinBoot --output .deps/bootloader
python3 tools/prepare-sources.py uefi \
  --upstream /path/to/Mu-Silicium --output .deps/uefi
python3 tools/prepare-sources.py graphics/turnip \
  --upstream /path/to/mesa --output .deps/turnip
python3 tools/prepare-sources.py graphics/runtime \
  --upstream /path/to/metal2vulkan --output .deps/metal2vulkan
```

工具读取 Git 中的固定提交，先校验和应用补丁，再复制覆盖层，不改变输入仓库的工作文件。输出包含源码，不包含 Git 子模块。UEFI 子模块须按锁文件的 `uefi_submodules` 单独准备，并应用 `uefi/patches/` 中对应的子模块补丁。OEM 二进制、BootShim、ramdisk 和最终 FD 打包仍需要板级构建配置，不能直接使用其他机型的产物。

内核覆盖层包含 r222 原构建使用的 `config/MASTER.arm64.sweet`。该文件必须随组装树保留；缺失时构建会回退到通用配置，漏编 `nos_arm_asm`、`nos_arm_pmap` 和本机文件系统，不能只凭 C/C++ 编译结束判断内核可用。
该配置还启用 `no_kextd`，与内置驱动及没有 IOKit daemon 的 iOS 根卷对应。检查实际生成的 `no_kextd.h` 为 `NO_KEXTD=1`；不能以手工减 busy 计数替代正确的构建模式。r242 已确认根注册表不再忙碌，用户估计 About 首次进入不到 10 秒、明显加快；不能将其扩展为 Wi-Fi 或所有系统服务均已完成。
本次也补回了同一构建树中因旧编码注释漏导出的 14 个 HFS 源文件/头文件；仅将注释中的非 ASCII 字节写为 `\xNN` 文本并规范空白，保留代码和许可。

## 固件头文件

内核需要的 GMU、SQE、AQE 数据只保存长度和 SHA-256，见 `kernel/firmware-inputs.json`。从自有匹配固件取得原始文件后生成私有头文件：

```bash
python3 tools/make-firmware-headers.py \
  --gmu /path/to/gmu.bin --sqe /path/to/sqe.bin --aqe /path/to/aqe.bin \
  --output .local/firmware-headers
```

将生成的两个头文件放入本地组装树的 `iokit/Kernel/houji-ufs-root/`，不要复制到仓库的公开覆盖层。哈希不匹配时应重新检查厂商版本，不能为绕过检查随意改动校验值。

## XNU 构建

准备好内核树、KDK、CTF 工具及内核构建依赖后：

```bash
export HOUJI_XNU="$PWD/.deps/kernel"
export HOUJI_KDK=/path/to/KDK/Payload
export HOUJI_FAKEROOT=/path/to/darwin-build-tools
export HOUJI_BUILD_ROOT="$PWD/out/kernel"
bash tools/build-kernel.sh
```

入口沿用已使用的 `DEVELOPMENT ARM64 SWEET` 配置和 Darwin 22 参数。先验证 KDK/CTF 路径与两个生成头文件的测试身份一致，再更新时间戳，避免复制旧时间戳后增量构建漏编。生成绑定必须来自当轮日志分配，不能重放旧测试标识。组装树缺少 `IOHIDUsageTables.h` 时，构建脚本会从当前 macOS SDK 复制到该本地树；也可用 `HOUJI_HID_USAGE_HEADER` 指定本地匹配头文件。这份 SDK 输入不能加入公开覆盖层。LLDB 调试脚本的安装入口已改用 `python3`，不要求系统存在 `python` 别名。脚本不负责下载 SDK、创建系统卷、组装 UEFI 镜像或写手机。`tools/iig-darwin22.py` 是此旧内核配置使用的兼容入口。

## 图形组件

`graphics/bridge/Cargo.toml` 使用仓库中的前端源码和 `.deps/metal2vulkan`。构建还需要本地提供的 AIR 输入（原构建的 `NMB_FIXTURE_AIR` / `NMB_FC_AIR`）、对应 LLVM 工具和 Mesa 头文件。运行时标识必须随源码变化而更新，以免错误复用 shader 缓存。

组装 `.deps/metal2vulkan` 后，用匹配的本地 Turnip 动态库构建 bundle：

```bash
python3 tools/build-metal.py \
  --mesa-include /path/to/mesa/include \
  --fixture-air /path/to/runtime_examples.air \
  --function-constant-air /path/to/function_constant.air \
  --turnip /path/to/libvulkan_freedreno.dylib \
  --output out/metal
```

入口校验运行时来源和全部 Rust 文件的锁定身份，使用 `graphics/bridge/Cargo.lock`、Rust 1.98.0
及 iOS 16 目标，构建 Rust、PM4 与 Objective-C++，输出签名 bundle、输入/产物校验和和命令记录。
调试符号 `NativeAdrenoMetal.dSYM` 保存在输出目录、位于 bundle 外，签名前即移出，避免运行包依赖未安装的调试资源。
可用 `--runtime` 指定另一份按锁组装的源码；`--target-dir` 复用已有 Cargo 产物。
`--primelist /path/to/NativeAdrenoMetal.primelist` 可内嵌从对应系统镜像枚举的绝对 `.metallib` 路径，
避免渲染进程不能读取 bundle 旁的清单。构建报告记录条数和哈希；这份系统版本相关清单保留在本地。
编译必须通过 rustup 的 Cargo 代理选择 1.98.0；只有 Homebrew Cargo 时不能使用 `+1.98.0` 语法。
`--turnip-render-mode autotune` 构建显式对照版本，让 Turnip 选择 GMEM/系统内存；默认仍为
`sysmem`。两者的默认环境均关闭并发分箱；已有进程环境不会被覆盖，日志 `TU mode/flags`
记录编译选择与实际环境。构建报告记录选择，主机检查只验证配置与环境处理，不证明 GPU 稳定性。
只生成本地组件，不挂载系统卷或写设备；仍需检查目标 iOS 用户空间导入符号和实际运行。

Turnip 的 Darwin 后端与内核 `NativeAdrenoABI.h` 必须匹配。128-IB 扩展通过 Query 的 `NativeAdrenoParamsSubmitBatch` 协商，method 17 接收 3104 字节；旧 method 5 保持 416 字节/16-IB。新运行时在旧内核使用旧接口，不在提交失败后重新发送。检查同时执行实际直接/隧道传输、分批顺序、128 个引用的 fence 生命周期、完整 ring 包捕获及板级校验；这些主机检查不证明 GPU 执行和性能。

Metal 前端与 Rust 对象桥接也必须一起构建：`NmbTextureDescriptor` 为 120 字节，包含 `allowGPUOptimizedContents` 与四个通道来源。`checks/texture-properties.py` 将实际前端函数生成的 C ABI 数据交给实际 Rust 转换函数，覆盖两种优化属性、全部 1296 种通道组合及非法值；不执行 GPU 混合或证明阴影颜色正确。

颜色定位可在构建时显式传入 `--diagnostic-fresh-pattern green`：仅把新优化私有 RGBA8/BGRA8 纹理原本的初始图案换为绿色。默认构建不启用；构建工具清除环境里继承的诊断值，记录选项，并派生独立运行时/缓存身份。`INIT green-marker=1 plans=N` 确认诊断已启用及生成计划次数，不代表这些纹理均创建或显示成功。该版本会改变初始内容，不能发布为颜色修复，也不能与已预热版本作帧率对照。
本入口已在已有开发环境验证，完整 Mesa、UEFI、系统卷和全新环境的一次性构建仍未完成。

## 实机验证

测试需区分：UEFI 启动、XNU 启动、GPU 命令完成、渲染正确性、持续交互性能。频点请求成功、GPU fence 完成或软件 120 Hz 通知，均不能单独证明桌面达到目标帧率。

每轮保留源码标识、组件哈希、镜像与分区布局、运行 UUID、带校验的日志和用户观察。日志可在返回 OrangeFox 后提取；处于早期异常或硬件锁死时仍可能无法保存最后一次调用。恢复和保留策略见 [recovery.md](recovery.md)。

原始分区、CRC/UUID 校验及本轮 iOS 崩溃报告的公开采集入口见[日志采集](log-capture.md)。

## 用户空间兼容库

```bash
python3 tools/build-userland-compat.py --output out/userland-compat
```

该入口构建并签名 `/usr/lib/HoujiKeyboardGeometry.dylib` 的本地候选，不修改镜像或设备。保留已使用的键盘几何逻辑，并包含[状态栏适配](display-geometry.md)。r238 的 Core Image 软件 context 尝试在实机无效，已撤下；构建不再含该 hook。目标用户空间导入、系统卷原文件所有者/权限及签名仍须分别校验。

Metal 的七个异步函数/管线创建入口使用串行后台编译队列，提交前复制可变描述符，回调在独立队列执行；同步入口保持原行为。`ASYNC` 行记录各类请求、完成、回调和排队耗时。主机门控检查执行实际入口并验证返回时机、参数快照、生命周期、错误/反射传递及回调重入，不证明手机上已改善动画。

`tools/build-metal.py` 同时输出 `NativeAdrenoMetal.clients`，由 `graphics/metal/NativeAdrenoMetal.clients` 固定输入。将它作为 `/System/Library/Extensions/NativeAdrenoMetal.clients` 安装，不能只替换 bundle。新增的 Preferences 名单必须配套 `HoujiGpuClientLayout.h` 的第五个受限窗口；进程名不构成 SMMU 隔离，既有沙箱、窗口边界及失败隔离继续生效。

r238 的桌面进程 ASYNC 计数全部为 0；同步编译和其他进程仍需分别分析。驱动接入与验证顺序见[待完成项](roadmap.md#按依赖推进)。
