# Houji full host graph：离线 CPU 候选

此目录是新的独立 C ABI。仅准备、复制、验证和 CPU 发布 RAM；没有 MMIO、SMC、bank/stream 装载、device refs、固件执行、HFI 发包、HWSCHED/resource 回应、FS 或释放入口。当前仅为仓库内离线候选，未加入 actual XNU 编译或启用设备运行。

`houji_native_full_host_graph.h` 为 C11/C++14 POD；`FhgStorage` 固定 32768B、16B 对齐。第一次使用前清零，init 后地址就是身份；不得复制、移动、手动清零或复用。一次 prepare，包括失败。所有转交的 BO 保留到 platform reset。外部串行调用；回调重入被 BUSY 拒绝。

## 真实对象与图

私有 C TU 用 `HFM_WITH_SCRATCH=1` 直接 include 原 `GpuFirmwareMemory.h`，调用原 `hfm_prepare`。scratch/GPU ranges 用原 `hsc_pool_ranges`、`hsc_large_range`、`hsc_gpu_only_ranges`；code 用原 `hcc_firmware`、`hcc_copy`、`hcc_ranges`。两个图均由真实 `ArmSmmu4KBuild` 构造并由真实 descriptor reader + `ArmSmmu4KAuditTables` 遍历，不手写表。

|slot|对象|logical GPU4K pages|CPU16K owned bytes|CPU属性|
|---|---|---:|---:|---|
|0..4|5个 GMU FW reservation|19/27/19/37/2|81920/114688/81920/163840/16384|WB|
|5|17-queue HFI|18|81920|Normal NC|
|6|log|16|65536|Normal NC|
|7|VRB|1|16384|Normal NC|
|8|shared|256|1048576|Normal NC|
|9|GMU-only|256|1048576|Normal NC|
|10|large|1024|4194304|Normal NC|
|11|GMU table pool|10|49152|WB|
|12|GPU-only pool|256|1048576|Normal NC|
|13|SQE/AQE/record sparse code arena|64|262144|Normal NC|
|14|GPU table pool|7|32768|WB|

GMU：11 ranges、1675 leaves、9 个使用中的表页、4608 descriptor reads，表池容量10个GPU4K页。GPU：12 ranges、1567 leaves、7表页、3584 descriptor reads。均为 input32/output36，接受36bit高PA；GPU与GMU的共享数据复用同一真实 BO，并非复制 allocations。全部表页本身和每个 BO 的 rounded CPU tail 均不映射为 leaf。

原图的 permissions/writeback/shareability 完整保留，包括原 HFM1 的 GMU-only 可执行位；本候选不宣称它是更小或重新设计的图。GPU code 中 SQE21页/AQE9页为 RX，record1页为 privileged RW/NX，其余 code arena holes 不映射。

## Native 边界与资产

`FhgOps` 只有 CPU sha256、allocate、validate、publish。request 明确 slot/kind、GPU4K logical pages/bytes、独立计算的 rounded owned bytes 和 CPU4K/16K几何。Backing 必须是一个物理连续完整 owned span；core 检查CPU对齐、36bit上界、full-owned VA/PA交集、与storage/输入资产/output不交叠。Native 仍必须独立检查 descriptor、实际 physical segments、CPU0refs、NC/WB属性、全PAR与 dormant alias AT-only。回调返回值不是 DMA 资格。

SHA callback 应直接使用真实 `NativeAdrenoSha256::hash`；core 在所有分配前及最终发布后比较以下固定32字节hash。verify 在重复 Native read-only lease检查前后再次检查hash。全部资产必须 immutable、存活到 platform reset。

|文件|bytes|SHA256|
|---|---:|---|
|gmu_gen70900.bin|78588|9685f62c42543befcaee68d25355e16bf55cdb0d573bddcc9f6633f59eec3f72|
|gen70900_sqe.fw|85300|8e2c5ce74140de7e161f14654b44de999855bce01b690fdd18c3358a73498cd1|
|gen70900_aqe.fw|33176|25237c161d727b8ea92b4beb837a31651b44ea78bfc34d95672af8f346a45825|

SQE/AQE 还经过原CRC/长度/零头检查和原 `hcc_copy` skip4；code完整256KiB的payload、holes、record初始零均读回。GMU内容验证重复真实两个独立planner；5FW全部payload/holes、HFI17 headers/rings/padding、log/VRB、shared/GMU-only/large、GPU pool和每个owned tail均检查。publish每BO恰好一次，共15次。verify只重新查lease/内容/表，不清零、不publish、不改属性。

## 失败与只读输出

`FHG_OK` 是 API 调用完成；`out_code`/summary.ready 才说明CPU准备结果。API坏参数保持out不变。若allocate回调返回一个覆盖out的 backing，prepare消费该次尝试、保留部分资源，返回 ARGUMENT且不再写out；可用另一个CPU输出对象读取summary。

原 `hfm_prepare` 失败会调用原 `hfm_release`。桥的内部 release boundary 始终拒绝释放并记录精确下降顺序；不把任何已释放位伪造成成功。summary同时保留原raw hfm allocated/validated/released/retained、return code以及被 `HFM_RELEASE` 覆盖前的首因。最初分配失败且无已分配BO时，原返回仍为 `HFM_ALLOC`，不能硬编码成 `HFM_RELEASE`。callback非零但返回非零输出另记uncertain，不能捏造进upstream allocated位。

成功返回但非法的 backing 也保留原输出和实际转交位；未通过validate之前不触碰它的数据。所有失败不free/unmap/retire；由Native保留/隔离直到reset。只读 getter 不导出上游指针；其POD快照不授权执行。

## 后续接法

旧 HHI/HSN 的 ABI、宏profile和封存对象不变。本候选不接收旧 HhiStorage，不清其busy，不从其snapshot重建新result。

下一阶段若接原HGF/HHP、bank0/GX/code/gen7/CP，typed runner必须新增在这个私有C TU，直接使用其真实 `FhgState.hfm` 与真实GPU config/built；或者先把完整State移到仅内部C使用的private header。**不能由 `fhg_graph`/`fhg_row` POD复制拼装 `hfm_result`，不能把32768B opaque或ready当成执行token。** 实际运行owner需另行取得boot epoch/owner/所有BO refs/immutable tables/NC leases/secure prerequisites与阶段许可；本准备API没有这些功能。没有预留宽泛MMIO/SMC callback或任意packet接口。

## 离线验证

运行 `python3 ${HOUJI_PORT_ROOT}/tests/full-host-graph/run_core_tests.py`。使用真实固件、真实Native SHA和原vendor C实现，ASan/UBSan，C11/C++14；另原样运行原 `check-gpu-firmware-memory.c`（HFM1）及 `check-gpu-code-memory.c`。证据是 `tests/full-host-graph/build/core/source-manifest.json` 和 `tests/full-host-graph/build/core/test-output.txt`；Native descriptor 集成验证为 `tests/full-host-graph/run_native_graph_tests.py`，证据保存在 `build/native`；使用真实 Native Memory/Cpu 实现，仅替代 IOKit 和架构边界。

`HoujiFullHostNativeMemory` 约250KiB，必须 static 或显式持有的堆存储，不能放 XNU 栈。设备运行入口必须传入完整 foreign owned-span ledger，host 空 ledger 不是设备资格。封存前重复核对同一实际 opaque graph 和15个 descriptor；失败需 retainFailure，资源不回收。

这些host证据不证明Native实际大块分配成功、设备运行、HFI/CP ACK、DMA drain、ZAP认证、2D或图形能力。
