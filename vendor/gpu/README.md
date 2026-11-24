# Houji Adreno 750 bring-up inputs

This directory vendors the inputs needed to reproduce the Adreno 750 GPU
bring-up archived by `scripts/build-houji-gpu.py`.

- `Sm8550Platform/` is the pinned SM8550 GMU/command-DB platform library from
  `UniXNU/UniXNU-sm8550-common`. SM8550 and SM8650 use the same register map
  for the GPU, GMU and GPU SMMU windows used here.
- `linux-src/` contains the eleven Linux v6.16 files pinned by
  `scripts/data/houji-adreno-inputs.json`. They are used only to derive the
  register, RSC/PDC, OPP and BCM tables; Linux itself is GPL-2.0.
- `generated/` contains those derived headers and the firmware byte arrays.
- `firmware/` contains Houji's GMU, SQE, AQE and signed ZAP inputs, pinned by
  the same JSON file.

`package-gpu/` at the repository root is the SM8650/A750 bring-up package from
the NX769J port. Its boot argument is still named `nx769j-gpu=<mode>` for
provenance. Mode 9 proves CP execution; mode 11 publishes the NativeAdreno
service and AGX accelerator.
