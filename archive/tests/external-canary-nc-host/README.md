# NormalNC external-canary Native candidate

本目录是 `/tmp/houji-nc-canary-native` 独立候选的离线验证。没有修改 P、actual XNU、设备、启动镜像或内核。

```sh
cd /tmp/houji-nc-canary-native
python3 tests/check-houji-gpu-external-canary-probe.py
python3 tests/external-canary-nc-host/run_native_nc_test.py
```

最终结果：WB **6050** 个原有用例通过；NormalNC **6479** 个用例通过；两者均使用 ASan/UBSan。WB 保留所有原断言，并增加 `gec_result` 新增尾部四字段全零的断言。NC 仅在精确的逐次 AT 失败循环允许进入 CPU finish 后的再次属性检查失败；未知执行和精确故障矩阵的所有原 `!cpu_finish_called` 断言保留。

候选的 `houji_gpu_external_nc_probe` 缺失或为 0 使用 WB，值为 1 使用 NC，其他值拒绝。table BO 始终 WB；data 与 PRR zero 各独占完整 16 KiB backing，并通过真实 `makeWriteCombined()` 在任何 device reference 前完成完整 owned CIVAC、DSB 和 pmap 属性转换。只有一个 4 KiB data leaf；PRR zero 仍然仅是 physical page，没有新增 zero IOVA 或 leaf；table walk、MAIR 和 context 协议保持原值。

NC 模式只通过 descriptor 访问 data/zero。物理 aperture 在完整 `gPhysBase/gPhysSize` 边界验证后仅用于 AT R/W 观察，每个 4 KiB 的完整 64 位 PAR 均保留并锁定；未知属性、R/W 不一致、PA 错误或后续变化会拒绝继续。WB alias 的 inactive 只描述本 adapter 从不解引用它，不授予 alias 数据访问权限，也不能证明系统不存在其他 alias 或并发访问。Normal iNCoNC 的 EffectiveShareability 为 OSH，测试接受 PAR.SH=0/2/3，拒绝保留值 1；没有修改全局 pmap 策略。

NC publish 使用 DSB SY，acquire 使用 DMB OSHLD + DSB SY，恢复写入后再次 DSB SY。NC 的旧 `cpu.invalidated` 始终为 0；core 自行记录 profile，新证据严格要求 `nc_acquired=6`、`nc_restore_published=1`、`nc_table_invalidated=1`。table 的真实 WB invalidate 与 NC data 可见性分别记录。

成功 profile 保留 179 stores、24 个 core fresh 加 2 个独立诊断观察、全部三个 BO/device references，未调用 release 或 retire。NC profile 有 656 次 AT、两个 16 KiB 转换的 512 条真实 CIVAC 操作、5 个 NC 屏障调用；NC data 转换后任何 DC 操作都会让 host peer 失败。保留所有 terminal、precise-frame、safe-to-save 和 unknown-execution no-FS 门。

`build/verification.json` 保存实际编译/运行命令、所有输入快照 SHA-256 和架构替换边界；`build/snapshot` 是本次输入副本，`build/probe.cpp` 是编译的完整 host translation unit，`build/test-output.txt` 是 NC 输出。`wb-evidence` 保存最终 WB 命令、输入 hash 和输出。`NativeAdrenoMemory.cpp` 与 `NativeAdrenoCpu.cpp` 原样编译，只有 MRS/DC/DSB/AT、IOKit/pmap 和设备 MMIO 是 host 边界 peer。

NC DMA peer 直接更新 descriptor 的 NC memory；NC acquire 只检查排序，绝不从 WB invalidate hook 复制数据。故意只更新 DRAM 的错误 peer 会被拒绝。额外用例覆盖严格 bootarg、明确 0/缺失值、完整 aperture 边界/溢出、NC pmap 写失败、未知 alias 属性、PAR 故障、属性/alias 在 checkpoint 或 acquire 后变化、NC 属性/SH 编码以及精确负例。

这些结果仅证明离线 Native adapter/core 判断和 peer 协议。它们不证明实际 Arm 指令执行、真实 pmap/全部 alias 的 CPU 状态、实际 SMMU/CM3/PRR/DMA、外部 RAM writeback、固件/HFI/CP 或桌面加速。
