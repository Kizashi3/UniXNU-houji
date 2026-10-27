# 20H392 prelink validation (2026-10-27)

This fixes the instruction-inventory failure at 0xfffffff005b8c1cc and a
subsequent stale AMFI initializer address. It does not qualify the kernel ABI
or phone boot.

## Inputs

- Original IM4P: kernelcache.release.iphone10b from iPhone X iOS 16.7.16 / 20H392.
- IM4P SHA256: 2d6a13d040aaf87cec09bb6906d43e9bd8cea951e43d1aa1cd62707dfdc5aaec
- Decompressed ARM64 slice SHA256:
  2ec297bac95bcba01046fd0148e97e7e5885c05a6c18827f39f534ba375c1221
- The local end-to-end check uses the previously downloaded native-kernel
  baseline from action-40438667582, NOT the latest Actions artifact.
- Local UniXNU checkout: 1a01c2afa197d975d04da892325c56b6b14aaecb.

## Libm constant pool

The offending word is 0xf09d5f48 in com.apple.kec.Libm. Decoding it as ADRP
produces target 0xffffffef40777000. It is part of a floating-point table,
not a cross-component instruction.

Evidence from the original bytes:
- A return ends at 0xfffffff005b8c050.
- Literal table is [0xfffffff005b8c054, 0xfffffff005b8c520), 1228 bytes.
- Code at 0xfffffff005b8bf40 loads a literal from 0xfffffff005b8c058.
- Code at 0xfffffff005b8bf5c loads a double from 0xfffffff005b8c4c4.
- Code at 0xfffffff005b8bf78 obtains 0xfffffff005b8c4cc and uses vector loads.
- The next function starts with STP x29,x30 / MOV x29,sp at 0xfffffff005b8c520.
- Full pool SHA256:
  73df5b757c53532583e3686b7d93df11ec1f5dd8c201d05502654a7812cc385f

The patch adds an entry to the existing hash-qualified MATH_LITERAL_POOLS.
It does not alter the kernelcache bytes, skip all Libm, or weaken the
external-PC-relative rejection.

## AMFI initializer

The inherited address 0xfffffff005ab4ae0 is outside this image's AMFI code.
The pinned replacement is 0xfffffff005703c54.

Static evidence:
- The preceding method calls it at 0xfffffff005703bd8.
- Entry has a stack prologue and establishes its arguments internally;
  it does not consume caller arguments before preparing its first call.
- It initializes the AMFI policy operation table.
- At 0xfffffff005703fa4 it calls 0xfffffff0057184ac.
- That import stub reads GOT slot 0xfffffff006cb5c38.
- The original GOT value is 0xfffffff007804ef0, exported as _mac_policy_register.
- The routine has normal returns and a stack-check path before the next
  function at 0xfffffff005704074.
- SHA256 of its 1056 bytes:
  3a7c782c190e6615797d7b2bc2471e4e5d8599e6d5cc7e539d21305943760551

These are static call/ABI observations, not runtime qualification.
The decompressed kernelcache is pinned in board.toml to keep the address
and table identity tied to the analyzed input.

## Checks

- Parsed workflow YAML; bash -n on every run block; executed the actual
  annotation and compatibility steps in a fresh source fixture.
- All 23 upstream NativePrelink tests passed.
- verify-prelink-ios16.py reproduced the original failure without the new
  pool entry, then scanned all 29 selected executable components successfully.
- 223220 PC-relative encodings preserved.
- Changing one pool byte outside its prefix restored the rejection.
- Inserting a branch outside selected extents at the next function entry
  also caused rejection: executable code is still checked.
- Verified AMFI code ownership and exact initializer bytes.
- Full emit using the archived native baseline generated 57020416 bytes.
- Candidate SHA256:
  40c0ecf22500353f82f511ff7ded92f568f3f3df3a2de38c0a6e5c736ee8c71f
- Output report still marks runtime_qualified=false and loadable=false.

## Local archive

All diagnostic inputs, candidate and reports are on Ubuntu:
 /home/yun/桌面/临时/prelink-analysis/

The local candidate is kernel-local-baseline.macho; it is NOT a phone-tested
or release image. Cloud confirmation must use a new Run workflow on main.

The pre-existing IORPCMessageFromMach -> IORPCMessageFromMachReply mapping
remains experimental: resolving an address does not establish equivalent
request/reply semantics. This patch does not claim to fix that ABI risk.

## Reproduce the input checks

After the workflow patches are applied to the UniXNU checkout:

    python3 DEVICE/scripts/verify-prelink-ios16.py \
      --kit out/houji/tree/kits/NativePrelink \
      --kernelcache out/ipsw/20H392/kernelcache.decompressed \
      --board DEVICE/board.toml \
      --output out/houji/logs/prelink-ios16-validation.json

No phone boot, partition write or data wipe was performed.


## Cloud directory-layout correction

The cloud UniXNU checkout stores the module at kits/XnuPrelink. The board's
out/houji/tree/kits/NativePrelink path is an alias to that submodule.
The workflow now resolves the board's emitter path to its physical parent,
then applies the patch with git -C <physical-kit> apply -p3. Compilation,
unit tests and the later real-cache regression step all use that same path
through PRELINK_KIT.

Validation used actual Git submodules, not just copied files, at XnuPrelink
revision f876e3ee62e18fc06653dd75ed7dafcfb3950ac0:
- both kits/XnuPrelink and legacy kits/NativePrelink layouts passed;
- each ran the workflow's annotation, patch/test, and input-validation steps;
- 26 upstream tests passed per layout;
- both scanned 29 real-cache components and 223220 PC-relative encodings;
- full emit with this cloud-kit revision and the archived native baseline
  generated 57020416 bytes (same SHA256 as the earlier local candidate).
- YAML parsing and bash -n passed.

Fixture paths and results are archived on Ubuntu in
/home/yun/桌面/临时/prelink-analysis/workflow-path-validation.json.
The latest cloud native kernel still requires a new workflow run.
