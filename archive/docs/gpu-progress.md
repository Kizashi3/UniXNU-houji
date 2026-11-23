# GPU 当前状态与迁移边界

2026-10-27；以原始实机结果为准，离线候选不记为设备里程碑。

| 环境 | 已证实结果 | 原始记录 |
| --- | --- | --- |
| UEFI r131 | CP_INIT、实际命令环和两次独立 GPU 写回 | `native-ios-r131-result.json` |
| UEFI r135 | 首次上下文初始化、32×32 CP_BLIT、1024个红像素、CRC E843B26A | `native-ios-r135-result.json` |
| XNU r150 | NormalNC 独占缓冲区中的有限 GMU 执行及写回 | `native-ios-r150-result.json` |
| XNU r156 | 签名PAS13、MODE0、首次25DW上下文、32×32 CP_BLIT、1024红像素/CRC E843B26A、8标记和2次写回全部通过；终态自动落盘 | `native-ios-r156-result.json` |
| XNU r155 | CP_INIT、3次提交、2次独立GPU写回；终态日志自动落盘 | `native-ios-r155-result.json` |
| XNU r154 | bank0/SID0+1、GX、SQE/AQE代码绑定、全部102项Gen7配置 | `native-ios-r154-result.json` |
| XNU r151～r153 | secure-CX、原厂 GMU/HFI、普通主机配置五条消息全部应答 | `native-ios-r151-result.json` 至 `native-ios-r153-result.json` |

这些原始结果均在 `${HOUJI_ARTIFACTS}/native-port/evidence/`。
UEFI 的实机成功继续有效；XNU 已完成 CP/ring、签名固件/模式退出/首次上下文、实际2D图形像素和两次独立GPU写回；桌面加速尚未完成。
r153 的 `qualified=1` 仅证明固定五消息兼容；没有证明 GPU 最终工作模式或图形执行。

迁移需要替换的边界是 UEFI identity/4K/低地址分配与 XNU descriptor VA/16K/高物理地址、缓存及资源生命周期。
这不要求重新发现已经成功的 PM4、首次上下文和 CP_BLIT 序列。后续使用 r135 的完整图及原命令顺序。
已通过的固件通信作为整体启动前置；只有修改相应实现或出现回归时才另做针对性复验，不再为每个已通过前置单独安排手机重启。

下一条设备验收链为：完整内存图 → bank0/SID0+1 → GX/代码与原始配置 → CP_INIT → 原签名 ZAP 协议 → 模式/上下文 → 实际像素写回。
随后才接提交、同步、显示发布与 AdrenoMetal。软件准备、固件 ACK 和真实图形输出分别记录。

## 已合并的离线候选

`native/gpu/xnu/full-host-graph/` 直接使用原 HFM1 和 scratch/code helpers，为整条链准备15个BO。
GMU图11范围/1675叶/9个使用表页；GPU图12范围/1567叶/7表页。
`HoujiFullHostNativeMemory` 使用真实 Native Memory/Cpu，核对完整owned CPU页、descriptor物理段、全PAR、只做AT观察的别名以及跨owner交集。
准备过程无设备引用、MMIO、SMC或设备执行；后续运行仍需取得独立的设备所有权。

r154 已加入 actual XNU 编译并完成实机整条前置验证；102/102 Gen7、75项电源记录均通过。
CP、ZAP、2D和桌面加速仍未完成。测试入口为 `tests/full-host-graph/run_core_tests.py` 和 `run_native_graph_tests.py`。
旧 HHI/HSN 的类型和封存对象保持原样；后续执行器须直接使用新模块私有的真实结果，不能用诊断快照拼装执行对象。

签名固件低地址metadata与原厂保留区的迁移方案见 `gpu-zap-native-handoff.md`。
它要求专用16K低地址交接；GPU目标所在16K页的前8K属于IPA，不能整页读写或清零。

## r154 日志边界与后续

r154自动返回OrangeFox并抓到CRC及run ID绑定的checkpoint1；执行后末尾尚未落盘，成功证据来自IMG_0784。
r155合并CP_INIT和两次独立CP_MEM_WRITE；只有真实CM3 reset1与GX/client/arb三步halt ACK并持续保持时才允许保存最终结果。任何未知状态继续保留全部BO、引用与映射，不写日志分区。
本地主机peer仅检查边界和失败判定，不是A750仿真，也不构成设备执行证据。

## r155 实机与自动日志通过

实际CP_INIT idle1、3次提交、RPTR/WPTR=20/20、两次GPU写回C0FFEE00/C0FFEE01。CM3 reset1、GX/client/arb ACK1/3/3后保留全部资源，最终日志成功提交/flush/回读。自动恢复59.207秒、捕获59.869秒；run ID B400987DEF334248BEA98D72E0A16FD1，正文CRC56DC9D88。IMG_0788与落盘结果一致。照片另外显示commit成功回执及save返回，这两行发生在正文快照之后，不会出现在同一份正文中。

下一步复用r135原签名PAS13、模式退出、25DW首次上下文、32×32已知图像命令；不重新单独测试已通过前置。

## r156 实机：完整签名2D链与自动末尾日志通过

新低地址交接实测metadata D2770000，raw D276F000/28672全部保留；XNU创建两个CPU16K NormalNC映射，目标页前8K为IPA且无数据访问。签名PAS13 INIT_IMAGE真实中断两次后成功resume，MEM_SETUP和AUTH_RESET均a0/a1=0/0。仅复制原1072字节签名段，目标权限关闭后不再AT或读取目标。

MODE0 RPTR12、25DW上下文RPTR37、CP_BLIT RPTR41均idle；七页完整校验、1024红像素、CRC E843B26A、8标记FF。后续两次GPU写回C0FFEE00/C0FFEE01，最终六次提交RPTR/WPTR51/51。实际CM3 reset与GX/client/arb ACK1/3/3后保存终态，59.030秒自动恢复、59.751秒完成抓取；本轮成功全部由current-trial/CRC绑定自动日志证明。BOOT5/GPT12/misc保留区未变。

剩余实际集成是持久Native设备owner、动态VM与提交/fence、IOKit用户客户端、AdrenoMetal和显示呈现。当前独立源码内核仍没有原始IOGPUFamily，不能把旧原始cache的类地址作为当前内核import，也不能把固定2D成功称为完整Metal/shader/桌面加速。保留原user ABI v1和已编译前端，下一步先接真实运行期provider与query/BO/submit/wait，避免反复重编插件。


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


## r168：用户态 ABI、实际计算/渲染/导入写回通过，IOSurface 待验证

内核与 UEFI prebuild 均成功，实际 UEFI 的 27 个静态启动参数和动态触控参数共占 502/608 字符。当前 kernel SHA256 为 `22d143a09b78993f9130fc322edc42f46d7903bf9eccab23b019b046efccad3b`。构建结果与用户态执行结果分别记录。

新模式保留 r166/r167 已验证的 GPU owner/VM/ring 后继续启动 BSD 用户态，使用现有 ABI v1 AdrenoMetal/Turnip 构建，一轮执行 shader 计算、渲染、导入和真实 IOSurface 写回。用户态各客户端使用与 12 个静态启动映射不重叠的 VA 区间。额外的整图 CRC 按真实 VM generation 更新；核心 PTE 更新审计保持原样。

测试进程只加入 probe allowlist，桌面仍走原路径。监控线程读取两条固定、普通、root 所有的日志路径，遇到完成/失败或 240 秒期限后，先经过共享 IOKit gate 和真实 GPU reset/halt，再归档 JSON/stderr。末尾同时保存最后的 IOKit 调用、返回码、inflight、进程和 marker。只有 GPU/UFS 同 owner 共存资格已建立时才开放运行期文件 I/O。

当前手机完整 12 GiB root 已保存为 `phone-before-adrenometal-r168/ios16-phone.hfsx`，SHA256 `80ca8b77a71de1343f2e6ba1aee2ab93d5b7901309f6689e1c1df4498b174930`，96 个 chunk 与手机只读比对一致。候选镜像的 15 个新增路径已完成数字所有权、权限、哈希、签名和 owners-on 只读重新挂载验证。所有权脚本仅操作本地镜像，重新以 owners-on 只读挂载验证数字 UID/GID、权限、文件哈希和签名后卸载。delta 仅更改 0/1/95 三个 chunk，安装前后全部 96 个 chunk 已直接读回一致，BOOT5/GPT12/misc 未变。安装后整卷 SHA256 为 `eae5d03d0f74ae4aee0376e4be80cb70cbb55ee11c1809bd300425435a4046d0`。payload 和启动工具同时核对安装报告；2139 个冻结源文件已逐一验 hash，真机 `fastboot boot` 返回 OKAY，自动 watcher 正在监听。实际用户态日志已从本轮只读 root 快照中取得：`_MTLDevice` 528 字节，插件/Turnip 加载及真实 Mach ABI 查询成功，compute_bad_of_1000=0、render_bad_of_64=0、import_bad_of_4096=0、seen_steps=63、return_code=0。日志最后停在 bridge-results，下一条调用是插件的 initWithAcceleratorPort，尚无 IOSurface 或桌面加速成功结论。内核最后保存的检查点到 51.57 秒，末尾未归档；恢复检测在约 205 秒完成。BOOT5/GPT12/misc 保留区未变，root 快照 SHA256 为 `c53f9ab501e94897aca7da1aed85549b4596d71d8b787f20bb955b46905e7368`。


## r169：终态日志通过，运行窗口在插件加载前结束

仅重编小型测试程序，AdrenoMetal、Turnip、Rust 翻译器库保持 r168 原字节。跳过已通过的原始 shader 自测，直接使用已知 cache 路径创建真实 Objective-C Metal device 并校验 4096 个 IOSurface 像素，再逐项记录 CFPreferences、用户 cache/temp 目录和实际插件初始化。每条记录先走现有 0x4147xxxx 无连接进度通道，终态 66fe/66ff 由当前 adrenometalprobe 进程写入本轮 RAM 状态，不改 wire ABI。

GPU owner 线程在已实测的同 owner GPU/UFS 共存窗口内、无 GPU gate 时保存进度，再 try-lock 轮询 provider。gate 超过 10 秒未释放则保持全部资源并通过原 PSCI panic 返回；另有独立 150 秒无文件系统保护线程。终态在任何诊断 vnode lookup 前先经过真实 GPU stop/isolation 并提交内核日志。已核对实际链接的 try-lock、marker acquire/release、保护线程无 MMIO/FS、终态先保存后 vnode 读取（读取 helper 已内联）。

修改四个原有 root 文件，采用原 inode 内写入，未新增路径或再次更改所有权；新程序/launch job 等可访问路径以 owners-on 只读重新挂载核对数字 UID/GID、权限和内容，两条清空日志保留原 inode/所有权。只更改 0/1/95 三个 chunk，全 96 chunk 读回一致，BOOT5/GPT12/misc 未变。新 root SHA256 `f9139a6c74db8ae2bd75c9dcc2c09820b0b13145331349cd93a59c659007b9b6`，kernel `dd7401df0c706b4311c3ea1ecb7154963d5b9540a874275efbc6bc9e2f85bd73`。2186 个冻结文件核对一致，真机 fastboot boot 已返回 OKAY，自动 watcher 已于约 181 秒取得完整终态。实际打开 GPU 客户端为 0，GPU fence 仍为引导自测的 84；probe 在 uptime 148.963 秒才记录 objc-abi，worker 在 uptime 170 秒的 120 秒期限结束，尚无 plugin-load 结果。因此本轮不是 GPU 执行失败，未产生新的 IOSurface 成功/失败证据。终态记录、真实 reset/ACK、两条 vnode 读取及校验保存均通过。


## r170：减少诊断 I/O、复用 r169 用户态，真机运行中

未安装新系统卷或重编任何用户态组件。空闲 try-poll 只在持有原 GPU gate、真实 submit.outstanding()==0 时跳过定时器的额外审计；所有实际 externalMethod/import/close/stop 保留原严格检查。检查点改为 marker/inflight/selector 变化时才保存，不再每秒写同一进度。现有探针在截断自己的 stdout 后、通过当前进程的 6601..66ff marker 设置本轮 started；只有此后才可解析其 watchdog 文件，避免旧启动记录触发误判。

worker 上限 300 秒、独立无 FS 保护上限 360 秒，完成/失败立即停止。启动参数仍为 502/608 字符。新内核及对应源码层的编译/链接检查已通过，真机 fastboot boot 返回 OKAY，后台监听已启动。硬件核心、AdrenoMetal/Turnip/translator 与已安装 r169 probe 不变；IOSurface 和桌面加速仍待实测结果。
