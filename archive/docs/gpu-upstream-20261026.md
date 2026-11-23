# houji 最新 GPU 上游只读核对

核对时间：2026-10-26 13:20 UTC / 21:20 Asia/Shanghai。
范围：GitHub connector 的 public organization repository list、commit/compare/file GET，以及 unixnu.com 官方文档；没有 fetch/pull/reset、源码/依赖/分支修改或设备操作。此文件是研究笔记，不是硬件验收。

## 结论

存在新的主机环、故障快照、SMMU 性能、Metal 稳定性实现；不存在可据此确认的 A750/SM8650 原生 iOS16 桌面支持声明。Adreno740 当前 README 仍限定 A740 / SM8550，验证设备为 sheng。
当前正在验收的 houji 外部 4K 高 PA 写回/故障链路无需为了这批上游更新而改动。尤其新上游放宽诊断/全表验证频率，是性能路线，不能替代本机严格故障与隔离证据。

## 实际仓库、改名和 HEAD

GitHub 组织搜索返回 29 个公开仓库。GPU 相关实际仓库为 Adreno740、AdrenoMetal、AdrenoFirmware、AdrenoPM4、ArmSmmu4K、GopFramebuffer；集成在 UniXNU、UniXNU-sheng、UniXNU-sm8550-common。未见组织内名为 Adreno750、SM8650 common 或独立 XNU source 的仓库；内核补丁、构建及 OS profile 在 UniXNU / 板仓。

旧仓库 URL 经 connector get_repo 返回同一 repository ID 的新名称：
- NativeAdreno → Adreno740，ID 1426848889。
- NativeMetal → AdrenoMetal，ID 1426849428。
- NativeMobileDisplay → GopFramebuffer，ID 1426849559。
源码文件、运行时服务及 bundle 名仍保留 NativeAdreno / NativeAdrenoMetal，不能随仓库重命名一起改 ABI 标识。

| repo | 本地当前研究/候选 pin | 远端默认 HEAD | HEAD committer UTC | 实际增量 |
|---|---|---|---|---|
| UniXNU/Adreno740 | 研究 4e0314df8ad29d52f6fa3f9383a540adcd618b87；候选 b686b9054f57d393c80195b82568a09f8ca106a2 | 5c8c1453c67d6ef6b10ec43ab1f8fc570a2f33e1 | 2026-10-25 22:35:25 | 研究 pin 后 14 提交；b686→4e 另外 2 提交仅文档/路径注释 |
| UniXNU/AdrenoMetal | 454ff2ce83766ce7b3e0f355e83f1d72907708b3 | ce5e19e33e05e1873d38d818e23cabfe0ac708c3 | 2026-10-25 22:35:51 | 22 提交 |
| UniXNU/ArmSmmu4K | vendor 8bb168ad058c28d5c04f179ba407875eacba7ef3 | 3ba92451bd44bb742d11758fbfcd3a446ecad685 | 2026-10-25 22:34:41 | 2 提交 |
| UniXNU/GopFramebuffer | 8666a9950c9699b368931d18cac92c0fdb2ce9c0 | 33e941a878dcf01b98dbd9160d798bd56e7551ea | 2026-10-25 22:37:09 | 1 文档、1 实现提交 |
| UniXNU/AdrenoFirmware | vendor 20ad3d7aca14bd46aecab6335c780f5413fa054b | 同左 | 2026-10-24 18:03:54 | 无新改动 |
| UniXNU/AdrenoPM4 | 研究 282606b528b2595bc4274ea7490b62b323f35a5f；候选445f8fe6d115738352b9d78dc70af6d61aa7f62f | 282606b528b2595bc4274ea7490b62b323f35a5f | 2026-10-24 18:03:54 | 研究 pin 后无新改动 |
| UniXNU/UniXNU | 原 checkout HEAD 79d81c10220caebb15da5737a4eb6c20724cc731；研究文档 base bd127c008cdc584b83cf00eaea269e4f1adf3cc8 | ae687009348296e97e49ce6e925795044f363ce6 | 2026-10-26 04:13:43 | 研究 base 后 64 提交；原 checkout 后 271 |
| UniXNU/UniXNU-sheng | 251b291adf941b9953fe3ae66a808b9b626e164d | 08cde20edc3254ed6f7df8d0f5384fb887786e8f | 2026-10-25 23:34:42 | 121 提交，涵盖多个外设 |
| UniXNU/UniXNU-sm8550-common | 文档记录23b2049fcd9e30356161def84231334fb55ecca9 | 同左 | 2026-10-24 18:03:13 | 无新GPU改动 |
| UniXNU/ArmCpu | 1951cc8444b340d7d8879e9418220cf29eb711d7 | 9066b53bbc82e92a98ec44a11dd50fd13eaf1a1b | 2026-10-24 18:03:51 | 仅 README/AGENTS 文档 |
| UniXNU/DarwinBoot | 此轮仅查HEAD | 3325e352d7df68a9f9ad74832ed94a6acbbd7390 | 2026-10-24 19:01:58 | 最新为文档说明 |
| UniXNU/XnuPrelink | 此轮仅查HEAD | f876e3ee62e18fc06653dd75ed7dafcfb3950ac0 | 2026-10-24 18:03:55 | 最新为文档说明 |

比较 primary URL：
- https://github.com/UniXNU/Adreno740/compare/4e0314df8ad29d52f6fa3f9383a540adcd618b87...5c8c1453c67d6ef6b10ec43ab1f8fc570a2f33e1
- https://github.com/UniXNU/AdrenoMetal/compare/454ff2ce83766ce7b3e0f355e83f1d72907708b3...ce5e19e33e05e1873d38d818e23cabfe0ac708c3
- https://github.com/UniXNU/ArmSmmu4K/compare/8bb168ad058c28d5c04f179ba407875eacba7ef3...3ba92451bd44bb742d11758fbfcd3a446ecad685
- https://github.com/UniXNU/GopFramebuffer/compare/8666a9950c9699b368931d18cac92c0fdb2ce9c0...33e941a878dcf01b98dbd9160d798bd56e7551ea

## 需要优先知道的 ABI 变化

[Adreno740 c232716c](https://github.com/UniXNU/Adreno740/commit/c232716ce093df4b73c9fca0e608d6fd430f5390)，committer 2026-10-25 22:35:25 UTC：
- NativeAdrenoABI.h：AbiVersion 1→2，MaxBuffers 16→128，Submit struct 416→3104 bytes。
- NativeAdrenoSubmit.{h,cpp}、NativeAdrenoUserClient.{h,cpp}：128 IB 的 scratch 数组改保存在对象中，避免内核栈增长。
- 每帧一次prologue替代每16个IB一轮；不是 A750 新初始化序列。
- houji 候选的 kernel/Turnip/Metal transport 必须同步核对版本和请求大小，不能只升级一端。现有候选 b686 的 ABI v1 不兼容新 v2 请求布局。

## 主机命令环与故障快照的实质增量

这些14个 Adreno740 新提交的 committer 日期均为2026-10-25 22:35:25 UTC（北京时间10月26日06:35）。

1. [ae93296c](https://github.com/UniXNU/Adreno740/commit/ae93296cc910c45943d29a597e2db15da4c56d8e)、[98af6bf4](https://github.com/UniXNU/Adreno740/commit/98af6bf49b9c86ea7c808642628b71cea6246217)、[9c38750f](https://github.com/UniXNU/Adreno740/commit/9c38750febce24fb9ea7f1977a7dbd4dd589af65)、[43c9b25f](https://github.com/UniXNU/Adreno740/commit/43c9b25f01475493f815df442e398634bb012fc2)、[ea460275](https://github.com/UniXNU/Adreno740/commit/ea460275770b3046842de29319ca2b62ec8ced8a)：
   NativeAdrenoRing::stallState/ibBefore、NativeAdrenoSubmit::noteStall/peekIb/peekFetch、NativeAdrenoVm::faultState/peekWordsUncached/handleAt。
   故障快照包括RBBM/CP/RPTR/WPTR、BR/BV IB、FSR/FAR/FSYNR0、故障附近16 dword、job时的next-map-handle与当下IB映射handle，辅助判断内存在GPU尚用时被重用。
   可参考诊断的时间点与数据结构；A740寄存器和BR/BV含义必须重新比A750；不替代 GMU SID5/bank2 与普通GPU SID0/1 的分离证据。

2. [c285ae85](https://github.com/UniXNU/Adreno740/commit/c285ae85f2ab6e065350fa20e28ed8763b4ba6e1)：
   NativeAdrenoRing::useContext(context)在提交client改变时设置reset_pending_，下次framed prologue重置BR/BV counters/timestamps。
   面向多client共享ring的context隔离/死等问题；本机单有界canary尚不能证明这条多client路径。

3. [5313bd7f](https://github.com/UniXNU/Adreno740/commit/5313bd7fdf66d8a4c035e8295e76bd2e41b27085)：
   NativeAdrenoService.cpp把gpu_window从start()栈变量改为service的ring_window_成员，修复ring长期持有悬空cookie；
   NativeAdrenoRing::writeWptr先写WPTR并检查GMU AHB fence status，重复最多200次。
   gmu_fence_status使用A740 GMU 0x23b13/0x23b14及0x6a000窗口差值，不能直接套本机。

4. [8ad15b60](https://github.com/UniXNU/Adreno740/commit/8ad15b606eb4001becbc63f61ea8e48d5754c6fe) 后由
   [f53000ca](https://github.com/UniXNU/Adreno740/commit/f53000cacdaf2fdad470846bf6040a366e79eb0a)纠正：
   NativeAdrenoSubmit::noteStall使用clock真实经过时间；50ms无推进才invalidateTlb+kick，200ms才drainBus；CP快照50ms及1s。
   NativeAdrenoRing::drainBus halt GBIF client、AXI，再release，并导出ACK。不是“超时即可free”；
   本机故意负向故障实验须保留原验收顺序，不能将此恢复动作加入故障证据前。

5. [25abaa4b](https://github.com/UniXNU/Adreno740/commit/25abaa4b15e5da2b9966152899cf99389c63008d)：
   NativeAdrenoHandleIndex、UserClient/find、Publish/viewSlot：对象4096→16384，handle索引、free hint、CPU-view token直接定位。
   作者报告sheng i568峰值5725无respring；这是sheng记录，不是本机结果。

## SMMU、缓存和写回适用性

[0d680d62](https://github.com/UniXNU/ArmSmmu4K/commit/0d680d621da8cd57fb4dba4a9bb97ee779a95f4d)，2026-10-25 22:34:32 UTC：
- ArmSmmu4KLiveMapContextBatchExclusive信任caller独占物理页，跳过对已映射区间的cache-attribute alias pass；变化内部仍互查。
- 同一diff把whole_verification从每64次变为仅generation==0；之后只验证变化的叶子并信任既有区间。context/fault MMIO观察也移至首次whole update，caller自定route观察。
- 这是性能与证明责任转移，不应直接覆盖本机full8/context/fault/frame严格校验。

[3ba92451](https://github.com/UniXNU/ArmSmmu4K/commit/3ba92451bd44bb742d11758fbfcd3a446ecad685)，2026-10-25 22:34:41 UTC：
- ArmSmmu4KSyncContextTlbPages：每4K leaf一次64-bit TLBIVAL@CB+0x620，VA[55:12]放[43:0]、ASID放[63:48]；一次TLBSYNC@0x7f0+bounded poll@0x7f4。
- ≤512页unmap使用逐页失效，更大用ASID失效；声明host tests通过，尚未实机测。
- 仍是GPU4K granule，不能证明XNU CPU16K bookkeeping适配。

[1c4065cf](https://github.com/UniXNU/Adreno740/commit/1c4065cfb1f3e05e4bff30fbfabc6c291f472c28)：
- NativeAdrenoVm::rangeAt/exclusivePages/preflight/map/unmap：排序区间二分搜索，区分自有BO与import；
- import仅在缓存class统一且不与pool/owned spans重叠时走exclusive，否则全检查；新计时[vm kinds]。
- sheng i570 owned map 0.66→0.20ms；import fast path尚未实机测。

[5c8c1453](https://github.com/UniXNU/Adreno740/commit/5c8c1453c67d6ef6b10ec43ab1f8fc570a2f33e1)：
- NativeAdrenoSubmit::submit移除每次submit的TLBIALL；仍publishMapped；stall仍invalidate。
- coherence sample改每64次，IB WC audit仅首16次；作者明确尚未实机测。
- 前提是map只填invalid leaf、unmap同步完成自身失效、上层页表终身不变，不能无条件用于仍在确权/故障验收中的路径。

CPU16K额外注意：新 NativeAdrenoVm::peekWordsUncached 仍按4095/4096对齐后调用 NativeAdrenoMaintainOwnedPages。此轮diff没有改 NativeAdrenoCpu.cpp。不能据此称有上游CPU16K解决方案；升级本地适配时需把此新增路径也纳入geometry/cache契约复核。
新代码并未让GMU高PA写回或CPU invalidate自动获得资格；那仍依赖本机观测。

## AdrenoMetal 桌面相关新实现

22个提交 committer均2026-10-25 22:35:51 UTC；下面只列与移植判定有关系的实质项。

- [ce5e19e3](https://github.com/UniXNU/AdrenoMetal/commit/ce5e19e33e05e1873d38d818e23cabfe0ac708c3)：
  NativeBridgeMetalFrontend.mm NBCommandBuffer::encoder:handle:what:在runtime handle失败时仍返回encoder object并refuse该command buffer，防止RenderBox缓存nil encoder的IMP后PC0；
  NativeAdrenoMetalPlugin.mm clientDevice和native_bridge_metal_problem_hook在故障线程同步报告首个问题。
  作者给sheng i570 WidgetRenderer拒绝但未crash记录。OS行为可参考，未实测iOS16 houji。

- [d67af6a2](https://github.com/UniXNU/AdrenoMetal/commit/d67af6a2b14c744aef0a4ac812acfd749e549244)：
  GpuScanoutPresenter::sourceFor按kernel mapping ID/base/bytes缓存4个surface GPU imports；GpuScanoutClient携带swap.reserved作为mapping ID。
  依赖kernel保证至少6个映射的存活/身份契约；不能只套用户态缓存。

- [ed654b40](https://github.com/UniXNU/AdrenoMetal/commit/ed654b40df5720dbc58bb6bfdb8fbb1cc86ff3b9)及
  [2d35c57f](https://github.com/UniXNU/AdrenoMetal/commit/2d35c57ffb0f97e5db235bad259af003acd439a5)：
  bridge/NativeMetalObjects.rs启用PaddedReadsPolicy::AliasWrites；
  patch0008允许写入padded-row texture直接alias，patch0016的linear_plan::tile_store_fits限制16x4 tile-store向右最多15texels/底部3行的越界，失败则退shadow。
  framebuffer stride/分配范围必须按本机IOSurface验证。

- [01ea5568](https://github.com/UniXNU/AdrenoMetal/commit/01ea556875e09546529a7535eadca8d6f0e53738)：
  bridge/patches/0009..0015记录metal2vulkan保留最终pass、减少draw分配、缓存draw command/list、避免不变重绑、tracker map、two-plane shadow布局。
  本地候选只有0001..0007，升级构建应按完整patch顺序匹配依赖。

- [461a8421](https://github.com/UniXNU/AdrenoMetal/commit/461a8421c60e83178aaaf84da25d7079b5d30ecb)：
  NativeAdrenoMetalPlugin.mm deviceForPort把TU_DEBUG默认设nocb（保留禁并行binning，GMEM/sysmem交给autotune），作者报告sheng i555 600s无stall/70fps p50。
  A750不能直接继承此性能结果；同项目此前强制sysmem已不是当前策略。

- PrimeShaders.h近期增加/修正首次拒绝原因、常量与linked functions、动画中暂停、prime-list存在时不扫目录；
  最新f0c31774避免目录扫描占一核8秒；这是pipeline warm-up/desktop性能参考，不能修内核提交不可用。

## 显示和Turnip/内核集成

[GopFramebuffer 33e941a8](https://github.com/UniXNU/GopFramebuffer/commit/33e941a878dcf01b98dbd9160d798bd56e7551ea)：
NativeLegacyDisplay.cpp startDirect/directSlot/flip/latchTick在sheng-dpu-scanout=2时经native_ufs_dpu_map映射surface并切两个VIG pipe、等CTL flush latch，默认关、失败fallback GPU/CPU copy。
明确DPU9.2@0xae01000、VIG0/1@0x4000/0x6000、bootIOVA0xb8000000、stride0x2fa0；这些是sheng面板/SM8550配置，不能拿来开启houji直扫。

[UniXNU cd1b9757](https://github.com/UniXNU/UniXNU/commit/cd1b9757fd5d730bf85aabb37a4bce729ede9e58)，2026-10-25 16:59:46 UTC：
patches/mesa/turnip-darwin-kmd.patch的dw fence wait从1ms slice变100ms上限或caller deadline；依赖内核wait可随GPU IRQ睡眠/唤醒，不是轮询本机canary的调参依据。

[UniXNU bc08de65](https://github.com/UniXNU/UniXNU/commit/bc08de65119f84fa69929f331ea052a8f5ddff4f)，2026-10-25 22:47:46 UTC：
实际gitlink同步Adreno740 5c8c、AdrenoMetal ce5e、ArmSmmu4K3ba9、GopFramebuffer33e9。
但是ae687009的components.toml仍写旧4e0314df/454ff2ce/8bb168ad/cf3b4297，docs/zh/porting/gpu.md source-map也仍链旧refs；最新目录/文档链接与实际子模块有不一致，应以明确SHA和消费端为准。

[UniXNU 018c8f34](https://github.com/UniXNU/UniXNU/commit/018c8f3439f1093b7ccd9965db0894516aace274)，2026-10-25 17:40:29 UTC：
修fresh clone遗漏TrustCache等XNU公开header的构建问题；不是GPU运行修复。此轮未更改本机内核patch序列。

UniXNU-sheng新package/BootLog.c、GpuPowerProbe.cpp导出[gpu pending]、[gpu wptr]、[vm kinds]、direct scanout、governor；36ec562c将fence waiter睡眠至1000us并由IRQ唤醒，支持touch/frame boost。这些回调、日志、时钟投票仍绑定sheng，需独立移植并测本机频率/IRQ。

## 官方文档当前含义

- https://unixnu.com/zh/porting/ ：六层启动交接，SoC共享与板级配置分离。
- https://unixnu.com/zh/porting/gpu ：先平台DMA/基础呈现，再GMU/HFI、SMMU、CP/ring/fence、有界known image、退出/失败，再Metal。最新已描述16384对象、exclusive map、按页unmap、无需每submit TLBI、拒绝encoder。
- 该页仍明确其他GPU代际须先实现对应kernel backend/compiler；CPU读取GPU结果前cache sync；timeout先停止队列确认DMA停后才释放BO/mapping。不能只部署Metal bundle宣称桌面加速。
- https://unixnu.com/zh/devices/sheng-unattended-test ：当前reader采用匹配sheng Linux image、userdata尾32MiB只读取回到RAM、CDC传输；正常autoreset在日志sync成功后，watchdog异常恢复区分记录。
- 对houji只能采用“启动ID+检查点+同步结果+恢复结果分别验收”的流程，不能直接使用sheng userdata布局、watchdog/复位地址或Linux镜像。此轮没有执行文档命令。

## 同芯片外部参考额外复查

tycykp/UniXNU-OnePlus-Ace5默认HEAD仍aaa100d19f6fb14e5897a7e496edf7838d4d4e9f（2026-10-23 16:43:06 UTC）：无新A750提交。
https://github.com/tycykp/UniXNU-OnePlus-Ace5/commit/aaa100d19f6fb14e5897a7e496edf7838d4d4e9f

ShueiTsuki/data-a-live当前HEAD91f1f2468f30841c39123c7ba20ae520ecd82c84（2026-10-25 19:34:49 UTC），最新是audio/DSP/MCA笔记；这轮没有把A8xx该仓全部新增提交逐一比较，因此不作“没有新GPU改动”的断言，也不当作A750支持证据。

## 本地只读事实

${UNIXNU_ROOT} HEAD 79d81c10220caebb15da5737a4eb6c20724cc731；
git submodule status显示NativeAdreno b686b905、NativeMetal c6d29caa、NativeMobileDisplay8666a995等尚未初始化的gitlinks。
${HOUJI_PORT_ROOT}的Adreno740/source-manifest.json仍source_commit b686b905、runtime_tested=false、provider_published=false；
这不覆盖父任务后续单项真机实验的证据。



本轮完成 r149 后再次通过 GitHub connector 只读查询各仓库默认分支最新提交：Adreno740 仍为 `5c8c1453c67d6ef6b10ec43ab1f8fc570a2f33e1`，AdrenoMetal 仍为 `ce5e19e33e05e1873d38d818e23cabfe0ac708c3`，主仓库仍为 `ae687009348296e97e49ce6e925795044f363ce6`。没有拉取、重置或混合 ABI；性能提交不能替代 houji CPU16K/HFI/GMU 实机资格。
