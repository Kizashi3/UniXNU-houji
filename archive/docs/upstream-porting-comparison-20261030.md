# 小米 14：最新移植仓库对照与可复用实现

核对日期：2026-10-30。目标保持为小米 14 / houji / SM8650 / A750v2，
使用所有者提供的 iPhone X iOS 16.7.16 / 20H392。下文的外部实测均指作者的设备，
不能代替本机验证。源码副本、版本清单和本机检查保存在
`out/upstream-comparison-20261030/`。

## 固定的参考版本

| 仓库 | 已核对版本 | 本次用途 |
| --- | --- | --- |
| [UniXNU/UniXNU](https://github.com/UniXNU/UniXNU/tree/f0721e9745c45ad2600cd69c74730f1cca55d56a) | `f0721e97` | format 2 迁移、组件目录、设备记录、WebKit 路径 |
| [UniXNU/UniXNU-sheng](https://github.com/UniXNU/UniXNU-sheng/tree/08cde20edc3254ed6f7df8d0f5384fb887786e8f) | `08cde20e` | CPU/GPU governor、显示、ADSP、音频、电池；iPadOS 17.7.11 |
| [rootstockos/UniXNU-asteroids](https://github.com/rootstockos/UniXNU-asteroids/tree/014bd043037b73a4dc686df8ddec845deb63a675) | `014bd043` | Nothing Phone 3a 的提交耗时、内存池、GPU trace、AMOLED 亮度 |
| [rootstockos/NativeAdreno](https://github.com/rootstockos/NativeAdreno/tree/5e2b23e058fe97d3380c2753a7e11a220e8f33ff) | `5e2b23e0`，分支 `asteroids` | 缓冲池及导入缓存维护的实现与限制 |
| [ShueiTsuki/data-a-live](https://github.com/ShueiTsuki/data-a-live/tree/1c0182a271caf1aa47b17083d10a2ef59f2d8c24) | `1c0182a2` | 小米 17 Pro；同一 iPhone X 20H392；Metal 接口清单、Turnip BO 生命周期、音频 |
| [markakash/UniXNU-ishtar-old](https://github.com/markakash/UniXNU-ishtar-old/tree/79ddf4578db06c3738dd5b56a49434270ee260b1) | `79ddf457` | 小米 13 Ultra 的降频、串口空转、ADSP 电池和显示；iOS 18 |
| [tycykp/UniXNU-OnePlus-Ace5](https://github.com/tycykp/UniXNU-OnePlus-Ace5/tree/aaa100d19f6fb14e5897a7e496edf7838d4d4e9f) | `aaa100d1`，已归档 | 同 SM8650 的板级输入、音频/Wi-Fi 依赖；GPU 尚无执行/Metal 实测 |
| [steelbrain/metal2vulkan](https://github.com/steelbrain/metal2vulkan/tree/219f01365dc4c8eb346816c405b5b17403793764) | `219f0136`，默认分支 `master` | 最新稳定翻译层差异；本机当前基线仍是带适配补丁的 `0dfdbcd5` |

`markakash/UniXNU-ishtar` 旧地址当前返回 404。目录另外收录的
`peter8889/UniXNU-ishtar` 是另一份实现，不能把它与上面的 iOS 18 端口混为一谈。
同样，`NativeAdreno`、`NativeMetal` 等旧名称仍可能出现在社区 fork 和运行时符号中。

## CPU、GPU 和运行速度

### 本机已有证据

- r218 所有者确认能进入桌面并完成设置/最近任务滑动。
- r218 记录了 16 条 CPU DVFS 域状态，以及 GPU 在 231/500 MHz 请求档之间的
  50 次变化，HFI 失败计数为 0；这些不是独立的核心频率测量。
- r217 的 Submit ABI 方法 5：2570 次，合计 19,867,626 us，均值约 7.7 ms。
  commit 到回调的均值约 27.4 ms，不能当成 GPU 执行时间。
- r218 的 1517 次解除映射在 transaction 阶段合计约 5.48 s。
  这给出了内存管理优化方向，但不是一次帧耗时的完整归因。
- 当前分配器的 `reservePool()` 返回 Unsupported，`allocate()` 忽略 pooled 参数；
  提交仍调用 `invalidateTlb()`，且缓存属性检查和发布遍历整个映射槽数组。

### 能直接指导后续修改的外部结果

1. **缓冲池和映射数量。** asteroids T65 恢复连续分块池，因为 T64c 的系统分配
   累积约 22.9 万个物理 span，映射/解除映射搬动排序数组的累计耗时显著上升。
   它还记录过合成器均值从池版本的 33 ms 恶化到 139 ms。应优先核对本机 span
   数和分配/释放耗时，再移植池分配；保留本机 CPU 页粒度、独占后备页、失败隔离
   和每个 BO 的生命周期，不能直接复制其物理地址或 1536 MiB 配置。
2. **避免无必要的 TLB 清空。** Adreno740 `5c8c1453` 删除正常提交的全局失效；
   前提是 map 只填无效叶子、unmap 已失效对应页、上层表不变。提交卡住的恢复路径
   仍失效。必须先核对本机 ArmSmmu4K 的这些不变量，不能只删一行调用。
3. **缓存维护需要按所有权优化。** asteroids T63 记录只读导入清理约 89 GiB，
   约占一次 4.4 ms 提交中的 3 ms。其 import-skip 开关也明确承认：CPU 在 map
   后继续修改的 surface 可能让 GPU 读到旧数据。因此本机不直接开启该开关或假定
   A750 与 CPU 全缓存一致；先按 owned/imported、CPU/GPU 写入方统计字节和耗时。
4. **事件驱动 fence。** sheng 的等待线程睡眠至 fence 中断或最多 1 ms，避免轮询
   占用 CPU；这与 GPU 高频是不同问题。应核对本机等待路径的睡眠、唤醒和门控锁。
5. **保持扫描输出引用。** asteroids 的直接显示曾在完成通知后过早释放仍在扫描的
   surface，出现半帧；等待 GPU fence 本身没有消除。它随后保留显示帧至下一次锁存。
   本机仍是独立缓冲加 CPU 复制，不直接套用其双管线 DPU 寄存器设置。
6. **先查真实 BO 生命周期。** pandora 最新交接记录指出 Turnip 的
   `darwin_bo_finish` 在归还槽并解锁后才清零 struct，会清掉另一个线程复用的 BO。
   参考脚本把清零移入 retire 锁内。需要对照本机实际编译的 Turnip 源码确认是否存在
   同一先后关系；没有确认前，不将它认定为本机紫色或乱码的原因。

### 已经存在的修复不重复做

本机 `0dfdbcd5` 翻译层已经包含取消旧颜色输出舍入的上游变化；不能再把
asteroids T61 的旧版本舍入热点当作尚未应用的修复。r217 的新 pf553 混合分支
计数为 0，两平面路径计数为 10，用户画面未改善，因此不能继续把同一补丁称为有效。

120 Hz 要分别验证面板时序、实际呈现完成间隔、合成器产帧；当前软件 120 Hz 通知
及属性许可没有证明桌面达到 120 FPS。本机约 1.4 ms 的复制均值也不代表完整帧耗时。

## 自动调频、发热与充电

sheng 的 CPU governor 每 16 ms 根据每域最忙 CPU 的空闲时间选档，四个低负载窗口
后降频；触摸保持 P 域高档，持续出帧提供短时频率下限。GPU 使用 XO busy 计数及 HFI
频率/带宽投票。小米 14 有四个性能域，已实现的版本不能换成其三域 CPU 编号或 OPP。

ishtar 的低负载计数被无条件清零，曾导致不能降频；修复和仅输出串口模式都已有作者
实测。该记录仍未给出长期温度/功耗或完整热保护验证。本机已保留对应串口空转修正，
继续核对负载来源、硬件限频和温度反馈，不能靠常驻高频掩盖调度/提交问题。

充电参考 sheng 的 `ShengBattmgr.c`、`ShengBattery.cpp` 和 ishtar 的 ADSP 接管：
先建立 PMIC GLINK 请求/响应，再发布 IOPMPowerSource。保存的 houji FDT 确认
`qcom,pmic_glink/qcom,battery_charger` 和 UCSI GLINK 节点，但尚不等于 iOS 已能充电。
sheng 的固件自动处理 PD/PPS，且其属性编号有板级偏移、认证和电流限制；不能把电池
图标出现等同于实际充电，也不能复制其电流设置。小米 14 要分别实测插拔、协议响应、
电压/电流方向、温度和净电量变化。

## 声音和亮度

| 功能 | 可复用接口 | 小米 14 还需要的板级工作 |
| --- | --- | --- |
| 扬声器 | sheng 的 ADSP/GLINK/GPR/AudioReach；pandora 的 iOS 16 IOAudio2 接口和音频生命周期 | FDT 中启用的两颗 **CS35L41**，地址 0x40/0x42；与参考的 CS35L43 不同。需本机功放固件、路由/ACDB、时钟、GPIO、增益和校准 |
| 音频时基 | sheng 修正 CoreAudio 24 MHz 假设，对接 19.2 MHz 计时 | 匹配本机系统 ABI 和采样时钟；先验证有界 PCM、缓冲完成，再接系统应用 |
| 亮度 | asteroids 的 `AsteroidsBacklight.cpp`：CoreBrightness 服务接 DSI DCS；sheng 的 OS 属性接口 | 本机 bootargs 选择 `mdss_dsi_n3_42_0d_0a_dsc_cmd`，DCS 背光、上限 4095、下限 25、HS 命令、inverted DBV 标记。需确认字节序、反向编码、HBM/熄屏状态；不使用平板 KTZ8866 I2C 参数 |

亮度首先验证最低/中间/最高的可见效果和回读；音频首先验证已知 PCM。UI 滑块存在、
服务注册成功、主机测试通过均不能代替输出验证。

## Safari、照片与 Metal 客户端

- pandora 对照真实 A11 驱动、iOS Metal 头文件、dyld selector 引用，生成接口缺失清单。
  它的交接明确承认部分壁纸/组件仍有问题，不能把“约 110 帧”推广为所有功能完成。
- 本机 v16 源码中的 22 个 NB 对象声明没有公开协议声明；只有 device 在运行时添加
  MTLDevice。静态清单已保存；这提示检查 Swift/框架的协议查询，但尚未证明是照片
  黑屏的根因，也不应仅声明协议就假装缺失方法已经实现。
- 上游有 Safari 的 Cryptex/ExtensionKit 路径修复，但它针对 iPadOS 路径。
  本地 **r213 只读检查副本**中的 iOS 16 使用 WebKit.framework/XPCServices，
  三个 WebKit 进程及 SafariShared 资源可见；不能直接套用 iPadOS 的 ExtensionKit 路径。
- 接下来的应用验证要分别记录 MobileSafari、WebContent、Networking、GPU 进程是否
  启动、退出原因、缺失文件和第一条 Metal 错误。先用本地 HTML 验证页面绘制/输入，
  再测 HTTPS、DNS 和 Wi-Fi，避免把未联网与渲染失败混在一起。

## 按新版 migration 教程整理本项目

[迁移教程](https://unixnu.com/porting/migration)规定 format 2 的 ARM64 → SoC → OS →
board 分层，以及完整数组覆盖、按依赖的归档顺序和每个设备独立输出目录。
当前主仓库为 `79d81c10`，houji board 未声明 schema（format 1），当前 CLI 不接受
`status --json`；兼容的只读 `status -D` 输出已保存。houji 仓库尚无初始 commit，
已有源码和测试快照需要先完整盘点，不能以拉取/重置方式覆盖。

迁移时保留 20H392/Darwin 22 的 ABI、本机四域拓扑、触控、157 应用统一键盘、原生
1200×2670 输出、现有分区及日志恢复。先固定有效源码、补丁与产物之间的对应，再分离
SM8650 公共资源和板级策略。官方目录仍将 Adreno740 的验证范围写为 A740/SM8550；
不能通过改组件名把它视作已验证的 A750 支持，也不改用示例 iPadOS 镜像。

## 当前执行顺序与日志限制

优先级保持 GPU/CPU 卡顿与颜色正确性；其次亮度和电池/充电，再做声音与应用兼容。
同一轮可同时采集 CPU 提交分项、GPU 时间戳、map/unmap、fence、帧间隔、调频及
应用第一错误；硬件策略按可归因的步骤修改，避免将全部新驱动同时打开。

r218 的自动回收日志 CRC 和身份有效，但只有运行中快照，退出阶段新计时未落盘。
另外 v15 的 transfer getter 会触发 `deferred.lower_all()`，并非只读；v16 已删除它，
保留同一翻译运行时及缓存命名空间，400 个非可选 iOS 16 导入检查通过。
v16 已完成双文件安装、256 块回读和保护分区核对，尚待真机验证。r219 提前返回，最后快照约在 42 秒的 GPU/UFS 预检；
未据此得出渲染性能结论，保护分区、12 段 GPT 和 misc 保留区检查通过。

下一轮应把 RAM 计数直接写入每次已验证的日志快照，而不是只在退出时打印。
硬件 GPU 时间戳不可用时明确标记不可用，不用 CPU 回调耗时替代。

## r220：匹配本机的完整 GPU 档位候选

在 OrangeFox 只读读取 qfprom nvmem 的 GPU 分档字节（0x9b，位 4..6）得到 bin 5；
SoC feature 为 AB。Qualcomm `adreno.c` 的选择逻辑配合 SOCINFO_FC_AB=2，
使用 `gpu-pwrlevels-3` 的通配 SKU 记录。单独的 pcode 不参与外部 AB 特性的选择。
证据位于 `out/upstream-comparison-20261030/houji-gpu-sku-readonly.json`。

此表的 12 档为 231、310、366、422、500、578、629、680、720、770、834、903 MHz。
候选用本机 AOP 的 ARC/MX 表生成每档电压票，并使用同档 DTS 带宽索引。
HFI 在 START 前声明全部档位，初始 500 MHz 变为表中索引 5，运行时请求同一索引的
频率与带宽，不直接写 PLL/稳压器寄存器。

策略以 16 ms 工作线程采样的 XO busy 占比为输入，使用平滑负载和约 55% 目标占用，
高负载快速升档，四个低负载窗口后降档；触摸提供短时 680 MHz 下限，空闲恢复提供
578 MHz 下限，持续队列保留 500 MHz 下限。最大请求限制为该表的 903 MHz。
这些是明确的板级策略，未宣称等同 Android 的完整 governor；帧截止时间与温度反馈
仍需要各自的测量和硬件驱动。CPU 的四域多档策略本轮不变。

主机检查通过了 12 个上限下的持续负载/空闲收敛、boost/上限优先级、无效输入，
以及 HFI 编码、初始投票、未改变的 CX/GMU 条目和填充。编译与硬件验证分开记录；
完整 OPP 表在小米 14 上的 ACK、各档驻留和桌面改善尚待 r220 实测。

### r220 实机结果

用户确认能进入，但仅解锁时短暂更顺，随后仍卡顿，并新增粉块；紫色和字体异常仍在。
CRC 有效快照保留到约 189 秒，包含正常隔离 GPU 和重启请求；Mac 后续才重新发现 USB。
2117 个成功命令的 GPU 时间戳区间均值为 13,924 us，commit 到完成回调均值 29,788 us。
提交内部分项为 3421 次/14.27 s，其中 publish 9.93 s、WC 重申 0.87 s。
315 次纹理创建和 210 次命令缓冲报 OutOfMemory(Device)，另有 DRM plane layout 错误。
这不是物理 RAM 不足的证明，亦未证明提高频率引起新伪影。

本机编译用的 Turnip 确认存在 pandora 的同一 BO 回收竞争顺序。已应用该精确修正并
增量重编译；用原函数强制重现复用窗口时失败，修正后的原函数保留新对象。
新库 iOS 16 导入检查通过；下一轮控制请求上限至 500 MHz，保留 12 档声明及范围内
的多档选频，单独验证回收修正，并将每档驻留和全部错误行纳入快照前缀。
