# GPU

Adreno 750 (`qcom,adreno-43051401`, gen7_9_1) bring-up on SM8650. The code runs in the kernel because the minimal UEFI
firmware has none of the vendor clock, RPMh or SCM drivers that houji's handoff path relies on.

- `GpuPower.cpp`: staged and gated, enabled with the boot-arg `nx769j-gpu=<mode>`. The boot-arg is unset by default.

  | Mode | Adds |
  |---|---|
  | 1 | Read the GCC and GPUCC state, the GPU SMMU and RBBM_STATUS |
  | 2 | `gcc_gpu_cfg_ahb_clk` |
  | 3 | CX GDSC plus the AHB and SMMU vote clocks |
  | 4 | The GMU's own 4K SMMU context (stream 5) |
  | 5 | GMU clock tree read; command DB turned into HFI tables |
  | 6 | GPLL0 votes, gpucc PLL0 and PLL1, hub 200 MHz, GMU 260 MHz |
  | 7 | GMU cold start and HFI startup |
  | 8 | HFI perf vote and OOB GPU_SET (GX on) |
  | 9 | `GpuCommand.cpp`: the GPU SMMU context, SQE, hw_init, ring 0, CP_INIT and one CP_MEM_WRITE |
  | 10 | `GpuCommand.cpp`: the zap shader through TrustZone, then CP_SET_SECURE_MODE 0 (`nx769j-gpu-zap=0` skips it) |
  | 11 | `GpuPublish.cpp`: the NativeAdrenoPublish user-client service and the IOAcceleratorES/AGXAccelerator for Metal and Turnip |

  It is a port of UniXNU-sheng `package/GpuPowerProbe.cpp` (2d4b58b7, SM8550 / A740). Linux runs both GPUs through the same
  a740-family GMU and HFI code.
- `GpuPowerBoard.h`: the SM8650 GCC and GPUCC facts. They match SM8550 except for three values:
  - the CX GDSC hw_ctrl register (0x9168);
  - the PLL0/PLL1 L and alpha values;
  - the GMU clock (260 MHz).
- `ShengGmuVotes.c`: sheng's HFI vote builder. Its inputs are generated.
- `GpuCommand.cpp`: mode 9, the command processor. It sets up the GPU's own SMMU context (bank 0, ASID 2, streams 0 and 1),
  copies `gen70900_sqe.fw` without its first dword, runs the A750 branches of Linux v6.16 `hw_init` (global clock gating with
  the P2S handshake, `RB_CMP_DBG_ECO_CNTL` bit 19, `TPL1_DBG_ECO_CNTL1` 0xc0700), starts ring 0 with the power-up list and
  CP_INIT, then has the GPU write 0x05e9a750 into a scratch page. Completion is polled; no interrupt is attached.
- `GpuBridge.h`: the accessors `GpuPower.cpp` hands to `GpuCommand.cpp` after the GMU cold start.

`scripts/build-nx769j-gpu.py` does the following:

- Generates the GMU registers, the RSC/PDC setup, the OPP and BCM tables and the firmware arrays from
  `.cache/adreno-source` (Linux v6.16) and `.cache/gpu-firmware` (stock vendor/firmware). Both are pinned in
  `scripts/data/nx769j-adreno-inputs.json` and not committed.
- Compiles the needed Adreno740, AdrenoFirmware, ArmSmmu4K, AdrenoPM4 and Sm8550Platform sources from the UniXNU catalog.
  Adreno740 is copied to `build/nx769j-gpu/adreno740` first and `patches/drivers/Adreno740/*.patch` applied to the copy.
  `gen70900-sqe-size.patch` raises `GpuSqeBytes` to 0x16000: the A750 SQE is 85360 bytes and A740's buffer holds 77824.

- `GpuCommand.cpp` mode 10 loads the signed zap shader through the SCM PAS calls and leaves CP secure mode off.
- `GpuPublish.cpp` mode 11 publishes UniXNU's `NativeAdrenoPublish` service and a self-defined `IOAcceleratorES`/`AGXAccelerator`
  (`MetalPluginName NativeAdrenoMetal`), since this kernelcache has no IOGPUFamily. Turnip and the Metal plugin open it.
- `GpuKernelStubs.cpp` answers the few sheng/driver symbols this board does not have (GOP hand-off, log export, DCVS) with "not available".
- `execReport()` prints the live GPU/ring/SMMU state every heartbeat; `nx769j-gpu-nocgc=1` leaves clock gating at reset (a bring-up switch).

The GPU userland (iOS 16 Turnip, the `NativeAdrenoMetal` plugin, `vktest`, `mtltest`) is built on a Mac by
`scripts/build-nx769j-metal.sh` and packed by `scripts/make-nx769j-gpu-addon.py`; see `third_party/data-a-live`.

## Status and known issues

On the device Turnip enumerates the Adreno 750 and client connections work. **Image clear and compute dispatch render
correctly** (`vktest` part 3 and part 4, 0 of 4096 words wrong). Two things do not work yet:

- **Graphics draw hangs** (`vktest` part 5). The submit succeeds but the fence never signals: the CP runs the draw and
  wedges at the colour-cache (CCU) flush in the submit epilogue (`execReport`: `RBBM_STATUS 00800005`, GPU busy, `cp-int` bit 0).
  Compute does not touch the CCU and completes. This is the blocker for GPU desktop composition, which is Metal render passes.
  The `hwInit` here matches the sheng A740 reference, so the difference is the A750 (gen7_9_1) CCU/cache behaviour.
- **Buffer fill/update returns wrong data** (`vktest` part 2): the fence signals but the CPU reads a wrong pattern, a data or
  cache-coherency problem distinct from the part 5 hang.

### Graphics hang: ruled out

Narrowed by elimination against houji (same SM8650 / Adreno 750, which reaches GPU composition through a vendor UEFI handoff). None of these is the cause:

| Lead | Test | Result |
| --- | --- | --- |
| Clock gating | `nx769j-gpu-nocgc=1` (clocks always on) | every submit hangs, even the clear/compute that pass; CGC must stay on |
| GBIF bus interface | write `GBIF_QSB_SIDE`/`GBIF_CX_CONFIG` from the kernel | wedges the bus; GBIF is firmware/GMU owned |
| Missing hwInit registers | compare with houji `GpuGen7Table.h` | every shared register matches |
| Ring submit epilogue | diff `NativeAdrenoRing` | `CCU_INVALIDATE_DEPTH`/`COLOR` fence sequence is byte-identical to houji |
| Memory-path clocks | read the GCC branches | `gcc_gpu_memnoc_gfx` and `gcc_ddrss_gpu_axi` are both voted on |
| GPU voltage/frequency | vote the highest OPP (`nx769j-gpu-perf`) | part 5 still hangs |

Everything comparable to houji matches. The remaining difference is the GMU-managed HFI startup state the vendor firmware
sets up and this port hand-rolls (ACD, startup votes), which needs offline study of houji's GMU bootstrap, not more register probing.

Clock gating must stay on: `nx769j-gpu-nocgc=1` makes even the image clear and compute hang. The device results are in
`docs/DEVICE-EVIDENCE.md` (`gpu1`..`gpu3`, and the `gpu11`..`gpu16` user-path runs). iOS still composes on the CPU.
