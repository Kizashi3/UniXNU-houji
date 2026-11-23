> **候选目录：未集成，未经小米 14 的 XNU 真机验证。** 本地 CPU16K/GPU4K 内存适配边界见 [CANDIDATE.md](CANDIDATE.md)。下文保留固定上游参考说明，历史结果不属于本候选。

# NativeAdreno

Native XNU Adreno 740 driver. Owns GMU startup, the CP ring, BOs, native 4 KiB SMMU contexts, fences and cache maintenance.

Current state: GPU commands and the scanout copy run on sheng hardware. Shader compilation is slow and there is no complete precompiled UI pack.

Linked into XNU by `unixnu build kernel`.
