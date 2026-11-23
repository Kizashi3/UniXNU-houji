# Fixed secure-CX Native candidate

候选目录 `/tmp/houji-securecx-native`。只新增 `native/gpu/xnu/HoujiGpuSecureCxProbe.inc` 和本测试包；P、actual XNU、设备及启动镜像均未改变。测试未执行真实 SMC 或固件。

```sh
cd /tmp/houji-securecx-native
python3 tests/securecx-native-host/run_native_test.py
```

最终运行：**154 个实际 Native/ggs host profile，ASan/UBSan 通过**；原样 `tests/check-gpu-scm.c` 的固定 ABI、原始返回、重试和 quarantine suite 也通过。baseline 为固定 3 个 SCM exchange、13 份新 cold snapshot、18304 次独立 AT、1937 次 RO MMIO peer 读取。测试先实际执行真实 NC external canary 与 Native firmware-memory preparation，拥有 3+9 个真实 Native BO；SCM 阶段两个旧 owner 整体保持逐字不变，GPU MMIO store 数保持 179。

接口为 `static bool houjiGpuSecureCxProbeOnce(void)`，在真实 ExternalCanary 和 FirmwareMemory `.inc` 后 include，由已经具备单一同步 owner 配置的正常 worker 调用。`houji_gpu_scm_probe` 缺失或 0 禁用，1 启用，其他值拒绝。新 once/owner/RO Device maps 独立存在。返回 false 时调用方必须进入已有的 retained、no-FS PSCI/reset 路径；不能恢复旧 owner、release/retire BO、拆 stream、重置 quarantine，或把 reset1 当成 DMA drain。候选不负责添加线程、启动镜像或调用平台复位。

只调用未修改 `giulia_gpu_scm.h` 的 `ggs_run(...,GGS_INIT)`；实际 SMC 边界转发其 `ggs_aarch64_call`。原始固定 frames 为：

| phase | x0 | x1 | x2 | x3..x7 |
| --- | --- | --- | --- | --- |
| convention | c2000601 | 1 | 02000601 | 0 |
| availability | 42000601 | 1 | 02002801 | 0 |
| INIT | 42002801 | 1 | b | 0 |

INTERRUPTED 仅按原 helper 的 x0=1 和完整 64 位 x6 cookie 恢复；BUSY 仅由原 helper 有界重试，使用正常线程 `IOSleep(30)`，下一帧原 function/x6=0。没有任意 SCM ID、PAS/ZAP、HYP_ASSIGN 或 firmware/HFI/CP 执行接口。每一次实际 SMC（包括重试）前、后都重新证明独立冷态；helper 自身仅两次 prerequisites 不替代这些每调用检查。

准入必须是本 boot 的真实 GEC phase4、NC profile、`gec_complete_proof`、safe1，且真实 GEC BO refs1/NC 属性和实际 descriptor/PAR 保持不变；FWmemory 必须已完成、inactive、全部 9 BO refs0。新只读 lease 逐个核对 descriptor、mapping、完整 owned spans、PA/VA 边界和全部 PAR，明确拒绝 12 BO 同图/跨图完整 owned 范围重叠。known physical aperture 只有 AT 观察，无 data dereference。没有调用旧 Own/MemoryIdentity/Fresh/Exclusive 或设置旧 active。

每次 cold 经真实 `gec_observe_ro`（内部真实 `hph_observe_ro`）、`hph_recheck` 和退役 `gec_state_qualified` 核验：全部 24 routes FAULT、22 banks M0、reset1、FWinit/HFI0、匹配 clocks、bank2 canonical SCTLR/TTBR0/1=0、ACTLR3/PRR0。新固定四窗口全部只读 Device，访问只经白名单与先行 gate。完整 raw cold snapshots、8×64 位 input/output 和每调用 attempted/returned/transport 都保留。

INTENT 仅在完整 cold 与当前 lease 成功后保存，保存返回后再 fresh，才进入 SMC。SMC 返回立即记录完整 RAW RETURN / `POST_COLD_PENDING`，不做 FS；新 post-cold 成功才记录 `POST_COLD_PROVEN`，`post_ok` 与 attempted snapshot index 分开。整个固定 INIT 成功、无 quarantine、最终 cold 成功后才保存成功报告；保存返回后再 fresh，只有该检查通过才 complete。失败不新增盲目的 FS 保存。Cold5 失败可能发生在之前合法的 final checkpoint 之后：此时必须 `report_saved=1/report_returned=0/complete=0` 并转 no-FS。

覆盖包括 fixed frames/full64-bit statuses 与 cookie、busy/interrupted 限额、WAITQ/transport/INIT 错误、每 call 前后变化、全部 24 SMR/24 S2CR/22 bank、canonical context/reset/FWinit/HFI/clock、4 个独立窗口的 allocation/map 失败、AT/refs/NC 属性/旧结果拒绝、Cold4 与 Cold5/final checkpoint 后变化，以及 descriptor/spans/PAR 自身一致但 FW VRB 与 GEC zero 物理页重叠的组合拒绝。

`build/verification.json` 记录完整实际编译/运行命令、输入快照 hash、fixture/base peer hash 和架构替换边界；`build/snapshot`、`probe.cpp`、`test-output.txt`、`helper-test-output.txt` 保留本轮输入/结果。base peer 复用已通过的 NC Native fixture；runner 逐字断言其中 Memory.cpp 等于当前真实源、Cpu.cpp 只存在列明的 MRS/DC/DSB 边界替换。真实 GEC、FWmemory、hhi bridge、SHA-256、firmware validator、SMMU vendor C 和 ggs business code 均编译执行。

这些证据不证明实际 Arm/Darwin SMC 指令和寄存器保存、真实 secure-CX 寄存器效果、真实 IO/全部 alias/并发 CPU 状态，或原厂 firmware/HFI/CP/DMA。实际 ARM wrapper 仍需 root 构建和核对。本候选没有设备执行资格结论。
