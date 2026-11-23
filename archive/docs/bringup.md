# 小米 14 单核 XNU 实机记录

2026-10-23，在已解锁 Bootloader 的 23127PN0CC / houji / SM8650 上使用
`fastboot boot` 临时启动，全程没有 flash、erase、格式化或分区表操作。

## 已确认结果

第三版 XNU 临时镜像在原生硬件上依次完成 UEFI、只读 RAM FAT 文件系统、
DarwinBoot、Darwin 22.6.0 内存初始化、NVRAM proxy 解析、平台专家及单核 CPU 初始化。
用户提供的 IMG_0655.MOV 最后清楚显示：

```text
HOUJI CPU: matched SM8650 boot CPU provider
HOUJI CPU: starting registered boot processor
MAC Framework successfully initialized
SWEET CPU: boot CPU 0 registered, SGI1 verified, initialization complete
```

`SWEET` 是早期移植内核沿用的编译配置名称；实际 ADT、匹配项、CPU 和 framebuffer
已改为 houji。该完成日志位于 `ml_processor_register`、`processor_start` 和 SGI1
真实中断自测之后。ADT 只有 CPU0，CPU 驱动会拒绝多 CPU 拓扑；没有启动其他核。

## 各次结果

| 镜像 | 实机结果 | 处理 |
| --- | --- | --- |
| UEFI r1 | EnvDxeEnhanced AutoGen.c:650 | 恢复 FD_Reserved 内存区名称以发现 scheduler HOB |
| UEFI r2 | DxeMain.c:561，缺少 Capsule 协议 | 添加始终拒绝更新的协议实现 |
| UEFI r3 | BmDriverHealth.c:553，缺少 FormBrowser2 | 按上游配置设 ZeroGuid，跳过健康修复页面 |
| UEFI r4 | 进入 UniXNU 默认三选项菜单 | 完成基本 UEFI 验证 |
| XNU r1 | 默认菜单倒计时 Return to firmware，未观察到载荷 | Android ramdisk 的传递方式尚不能依赖 |
| XNU r2 | Darwin 22.6.0 进入 VM 初始化，随后 NVRAM CHRP panic | 将 FAT 载荷嵌入 Image，并修正绝对路径；下一版补齐 NVRAM proxy |
| XNU r3 | CPU0 注册、启动和 SGI1 自测完成 | 达到本阶段目标 |

XNU r2 同时改变了载荷传递和配置路径；仅凭结果不能把 r1 的失败唯一归因于 ABL
忽略 ramdisk。嵌入 Image 的方案已经实机验证，仍无需添加物理存储驱动。

## 日志中的提示

- `"name" not a kext` / `"AAPL,phandle" not a kext`：XNU 的 OSKext 扫描器遍历
  memory-map 属性时遇到非 kext 名称，记录日志后继续；不是本轮停止原因。
- `gPanicBase is still not initialized`：没有配置 Apple panic 日志区，函数打印后返回。
  这影响 panic 日志保留能力；视频证明它没有阻止单核初始化。
- 目前停留在日志界面不代表 iOS 已安装。此阶段不包含可挂载的系统卷或用户态。

## 构建与证据

成功镜像：`houji-xnu-r3.img`，6,950,912 字节，SHA256：

`fe7398049ad4de05390c656f8c9681b3bb3c28a13d28107434ac4866c83a6833`

内核：Apple XNU 8796.141.3 / DEVELOPMENT_ARM64_SWEET，15,899,672 字节，SHA256：

`206c962e4c800b1781fb9af56d340e61f7c2681cabe75b2b4f9d7305feea4196`

DarwinBoot 固定于 `85332b317ee80898fc78939ea64e6ca52d3837a3`，修改 Darwin 22
boot_args 布局；Mu-Silicium 固定于 `42fe563791e51bf5500c2e470ed294ca0c94b97c`。
参考 Ace 5 仓库固定于 `18f51ec652501c62e19dd4f1035dc51daa2a3361`，Vermeer
早期补丁参考固定于 `d68e05df683f863f054b0f9c063c54d2b1342b2a`。

本地证据根目录：
`${HOUJI_ARTIFACTS}/native-port/`

- `evidence/uefi-xnu-r3-result.json`：实机结论、视频摘要、SHA256 和测试边界。
- `evidence/uefi-xnu-r3-single-cpu.png`：从用户视频提取的成功帧。
- `xnu-r3-trial.jsonl`：ADB / fastboot 命令及原始结果。
- `device-baseline/bootstate-before-xnu-r3.txt`、`bootstate-after-xnu-r3.txt`：
  返回 Android 后系统版本、槽位、vbmeta digest 和五个启动分区哈希完全一致。
- `firmware-xnu-r3.log`、`xnu-early-build-r3.log`：构建日志。

## 尚未覆盖

只完成单核早期启动，没有验证持续运行、其他 CPU、挂载系统卷、iOS 16.7.16 用户态、
GPU 加速、触摸、音频、网络、休眠或 USB 日志。用户提供的 iOS 16.7.16 / 20H392
仍是后续用户态测试输入；本次内核不是 IPSW 内未经修改的 T8015 内核。

Mac 端日志接收脚本已准备，但手机当前固件没有 USB CDC ACM 后端。
需要继续适配 SM8650 的 USB device 控制器、DMA 和日志输出链路后才能直接采集。


## 2026-10-24 后续实机进展

当前目标已继续到 iOS 用户态，尚未进入 iOS。以下结论有实机画面或返回 Android
后的采集支持，不把离线编译当作运行成功。

- `pstore-r1`（IMG_0658.MOV）报告在 A7200000 写入 130 字节标记；返回 Android
  后 `/sys/fs/pstore` 为空，没有验证跨重启取回。不能作为可用的自动日志通道。
- 扩展 SMMU 诊断在首个 S2CR 读取处出现外部访问异常；改为 SMR-only 后，首遍
  107 项扫描成功，但第二遍 SMR[0] 重读仍出现同类异常。因此不能断定是 S2CR
  特有权限限制，供电、访问时序和平台初始化仍待核实。
- `smr-single-r2`（IMG_0660.HEIC）单次扫描通过：一条有效显示映射，USB SID40
  没有有效映射。预检未写 SMMU、未启用 DMA。随后进入日历初始化，等待超过
  一分钟仍无完成标记；单核注册和 SGI1 自检再次通过。定时器诊断正在接续。
- `highram-probe-r1`（IMG_0661.HEIC）中，整个候选高区保持 EFI Reserved，
  只有六个指定 16 KiB 页面被逐页保存、两种模式写读并恢复原内容。6/6 页面
  全部通过，AT S1E1W 的 PAR 属性为 WB，地址转换符合目标。没有测试整片高区、
  6 GB 分配、XNU 高地址 RAM 或 USB 上传。
- 高内存测试返回 Android 后，五个启动分区哈希仍与原始基线一致。六个 UFS LUN
  的双 GPT 头、分区项数组已只读备份并核验 CRC；没有重分区。

完整 iOS 16.7.16 HFSX 系统卷和逐块验证的 5.63 GiB 压缩 backing 已在 Mac
生成。RAM COW 后端和 GUI 内核已离线链接；尚未在实机绑定、上传或挂载该根卷，
不能宣称 launchd、Setup 或 SpringBoard 已运行。

新增证据位于 `native-port/evidence/`，保留原图、镜像 SHA 和各次启动命令日志。
高内存候选默认关闭；`HOUJI_RAM_PROBE=1` 只能与 Conventional/RootRAM 功能
关闭时一起构建。实验镜像仍使用 `fastboot boot`，不刷写启动分区。


## 2026-10-24 持久化方案范围调整

用户先说明“安卓不用保留”，随后明确选择“系统和个人数据都可以清空”。这是最新范围，
替代早期保留 Android/userdata 的要求；整套压缩根卷上传 RAM 的路线已暂停。
后续先验证 UFS 和引导，再根据具体镜像/布局执行必要的清空与刷写，不为准备实验
提前破坏仍可用于 ADB 的 Android 环境。

37 个校准、通信/设备状态及 A/B 引导相关分区已只读备份，912,203,776 字节，
每份本地副本与手机端 SHA256 一致。manifest 位于任务证据根的
`recovery-backup-20261024/manifest.json`。其中包含设备特有数据，应留在本机，
不提交源码仓库。该备份不是完整 ROM 或用户数据备份，也不包含 RPMB 导出。

候选布局优先复用现有 `super_ext`（2 GiB）放 FAT32 引导文件，`userdata`
（约 480 GiB）放 iOS HFSX 卷；先避免移动任何物理分区边界。GPT 类型、启动项、
日志专用区域和文件系统最终大小待 UFS 只读验证后固定。此记录不是已刷写结果。

### UFS 原厂驱动前置服务预检

`storage-probe-r1` 的 IMG_0664.HEIC 显示 Clock、SCM、PlatformInfo 和 USB Function
IO 均缺失；因此应用没有启动 UFSDxe。仅找到一个内存盘 BlockIO，没有物理 GPT
通过，不能解释成 UFS 已可用。返回 Android 后五个启动分区与基线完全一致。

接续的 `foundation-r2` 限于本机提取的 SmemDxe、DALSys、HWIODxeDriver、ChipInfo、
PlatformInfoDxeDriver、ULogDxe、ScmDxeCompat。原始 PE 逐字节复制，保持本机来源
manifest；生成代码保留各驱动真实 DEPEX 的 GUID 合取，启动前逐项验证，并额外要求
真实 OEM Kernel/Scheduler、ULog 的 DAL 和 SCM 的 ChipInfo。缺失依赖或驱动返回
错误后停止，不伪造协议。此版本不包含 UFSDxe，不装载时钟、SMMU 或存储驱动。
当前仅通过离线构建，实机结果待单独记录。

`foundation-r2` 的 IMG_0665.HEIC 显示 OEM Kernel/Scheduler 的 EFI 协议缺失，
因此被应用的全局前置门挡住，七个服务均未启动。这不能证明调度器 HOB 缺失。
对本机 SmemDxe 的反汇编已确认：0x1c34 的构造函数先 LocateProtocol，失败后
在 0x1cf8 通过 GUID 8ec2bd8d-56d7-49ef-8796-631778f8ebf8 查 HOB，从 +0x18
读取真实接口地址。PlatformPeiLib 也实际构造此 HOB；r2 的门过严。
返回 Android 后五个启动分区再次与基线一致。

`foundation-r3` 将检查改为匹配原厂的 EFI 协议/HOB 两条获取路径。它核验 HOB
长度、接口及锁表在已映射 RAM 中、接口版本和 InitLock 函数位置，不发布替代
Kernel 协议、不修改原厂函数。其余七个模块及 DEPEX 门保持不变。已通过离线
编译与镜像解包校验，实机结果待反馈。

用户反馈 `foundation-r3` 自动返回 Android，未拍到屏幕，具体停止点未知。返回
Android 后 bootreason 仅为 `bootloader`，pstore 为空，五个启动分区哈希不变。
不能据此认定 Smem、SCM 或任何特定服务已执行或发生故障。

接续 `hob-only-r4` 默认只检查 HOB，15 秒停留后输出检查步骤；除既有 EnvDxe 外，
七个待测服务 PE 已从载荷删除，只有显式 `--foundation` LoadOptions 才会进入
服务加载分支，而该镜像的配置不提供此参数。用于区分 HOB 检查与原厂服务
初始化阶段，尚不作为重启问题已修复的结论。

组织仓库与 Wi-Fi 调查见 [上游模块对照](upstream-modules.md)。

`hob-only-r4` 的 IMG_0667.HEIC 显示 `HOB-only checkpoint PASS`：接口地址
`A703FD38`，版本 `0x1000B`，锁表地址 `A703FD10`，接口/锁表/InitLock 位置均通过
已映射 RAM 检查。没有启动额外 OEM 服务，也没有在此测试中调用该接口。
返回 Android 后五个启动分区再次与基线一致。该结果验证这次 HOB 读取路径可用，
仍不把 r3 自动重启归因到某个未观察到的服务。

`smem-only-r5` 将显式 `--smem-only` 限为服务表首项，载荷只有额外的本机原始
SmemDxe，缺少其他六个服务和 UFSDxe。LoadImage 前停 15 秒，打印加载结果与
基址后，StartImage 前再停 20 秒；结束后核对真实 SMEM 协议是否出现。若 SMEM
已存在则拒绝重复初始化。此版本用于区分映像加载与入口执行，实机结果待记录。

`smem-only-r5` 的 IMG_0672.HEIC 显示 LoadImage 和 StartImage 均返回 Success，
SMEM 协议由测试前 Not Found 变为测试后 present/Success。返回 Android 后五个
启动分区哈希不变。

`foundation-r6` 的 IMG_0673.MOV 中，前六项 Smem、DAL、HWIO、ChipInfo、
PlatformInfo、ULog 返回成功；尾段约 94–96 秒停在 `starting ScmDxeCompat NOW`，
99 秒已黑屏，之后用户确认返回 Android，没有观察到 SCM 返回。启动分区哈希
仍与基线一致。失败范围已缩小到 SCM 启动路径，内部具体位置尚未证明。

静态审计发现遗漏的真实依赖：SCM RVA 0x1e0c 查找 GUID
`9c1eb71f-dd6c-4ed5-9f6a-5cc0ca789f16`，随后通过其接口分配通信缓存；同一个
GUID 存在于本机 ShmBridgeDxeLA，其模块在参考机 APRIORI 顺序中位于 SCM 前。
`foundation-r7` 加入原始 ShmBridgeDxeLA，并把该真实协议加入 SCM 的额外门，
先确认提供者存在，再运行 SCM。这个依赖修正尚待实机验证，不能先认定重启已修复。

`foundation-r7` 已核对 Android 原始启动基线，并通过 `fastboot boot` 收到
Sending/Booting OKAY。镜像 SHA256 为
`c4a380ce786fa421817f8a86cc47d4c0a8a0a61b6a03554271800e37ba246f63`。
此确认仅表示引导程序接受临时镜像；ShmBridge、SCM 及完整服务序列结果仍待屏幕反馈。

`foundation-r7` 的 IMG_0675.HEIC 确认 ShmBridge 与 SCM 的 LoadImage、StartImage
均返回 Success，`foundation result=Success`，真实 SMEM、SCM、PlatformInfo
协议存在。Clock 和 USB Function IO 未加载，因此 Not Found；仅有内存盘，0 个
物理 GPT 通过符合该版本范围。返回 Android 后五个启动分区哈希与原始基线一致。

时钟前置审计确认原厂 ClockDxe 的 DEPEX 还要求 CmdDb GUID
`1c34f691-d33d-4e14-b8f8-32c6c029e95b`，它不是 SCM GUID；其字符串也有
PwrUtils/NPA 的 LocateProtocol 失败路径。Ace 5 APRIORI 顺序为 CmdDb、PwrUtils、
NPA、Rpmh、Vcs、Clock。接续 `power-bootstrap-r8` 先测试前三项，共 11 个服务；
保持原始 PE/DEPEX，NPA 额外要求真实 DAL。只有显式 `--power-bootstrap` 才进入
新分支，原 `--foundation` 保持限于前八项。r8 不包含 Clock、SMMU、UFSDxe。

`power-bootstrap-r8` 已通过离线编译、FAT 文件读回和镜像结构检查，11 个原厂
PE 与本机提取源逐字节相同；先前八项不再停顿，后三项各在 LoadImage 前停
2 秒、StartImage 前停 10 秒。临时启动前基线不变，Fastboot Sending/Booting
均返回 OKAY。镜像 SHA256 为
`11a850aab7391359498ce5c97cc6fd01fa1f46b7b136f8e7ec9a644039e2b464`，
服务执行与协议发布结果仍待实机画面确认。

`power-bootstrap-r8` 的 IMG_0676.MOV（57 秒尾帧）确认 CmdDb、PwrUtils、NPA
均返回 Success，三个真实协议均存在，`foundation result=Success`。返回 Android
后五个启动分区与原始基线一致，ADB 当前由 5047 端口持有。

`clock-bootstrap-r9` 显式增加 Rpmh、Vcs、Clock 三项，保持前 11 个原厂 PE
与 r8 相同。根据真实 LocateProtocol 路径及 Ace 5 的 APRIORI 顺序，为 Vcs
额外核对 NPA、PwrUtils、Rpmh，为 Clock 额外核对 NPA、PwrUtils、Rpmh、Vcs。
六个电源/时钟提供者在返回成功后还必须存在非空的实际协议接口，否则立即停止。
旧 `--foundation` 和 `--power-bootstrap` 分别仍限于 8、11 项；只有显式
`--clock-bootstrap` 才运行到 14 项。新三项各暂停 2 秒后 LoadImage、10 秒后
StartImage；不包含 SMMU 或 UFSDxe，实机结果待记录。

`clock-bootstrap-r9` 的 IMG_0678.HEIC 确认 Rpmh 和 Vcs 返回 Success 且实际协议
存在；Clock LoadImage 成功，停在 `starting ClockDxe NOW`，用户确认持续超过
一分钟无返回。右下出现一条水平噪点条，尚不能确定是时钟/电源操作、断言输出
还是显示缓冲问题。返回 Android 后五个启动分区哈希不变；再次取回的原厂 logfs
文件仍没有本端口日志或可归属此次 Clock 调用的异常信息。

接续 `clock-mmio-r10` 先运行已通过的前 13 项服务，然后只对 live FDT 的六组
时钟寄存器首尾页执行 AT S1E1R/W，并输出 PAR 与 GCD 描述。ClockDxe 文件已从
FAT 删除，显式 `--clock-mmio-check` 也把执行上限限制为 13；不执行 ClockDxe，
不读取或写入外设寄存器，不改映射。页表查询不能证明硬件寄存器可访问，也不能
证明整个范围已映射；更不能在结果出来前把映射缺失当作本次卡住的原因。
六组区间已逐项与本机 FDT 比较一致，保留 PAR 原值并在检查后恢复。

`clock-mmio-r10` 已编译、打包并校验 FAT 内容，镜像 SHA256 为
`6bb8604fc15d2e950bac81d0ba5d501a0bab01c11012edec184da6dbf202fa0f`。
启动前 Android 基线不变，Fastboot Sending/Booting OKAY；地址转换和花屏对照
结果仍待实机反馈。

`clock-mmio-r10` 的 IMG_0680.HEIC 确认 `fault-pages=10`、`nonidentity-pages=0`。
TCSRCC 首尾页 R/W 转换成功，GCD 类型 3；其余五组受测页转换失败，照片可见
PAR `0x80D`、GCD 类型 0。图中未见之前的水平噪点条。返回 Android 后五个启动
分区仍与基线一致。这证明 Clock 启动前有映射缺项，但不能单独证明 r9 卡住原因。

接续 `clock-mapped-r11` 添加默认关闭的 `HOUJI_CLOCK_MMIO=1` / PCD 开关，仅
补入本机 live FDT 的 GCC、CAMCC、DISPCC、GPUCC、VIDEOCC 五组 NS_DEVICE
MMIO 映射，末端按 4 KiB 向上取整。保留原有 41 项与已有 TCSR 映射。编译实际
C 映射函数的六种开关组合测试确认：关闭开关时输出与原源码完全相同，开启时
只追加五项，所有区间对齐且不重叠，并与 live FDT 范围一致。该主机测试不证明
ARM 页表或硬件寄存器可访问。

r11 显式 `--clock-mapped` 先执行已通过的 13 项，再检查十二个首尾页的 R/W
转换、身份映射及 MMIO/Device 类型；任何一项不符就停在 Clock 之前。通过才
单独加载原始 ClockDxe，不重复初始化前 13 个服务。同步异常与 SError 的 PC、
ESR、FAR 报告只在 CPU 协议允许注册时启用，不替换已注册的回调；Clock 返回
后撤销本次注册。未加入 SMMU/UFS 驱动或磁盘写入，实机结果待记录。

`clock-mapped-r11`（镜像 SHA256
`4ac63915559ea644c157be23689d55e52e3f3a7011ea496878b380045190832a`）的
IMG_0683.HEIC 确认 fault-pages、nonidentity-pages、wrong-type 均为 0；异常报告
的同步/SError 两项均注册成功。Clock LoadImage 成功，基址 D2858000、大小
38000，照片最后一行是 StartImage in 8 seconds。随后用户报告自动返回 Android，
未录到后续步骤，不能声称 Clock 返回、异常回调触发或缺项修正已解决重启。
返回 Android 后五个启动分区哈希不变，原厂 logfs 文件仍无本端口输出。

用户准备录像并明确回复“启动吧”后，以 `clock-mapped-r11-repeat` 标签重新
临时启动完全相同的镜像；Fastboot Sending/Booting OKAY，视频结果待反馈。

`clock-mapped-r11-repeat` 的 IMG_0684.MOV 约 56–59 秒保留了完整错误：
`Failed to map PhysicalAddr:0x3D00000, size:0x100000, SetMemorySpaceAttributes`，
随后为 `Clock_InitBases failed`、`ASSERT ClockDriver.c +6700: 0`；60 秒帧已黑屏，
用户确认自动回到 Android。无 Clock 返回状态，也未观察到同步异常报告。返回
Android 后五个启动分区哈希不变。视频中数字曾因模糊难辨，最终以清晰帧 OCR
及原厂表交叉核对，不使用先前猜测的其他地址。

原厂未修改的 DALSys SHA256 `949984d39680c9a4034eeabb66aa743d500f837dbd1c0133721ae19495be6635`
在文件/RVA `0x40A68` 的记录包含名称 `GFX`，`0x40A70` 为物理基址
`0x03D00000`，后续大小 `0x100000`。这是包含 Linux GPUCC 子银行的父窗口；
r11 仅映射 `03D90000+A000`，不能覆盖这个实际 HWIO 请求。r12 将同一映射
扩展为父窗口，不增加重叠项，不改 Clock PE、不绕过断言；映射开关仍默认关闭。

r12 的主机测试以实际 DALSys SHA、GFX 表字段与 live FDT 的包含关系为依据，
六种编译开关组合均通过默认布局不变、范围对齐及无重叠检查。实机前置检查增加
GFX 父窗口首尾页；通过后才执行原始 ClockDxe。此修正尚未实机通过，不能宣称
Clock/UFS 可用或重启问题已解决。

日志研究、只读取回脚本和测试边界见 [启动日志采集](log-capture.md)。

`clock-mapped-r12` 的 IMG_0685.MOV（48.255 秒）确认前置抽样页检查三项为 0，
Clock 仍未返回；新的失败是 `PhysicalAddr:0xAA00000, size:0x200000` 的
SetMemorySpaceAttributes，随后为 `Clock_InitBases failed`、
`ASSERT ClockDriver.c +6700: 0`。用户确认自动回到 Android。返回后五个启动
分区、slot/build/vbmeta digest 与原始基线一致。原厂 logfs 再次取回的六份文件仍无
本端口日志；PMIC PON 环记录含 PS_HOLD 的 warm/hard reset，但没有可将其中某条
唯一归属于本次故障的时间信息，因此不据此认定看门狗或其他具体复位原因。

继续审计原始 ClockDxe（SHA256
`f498e08bf978b36af750a3958c83b788d39f786069d31d6483d4df66d4ce69ba`）：
`0x7970..0x7998` 将 `0x2BBA8` 的 ClockBSP 装入上下文；其首指针为 `0x20280`、
数量为 8。`Clock_InitBases` 的 `0x3C80` 循环使用这张表，每项 24 字节，包含
物理基址、大小和映射结果指针。这给出了初始化所需的完整八个窗口，而不只是
已报错的下一个范围；所有八项还与同机原始 DALSys 的父窗口记录精确匹配。

| OEM 窗口 | 基址 | 大小 | r13 处理 |
| --- | --- | --- | --- |
| APSS_HM | 17000000 | 02000000 | 保留原映射 |
| CLK_CTL | 00100000 | 00200000 | GCC 扩为父窗口 |
| CORE_TOP_CSR | 01F00000 | 00100000 | 保留原映射 |
| GFX | 03D00000 | 00100000 | 保留 r12 父窗口 |
| IRIS | 0AA00000 | 00200000 | VIDEOCC 扩为父窗口 |
| MDSS | 0AE00000 | 00200000 | DISPCC 扩为父窗口 |
| PCIE_RSCC | 01D00000 | 00015000 | 新增明确列出的窗口 |
| TITAN_SS | 0AC00000 | 00200000 | CAMCC 扩为父窗口 |

r13 默认关闭的映射开关保持不变；开启后共追加六项 NS_DEVICE 区间，原始 41 项
和高内存试验布局不变。主机测试编译实际 C 函数的六种开关组合，校验两份原厂
PE 的 SHA、BSP/父窗口对应、FDT 子范围包含、八个窗口覆盖、对齐和无重叠；同时
校验应用内的诊断窗口与原始 ClockBSP 顺序和范围一致。结果全部通过。

实机检查从首尾页抽样改为对八个窗口全部 10,773 页执行 AT S1E1R/W，核对身份
映射、GCD MMIO 和 Device 属性，仅逐窗口显示汇总。它不读写外设寄存器；任何
失败仍会在执行 Clock 前停止。通过后才调用未修改的 ClockDxe；尚未加入 UFS、
磁盘日志写入或分区修改，硬件结果须另行记录。

r13 镜像 SHA256 为
`78f005f629f15bbb859852447222f2d8f6ddeb9a0528642241ade87d167bf204`。
两轮离线编译、FAT 文件读回和镜像结构检查通过，启动前 Android 基线不变；
Fastboot Sending/Booting 均返回 OKAY。实机逐页检查、Clock 返回状态和协议发布
结果仍待反馈；Booting OKAY 不代表 Clock 已成功初始化。

`clock-mapped-r13` 的 IMG_0686.HEIC 确认八个窗口全部 10,773 页检查通过，
fault/nonidentity/wrong-type 均为 0。Clock LoadImage 成功，用户确认长期停在
`starting ClockDxe NOW`，下方出现一条水平花屏。照片没有 Clock 返回状态或
前两轮的映射断言；不能把没有返回单独等同于硬件访问异常，也未确定花屏原因。
用户手动返回 Android 后五个启动分区、slot/build/vbmeta digest 均与基线一致。

接续 r14 使用显式 `--clock-trace`。保留原厂 ClockDxe 文件，在新的诊断副本中
仅将 23 条已核对的 BL、BLR X8、CBZ/CBNZ W0 改为专用 BRK：DriverInit、
InitBases、逐窗口 HWIO.Map、HALSetup、InternalAttach、SourcesSoft、Voltage、
DFSDomains、CESTA、Target、NPA 和后续 824c 调用。异常回调按原始指令恢复 PC
及 BL/BLR 的 LR，其余寄存器、栈、标志、函数返回值和原始条件分支均保留。
不跳过初始化或断言，不把失败强制改为成功；前 13 个原厂服务保持未修改。

该回调只接受自己的 BRK syndrome、指定 Clock 镜像内的 23 个精确位置和专用
指令字。未知异常继续原有报告/停机路径；无法取得自己的同步异常处理器则拒绝
启动诊断 Clock。实际 LoadImage 后也核对全部位置，原厂/诊断模式文件错配会
停止。上机首先运行 BRK→异常→RET 自检，成功才允许进入被跟踪的 Clock。

`tests/check-clock-trace.py` 将实际 C 控制流步进函数与 Unicorn 2.1.4 的 AArch64
原始指令执行对照：186 个输入/分支案例全部相同，包含正负偏移、W0/X0 宽度、
返回值高位、BL/BLR 的 LR、NZCV 保留；不支持的指令和空/不对齐 BLR 目标拒绝。
23 处补丁可完全逆转到原始 PE SHA，其他字节相同。模拟测试不代表实机异常入口
可恢复，也不证明 Clock 硬件初始化成功；跟踪还可能改变时序，故只用于定位。

r14 两轮编译、诊断 FAT 文件读回、BRK 自检桩机器码检查和镜像结构检查通过。
镜像 SHA256 为 `ec43fd5d3275acc80ada210e8bb2136c8ea23e09efa9dab63a4e980bf75fb3ef`，
元数据显式标记 `contains_oem_diagnostic_patches=true`。启动前 Android 基线一致，
Fastboot Sending/Booting OKAY；实机自检和最后一个跟踪阶段仍待反馈。

`clock-trace-r14` 的 IMG_0687.MOV（72.865 秒）记录了实际可恢复的跟踪：八个
HWIO.Map 和 InitBases 返回 0；InternalAttach、InitSourcesSoft、InitVoltage
返回 0；17 次 InitDFSDomains 也均返回 0。最后一条为
`HOUJI TRACE 61: InitCESTA BEGIN +07D3C`，没有对应 END。用户确认卡住，返回
Android 后五个启动分区及 slot/build/vbmeta digest 与基线一致。Trace 能执行和
恢复证明本轮自检门槛已经通过；尚不能把停止点具体归因于 CESTA 的锁、时钟等待
或寄存器访问。Clock 初始化和 UFS 仍未通过。

原 ClockBSP 的 CESTA 表位于 2BB98，两项为 cam_cesta（343F8，基址 0ADDA000）
与 pcie_cesta（34480，基址 01D05000）。cam_cesta 先依次开启
gcc_camera_ahb_clk、cam_cc_drv_xo_clk、cam_cc_drv_ahb_clk；pcie 项的前置时钟数为
0。这些范围包含在 r13 已检查的 OEM 父窗口内，不再为此增加新的 MMIO 映射。

r15 仍使用相同的显式诊断模式和指令步进算法，扩为 57 个跟踪位置，细分 CESTA
时钟查找/开启/释放、配置写入、供电准备、CmdDb/电压查询，以及 Clock 的同步锁、
源选择和 HAL 调用。轮询中的 delay/read 仅输出各自第一次命中，避免逐次打印
改变超时过多；原始指令仍逐次执行。查找时可显示已验证位于当前 PE 内的固定
长度 ASCII 时钟名，不读取任意指针或外设。390 个原始指令执行对照案例通过，
补丁可完全恢复为同一份原始 ClockDxe。硬件结果仍须另行记录。

r15 已通过两轮编译、FAT 文件读回、自检桩机器码和镜像结构检查。镜像 SHA256
为 `6fe1318404c00a8b4debcacfe73175947c0ab25b5e22c41748dacb769d516f53`。
启动前 Android 基线不变，Fastboot Sending/Booting OKAY；最后的 CESTA 内部阶段
及是否返回仍待实机反馈。

`clock-trace-r15` 的 IMG_0688.MOV（66.785 秒）继续进入了 CESTA 配置、供电
及释放前置时钟阶段。清晰尾帧的最后调用为
`TRACE 826: CESTA.DisableClock BEGIN +0A6C8`，前一条查找名为
`cam_cc_drv_xo_clk`，返回 ID 为 1005D。此前 cam_cc_drv_ahb_clk 已进入释放，
后续 XO 关闭未观察到返回；不能仅据此确定是锁、寄存器访问或关闭后的时序。
用户明确本次没有自动重启，是卡住后手动返回 Android。ADB 转由端口 5038 持有，
五个启动分区和 slot/build/vbmeta digest 与基线一致。

r16 为显式 `--clock-storage` 临时存储调试配置，保留相同的 57 处诊断跟踪。
在 LoadImage 已完成重定位、尚未 StartImage 时，验证 .data 中 ClockBSP 的
CESTA 表指针/数量以及两个节点地址；确认是当前固定版本后，仅把已加载镜像的
2BC50（8 字节指针）和 2BC58（4 字节数量）置零。原始 Clock PE 和磁盘内副本
的 BSP 数据不变，没有全局禁止时钟关闭或直接改写 MMIO。普通 profile 不改变
这些字段；任何布局不符在写入前拒绝。

这个配置有意暂不初始化相机、PCIe 的 CESTA，适用于继续验证 Clock/UFS 基础链，
并不是 CESTA 故障修复，也不代表相机/PCIe 可用。原 InitCESTA 的空表分支在
A710 跳到 A82C，正常返回 0；后续 Target/NPA 和真实协议安装仍须实际执行。
`tests/check-clock-storage-policy.py` 运行实际 C 策略，验证默认无改动、只改 12 个
可写数据字节、布局/数量/空指针/尺寸/重复操作拒绝且不产生额外写入；再以
Unicorn 执行原始 InitCESTA，确认空表路径 17 条 ARM 指令后返回 0，未进入
CESTA 配置/供电/释放调用。该离线结果不证明存储配置在实机成功。

r16 已通过两轮编译、FAT 读回和镜像结构检查，镜像 SHA256 为
`64946a7453888964cfb696f699abb1a62b38bfcf495109a00b6ec4abec78fd59`。
启动前基线不变，Fastboot Sending/Booting OKAY，元数据明确标记临时 BSP 策略。
Clock 的实机返回和协议发布仍待反馈。

`clock-storage-r16` 的 IMG_0690.MOV（71.05 秒）确认 TRACE 61/62 的 InitCESTA
进入并按空表策略返回，随后 InitTarget、InitNPA、DriverInit、PostInit_824c 全部
返回 0。中间结果页明确为 `ClockDxe returned Success`、
`storage scope r16 result=Success`、`Clock after test present (Success)`。
程序完成后故意保持结果页；画面静止不代表本轮仍卡在初始化。用户返回 Android
后五个启动分区和 slot/build/vbmeta digest 不变。这个通过结果仅限 Clock 的
存储调试配置与真实协议发布，不代表 CESTA、UFS I/O 或 iOS 已可用。

下一轮先测试 HALIOMMU 和 ICBDxe 前置服务，不包含 UFSDxe。同机 UFSDxe 含
ConfigStorPartitions、RPMB provisioning、black_box 日志写入等路径，不能仅凭
应用调用 ReadBlocks 就认定其整个初始化只读；写路径审计尚未完成，暂不执行。

HALIOMMU 的原 DEPEX 为十二项架构协议；其 51B8 LocateProtocol 另取
0389b776-625f-11eb-83be-c741a913de34，由当前 EnvDxeEnhanced 的 2C5C 安装。
增加实际存在检查后才允许 StartImage。HALIOMMU 在 151C 安装
54b6d3b4-5d33-4f91-8600-6c41d5deb19a，UFSDxe 的 20258 确实引用同一 GUID。
ICBDxe 在 1474 安装 5824f9de-17d2-4b1f-a5fe-5eb77fa53093，并注册后续事件；
服务返回及协议存在不能单独证明后续总线投票或 UFS 传输已可用。

r17 的 `storage-services` profile 将前十四个服务保持为原厂字节，追加原始
HALIOMMU、ICBDxe 并保留精确 DEPEX 与额外依赖检查。显式
`--storage-services` 使用无 BRK 补丁的原始 Clock PE，继续临时 CESTA 空表策略，
因此同时验证 r16 结果是否依赖跟踪时序。Clock 返回且协议真实存在后，才逐个
启动两个新服务；成功还须发布真实接口。异常报告附上当前驱动名/基址/PC/ESR/
FAR，完成页明确显示 TEST ENDED。未调用 UFS、块写入或分区配置路径。

`tests/check-storage-services.py` 验证前十四项的 manifest 与前一版原厂快照完全
相同、全部十六个 PE 哈希不变、两个提供者 GUID 与实际安装位置匹配、Env 协议
生产/消费 GUID 对应、DEPEX 不接受损坏或不支持的形式，且服务列表无 UFSDxe。

r17 两轮编译、FAT 全文件读回及镜像结构检查通过。镜像 SHA256 为
`fbfe1cab367867e42b29247fe2c82c902e9b879b23bbe275a0e92d22b81bef6f`。
Clock 文件 SHA 与原厂 `f498e08b...` 一致，元数据单独注明运行时 BSP 策略。
启动前 Android 基线不变，Fastboot Sending/Booting OKAY；无跟踪 Clock 及新两项
服务的返回/协议状态仍待实机反馈。此轮未启动 UFSDxe，也未提交块写入请求。

`storage-services-r17` 的 IMG_0693.HEIC 确认 HALIOMMU 与 ICBDxe 均返回
Success，真实协议在 StartImage 后及最终复查时都存在，最后为
`services result=Success`、`TEST ENDED`。这是完成后静止的结果页，
不是初始化挂住。本轮使用无 BRK 补丁的原始 Clock PE，仍启用临时 CESTA
空表策略；可以继续存储基础链，但不代表完整 Clock、UFS I/O、持久日志或 iOS
已可用。未包含或启动 UFSDxe；返回 Android 后的基线复核另行记录。

r17 返回 Android 后五个启动分区、slot/build/vbmeta digest 与基线一致。

r18 使用明确的 `--ufs-readonly` 诊断配置。在原始 UFS PE 的副本中，
4A9C 在普通 LUN 枚举后转到原函数已有的退出路径，省去 RPMB 打开、
监听器分配、通知和异步事件等后续入口。11834 的 LDR W8,[X1,#88] 改为
专用 BRK，必须先注册自己的异常处理器并通过实机 BRK 自检，才允许执行 UFS。
允许时精确恢复 LDR 的 W8 与下一 PC；拒绝时返回 int32 -EROFS，并经原始
1185C 退出代码恢复真实栈和寄存器。没有通过修改 Context.SP 模拟栈操作；
Mu 的异常返回汇编并不使用该字段恢复栈。另将异步提交 11B0C 改为直接返回
-EROFS，避免异步入口绕过同步命令门。

命令门仅允许 NOP、读取描述符/属性/flag、设置易失 fDeviceInit，以及明确列出的
SCSI 读取/查询和仅切换到 active 的电源命令。写描述符、写属性、其他 flag 修改、
写方向、RPMB LUN、写/擦除/格式化及未知命令全部拒绝，不伪装成功。
原厂 PE 保留，诊断副本的四个指令变更可完全逆转回原 SHA。应用只读取物理
LUN 的一个 4096 字节 GPT 头，校验 CRC，重复 DiskGUID 不计数，目标为六个。
StartImage Success 单独不等于存储读取成功。

新增默认关闭的 UFS MMIO 开关，覆盖同机 DAL 的 1D80000+40000 父窗口，
包含设备树全部 HCI/ICE/HWKM/MCQ 子范围；原始布局及 Clock 映射不变。
实际 C 命令策略的 2827 个案例通过；Unicorn 验证原函数的入口栈、LDR、
拒绝后的真实退出路径及异步 -EROFS 返回；12 个实际 C 映射组合均通过。
离线检查不代表 DMA、UFS 读盘、持久日志或 iOS 已验证。

r18 通过两阶段编译、FAT 全文件读回和整包结构检查。镜像 SHA256
`62fea32447662067cd8c433d4119001eaa47e7f71845a56194e82bab7176b349`，
受限 UFS 副本 SHA256 为 `3baf0ffe...`，原始 Clock 和其余十六项前置 PE
保持原始字节。启动前 Android 基线一致，Fastboot Sending/Booting OKAY。
实机 UFS 入口、命令门、GPT 读盘结果仍待反馈；本版不包含持久日志写入器。

`ufs-readonly-r18` 的 IMG_0702.HEIC 确认 UFS 映射 64 页、异常处理器和
BRK 自检通过。两次 NOP 均显示 ALLOW，随后 143/143/228，UFS.c:2544
Device Error 断言。用户确认断言后自动返回 Android。启动分区基线及六个
LUN 的主/备 GPT 原始备份范围全部一致。

更正 r18 的入口审计：11B0C 是同步、异步共同使用的完成等待函数，不是
单独的异步提交入口。102EC 的 NOP 在 10378 提交后，10388 必须调用它；
负数返回直接触发 103F4 的 143，外层 D078 两次失败后触发 D0E0 的 228。
r18 将该函数改为 -EROFS，正是本轮失败的原因，不能据此归因于硬件。
先前仅验证策略及短指令片段的测试没有覆盖完整生命周期，未发现这个错误。

r19 保留原始 11B0C..11C58 全部字节，不再修改完成等待路径。诊断副本只改
4A9C 的普通 LUN 后裁剪与 11834 的命令门，共两条指令。异步请求仍由命令门
检查 request[5] 拒绝，不通过破坏共用等待函数阻断。

新增实际 ARM 完整回归：D078 重试、102EC NOP、12618 请求布局、1180C 提交、
11B0C 等待、11718 响应解析、11C58 清理均执行原 PE 机器码。模拟控制器只提供
门铃/完成位和 NOP-IN DMA 响应；缓存、屏障、延时调用作环境模型，不替换驱动
返回值。原厂及 r19 完成模型均成功；以实际 r18 SHA 对应补丁重跑，精确复现
143/143/228 和 -EROFS；未完成模型产生超时，错误 NOP-IN 模型产生 144，均不
被转成成功。2827 个实际 C 策略案例仍通过。模拟不证明真实 DMA/时序已正常。

r19 两轮编译、FAT 文件读回及整包校验通过。镜像 SHA256 为
`4150774671f9e1d7c26c2d88f554f900f96f215b2cd78bb1c53984a1539c49a8`；
受限 UFS PE SHA256 `366896165157495de9d8e00698a23ec4bc8bf879752d7eeabebb07ca9dda9297`。
LoadImage 后还要求 11B0C/11B10 的原始指令，拒绝误用 r18 副本。
完整机器码回归与策略测试记录于 storage-candidate/ufs-readonly-r19/guard-test.txt。

r19 启动前五个引导分区和 slot/build/vbmeta digest 均与原基线一致，
Fastboot Sending/Booting 返回 OKAY。实机完成等待、UFS I/O、GPT 结果待反馈。

`ufs-readonly-r19` 的 IMG_0706.HEIC 显示 NOP 后已执行 SCSI TEST UNIT
READY，LUN D0，返回固定格式 Sense `70 00 02 ... 04 02`，继而 28b 和
UFS.c:2544 Device Error 断言。本轮不是 r18 的 143/228。T10 ASC-NUM
https://www.t10.org/lists/asc-num.txt 的 04/02 为 logical unit not ready,
initializing command required。启动分区和 slot/build/vbmeta digest 返回后
仍与原基线一致，GPT 读取尚未到达。

按用户要求，当前 UFS profile 去掉已通过基础链的全部观察停顿：启动前 15 秒、
Clock 的 15+2+8 秒、HALIOMMU 和 ICB 各 2+10 秒，共去掉 64 秒；新 UFS 入口
提示缩为 3 秒。驱动内部等待、超时和轮询不变。

r20 在 B008 的原 BL CA4C 位置使用专用 BRK 转到应用的正常调用上下文，
保留 BL 的原 LR，不在异常回调内运行驱动。验证原镜像的二十项 handle 表范围、
控制器指针、cookie、core 0、LUN D0 后，仍先调用原始 CA4C 就绪检查。
只在失败且控制器保存的 Sense 精确为 02/04/02 时，调用原始 CB78(Handle,1)
发送 SSU Active，再执行原始就绪检查一次。其他 Sense、Active 失败、再次就绪
失败均保留真实错误，不改写为成功，也不更改 controller 的跳过初始化标志。

实际 CB78 机器码构造的是 CDB `1b 00 00 00 10 ...`，Active 位在 CDB[4] 的
高四位；相应将命令门从先前未命中的 01 改为精确允许 10，仍拒绝 Sleep、
PowerDown、load/eject 和其他未知字段。新增测试执行实际 CB78 机器码核对 CDB，
编译实际重试 C 算法验证精确 Sense、调用顺序、单次重试和错误传递，验证 handle
边界及 BL link；3083 个命令策略案例和完整 NOP 回归通过。
此为 Active 状态恢复试验，实机是否能越过 TUR 尚待验证，不代表 UFS 读盘成功。

r20 两轮编译、FAT 文件读回和整包校验通过。镜像 SHA256
`601a4c094e914db8274c152f940bf1cd6e9c5bdb1ceace9d4b4d7d8b04020ea0`；
受限 UFS PE SHA256
`3f2c4f7b84a3e98415e0222f637116c2512d2ea9cf2023b2298455af9e37a354`。
已冻结源码及策略、完整 NOP 和 Ready/Active 回归测试输出；实际状态切换待反馈。

r20 启动前 Android 基线不变，Fastboot Sending/Booting 均 OKAY；实际
Active 命令返回、TUR 重试和 GPT 读盘结果仍待实机反馈。

## r20 实机 UFS 读取成功，r21 日志落盘准备

IMG_0709.HEIC 确认原厂 SSU Active 返回 0、再次就绪检查返回 0，随后六个
不同 LUN 的 4096 字节 GPT 头读取及 CRC 全部通过，最终 GPT read result=Success。
允许 43 条命令，拒绝 0 条；主 LUN 头 CRC 631fc7ea，其余为 9ce5a274、
4d68587b、764887b6、49bae3eb、2e0fc1e8。返回 Android 后五个引导分区、
slot/build/vbmeta digest 与原基线一致。首次 28b 已被后续真实 Active/Ready
恢复，不是最终失败。该结果不证明写盘、完整根文件系统或 iOS 已运行。

r21 开始前重新只读备份完整 logfs 8 MiB，设备读取前、本地与读取后 SHA256
均为 5c30e0e714a397b3780a7717f540bc68c231b0728a1bfc9c31d5fccc44022ab7。
新显式 --logfs-write-test profile 保留只读初始化，先验证主 GPT 头、完整
64 项分区表 CRC、磁盘与 logfs GUID，再非递归连接主 LUN 和唯一匹配的
logfs 子设备。仅在这些条件通过后开放物理 LUN0 的 [1000,1800) LBA
WRITE(10) 及无数据 cache flush。命令长度、同步标志、CDB 和范围均验证；
不允许 GPT、启动分区、其他 LUN、RPMB、擦除或格式化。原 --ufs-readonly
不开放此扩展。创建 UniXNU.log，已有同名文件时拒绝覆盖；Flush/Close 后
读回比较内容和 CRC，成功后重启 Android，另通过 ADB 独立验证。

首次覆盖范围是诊断应用自己的 Print 和 SerialPortWrite 文字，128 KiB
有界 RAM 快照，异常回调内仅追加内存、不执行文件 I/O；不是全局 OEM
DebugLib 或 XNU 消息缓冲。写入边界实际 C 的 100876 案例通过，并执行
五组原厂 ARM WRITE 构造器至实际命令门，验证分区起止、越界及 FUA 字段；
原只读 3083 案例、完整 NOP 生命周期、Ready/Active 回归继续通过。
r21 持久性结果在实际取回文件后另行记录。

r21 实机再次六 GPT PASS，pinned GPT/logfs entry matches=1；随后 parent
ConnectController 返回 Not Found，在开放写门之前停止，未创建 UniXNU.log，
没有自动重启。返回 Android 基线一致。审计发现此前把 DSC 中构建组件误认为
都已装入 FV：实际 RAM profile 中有 DiskIo/FAT，缺少 PartitionDxe。r22
在 GPT 校验后从嵌入 FAT 显式 LoadImage/StartImage 原 EDK PartitionDxe，
仅用于日志 profile；默认 stage-1 不变，并增加 parent DevicePath/DiskIo
诊断。FAT 20 个文件均读回相同。镜像 SHA256 为
57da47f9acab876daa23dcee95a13dc3b9c6bbb18bae5d4484bfa54f455f5fe7。

Android 会继续更新 UefiLog，编译期间 logfs 原始 SHA 再次变化，预检仍拒绝
过期备份。紧接启动前重新备份完整分区，前/本地/后哈希一致，并绑定到
logfs-backup-before-persistent-log-r22-final（SHA 5b29d41c460bf150634283512535afab570f1fc65b59d96b592ee70876f514f6）。
备份 SHA 是本地 provenance 元数据，更新它不改变固件/FAT/boot image 字节；
镜像 SHA 及文件清单仍验证。实际 r22 文件系统和写入结果待反馈。

r22 跨重启日志验证 PASS：回 Android 后只读取回新建 UniXNU.log，
11,609 字节、233 行、233 个 HOUJI 标记，r22 起始和最后 snapshot end
均完整。PartitionDxe/FAT/分区匹配全部 Success；设备前/本地/后 SHA
一致，为 643e6a4a69ffdb1c0813133b2cfae615bf1d6e25ffced8c9ef49f8d2eb8c092b。
返回后的五个引导分区、slot/build/vbmeta digest 以及六 LUN 主/备 GPT
共 12 个备份范围全部与原始基线相同。此为已验证的诊断应用文件持久化，
不代表完整 OEM 或 XNU 持续日志，也不代表 iOS 已进入。

## r23 UFS 到原生内核的交接状态

r23 在 OEM UFS 成功初始化、六 GPT 再次通过后，仅做 HCI/SMMU 读取。
完整扫描并自动返回 Android；通过 ADB 取回快照，payload 18,919 字节，
CRC32 66557540，长度和 CRC 在 Mac 独立重算一致。启动分区基线不变。
HCI CAP=f5c7031f、版本 0400、HCS=010f、HCE=1，UTRL=d2898000，
UTRL run=1，transfer/task doorbell 都为 0，IE=0。
SMMU IDR0=4c017e6b、IDR1=60000047、IDR2=5111，107 个 SMR、
71 个 context bank、128 个 global 页。只有两个有效 stream；
UFS SID60 位于 slot0，S2CR=0，指向旧 context0（SCTLR=0a9f00e0，
CBAR=0001f000，CBA2R=1）。本轮读取没有发生外部异常。

原 Ace 5 的接管策略在这份实测快照上会为 UFS 分配独占 context70，
保留旧 context0 和显示 stream 的映射；主机故障用例验证队列未停、
stream 改变、掩码冲突、地址宽度不足时拒绝，并在 bank70 被占时
改选 69。此时还没有在手机上执行这组原生接管写操作。

## r24 XNU 原生 GPT 读取测试准备

新增默认关闭的 houji_ufs_read=1，放在 BSD 早期 timer/USB/RTC 等待前，
调用直接编入 XNU 的原生读取代码。参考 Ace 5/NativeUfs 固定源码，
不沿用其 userdata、SHNGROOT 或系统卷布局，也不发布 IOBlockStorageDevice。
原生提交门只允许 NOP、读取电源属性、LUN0 TUR、Active-only SSU，以及
LUN0 LBA1/count1、LBA2/count2 的 READ(10)；数据出方向和写命令全部拒绝。
头和全部 64 项分区表分别须匹配本机备份 CRC 631fc7ea/9f1bb496。
成功和失败都以明确的 HOUJI NATIVE UFS READ 页面停止；这不是挂载 iOS。

1,288 个实际 C++ 命令策略案例、真实备份 GPT 和损坏输入检查通过；
SMMU 策略用实际 r23 寄存器输入验证。内核已编译链接，SHA256 为
b10bb1c267b7a06961ac386e64f4d2c93a2715053563039fa6ccb8dde4139558。
UEFI 先保存并关闭带 CRC 的日志检查点，关闭 logfs 写门，再通过实际
UniXNULoader v2 协议调用 DarwinBoot；只有显式 --xnu-ufs-read 才选择此路。
根系统卷不传入 RAM；此次只用 RAM 引导 UEFI、内核和 ADT。
已移除 UFS 入口原有 3 秒观察停顿；真实轮询和超时保留。
XNU 本身的结果仍不在 UEFI 检查点中，首次原生读盘结果需要屏幕反馈。

r24 两阶段固件构建、23 个载荷文件读回和整包校验通过。最终镜像 SHA256
fd83754cfa9eb1e06a34eb53e0e9932fd9c100150ca41f4f025b7be6cc88f307。
启动前再次归档上一轮已完整校验的日志，备份包含它的整个 logfs；仅删除
自己的旧 UniXNU.log 并 sync，再备份用于本轮的完整分区，SHA 为
840a950254d709adc53998dd3237f139a0517cdcce2f04a4ffaf4aeec12bc432。
旧日志和所有旧分区快照均保留。启动前五个引导分区及 slot/build/vbmeta
与原基线一致，Fastboot Sending/Booting OKAY。原生 XNU GPT 结果待屏幕
反馈；此时不能将固件和内核编译成功写成原生 DMA 或读盘已成功。


## r24 原生读盘实机通过

IMG_0714 的末页记录 HOUJI NATIVE UFS READ PASS：XNU 实际接管 UFS DMA，
完成 NOP、电源状态查询、LUN0 就绪及 GPT 主头和全部 64 项读取；CRC 分别为
631fc7ea / 9f1bb496，DMA=ba300000，独占 SMMU bank70，slot0。
此处 panic 是测试预设的停止页，不是新的读盘失败；未发布根介质或挂载 iOS。
返回 Android 后，五个启动分区及 slot/build/vbmeta 与基线一致，六个 LUN 的
主、备 GPT 共 12 个原始范围逐字节与备份相同。进入 XNU 前的 UniXNU.log
已独立取回，payload=11,557 字节、CRC=dd80495d；该快照不含原生内核结果。

## r25 原生内核日志准备

Android FAT 先新建并分配 64 KiB XnuLog.bin，完整 logfs 在分配前、后均保存。
实际 FAT12 链为 cluster69..84，对应 LUN0 LBA4170..4185。读取挂载 FAT 的
裸块设备发现普通缓存可能过期，因此新增固定只读 O_DIRECT helper，直接读取
两次相同，并将原始 FAT 数据块与挂载文件逐字节核对。没有在 Android 中裸写。

默认关闭的 houji_ufs_log=1 在 r24 GPT 校验后读取 FAT12 元数据，重新核对
BPB、双 FAT、目录、固定链、其他文件不重叠、初始化内容 CRC 和本轮唯一编号。
只有这些检查通过才开放上述 16 个文件数据块的 WRITE(10)，不开放 FAT 元数据
或其他文件/分区写入。正文先写并 flush，最后写带 CRC 的提交头并再次 flush，
逐块读回全部内容成功后才通过本机 FDT 指定的 PSCI SMC 返回 Android。
内核消息缓冲尾部和显式存储阶段文字都在正常 BSD 初始化上下文复制；不从 panic
处理器递归访问存储。早于原生 UFS 可用处的故障仍不能通过此路径保存。

25,601 个实际 C++ 命令边界用例通过；真实 FAT 分配及初始化文件接受，损坏/
交叉引用拒绝；34 个事务失败点均立即停止后续操作，提交顺序和读回损坏检查通过。
本轮持久化与自动返回尚待实机验证，不能据离线测试宣称日志已修复。


## r25 内核日志跨重启实机通过

镜像 03122c99f839a6f2ccee24e2561f5a1bd1774882d4a143b00fb4a4f150bb4e32
临时启动后自动返回 Android，ADB 在 5047 重新上线。没有依赖照片或视频，
独立取回 XnuLog.bin 并导出 XnuLog.txt：payload=10,583 字节，正文 CRC32
15753b53，头部 CRC32 4f9a592f，本轮编号 ce304c0b298341848bf514b7187fc451
完全匹配；64 KiB 文件 SHA256 为
0023d7651164db7ac6b97384ccdfe5e9a3b172beb0dad605bd2593823b96dbd4。
内容包含 XNU 22.6.0 从早期启动到 BSD、原生 DMA/SMMU/GPT PASS、FAT 验证
及提交前的内核消息和阶段记录。DMA=ba2e4000，slot0、bank70。

返回后两次 O_DIRECT 全分区读取相同，依据原 FAT 链重建文件与 ADB 取回文件
逐字节一致；16 个数据块归属不变、无其他文件交叉引用。五个引导分区与
slot/build/vbmeta 仍为原基线，六个 LUN 主、备 GPT 共 12 范围仍与原备份相同。
证据在 evidence/logfs-adb-capture-r25 和 evidence/native-log-r25-result.json；
完整事前/事后 logfs 均保留。r25-source 保存这次实际固件、内核源与主机脚本。

此结果确认正常检查点的 XNU 消息快照可跨重启取回，并未实现实时 USB 日志或
任意崩溃保存。当前文件保持已提交状态；同一镜像不会静默覆盖，重新测试需要先
归档、用新的运行编号分配/初始化并重新绑定源码与启动元数据。iOS 尚未启动。

## r26 日历、HFS 注册与恢复环境实机通过

原来的 IORTC 等待改为显式 houji_epoch 启动参数提供 UTC 种子，并使用实际
19.2 MHz 架构计时器累计时间。没有发布虚构 IORTC 服务；这不是硬件 RTC 驱动，
种子以构建时刻为准，尚不提供联网校时或关机走时。实际 XNU 日志证实越过
IOKitInitializeTime，并完成 hfs-627.100.6 注册。

固定文件原生日志连续提交三次成功，最终 13,047 字节，CRC32=b684045e。
XNU 用经过测试的 BCB 字段修改返回已验证的 OrangeFox root ADB，取回无需照片。
misc 保留字段与 A/B 数据原样保存，未对 userdata 发出写命令。证据：
native-port/evidence/logfs-recovery-r26、evidence/native-ios-r26-result.json。

恢复镜像是原 houji OrangeFox 的三份 ramdisk 文本修改，使用原镜像相同的
公开 AOSP AVB 测试密钥生成可验证 footer；只写 recovery_a。原 recovery_a/b、
boot/init_boot/vendor_boot/vbmeta、校准与通信等 37 个分区均已保存并核验备份。
恢复失败槽位时 set_active=a 与 mark-boot-successful 仅改变 sde 中 boot_a/b
槽位属性和两层 CRC；分区布局未变。主机后续预检固定审计后的两个完整 GPT
快照，其余十个范围仍固定原备份，不能接受任意 GPT 变化。

下一步把已校验的 12 GiB HFSX 系统卷安装到现有 userdata 的起始部分，使用
真实 UFS 回调提供 BSD 块设备接口。md0 名称来自通用 XNU 接口，数据不存放 RAM。
只在本机 GPT 与 HFSX 体积/块大小/卷编号都匹配后开放该 12 GiB 的写入范围；
尚未实机验证挂载或 launchd，不能把以上检查点写成 iOS 已启动。

## iOS 根卷已写入 userdata 并完成全卷直接读取校验

现有 userdata 分区起始 12 GiB 安装了用户提供的 20H392 iPhone X 系统卷，
未移动分区边界。Android 个人数据已按授权覆盖。Fastboot 45 批报告成功后，
全卷哈希检查发现最后 640 MiB 与源不符；128 MiB 分块确认前 11.375 GiB
完全相同。对照源文件，仅修复该尾部的零区与原始最后 4 KiB 备用卷头并 fsync。
随后固定只读 O_DIRECT helper 从手机读取完整 12 GiB，SHA256 精确匹配
c49c2349a088af4888e3fda1ad08e0593e7eba70516d8b1c8177e78c7ab55385。
证据：native-port/native-root-install-r1/install.json、tail-repair.jsonl 和分块哈希。
没有把 Fastboot 的成功状态单独当作系统卷完整性的证明；稀疏写入的具体缺失
原因仍未确定。当前只确认卷安装完整，尚未确认 XNU 根挂载或 iOS 用户态启动。

## r27 原生系统卷挂载实机通过

XNU 原生 UFS 注册 12 GiB 回调块设备，随后实际输出：
`hfs: mounted HoujiIOS16 on device b(1, 0)`。
HFS 还成功创建并写入 hotfile btree，证明本轮不仅识别卷头，还完成文件系统
元数据 I/O。正常检查点日志 18,324 字节、CRC32=5c7ec672，运行编号匹配，
之后自动返回恢复环境。证据在 native-port/evidence/logfs-recovery-r27。
本轮按设计停在根挂载后，尚未运行 launchd，不能据此宣称 iOS 界面已启动。

## r28 到达 launchd 的平台检查

GUI ADT 实机确认 AppleCLCD 匹配、真实 1200×2670 / stride4800 几何守卫通过，
1125×2436 逻辑画布居中。根卷日志回放和挂载成功，正常日志保存至 before launchd
exec，19,570 字节，CRC32=e60bdd73。随后照片 IMG_0715 记录 launchd CS_KILLED，
namespace9/code14。源码 reason.h 对应 OS_REASON_EXEC / WRONG_PLATFORM，
不是内存或 UFS 错误。该构建沿用上游 MacOSX SDK 的 SWEET 兼容路径，
kern_exec.c 在 iOS 平台且初始 exec 没有 spawn 平台属性时要求已有 DEVELOPMENT
开关 unentitled_ios_sim_launch；本轮未传。后续先补参数验证，保留签名页校验代码。
本轮没有 iOS 用户态运行成功的证据；五秒观察线程尚未完成第一次记录。

Ace 5 固定参考的 scripts/make-ios16-payload.py 和 DEVELOPMENT_STATUS.md
也记录相同 9/14 平台拒绝，并通过 unentitled_ios_sim_launch=1 解决。其启动参数
同时包含 launchd_unsecure_cache=1：原始任务缓存加载器在没有 AMFI IOService
时使用这个既有开发模式。r29 同步补齐这两个用户态兼容参数，以及已有的
sweetfb_hz=30 / sweetfb_noconsole=1 图形呈现参数。尚待实机结果，不据参考机
的成功记录认定 houji 已运行系统服务。

## r29 已运行原生 iOS 用户态，图形尚未呈现

补齐参考启动参数后，60 秒观察完成并自动回 OrangeFox。最终检查点 CRC、
运行编号及头部校验通过；日志显示 launchd[1]、SpringBoard[5]、backboardd[35]，
以及 logd、securityd、mobileactivation、runningboardd、迁移服务等持续运行。
backboardd 还实际打开 IOMobileFramebuffer 并调用其用户客户端方法。
这些是手机上原生 iOS 用户态的运行证据，仍不是 iOS 欢迎或主屏幕已呈现。
用户明确反馈整轮始终只有启动日志。最后快照填满 61,440 字节上限，保留内核
消息尾部和显式检查点；未把缺失的早期消息解释成没有执行。

证据：native-port/evidence/logfs-recovery-r29，payload CRC32=c5d82f2d，
头 CRC32=9c0d50d9。下一轮延长到五分钟，加入实际帧交换/呈现计数和已有
只读进程 PC/LR 采样，定位界面与迁移服务的等待位置。

## r30 首次 iOS 图形呈现与服务等待定位

用户实机看见 Apple 标志和进度条；尚未看见欢迎、设置或主屏幕。重启恢复后
正常检查点日志通过运行编号与双 CRC 校验，保留至约 281 秒、第 52/60 次采样。
画面实际提交计数从 485 增至 490，交换计数从 1037 增至 1045。说明该时段
仍有图形工作；不能把静止的进度条直接解释为 XNU 整体停止。

用同一 20H392 本地只读系统卷的 dyld cache 解析 PC/LR，SpringBoard 的主线程
停在 LaunchServices 的 _LSCopyServerStore，同期迁移插件等待其数据库 reseed
回复；backboardd 与 accountsd 等待 DataMigration，securityd 等待 Accounts。
这些是采样时的等待点，不是已经证明的根因。完整系统卷正通过固定 O_DIRECT
只读 helper 导出，保留当次文件系统状态供检查。

r30 没有按设计自动回恢复，用户手动返回。源码审计发现原采样器持 task lock
执行可缺页的用户栈读取；不能据此认定这就是 r30 未返回的原因。r31 将寄存器
快照留在锁内，持有 map 引用后在锁外读栈，并加入 lsd/installd/appstored、
实时 VM 计数、每个进程的采样起止标记，以及采样前检查点。进程清单缩小到
目标服务，减少 64 KiB 日志尾部被重复清单覆盖。源码在 native/userland-sampler，
可由 scripts/patch-userland-sampler.py 校验并复现；编译通过不等于实机已通过。

## 主机 UUID 接口补齐候选

同版本 ios-sweet 的 NOTES.md 记录缺少 IOPlatformUUID 会影响 CurrentHost 配置。
当前 houji ADT 已去掉参考机伪造的 unique-chip-id，原始 ARM 平台 UUID 生成路径
因此没有输入。补充 ARM64 SWEET 专用、显式 opt-in 的 houji,platform-uuid 回退：
从本机已验证 USB 序列号和 UniXNU 设备命名空间生成 UUIDv5，16 字节写入 ADT，
供 gethostuuid 与主机配置使用，不设置 Apple ECID 或激活状态。原有 Apple UUID
优先路径保持优先；缺失、长度错误、版本或 variant 错误时不发布回退值。

实际 C++ 方法在主机执行 56 个边界和优先级用例通过，内核集成编译通过。
设备树对比除新增 UUID 和新随机种子外完全相同。此时仍未启动该候选，不能
认定 UUID 已在手机发布或已经解决迁移。可复现来源在 native/platform-uuid，
应用器为 scripts/patch-platform-uuid.py，ADT 生成器增加 --platform-uuid。

### r31 / r32 and the next high-memory profile

r31 completed all 60 samples through uptime 321.76 seconds and automatically
returned to OrangeFox. SpringBoard and backboardd were present; the owner still
saw only the Apple logo/progress screen. At the final sample the 256 MiB kernel
window had 902 free 16 KiB pages. These counters show limited headroom, but do
not prove that memory caused the LaunchServices/migration waits.

r32 uses 320 MiB, a device-bound RFC 4122 UUIDv5 fallback, and 180 samples over
15 minutes. While it was running the owner reported a faster progress bar and
requested more RAM after this trial finishes. No interruption is planned.

The 2 GiB candidate uses only normal DRAM from the captured Linux map, within
`[0x8c0000000, 0xbea400000)`. SEC/PrePi still constructs its heap from the named
low `DXE_Heap`. The houji high-RAM build caps the actual Mu `FindFreePages`
search at `0xffffffff`, including preferred/default bins, pool allocations and
resource-promotion retries. Explicit `AllocateAddress` remains unchanged so
DarwinBoot can own the whole XNU window. This cap is compiled only into the
opt-in high-RAM profile. Ordinary allocation exhaustion must fail, never spill
into high RAM for an OEM driver.

The high-memory loader checks ordinary page/pool addresses and then writes,
flushes and reads every 64-bit word of its owned 2 GiB twice, using address-based
complementary patterns. The first native trial stops before mounting HFSX,
verifies native UFS/GPT and fixed-file checkpoint/BCB return, and only then may
be extended to launchd. Host tests compile the real allocation search and the
real pattern loop; hardware results must be recorded separately.

For a new phone filesystem snapshot, `scripts/snapshot-native-root.py` can clone
a verified earlier APFS-hosted 12 GiB snapshot and replace only changed 128 MiB
chunks. It independently indexes all 96 chunks before and after transfer and
checks the entire reconstructed image against the phone. The r31 snapshot took
105 seconds and passed all chunk checks. It performs no userdata writes.

The r32 committed snapshot was recovered successfully after a manual return.
It ends at sample 139/180, uptime 718.26 seconds, with 911 free 16 KiB pages,
8,502 framebuffer swaps and 3,980 physical presents. The platform UUID is
published. The owner saw progress advance to roughly one quarter. Automatic
return did not run; the last saved checkpoint does not identify the later
stopping instruction. This is not a completed 15-minute run or a full iOS boot.

r33 passed on hardware: the pinned loader's full-window memory test gated
entry into XNU, which reported physical base `0x8c0000000`, length
`2147483648`, and native UFS DMA at `0x8c2b00000`. GPT CRCs and the real HFSX
volume identity matched. A fresh 17,637-byte checkpoint passed CRC/run-ID checks
after automatic OrangeFox return, before mounting HFSX. Misc reserved bytes
864 through the end were unchanged. This verifies the high-memory transport
profile; it does not yet prove iOS userland stability at 2 GiB.

### r34 / r35: persistent migration and verified 8 GiB

r34 completed all 180 samples at uptime 947.39 seconds and automatically
returned to OrangeFox. The owner saw approximately three-quarter progress,
with no Hello/Setup screen. The last checkpoint recorded 24,234 swaps and
10,765 presents. A stable 12 GiB root snapshot was reconstructed from 28 changed
128 MiB chunks; all 96 output chunks match the phone before/after indexes.
Its SHA256 is `a1c8992adb77d942294fefc99e5d10f9c3cc698fa3c0b5cf96a91a4579df7c59`.

The complete iOS precautionary stackshot identifies CoreLocationMigrator as
waiting for over 10 minutes. At that snapshot, memoryPressure is false and
compressor size/compression/decompression counts are all zero. The wrapper
waits in CLInternalPerformMigration for a synchronous reply; locationd's
CLInternalServiceSilo waits on CLHarvestControllerSilo. These are observed
wait sites, not proof of the underlying cause. No migration-completion flags
or Setup/activation states were seeded.

r35 passed the same full-word two-pattern loader test with an 8 GiB window
`[0x8c0000000, 0xac0000000)`. The captured FDT and Linux RAM map cover this
entire interval, with no overlap in 43 checked reserved ranges. XNU reported
8,589,934,592 bytes and native UFS DMA at `0x8c4284000`. GPT/HFS identity reads,
fresh committed checkpoint and automatic recovery all passed before HFS mount.
Misc reserved bytes 864 through the end remained unchanged. This verifies
memory/storage transport, not 8 GiB iOS userland stability.

The opt-in CPU0 EPSS probe performs only reads. r35 read MIDR `0x410fd801`,
MPIDR `0x81000000`, and requested performance index 12, but rejected its timing
sample because the direct reference-counter read moved backwards. No CPU MHz
is inferred from that invalid sample or from the 19.2 MHz timer. The next
version uses XNU's ordered clock_get_uptime interface. CPU/GPU DVFS, voltage
control and thermal governors remain unimplemented.

The userland observer now accepts houji_trial_samples in the range 12..720,
at the existing five-second interval; absent/invalid arguments retain 180.
This permits an uninterrupted one-hour first-boot observation rather than
forcing return after 15 minutes. It does not bypass any migration plugin.


r36 was temporarily booted at 2026-10-24 18:54:34 +08:00 with the verified
8 GiB profile, a fresh log run ID, the ordered read-only CPU frequency probe,
and 720 planned five-second samples. The owner manually returned to recovery
after the Apple progress screen remained stalled. A valid checkpoint retains
sample 581/720 at uptime 2969.11 seconds, with 361,502 free 16 KiB pages,
50,951 swaps and 22,049 physical presents. This is a partial observation, not
a completed one-hour run or an iOS GUI boot. The early CPU frequency sample
has fallen outside the bounded log tail, so no MHz is claimed.

The latest complete stackshot contains 206 processes and explicitly reports
CoreLocationMigrator waiting for 42 minutes. Locationd's CLHarvestControllerSilo
is again waiting in the same MIG stub, image offset 0xc74f4. Memory pressure is
false; compressor size and compression/decompression counts are zero. The
reply endpoint remains unverified. No migration, Setup or activation completion
state was injected.

The r36 12 GiB snapshot was reconstructed from 38 changed chunks and independently
verified against all 96 before/after phone chunks. SHA256 is
`623169b6b77e938f01f6135d80e47b0b721c5f288a953ca862a69018df46856a`.
Misc reserved bytes 864 through the end are unchanged. The original image and
checkpoint are archived before preparing another run.

### r37: two-CPU precheck candidate

See [CPU scheduling references](cpu-scheduling.md). The prototype exposes only
the captured equal-capacity affinities 0 and 0x100, uses the existing Clutch
scheduler, starts CPU1 through PSCI/SMC with an explicit physical context,
and uses the captured 0x40000 GIC redistributor stride. No frequency or voltage
writes are added. The first test requires a CPU1-bound worker and real timer/IPI
counters, then stops before mounting HFS. Compilation and host checks have
passed; hardware outcome is recorded separately.


r37 reached CPU0 online and requested CPU1, then panicked with a displayed
return of 3288334339 (`0xc4000003`, the CPU_ON function ID). The owner photo
IMG_0723.HEIC and linked-kernel disassembly show the cause: the inline assembly
string used `dsb sy; smc #0`, and Darwin's assembler treated the semicolon as
a comment. The emitted function contains DSB but no SMC instruction. Thus r37
did not issue CPU_ON; this result says nothing about firmware CPU_ON support.
The native checkpoint is still the exact fresh uncommitted file, consistent
with stopping before native UFS initialization or HFS mounting. The owner
returned to OrangeFox; UEFI logs and the photo were archived.

The corrected call uses separate assembly lines. `tests/check-psci-assembly.py`
cross-compiles the actual call for Darwin arm64, requires both real opcodes,
and rejects a regression fixture using the old separator. Its `--kernel`
option additionally checks the linked SweetCPU function before any new boot.


r38 fixes the emitted PSCI instruction. IMG_0724.HEIC reports CPU_ON returned
0 and a panic on CPU1: console output from an interrupt-disabled context.
This confirms secondary execution reached XNU, but not scheduler/worker success.
The initCPU diagnostic IOLog was still in the masked-IRQ path. The next version
records MIDR, MPIDR and initial IRQ state without output, then prints those
fields from the normal startup helper after processor_start returns. The global
console policy remains unchanged. A linked-code check now rejects direct console
calls from initCPU; the actual r38 binary is a verified negative fixture.


### r39 / r40: separate secondary state and interrupt delivery

r39 passed the actual PSCI call and avoided console output in masked initCPU,
but timed out waiting for both IOCPU Running and the first SGI. The owner photo
IMG_0725.HEIC shows CPU_ON returned 0; it does not distinguish which condition
was missing. The phone automatically rebooted to OrangeFox. The complete UEFI
log was recovered and XnuLog.bin still matches its exact uncommitted initial
bytes. Misc bytes 864 through the end are unchanged. This was a panic reboot,
not a successful phase-3 log checkpoint.

r40 saves the initialized GIC redistributor and CPU-interface state to memory
without printing in the masked context. The CPU0 startup helper reports saved
MIDR/MPIDR, IOCPU state, timer/IPI counters and pending bits, sends one bounded
post-start SGI1 to CPU1, and retains the existing strict completion gate. The
diagnostics read only already-configured GIC registers. They do not enable
new interrupt sources or change CPU frequency/voltage. Host ASAN/UBSAN tests
cover all eight pending-register frame offsets and reject inactive, out-of-range
and overflow cases without register-memory writes. Final linked-code checks
verify a real SMC instruction and no direct console calls in initCPU or the
snapshot helper. The image was temporarily booted; hardware result is pending.

The r40 photo IMG_0726.HEIC instead shows a CPU0 data abort before attempting
CPU1. Exact linked disassembly resolves PC fffffe0007a75170 to the newly added
GICR_IGROUPR0 read in houji_smp_capture_gic. Host memory-bound tests did not
validate hardware accessibility. The next diagnostic removes all redistributor
MMIO reads; it retains CPU-interface system registers and actual IRQ counters.
No SMP hardware conclusion can be drawn from r40.


### r41: two physical A520 cores passed the precheck

The system-register-only diagnostic completed, returned automatically to
OrangeFox, and produced a valid committed XnuLog.bin (SHA256
4ccfcd0d924447d585751d9e173498ceec1a3bb9eecbf341c649641e7a8a4422).
Both CPUs report MIDR 410fd801, with MPIDRs 81000000 and 81000100.
The CPU1-bound worker produced all 30 heartbeats; timer counters were 609/114
and IPI counters 40/72 at the preflight gate. HFS was not mounted. Misc reserved
bytes remain unchanged. This confirms actual secondary execution, thread
scheduling and interrupts; it does not yet validate multicore iOS userland.

CPU0's ordered read-only EPSS measurement returned 1689595 kHz over approximately
100 ms (cycles 168960176, reference ticks 1920007 at 19.2 MHz). This is a short
busy average, not a fixed operating frequency, maximum frequency or working DVFS
governor. No frequency or voltage writes were added.

Compared with r39, the helper is bound to CPU0 and sends one post-start remote
SGI. This test does not isolate which change was necessary. The next short
userland trial retains both changes and the strict two-core preflight.


### r42: short two-CPU iOS userland / locationd observation

The candidate preserves r41's successful startup helper and remote SGI, exposes
the same two A520 affinities and 8 GiB, and runs 24 five-second inventory samples
before the recovery checkpoint. It enables the passive locationd request 1203 /
reply 1303 observer and includes locationd plus fairplayd.H2 in stack targets.
The 12 GiB root window permits ordinary iOS writes, as in earlier userland
trials; no migration-completion flags or replies are synthesized. The r36 full
snapshot remains the last archived root state before this trial. Hardware
outcome is pending.


The r42 two-CPU userland trial completed all 24 samples and returned to recovery
with a valid committed log. At 152.244331 seconds: initialized=2, worker_cpu=1,
beats=30, timer IRQs 118120/105933 and IPIs 44477/43674. Display counters reached
3265 swaps and 1363 presents; 371100 free 16 KiB pages remained. Locationd again
waited at image offset c74f4. The passive observer captured one request, zero
replies, kotype 0 and queue count 2, but no in-space receiver at send time. The
current evidence does not identify the service or establish why it fails.

The r42 12 GiB root snapshot reconstructs 24 changed chunks from r36, with stable
independent phone indices and every output chunk matching. Its SHA256 is
93e38ceb8d625af22a753f31874d321dc8e97785becbf34483e6d53b091c4bab.
A shadow-backed inspection mount contains no fairplayd crash report. Repeated
exec messages alone do not establish a fairplayd failure cause.

r43 extends the passive observer with the existing XNU trace's temporary-owner
lookup, opaque kmsg receipt/copyout result tracking and token clearing on free.
It also records selected services' normal exit status and reason namespace/code
into a separate bounded memory record, printed by the sampler outside locks.
No port rights, message headers, return values, exit reasons or migration state
are modified. Host sanitizers test ownership, receive/free lifetimes, status
propagation and unchanged input objects. Hardware outcome is pending.


### r43 / r44: service wait narrowed without changing IPC semantics

Both two-CPU trials completed 24 samples and returned valid persistent logs.
r43 recorded one locationd request, no reply, temporary-owner port state 1,
zero copyout attempts and no unreceived-message free. fairplayd.H2 exited 11
times with status 0 and no exit reason. This is not a crash diagnosis and does
not by itself identify the request's service.

r44 compared the live destination reference with host service-port slots under
the host lock (with no port or observer lock held). None matched at request
time. Its final scalar BSD trace contains six consecutive SYS_open returns of
ENOENT before a clean exit. File paths were not captured in that version; no
missing file or hardware failure is inferred yet.

r45 records only the last eight open pathnames (maximum 160 bytes each) for
fairplayd.H2, using bounded copyinstr after the original syscall returns and
before the observer spinlock. It does not read file contents, modify syscall
results, change port rights or write migration-completion state. Host tests cover
ring rollover and PID reset with unchanged input strings and returned status.


## r125–r126：CP 页属性及正常屏幕输出对照（2026-10-25）

- r125 临时启动镜像 `f54f4a40c974bdc7775c1952903b72d3057b799e55e8abc0ebe43f8a9e27876b`，
  固定 CP 页 `03d02000/1000` 由 CPU 页表库改为 Device-nGnRE。
  实机 Stage8/status0；TTBR0 `D39FF000`、TCR `280803518`，MAIR
  `FFBB4400 -> 4FFBB4400`，37 个表／11824 个叶子，未拆分。
  CP 读写 PAR `0400000003D02B00`，前后相邻页仍为原属性。
- r125 自动恢复 82.819 秒；原生快照 payload 75106 字节，CRC `7853C529`。
  IMG_0756 的上方仍为 seq `050c`、step `5004`、地址 `03d02020`、值 `1`。
  该码位于写入前的 trace 调用中；不能仅凭屏幕码断言 STR 指令已执行。
- r126 临时镜像 `1c17ad1f62f8619137a1bb69f5c2a6bba54cf8c7720d204c2b11d4b72290b6bb`，
  保持 CP 页属性和原 SQE/CP_INIT/两次写回，只将临界区的正常 trace 绘制关闭。
  ProbePrint 仍追加 CPU 文本缓冲，recorder 启用时跳过 ConOut；Stop／fatal 后可输出。
  实际 console/trace glue 273 项与原 portable trace 2239 项通过 ASAN/UBSAN。
- r126 自动恢复 79.448 秒；快照 payload 75107 字节、CRC `84070A3F`，仍只提交到
  host preparation，未提交 SQE 返回、CP 初始化完成或任一 GPU 写回结果。
  因此两项对照均未打通 GPU；不能将编译、属性读回或日志 CRC 当作 GPU 成功。
- 两轮五个启动分区、12 处 GPT 备份范围及 misc 的保留区域均复核未改变。
  XNU 未启动，其旧初始日志不应被解释为本轮 XNU 日志损坏。

SQE/AQE 的 data+4、有效长度、完整复制、零 padding 和代码 AP3/RX 与参考一致。
实际 incoming GPU SID 尚未观测。下一候选差异是 Linux SM8650 GPU 同时列 SID0、SID1，
当前适配仅 SID0；本机 live DT 明确 SID1=LPAC、SID2=secure、SID5=GMU。
该差异尚不能证明复位原因，需独立读回和同一组实际执行／写回验证。

### r128：基础服务通过，SQE 写入已返回，后续读前门拒绝

临时镜像 SHA256 `02ea50cfb9b95b94ca7ab26ab07f5ba22173ef3144c2572a1e1f80039ec9613e`；约60.37秒自动回 OrangeFox，原生日志 payload327549 B，CRC32 `f88260d4` 验证通过，保护分区/GPT/misc保留区一致。

SCM固定9点、自测、两次分配、SmcInvoke/ClientEnv和handler注销全部通过。SID0+LPAC SID1到拥有的bank0读回通过。环状态writes8/reads11、首次失败op1/read、host-write calls1/faults0证明SQE启动STR/RET及后续DSB链已返回成功，随后SQE读回前guard失败；不能再把此轮判为STR卡死。关键trace被1024条回收环覆盖，尚不知具体guard原因；kicks/writebacks均0，无CP或GPU写回证明。

R0/R1 GMU配置均稳定CMD0/CFG0/CBCR2001，PLL1 MODE100/OPMODE0/STATUS0/L0/ALPHA0/USER1，Get为Not started；名义配置解码XO19.2MHz，不是测频。HUB配置缓存200MHz、CFG505，外部GPLL0父源未观测，不猜实际频率。

[完整结果](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r128-result.json)。r129只增首次guard判据及CPU trace冻结，不放宽门、不改时钟/固件/PM4。

### r129：首次失败精确归因 GPUBUSYIGNAHB 误分类

镜像 `eb157d6226acc5416d4c99aeb95b269071cc93c139a8a313f627ea9ffc9f888f`；61.671秒自动回收，payload381007B、CRC32 `5c5c21e5` 有效。冻结窗口1011..1522共512条、invalid0，保留了5004→5005→5007→500a以及3125返回0。首次拒绝为phase3/stage2/kind3，`03d8ec30 & 00800000` 期望0，实际 `71c00004`，原始读取返回0。GPU启动写确已返回，后续SQE读回尚未执行。

bit23是GPUBUSYIGNAHB idle判据，Linux/OnePlus在SQE启动后提交CP_INIT，再有界等待idle；不能在每次运行期IO前要求瞬时idle。r130将只修正此阶段判断，保留电源/CM3/HFI/SMMU/roots/routes，完成和文件系统开放仍要求idle。r129仍kicks0/writebacks0，不能声称CP执行或GPU加速通过。

[结果记录](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r129-result.json)。

### r131：A750 CP_INIT、实际命令环与两次 GPU 写回通过

镜像 `6d9ffca063d5b08945f576e680c539d427cfdff9c8acd1757d7262ab739d80ed`，实际app `25a500c7603f5a3ef9ed0ea6ba2694aeb375ac8cb3f53a39445e31e9ffc14dcd`；64.518秒自动回OrangeFox，payload402648B、CRC32 `0d60c25c` 有效，5boot/12GPT/misc保留区校验一致。

实测 `code0/phase8/kicks3/init-idle1/writebacks2`，RPTR/WPTR依次10/15/20，scratch依次`C0FFEE00/0`→`C0FFEE00/C0FFEE01`，IRQ/fault0，completion GMU busy71000000有效且bit23清零。CPU只发布固定PM4到ring，没有将预期canary写入scratch；不同提交与不同目标字排除单一陈旧结果。

正常最终HALT3的1000轮poll首末均valid3F/failed1：SQE读1、RPTR14(十六进制20)、RBBM1、IRQ0、fault0、busy71000000；只有精确SQE==3判据不满足。仍通过CM3reset＋三halt ACK1/3/3独立隔离后才保存日志。不能把隔离成功称为普通HALT条件通过；SQE字段语义继续查原始定义。

这证明UEFI中CP和设备写回，不表示真实绘图、XNU GPU后端或桌面加速通过。下一里程碑是known-image图形测试及XNU/AdrenoMetal实际接入。

[完整结果](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r131-result.json)。

### r132：CP 写回复验及 PAS13 只读能力查询通过

r132 再次完成 `CP_INIT` 和两次独立 GPU 写回，结果为 `C0FFEE00/C0FFEE01`，
RPTR/WPTR=20、IRQ=0、CP fault=0。五次真实 SMC 查询均返回 a0=0/a1=1，
确认 PAS13 支持及加载所需四个接口可用，无重试或 quarantine；本轮没有加载、
认证 ZAP 或发送退出安全模式命令。三个阶段的 `TRUST_CNTL` 原值均为 1。

自动返回 OrangeFox 后，原生日志 payload 447121 字节、CRC32 `e88c3055` 校验通过。
普通 HALT 的精确读回条件仍未通过，沿用 CM3 reset 和三项 ACK `1/3/3` 隔离。
五个启动分区、12 处 GPT 范围和 misc 保留区均未改变；本轮未启动 XNU。
见[结果清单](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r132-result.json)及
[原始日志](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r132/UniXNU.log:4164)。

### r133：签名 ZAP 认证和安全模式切换通过，2D 仍等待完成

本机原始签名 ZAP 的 PAS13 INIT、MEM_SETUP、精确 1072 字节段复制和 AUTH 已实机通过，
共七次真实 SMC；认证后没有继续访问该保留段的 CPU 内容。
随后提交固定 `CP_SET_SECURE_MODE(0)`（`70e60001/0`），实际 idle 完成，
`TRUST_CNTL` 从 1 读回为 0。未直接写该寄存器来伪造模式切换。

固定 247 DW 的 32×32 CP_BLIT IB 已提交，外层 RPTR/WPTR=16；但 10000 次有界
轮询后仍为 `RBBM_STATUS=00800005`、IRQ=0、CP fault=0，CP/GPU idle 未完成。
外层指针一致不证明 IB 内部或图形引擎已完成；本轮没有执行成功后的像素读回，
不能宣称清屏、真实绘图、XNU GPU 后端或桌面硬件加速可用。

约 58.37 秒自动返回 OrangeFox；原生日志 payload 384402 字节、CRC32 `f2e5b2af`
校验通过，五个启动分区、12 处 GPT 范围及 misc 保留区仍一致，XNU 未启动。
见[结果清单](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r133-result.json)、
[认证及 2D 原始日志](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r133/UniXNU.log:3469)及
[自动采集与 CRC 记录](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r133/capture.json)。
GPU 仍为当前最高优先级；后续 r134 的合并采样结果如下。

### r134：首个 GPU 标记写回，等待／线程切换区间继续定位

r134 重复通过签名 PAS13 认证及退出安全模式的 idle 检查，随后提交含八个固定进度
标记的 287 DW IB。CM3 reset 与实际三项隔离 ACK 完成后读取七页保留区，只有
标记 1=`4B490101` 写回，mask=1，其余标记仍为 CPU 初始 `A5A5A5A5`。
输出红像素=0、原始输出 CRC32=`5e877891`，其余保护内容完整。
该隔离后诊断没有设置运行期 completed、readback-verified 或渲染成功。

标记 1 后还有 `WAIT_MEM_WRITES`，再接原始两 DW `THREAD_CONTROL BOTH` 和标记 2。
因此当前证据只夹住“首标记写后等待 → THREAD_BOTH → 次标记写入”的区间，
没有证明 THREAD_BOTH 已执行，更不能直接断言正在等待 BV。Mesa 固定源码确实说明
切换 `CONCURRENT_BIN_DISABLE` 会触发隐式线程同步及 BV skipsaverestore；
本机从 CP_INIT 的 bit27=1 到 BOTH=3 存在该切换，与上下文假说一致，但因果尚待对照。

超时前两阶段的 20 项原始读取均有效；IB1 base=`62084000`、remaining=`1f`，
`CP_STATUS_1=8001040a`，CP IRQ、保护及硬件故障寄存器均为 0。
remaining 是独立长度寄存器快照，不是 SQE PC；不能用 287−31=256 推断已执行 256 DW。
隔离前读取的 SMMU FSR=`400` 也不是 translation fault：其 FORMAT=2，
`FSR & c00001fe = 0`，TF、SS 和 MULTI 均未置。FAR=`1f7ffdffffffc`、
FSYNR=`17057f` 保留为原值，不能当成本轮有效故障地址或访问类型。
r132 成功写回时也有 FSR=`400` 和类似 FAR/FSYNR，不能据此补映射或扩大权限。

约 58.439 秒自动返回 OrangeFox；原生日志 payload 394018 字节、CRC32 `a7586b06`
完整，五个启动分区、12 处 GPT 范围和 misc 保留区均未改变，XNU 未启动。
见[结果清单](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r134-result.json)、
[隔离后标记及输出诊断](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r134/UniXNU.log:3495)和
[超时前原始寄存器](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r134/UniXNU.log:3525)。
r135 增加 Linux 外层首次上下文初始化后，同一 287 DW IB 已通过真实 GPU 2D 绘图，详见下一节。


### r135：A750 首次上下文初始化及真实 32×32 GPU 2D 绘图通过

保持原签名 PAS13 认证、安全模式退出、GPU 页表及 287 DW 图形 IB 不变，在特权
外层 host ring 加入 Linux 固定源码对应的 25 DW 首次上下文初始化。它验证当前
bank0 根表 `D1DEB000` 与 ASID `751`，保留 BR/BV 同步、上下文状态重置、同根表
更新和缓存事件，再有界等待完成。该外层序列完成后才允许提交原图形 IB。

本轮实际完成上下文初始化和 CP_BLIT，运行期 `completed=1/readback-valid=1/verified=1`，
输出为 32×32 共 1024 个 RGBA8 红像素 `FF 00 00 FF`，完整输出 CRC32=`E843B26A`。
七页保留区检查通过，八个 GPU 进度标记全部写回（mask=`FF`），保护内容完整。
CPU 初始输出页为 `6D`，没有向输出页写入预期红色；这与仅由 CP_MEM_WRITE 写回
一个 canary 或仅观察外层 RPTR/WPTR 不同，已取得图形引擎的实际像素结果。

| 实机结果 | r134 | r135 |
| --- | --- | --- |
| 外层首次上下文初始化 | 未提交 | 25 DW，实际 idle 完成 |
| 图形 IB | 同一 287 DW 进度测试 | 同一 287 DW 进度测试 |
| GPU 标记 | 仅标记 1，mask=`1` | 八个均写回，mask=`FF` |
| 红像素／输出 CRC32 | 0／`5E877891` | 1024／`E843B26A` |
| 运行期完成与像素验证 | 超时，未进入成功读回 | completed/readback/verified 均为 1 |

实际 host ring 门铃位置依次为 10（CP_INIT）、12（模式切换）、37（首次上下文）、
41（图形 IB）、46、51（两个独立 canary）；最终 `code=0/phase=8/kicks=6`，
`RPTR=WPTR=51`、RBBM=1、IRQ=0、CP fault=0，canary 为 `C0FFEE00/C0FFEE01`。
首次上下文和图形提交的 kick/idle code 均为 0，未出现首次 guard 或 IO 失败。
这组对照支持首次上下文初始化是前一版缺少的前置，但没有进一步隔离 25 DW 中
每个包的必要性，也没有证明 r134 卡住的确切 SQE 调用位置。

pre-2D 的 20 项 CP/GPUCC 原始观察全部有效。本轮图形等待没有超时，因此没有
触发 post-timeout stage1 采样；缺少该阶段符合本轮成功路径，不是日志漏抓。

正常最终 HALT 的精确 `SQE==3` 条件仍未通过：1000 次 poll 首末均为
valid=`3F`、failed=`1`，实际 SQE=1、RPTR=`33`（十六进制，即 51）、RBBM=1、
IRQ/fault=0、busy=`71000000`。随后实际 CM3 reset 与三项 halt ACK `1/3/3`
完成隔离，`unsafe=0` 后才持久化日志。普通 HALT 尚未适配完成，资源继续保留到
平台复位；不能把紧急隔离通过描述为普通 HALT 成功。

后台轮询在约 52.154 秒后自动取回 OrangeFox 日志，无需人工拍摄。
`UniXNU.log` 共 398690 字节，最后快照 payload 398623 字节、CRC32=`9D191471`，
实际值与 footer 相同，SHA256 为
`e1f497c2392be8607c38f08f0301cae341ab3f401338a142cc5a3bb7c0345170`。
五个启动分区、12 处 GPT 范围与 misc 保留区均复核未改变。该轮只运行 UEFI，
没有启动 XNU；`XnuLog.bin` 仍是未提交的初始内容，不属于本轮 GPU 日志完整性失败。

这证明 A750 的原生 CP_BLIT 2D 图形及像素读回已通，不表示 shader、CP timestamp
fence、XNU GPU 后端、Metal 或 iOS 桌面 GPU 加速已经通过。后续接入仍需在 XNU
内建立相应资源所有权、BO/VM、提交、同步及显示发布链，不能直接继承本轮 UEFI
低地址缓冲区的所有权。

证据：

- [r135 结果清单](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r135-result.json)
- [上下文、提交与最终隔离原始日志](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r135/UniXNU.log:3403)
- [实际像素验证、八个进度标记及 pre-2D 采样](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r135/UniXNU.log:3623)
- [采集大小、SHA256 与 CRC 校验](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r135/capture.json)
- [自动回收轮询记录](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r135-watch.json)

### r136：Loader 连续内存不足与旧 RootRAM 预留

r136 原计划进入 XNU 执行 CPU 页几何探针，实机照片显示 Loader 返回
`Out of Resources`。申请量为 8 GiB，最大连续空闲区仅 7547682816 字节
（约 7.029 GiB）；本轮没有进入 XNU，CPU 探针和 GPU 执行均未发生。
此前 `HOUJI_ROOT_RAM=1` 保留的旧 EMPTY 根卷区间为
`[0xA81E08000, 0xBEA400000)`，大小 `0x1685F8000`（约 5.63 GiB），
该已不用的预留挤占了连续空闲空间。不能把此轮失败归因于 XNU 页 ABI 或 GPU 驱动。

返回 OrangeFox 后，五个启动分区、12 处 GPT 范围与 misc 保留区复核未改变。
最后一份原生日志快照 payload 17497 字节、CRC32=`E1EFC2C1` 有效，但只提交到
`before-XNU-CPU-page-geometry`；Loader 返回状态来自照片，不声称已写入该快照。
本轮由用户手动返回，初始 `XnuLog.bin` 不是已提交的 XNU 运行日志。

r137 保持同一内核和 8 GiB ADT，保留 `HOUJI_HIGH_RAM=1`，将
`HOUJI_ROOT_RAM` 改为 0。实际解压 FVMAIN 已确认不含旧 RootRAM 模块 GUID
`b8f44837-e6d6-43ab-9f23-eaf721117180`。四条可处理退出路径统一经过恢复 helper，
6963 项离线检查及既有 recovery 测试通过；这不覆盖硬件卡死，尚无 hardlock
watchdog。上述配置检查只证明候选取消了旧预留；r137 的实机结果见下一节。

证据：[r136 结果清单](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r136-result.json)及
[r137 实际固件配置证明](${HOUJI_ARTIFACTS}/native-port/native-ios-candidate/r137-firmware-profile-proof.json)。

### r137：进入 8 GiB XNU 窗口，CPU1 启动超时

r137 实机照片确认已经越过 Loader，进入所申请的 8 GiB 内核窗口。
CPU0 的实际 `TCR_EL1=226511A511`、`TG0=2/TG1=1`，对应当前 16 KiB CPU 页配置；
`TTBR0=8C2238000`、`TTBR1=8C223C000`。这只确认 CPU0 当前转换配置，
尚未执行后面的独占 descriptor 内存探针，不能当作全部 8 GiB 内存或 GPU4K 映射资格。

CPU1 的真实 PSCI CPU_ON 返回 0，entry=`8C148C020`、context=`8C27C6730`，
但 init 未观察到，state/timer/IPI/MPIDR 均为 0，最终在 `SweetCPU.cpp:157`
出现 `HOUJI SMP: CPU1 startup/SGI timeout`。返回值不能替代 secondary init、
定时器或 IPI 的实际运行证据。上述诊断来自照片，没有被写入本轮 XNU 日志。

后台在约 127.618 秒完成 OrangeFox 自动回收与抓取；已观察到自动返回，具体
复位机制仍未证明。UEFI 原生快照 payload 17497 字节、CRC32=`026F70C6` 有效；
`XnuLog.bin` 仍是本轮编号匹配但未提交的初始文件。五个启动分区、12 处 GPT 范围
及 misc 保留区未变。本轮不计作 CPU 内存探针、GPU 执行或 XNU 日志写回成功。

证据：

- [r137 结果与照片摘要](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r137-result.json)
- [r137 CPU1 超时原始照片](${HOUJI_ARTIFACTS}/native-port/evidence/r137-cpu1-startup-timeout.jpg)
- [r137 两类日志的独立完整性结果](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r137/capture.json)
- [r137 自动回收轮询记录](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r137-watch.json)

### r138：八核、CPU16K 内存及实际 NativeAdrenoMemory BO 检查通过

r138 增加两个有类型启动变量的 PoC 发布后，实际完成八核启动、全部 secondary
bound worker、timer 和 IPI 检查。最终汇总的八个核心 `TCR_EL1` 均为 `226511A511`、
`TG0=2/TG1=1`，`PAGE_SIZE/page_size/kernel_map_page` 均为 16384、shift=14。
该对照没有分别隔离两个变量的必要性，但本轮已取得真实 secondary 运行证据。

独占 16 KiB CPU descriptor 的四个 4 KiB 子范围观察均有效，`rows=4/4`、
`code=0`，prepare/complete/release 通过、retained=0。随后直接运行候选的实际
`NativeAdrenoMemory`，创建两个彼此独占 CPU 页的 BO：

| BO | logical／owned 字节 | 物理字节地址 | pmap 属性报告／采样掩码 | 释放结果 |
| --- | --- | --- | --- | --- |
| 0 | 4096／16384 | `8C5D10000` | `2/6/0`，mask=`3` | status=0，released=1，quarantined=0 |
| 1 | 4096／16384 | `8C5D14000` | `2/2/2`，mask=`7` | status=0，released=1，quarantined=0 |

BO0 的第三格 `0` **没有采样有效位**：mask=`3` 只表示前两次观察有效，不能解释成
恢复失败。release 内部先验证恢复默认属性，再 complete 和释放；探针没有在 free
后访问 BO0 来填第三格。相邻 BO1 的属性及模式内容保持不变，两个 BO 均成功释放，
quarantine/retained=0。24 次实际 CPU AT 读／写翻译样本均取回，默认 PAR 属性
最高字节为 `FF`，BO0 write-combined 后为 `44`；MEM RESULT 为 phase=9/code=0、
neighbor=1/completed=1。上述结果只资格化 CPU 翻译、缓存属性和 backing 隔离，
没有安装 GPU 映射或执行 DMA。

正常 checkpoint3 提交并读回 XNU 日志后，执行 BCB 核验和 PSCI 返回；后台约
41.481 秒完成 OrangeFox 回收。`XnuLog.bin` 本轮 `committed=true/valid=true`，
运行编号匹配，正文 38974 字节、CRC32=`B586E25C`，头 CRC32=`322BEB1A`；
UEFI 快照 payload 17497 字节、CRC32=`CD99A78E` 也有效。五个启动分区、12 处 GPT
范围及 misc 保留区复核未变。本轮在 HFS 挂载前停止，未执行 GPU 或桌面加速测试。

新增默认关闭的 `houji_panic_recovery=1` 已有 host/object 检查，**本轮未触发 panic
返回路径**。它使用真实 PSCI SYSTEM_RESET，panic 中不访问文件系统、提交日志或
改写 BCB，依赖主机事前独立验证的 no-wipe BCB；硬件 watchdog 尚未接入。
不能把正常 checkpoint3 的自动返回扩大为任意 panic 或硬件卡死都能恢复。

证据：

- [r138 实际结果清单](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r138-result.json)
- [八核运行与最终核心页配置](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r138/XnuLog.txt:389)
- [descriptor、两个实际 BO、AT 及释放结果](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r138/XnuLog.txt:457)
- [r138 提交完整性与稳定抓取结果](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r138/capture.json)
- [r138 自动回收轮询记录](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r138-watch.json)
- [r138 panic 复位候选的源、host 与 object 资格](${HOUJI_ARTIFACTS}/native-port/evidence/xnu-panic-recovery-r138/capture.json)

### r139：CPU 构建未启用的 GPU4K 页表，受控 panic 配置下自动返回

r139 重复通过八核和 CPU 内存检查，随后在两个独占 16 KiB backing 上运行实际
`ArmSmmu4KBuild/AuditTables`。数据 PA=`8C5D14000`，表根 PA=`8C5D18000`，
四页表容量中使用三个 4 KiB 表页，生成四个 4 KiB 叶页；实际物理 descriptor 审计
读取 1536 次，连同独立查找共读取 1554 次。`phase=9/code=0`、audit complete，
spare 表页保持零，相邻 IOVA 无映射，两个 BO 都释放且 quarantine/retained=0。
这些表始终不对 GPU 可达，没有写入硬件 context、安装 SMMU 根表或执行 DMA；
CPU PoC clean 和 CPU 页表遍历不是 GPU 翻译、图形或桌面加速的资格。

本轮启用 `houji_panic_probe=1`：正常上下文先执行 no-wipe BCB 的读／改／写和
完整读回，记录 armed 意图，再成功提交并读回 XNU 日志，随后选中专用 panic
终止分支，不选正常 checkpoint reset 分支。该分支的实际链接 panic／PSCI 出口
已核对，后台约 44.513 秒自动抓回 OrangeFox。保存的快照在故意 panic 前提交，
**未持久化 panic 文本**，不能把 armed 日志本身当作 panic 执行证据，也不能将
本次受控条件下的自动返回扩大为任意 panic 或硬件卡死都能恢复；硬件 watchdog
仍未接入。

`XnuLog.bin` 已提交且运行编号匹配，正文 41846 字节、CRC32=`692CA9BB`，头
CRC32=`283F3CA7`；UEFI 快照 payload 17497 字节、CRC32=`E465E256` 有效。
五个启动分区、12 处 GPT 范围及 misc 保留区未变。本轮未挂载 HFS、未执行 GPU。

证据：

- [r139 实际结果清单](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r139-result.json)
- [实际页表、物理审计及释放结果](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r139/XnuLog.txt:487)
- [受控 panic 的提交前意图记录](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r139/XnuLog.txt:504)
- [日志完整性](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r139/capture.json)及[自动回收轮询](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r139-watch.json)
- [CPU 表构建源码层与摘要](../native/gpu/xnu/table-runtime-manifest.json)

### r140：电源标量交接与 XNU 独立只读复核通过

r140 只在 UEFI 保留已取得的电源／时钟引用和 held-reset 总线状态，不装载
GPU 固件、不释放 CM3、不配置 SMMU stream/context，也不提交 GPU 命令。
1376 字节 v1 标量记录带 CRC，经 DarwinBoot 校验完整记录和 `complete=1` 后复制到
`/chosen/houji,gpu-power-handoff`；EFI 指针、缓冲区、页表根及 IOVA 不随之交接。
XNU 只接受同名、精确长度的 `OSData` 并重新解码，再新建静态保留的 Device
只读映射，先验证 GCC／CX／AHB 等前置门，再取回实际冷状态、原始时钟和各
stream/bank 状态，与标量记录比较。配置频率和名义推导值都不当作实际测频。

实际 XNU 复核 `code=0/observer=0/recheck=0/complete=1`，131 次读取全部有效，
八个访问门及四组新映射通过；CM3 reset=1、FWINIT/HFI=0、GXPOWER=3，
24 个 stream 为 FAULT、22 个 bank.M=0，无 GFSR。约 43.094 秒后首次检测到
自动返回 OrangeFox。XNU 已提交 61440 字节、CRC=`FBFE52AC`，运行编号匹配；
五个启动分区、12 处 GPT 及 misc 保留区均未改变。native CRC=`E099019C` 有效，
但其完整捕获标题误留 r139，监听器因此重复取证三次后拒绝自动通过。
该标题问题已单独记录，不能将监听器拒绝误解为硬件复核失败。

`exclusive` 只描述
本轮软件单 owner／同步调用配置，不声称硬件租约；只读 MMIO 本身如遇硬件
停止或异常，没有新加入的故障恢复框架。该轮仅为 fresh RO 验证，不发布
NativeAdreno/Metal 设备，也不取得 DMA 或桌面加速资格。

源码边界：[XNU 交接层摘要](../native/gpu/xnu/handoff-runtime-manifest.json)、
[Loader 标量复制层摘要](../native/gpu/handoff/darwinboot-power-handoff-manifest.json)。
实际证据：[r140 结果](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r140-result.json)、
[XNU 复核日志](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r140/XnuLog.txt:648)。

### r141：XNU 独立 TCM 写读与恢复通过，CM3 未执行

本轮关闭已验证的独立 RO/CPU 内存/表测试，使用新建的 XNU Device 映射和单次
TCM owner。1376 字节记录仍重新解码；9 次 fresh 观察覆盖最初资格与两次持久
检查点后的复核，另检查实际 CXO `03D99144`。TCM 读取允许合法全一数据。

实际流程为 58 字原值备份 → 固定 34 字代码与 8 个零邮箱写读 → 16 个栈字只读
核验 → 恢复曾写过的 42 字 → 独立核验全部 58 字。共有 84 次实际 store、216 次
TCM load，写后 DSB 与逐字读回均通过；`code=0/native=0/complete=1/safe-to-save=1`，
原值 CRC=`623071D5`。CM3 reset/control、SMMU、外部 RAM 均未写入，代码没有执行，
不能解释为 GPU 任务或 GPU 写回已通过。

首次约 41.949 秒检测到自动返回，监听器一次抓取即 `complete`。修正后的完整
native 标题为 r141，native CRC=`D6BDFD43`；XNU 已提交 45377 字节，
正文 CRC=`4256E192`、头 CRC=`A46EAE0C`、run ID=`75ab0654de854d2895a208cf0bb80aa6`。
五个启动分区、12 处 GPT 及 misc 保留区仍与基线一致。

`safe-to-save` 只表示已恢复并可保存诊断，不能替代 `complete/code`。若资格未知，
调用方直接 panic，使用既有 PSCI 返回，不再进入后续 checkpoint/HFS。

见[r141 结果](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r141-result.json)、
[实际最后报告](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r141/XnuLog.txt:510)
及[实际源码层](../native/gpu/xnu/held-tcm-runtime-manifest.json)。

### r142：XNU 启动固定内部 CM3 程序并取回完整邮箱

同一轮完成冷态备份、42 字代码／零邮箱写读、9 个控制字准备、提交后真实复读
42+9 字、释放 CM3、完整邮箱检查、重新复位、恢复及最终审计。运行期间使用实际
reset=0 的独立观察器；cleanup mode2 只允许实测 reset=0/1，不改造冷态快照。
全程没有 GPU context、外部 RAM、HFI 固件或 CP 命令。

实际八字邮箱为 `A7500002/750C0DE0/00000080/0/0/0/0/0`，有效位 FF，
首次 poll 已完成。CPU 在运行前只向邮箱写零；这些签名由 CM3 程序写入，属于
软件载荷常量，不能用作硬件 ChipID。reset 读回 1 后完整恢复 58 个 TCM 字及
前 7 个控制字，两个 IRQ mask 保持屏蔽；stack changed=0。
实际 118 次 store、2423 次 load、16 次 fresh 检查、3 次提交，最终
`code=0/native=0/complete=1/safe-to-save=1`。所有资源保留至平台复位。

约 41.969 秒检测到自动返回，监听器一次抓取成功。XNU 正文 49921 字节、
CRC=`A2B101DA`、头 CRC=`6EF892FE`，run ID=`8045bb69c39a483a979ddc94ed090b05`。
五个启动分区、12 处 GPT 及 misc 保留区均与基线相同。
这是内部微控制器执行验证，**不是 GPU CP 执行、外部 RAM 写回或桌面加速**。

见[r142 结果](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r142-result.json)、
[最终实机报告](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r142/XnuLog.txt:537)
及[实际源码层](../native/gpu/xnu/internal-exec-runtime-manifest.json)。

### r143：外 RAM 探针前置退出，自动返回和日志抓取正常

XNU 八核 bound worker、timer/IPI 检查通过。约 43.580 秒后自动返回 OrangeFox，
监听器一次捕获通过；XNU 正文 34261 字节、CRC=`3A27694B`、头 CRC=`51C71196`，
run ID=`19d55ecc1f9a42f19536bc8f98cfe58c`。最后持久检查点为外 RAM canary 入口，
没有第一笔 GEC backup commit 或最终结果，不能声称 GPU context／DMA 已执行。
最初 NativeFresh 或独占内存准备拒绝后的诊断仅在 RAM 中，随后 PSCI 返回未追加 FS。
五个启动分区、12 处 GPT 及 misc 保留区与基线一致。

离线实际 core 3452 项、NativeMemory/Cpu/adapter/core 5006 项 ASAN/UBSAN 测试通过，
完整内核已链接并核对真实 MMIO 屏障。它们不能代替此次缺失的硬件完成证据。
下一轮仅在无 GPU store／publish／device refs 且独立真实 cold 复核通过时保存前置失败；
不会用该日志资格放宽 canary 的执行门。

见[r143 结果](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r143-result.json)
及[最后已提交检查点](${HOUJI_ARTIFACTS}/native-port/evidence/logfs-recovery-r143/XnuLog.txt:457)。

### r144：早期诊断确定为初始化前 SCTLR 误判

新增的独立131次冷态RO在无GPU写入、无publish/refs/core启动时验证通过，允许保存
原始失败快照。raw observer返回0、有效位1fff，但初始 selected SCTLR=`3FF5A71E`，
Native误要求全部为0而拒绝；ACTLR=3、PRR=0、FSR=0，TTBR等未初始化字段只备份。
原UEFI使用`SCTLR & 0x41`初始门，再写canonical禁用配置，不能把后置零值门前移。
此诊断资格不继续core或设置safe/complete；保存后的复核不在本次durable快照中。
XNU正文37243字节、CRC=`6B235AEA`、头CRC=`234DCC75`，
run ID=`30661FC2EF6347AF9E2DF6FF09ACB427`。44.098秒首次发现恢复；ADB迁移导致
首次捕获失败，5038端口重试取得有效匹配快照。启动分区、GPT和misc保留区不变。

### r145：独占内存、GPU页表及禁用上下文准备通过

按UEFI阶段边界修正初始SCTLR门后，三个独立16KiB BO、完整高36位PA/AT和
一条4KiB映射通过；邻页60002000保持未映射。实际表PA=`8C5D90000`、
data=`8C5D94000`、zero=`8C5D98000`；1536次descriptor审计通过，持有/发布mask=7。
68TCM+9control+9context原值已保存，52代码/邮箱字和9控制字写读通过。
77次实际store和对应DSB通过，已知禁用配置SCTLR=0，
TTBR0=`7500008C5D90000`、ACTLR=`32B`、PRR=`8C5D98000`。

最后durable快照在第二次callback保存前（attempted2/returned1），之后仍退出；
不能据此确定是否已启用上下文、释放CM3或进入运行期，也不能声称外RAM写回通过。
约42.555秒自动返回，监听一次捕获，正文42323字节、CRC=`166C879C`、
头CRC=`80D3FC67`，run ID=`E38CCAE7BC1545BCB1A3B38C3789AA7F`。
启动分区/GPT/misc保留区不变。见[r145结果](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r145-result.json)。

### r146：已启用上下文和 SID5 路由，外部写回仍未通过

实机 checkpoint 确认 80 次寄存器 store 及对应 DSB 已返回，前两次原生保存回调
已返回；bank2 SCTLR=`27`，SMR=`80000005`、S2CR=2，TTBR0、ACTLR 和 PRR
仍指向持有的私有对象。独立保存前复核的 149 次读取返回，表 CRC=`37003949`
与原始表一致；CM3 reset=1、release_seen=0、possible_execution=0。

最后快照产生于这次保存回调返回及保存后复核之前。因此它不能证明随后释放了 CM3，
也不能证明外部 RAM 写回、CP 执行或桌面加速。正文 46823 字节、CRC=`A89ACC8D`、
头 CRC=`065829CD`，run ID=`8FD747A5CC714F1DA900DAC34585D5A7`。约 46.029 秒
发现返回 OrangeFox，第二次捕获得到完整有效快照；启动分区/GPT/misc 保留区未变。
见[r146结果](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r146-result.json)。

### r147：失败末尾的缓存状态显示，尚待实机观察

仅在 core 已启动但不能安全保存的原有失败出口，显示四行 `HOUJI GMU STOP`，
随后 `IOSleep(8000)`，再沿原来的 false → panic/PSCI 路径返回。四行只读取已经
完成的 CPU 内存记录，不增加 GPU MMIO、文件系统写入、资源释放或恢复测试资格。
独立保存前/后复核若比普通 Fresh 更新，第二行选择其真实原始快照；未读字段仍可能
无效，不能把零值当作硬件状态。正常成功不等待 8 秒。此版本尚未实机启动，
实际 ARM64 对象编译及 5276 项原生主机用例通过。

### r147 实机：故意负向访问进入异常分支，原完成判据拒绝

运行约 50.448 秒自动返回 OrangeFox，51.206 秒完成一次捕获。XNU 正文 46810
字节、CRC=`B7DCDF2E`、头 CRC=`CCBADD88`，run ID=`164AF4BF4BD44DD087EACEE8461D1D7A`。
启动分区、GPT 和 misc 保留区校验未变。文件快照仍停在 release 前；后续状态来自
`IMG_0770.MOV` 的 24 秒画面，不能当作已落盘日志。

画面确认 release、运行态 Fresh 及随后 reset 返回；完整邮箱为
`A750DEAD/7504CAFE/86500071/A750CAFE/0/0/8200/60002000`，
SMMU FSR=`402`、FAR=`60002000`、FSYNR=`1F0023`，精确负向读取故障成立。
原 176 字节载荷访问未映射地址后，异常处理器写入 `A750DEAD` 和 CFSR/BFAR；
当前 GEC 在 poll 阶段直接记 `GEC_FAULT`，只认可正常返回的八字邮箱，因而退出。
此时尚未退役 stream/bank/TLB 或进行 CPU invalidate/独立内存核验，仍不称写回通过。
见[r147结果](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r147-result.json)。

### r148 候选：精确负向异常及真实栈帧契约

保持原 176 字节载荷、映射和寄存器写入序列。新增的完成路径只接受上述完整八字
邮箱、同一精确 SMMU 故障，以及实际读取的八字异常帧；下八字栈 guard 必须原样。
帧中 R0/R1/R2/R3、PC=`6E` 和线程/T/IT/对齐状态固定；R12/LR 及 NZCVQ 仅作
原始数据保留，处理器不会使用它们或异常返回。原始栈变化 mask 保留，不伪装为零。
任何未知帧立即停止，正常返回路径的未知栈变化也提前停止，不进入 CPUfinish/FS。
Native 的隔离门采用相同完整判据，其他隔离、TLB、恢复和 CPU 内存核验保持。

4325 项核心及 6050 项原生适配主机用例通过。另以同一机器码执行 32 组真实
Unicorn 未映射读取失败，再显式构建架构规定的异常入口并执行原 handler；此项
不模拟设备 NVIC，也不是硬件异常交付证明。帧布局、精确故障 PC 及 DSB 语义依据
[ARM Cortex-M3 Guide](https://documentation-service.arm.com/static/5ea823e69931941038df1af5)。
候选仍需实机验证全部退役及 CPU 缓存/内存链路。

### r148 实机：XNU GMU 高 PA 外部内存写回及精确负例通过

最终落盘结果为 `phase=25/code=0/native=0/complete=1/safe-to-save=1`，
positive/negative/isolated=1。实际栈帧为
`10004000/A7500001/60002000/A750CAFE/0/FFFFFFFF/6E/01000000`，
下八字 guard 原样，raw changed=`FF00`；全八字邮箱及 CFSR/BFAR 与预期精确匹配。
表/data/zero PA 分别为 `8C5CEC000/8C5CF0000/8C5CF4000`，CPU backing 各
16KiB，唯一 GPU 映射仍为 4KiB。179 次 store/DSB、422 次 load 全部返回。

stream/bank/TLB/fault 已退役，TTBR0/1=0、ACTLR=3、PRR=0；68 个 TCM 字恢复并
读回，七个控制字恢复，两个 IRQ mask 保留禁用。原生 CPU invalidate 已执行，
读到设备标记 `A750CAFE`；1024 字数据和 data/zero/table spare/padding 验证通过，
CPU 标记已恢复为零。三次 GEC 保存及其返回均有后续落盘证据。所有 BO 仍持有至
平台复位，未据此声称正式 HFI、CP、图形或 Metal 桌面加速。

42.699 秒发现 OrangeFox、43.818 秒完成一次捕获；XNU 正文 56108 字节，
CRC=`48E7ECAA`、头 CRC=`BC00E71C`，run ID=`EFDC2F37062B41BC94D9E1AF91E51ABC`。
五个启动分区、12 处 GPT 和 misc 保留区校验未变。
见[r148结果](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r148-result.json)。


### r149 实机：原厂固件和 HFI 的 inactive CPU 内存准备通过

以真实 NativeAdrenoMemory 分配 9 个互不重叠的独占 BO，逻辑共610304字节，
完整 CPU16KiB backing 共671744字节。原厂 GMU 固件78588字节的长度/SHA和15条记录
验证通过，77808字节已装入内存，540字节TCM内容仅记录、未写硬件。
17个HFI队列、log/VRB及全部零洞/尾部均逐字节验证。6张GPU4KiB表和139叶页
经3072次描述符读取审计；2624次真实AT校验完整owned范围的R/W物理地址和属性。

所有BO refs=0、retained=1FF；HFI/log/VRB的descriptor为NormalNC，已知
phystokv别名仍WB。alias仅AT，不读取/写入其数据。该轮明确DMA-eligible=0，
无SMMU/stream装载、MMIO、SMC、TCM写入或固件执行。纯CPU拒绝分支另保存报告，
不改变任何active GPU失败路径的no-FS规则。

2743项真实Native host边界/失败profile及Cbridge105724断言分别通过ASan/UBSan；
实际链接审阅确认AT、PAR/DAIF保存恢复、DC/DSB与真实Native firmware/SHA/Cbridge调用。
这些离线检查与本轮真实硬件成功分别保存，不互相替代。

42.391秒发现OrangeFox，43.019秒完成一次捕获，无固定grace sleep。
XNU正文37082字节，CRC D54EAFB3、头CRC 6E7DFBC9；run ID
AA4783E2A9B647FA9E6D5BDB238A5E25。BOOT5、GPT12及misc保留区不变。
见[r149结果](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r149-result.json)。


### r150 实机：独占 NormalNC 有限 GMU 写回通过

code/native=0、phase25/complete/safe-to-save/positive/negative/isolated全1。table/data/PRRzero PA分别8C5CF4000/8C5CF8000/8C5CFC000，各有完整CPU16KiB backing，仅data映射GPU4KiB。data/zero真实descriptor PAR Attr44，aperture AttrFF；每个完整64位R/W PAR被锁定并再次核对，aperture从未用于数据访问。

NC-publish=6、NC-acquire=6、NC-restore=1，真实DSB/DMB调用3/2；只有WB表invalidate，CPU data invalidated=0。实际CPU通过NC映射读到A750CAFE，1024 words和全部owned padding/zero/table尾部正确，marker已通过NC写回及DSB恢复。179个store/DSB和422个load全部返回，三次core日志提交及返回均有后续证据。stream/bank/TLB/fault退役与68TCM/7control恢复通过，三BO和refs保留到平台reset。

Core WB4325、NC4444（64旧结果全字节比较、新tail全零及严格NC完成字段）、Native WB6050/NC6479与32pinned机器码执行分别离线通过；实际链接的AT/PAR/DAIF、NC屏障和真实缓存函数另核验。该轮只是有限NormalNC ownership/cache路径的实机资格，不代表liveHFI/原厂固件/CP/桌面加速，也不宣称系统全部别名不存在。

见[r150实机结果](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r150-result.json)。


### r151 实机：原始 secure-CX INIT 通过

r151 同一启动中，NormalNC GMU 小程序执行/写回 complete=1、safe-to-save=1，原厂固件/HFI 的 CPU 内存准备 complete=1。原始 convention、availability 和 secure-CX INIT 三个固定 SMC 均实际返回成功；每次返回后独立冷态、时钟、上下文及 12 BO ownership/cache lease 核验通过，最终 phase4/complete1、13 次 cold proof。无 busy 或 interrupted 重试。

日志正文 61440 字节，CRC D044EA6E、头 CRC 9B144BA6，run ID 33795257AB204AFBB2DC0BF5847902BE。46.544 秒检测到 OrangeFox，47.535 秒完成身份/CRC 绑定捕获，无固定 grace sleep；BOOT5、GPT12、misc 保留区均未变。

此轮没有执行原厂 GMU 固件、HFI、CP 或图形命令，不是桌面 GPU 加速的完成证明。下一步集中实现原始固件/HFI 端到端；资源在可能执行后保留，未知 DMA 状态不得写日志分区。

见 [r151 实机结果](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r151-result.json)。


### r152 实机：原厂 GMU 固件和 HFI 查询通过

照片 IMG_0773.HEIC 的实际末尾为 phase10/code0/native0/bridge0、FW1/HFI1/QUERY1/1/VALUE1/STATUS0。TCM loaded/backup=135/8192、RSC19、BOOT19、RX1/1且dropped0、reads9455/writes194；原始响应为 0001040c/0010030c/00000001/00000000。reset attempt/return=1/1，九个FW BO refs1ff和PRRzero额外ref保留。

完整流程直接调用原始 hgf_run 和 ggh_send/receive，输入为同一HhiState真实result而非summary重建。HHI先在FW refs0时验证内容并永久seal，第一次原始prerequisite冷态确认后才持有FW refs和PRRzero额外ref；WB全owned CPU16K页在执行前CIVAC，NC仅从独占descriptor访问。实际链接确认volatile32/64与DSB/DMB、真实result地址以及terminal panic不能流到checkpoint3。

自动恢复检测54.901秒、捕获55.643秒，current-run CRC绑定正文保存到pre-stock-write checkpoint1。执行后的成功证据来自用户照片，**不声称末尾自动落盘**。raw FSR=400/FAR=60002000保留记录；该值不能宣称为零，也不能单凭它推定新DMA错误。未知或执行后的任何终止均不写FS、不退役引用、不撤映射，只经缓存报告/8秒显示/已武装PSCI返回。BOOT5、GPT12、misc保留区复核不变。

这一轮没有CP、PM4、host ring、HWSCHED或图形执行，桌面GPU加速尚未完成。下一步沿现有UEFI成功的普通host-profile五消息路径（PERF4/BW3/CORE14/START10/QUERY12），不误走HWSCHED9步资源分支，再迁移实际图形内存/代码/bank0+SID0/1/命令环。

见[r152实机结果](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r152-result.json)。


### r153 实机：普通主机模式五条 HFI 消息全部应答

IMG_0780.HEIC确认 mode2/attempted1/code0/0/stage5/completed5/5/qualified1/resources0/0。PERF4、BW3、CORE14、START10全部3DW legacy ACK（value0、无第四个status）；QUERY12为4DW ACK/value1/status0/present1。六条实际RX、十次receive调用、dropped0，reads9608/writes199，较r152只增加五次doorbell。TCM135/8192、RSC19、BOOT19；九FW BO refs1ff与PRRzero额外ref均保留，终态reset1/1。

原始hgf→hhp及queue代码直接运行，未新增MMIO范围；未启用HWSCHED/AQE、未分配资源、无CP/PM4/图形执行。此处qualified仅代表固定五消息兼容，不独立证明GPU最终选择的运行模式。执行后的实际证据是照片；CRC绑定落盘正文仅到pre-write checkpoint1，绝不据此冒充完整末尾日志。

自动恢复检测54.664秒、抓取55.408秒。run ID 70C0AC77D024487B83E2D47F92647C23，正文CRC0C5BD811/头CRC546A4214。BOOT5、GPT12与misc保留区不变。见[r153结果](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r153-result.json)。


### r154 实机：原生完整主机前置通过

IMG_0784确认bank0与SID0/1连接、GX应答/清除、SQE/AQE四项代码地址绑定、Gen7 102/102操作及75项记录通过。15个BO和PRRzero引用保留，reset1/1。CP/ZAP/2D均未执行；UEFI旧CP/像素成功不替代XNU执行证据。

自动恢复检测58.818秒、抓取59.509秒。正文CRC F943942C/头9E4369E1、run ID ED1301AB458A45689EF7A8F9B5619956；落盘仅到首次设备写入前，执行后末尾由照片补齐。BOOT5/GPT12/misc保留区复核不变。见[r154结果](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r154-result.json)。


### r155 实机：原生CP执行、GPU写回、最终日志自动保存

真实XNU下CP_INIT完成，3次提交、RPTR/WPTR20/20、两次独立GPU写回C0FFEE00/C0FFEE01。Gen7/前置仍全部通过；CM3 reset1和GX/client/arb halt ACK1/3/3后保存终态日志，CRC56DC9D88，与IMG_0788一致。59.207秒自动回OrangeFox、59.869秒完成抓取，无需照片证明主要结果。照片补充的commit/readback/save-return回执在正文取样之后，头CRC独立确认已提交正文。BOOT5/GPT12/misc保留区均未变。尚无PAS/ZAP、2D或Metal执行，桌面加速未完成。

见[r155结果](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r155-result.json)。


### r156 实机：原生签名固件和真实2D绘制通过

同轮执行PAS13签名INIT/MEM_SETUP/AUTH（INIT含两次真实中断resume）、MODE0、首次25DW上下文、固定287DW CP_BLIT、两次GPU写回。1024红像素、CRC E843B26A、8进度标记FF、全部七页校验通过；6次提交RPTR/WPTR51/51。低地址metadata D2770000、raw D276F000/28672和全部BO一直保留；CPU16K目标映射中的IPA前8K未访问，1072字节目标复制后不再读/AT。CM3 reset和GX/client/arb ACK1/3/3后最终日志成功保存，自动恢复59.030秒/捕获59.751秒，BOOT5/GPT12/misc保留区不变。

原生2D执行已经证实，尚未发布持久运行期用户客户端或Metal桌面加速。见[r156实机结果](${HOUJI_ARTIFACTS}/native-port/evidence/native-ios-r156-result.json)。


## r157 实机：Native 运行期提交和 GPU fence

真实 NativeAdrenoRing 接管已初始化的同一命令环，未重置 ring 或伪造 fence；连续32次 framed CP_BLIT，每轮重新毒化输出后验证七页、1024红像素和 CRC E843B26A。GPU EVENT_WRITE7 时间戳真实递增1至32，最终 RPTR/WPTR=1523/1523、IRQ/CP-fault均0。180293微秒包含CPU图像校验和完整保护检查，不作为桌面FPS。

CM3 reset与GX/client/arb ACK1/3/3后自动保存完整结果，59.308秒恢复、59.948秒捕获。run ID 0F2A040B96954765A0BD2BE6C1A567C9、正文CRC8CCB1A1A；BOOT5/GPT12/misc保留区不变。动态VM、持久设备owner、用户客户端和桌面加速仍待接入。


## r158～r162：真实动态映射和 TCR 修正

r158 将 GPU 根扩为1027个硬件4K表页，保留完整1028页/257个CPU16K页。该根上固定32次绘制/fence继续正确。Live映射在第一次PTE写入之前拒绝上下文；r160/r161完整日志确认首次CP_SMMU_TABLE_UPDATE把TCR从80802020改为80002020，清除了EPD1。SCTLR轮询模式单独明确为1027（ASIDPNE读回可为0），不允许把中断模式静默当作有效。r159没有提交UEFI/XNU结果，仅保留原始初始化标记，不计作GPU测试成功。

r162在全部正常GPU master已空闲、原root/ASID/引用及图像严格匹配后，仅恢复未拥有的TTBR1上半区禁用位，再核对完整上下文并对bank0执行TLBIALL/Sync；没有换根或修改CPU/GPU页大小。此后四次映射/解除映射均通过：同一个40000000 GPU地址交替使用两个物理输出，32次绘制每次均有GPU fence及1024红像素/CRC E843B26A，最终generation8、fence64、RPTR/WPTR2995。全部资源保留；reset和三ACK后自动提交日志，BOOT5/GPT12/misc保留区不变。

同轮已链接真实NativeAdrenoVm/Submit/UserClient核心，但停在Streams观察器的GFSR读取：该已知寄存器漏列在适配层读地址校验中。未打开客户端、未分配新BO，不能把结果文字中的固定计划描述当成三BO已分配。r163修补此读取和结果描述，继续合并验证。仍无持久IOKit provider、Metal/shader或桌面加速的实机通过证据。


## r163/r164：Native BO、VM、提交和 fence 核心通过

r163 的额外末尾 I/O 记录确认两层读地址校验不一致，停在 SCR0 前、尚未分配 BO。r164 用同一个严格只读谓词覆盖原始 Streams/Context 观察器需要的全局寄存器、bank0 图像和全部24个路由槽；原函数的寄存器 peer 测试完成189次读取、0写入，并验证全局故障、冲突路由及未授权偏移拒绝。该测试不仿真GPU。

r164 真机实际打开 NativeAdrenoUserClient ABI v1 核心，3个独占 CPU16K NormalNC BO 完成3映射、16次真实 Submit/WaitFence、3次保留分配的TLB解除映射。每帧毒化后验证1024红像素、CRC E843B26A和其余CPU页保护区；fence80/80、RPTR/WPTR3731、generation14、job0。连同固定/动态阶段共80次绘制。真实CM3 reset与ACK1/3/3之后自动提交CRC绑定的完整日志；BOOT5、GPT12、misc保留字节未变。

持久设备owner、GPU/UFS并行、IOKit公开客户端、Metal/shader及桌面加速尚未通过。r165新增独立的live handoff状态，明确不把retained标作stopped；计划合并验证896次固定blit期间独立UFS读/预分配日志写，及10秒持续上下文，再真实隔离、保存和自动恢复。


## r165/r166：持续 owner 和 GPU/UFS 同时执行通过

r165 声明策略中有 runtime=1、实际UEFI BaseBootArgs却没有，故只重跑了已知80次提交，未执行live分支，不能记为持续owner通过。r166补齐实际参数，并按Darwin22的608字符ABI对比编译后EFI中的完整字面量；最终含动态touch与NUL最多602字符，没有改变boot_args结构。新增脚本 `scripts/check-compiled-uefi-bootargs.py` 校验每个静态参数、动态touch边界及实际PE字符串。

r166 实机独立验证UFS DMA 8C4510000/147456字节与全部27个原GPU/GMU BO、3个新BO、实际GPU/GMU页表及各映射均不重叠。随后4个GPU任务各执行224次固定blit，在fence未完成时2次读取系统卷头、2次提交预分配日志。读取前后fence仍分别80/80、82/82，写日志期间分别81→82、83→84；最后84/84、CRC E843B26A、generation20，所有16K保护区正确。该结果只授权这个实际保留owner的已验证独立UFS路径。

HHR/FHR/HGF使用独立retained-live状态，未把未停止的GPU标为stopped，也没有复位后重新建表来模拟持续运行。100轮后台检查均通过；每轮sleep100ms加完整审计，实际约19.67秒，不能把日志中的名义10秒视为实际墙钟时间。最后真实CM3 reset和ACK1/3/3后提交终态，84.323秒自动抓取完成，BOOT5/GPT12/misc保留区未变。试验停在用户态前，仍不是IOKit Mach trap、Metal/shader或桌面加速。下一轮接原v1 IOKit客户端的两轮创建/视图/绘制/关闭回收。


## r167：真实 IOKit 客户端、CPU视图和回收通过

已接原 NativeAdreno ABI v1 IOService/AGXDeviceUserClient，保留原生外部方法表；每次变更前在同一owner门锁内等待全部真实fence并审计活动VM。使用源码IOAcceleratorES→IOService兼容基类和136字节AGXAccelerator实例注册，不导入旧原始cache的类地址，不加载原IOGPUFamily。未启用上游额外sandbox grant、mailbox、blob导出和GOP handoff；BO CPU视图仅暴露自身完整CPU16K backing并显式使用WriteCombine/NormalNC。

真机两次创建/两次clientClose回收、4个完整CPU16K视图的PAR读写属性及4次真实外部方法绘制均通过，CRC E843B26A、fence88/88。仍从调用内核IOUserClient入口发起，尚未经过Mach trap或Metal。继续保持实际owner并完成后台检查后，真实CM3 reset/ACK1/3/3终态日志自动保存，88.250秒完成抓取，BOOT5/GPT12/misc保留区未变。

A750v2/GMEM/trap取自当前已实测的gen7寄存器配置；SM8650的UBWC4/HBB16来自Linux `drivers/soc/qcom/ubwc_config.c`，swizzle6与8-channel macrotile1来自同树 `include/linux/soc/qcom/ubwc.h` 的版本派生函数，原文件及SHA256保存在native-research。没有开启未经本机CPU16K验证的cache-coherent标志。AdrenoMetal/Turnip现有ABI v1构建已通过原688个必需导入核查并打包为probe-only候选；未将候选包当作shader/桌面加速成功。
