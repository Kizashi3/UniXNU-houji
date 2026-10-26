"""Bounded, read-only A750 diagnostics over the existing terminal transport.

The caller must already own live CX/clock/SMMU prerequisites and the mappings
used by gpu-native-hwsched.py. This module never maps, wakes, acknowledges,
clears, resets or enables an interrupt. GX reads additionally require an
acknowledged OOB hold and the configure-stage 0x3d00000..0x3d3ffff mappings.

Offsets are dwords in the pinned OnePlus gen7_reg.h, except SMMUv2 offsets
which are bytes. The GPU source revision is 453d8875f815bf9dfad9035982861226a4823a6c.
See adreno_gen7.c:gen7_irq_handler/gen7_irq_poll_fence and
adreno_gen7_gmu.c:gen7_gmu_version_info/gen7_gmu_gx_is_on. In particular,
RBBM_INT_0_STATUS is excluded: its read can let GX collapse, and the vendor
handler surrounds it with a KEEPALIVE write. The AO unmasked mirror is used.

An atomic host JSON checkpoint is written before and after every MMIO read.
This preserves completed host evidence on a transport failure; it cannot
capture faults occurring after the phone abruptly resets or enters 900E.
Snapshots are sequential observations, not an atomic hardware crash dump.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import NamedTuple


class Register(NamedTuple):
    name: str
    address: int
    width: int = 32
    domain: str = "cx"


def _gen7(name, word, domain="cx"):
    return Register(name, 0x3d00000 + 4 * word, 32, domain)


GX_POWER = _gen7("GEN7_GMU_GFX_PWR_CLK_STATUS", 0x1f8d0)
AHB_FENCE = _gen7("GEN7_GMU_AO_AHB_FENCE_CTRL", 0x23b10)
CX_REGISTERS = (
    _gen7("GEN7_GMU_GMU2HOST_INTR_INFO", 0x1f992),
    _gen7("GEN7_GMU_GMU2HOST_INTR_MASK", 0x1f993),
    _gen7("GEN7_GMU_AO_HOST_INTERRUPT_STATUS", 0x23b05),
    _gen7("GEN7_GMU_AO_HOST_INTERRUPT_MASK", 0x23b06),
    _gen7("GEN7_GMU_AHB_FENCE_STATUS", 0x23b13),
    _gen7("GEN7_GMU_RBBM_INT_UNMASKED_STATUS", 0x23b15),
    _gen7("GEN7_GMU_GMU_PWR_COL_KEEPALIVE", 0x1f8c3),
    _gen7("GEN7_GPU_GMU_CX_GMU_RPMH_POWER_STATE", 0x1f8ec),
    _gen7("GEN7_GPU_GMU_AO_GPU_CX_BUSY_STATUS", 0x23b0c),
    _gen7("GEN7_GPU_GMU_AO_GPU_CX_BUSY_STATUS2", 0x23b0d),
    _gen7("GEN7_GMU_CM3_SYSRESET", 0x1f800),
    _gen7("GEN7_GMU_CM3_FW_BUSY", 0x1f81a),
    _gen7("GEN7_GMU_CM3_FW_INIT_RESULT", 0x1f81c),
    _gen7("GEN7_GMU_HFI_CTRL_STATUS", 0x1f980),
)
# Version words are read from the fixed DTCM trailer, not inferred from HFI ACKs.
VERSION_REGISTERS = tuple(
    _gen7("GMU_VERSION_" + name, 0x1c400 + 0xff8 + index)
    for index, name in enumerate(("CORE", "CORE_DEV", "POWER", "POWER_DEV", "HFI"))
)

# kgsl_iommu.h and the pinned arm-smmu oracle's arm-smmu.h. GR1 begins at
# 0x1000 on this verified 4 KiB-register-page SMMU; CBFRSYNRA is GR1 + 0x400.
SMMU_REGISTERS = (
    Register("SMMU_SCR0", 0x3da0000, domain="smmu"),
    Register("SMMU_GFSR", 0x3da0048, domain="smmu"),
    Register("SMMU_GFSYNR0", 0x3da0050, domain="smmu"),
    Register("SMMU_GFSYNR1", 0x3da0054, domain="smmu"),
    Register("SMMU_GFSYNR2", 0x3da0058, domain="smmu"),
    Register("SMMU_SLOT0_SMR_GMU", 0x3da0800, domain="smmu"),
    Register("SMMU_SLOT0_S2CR_GMU", 0x3da0c00, domain="smmu"),
    Register("SMMU_SLOT1_SMR_GPU", 0x3da0804, domain="smmu"),
    Register("SMMU_SLOT1_S2CR_GPU", 0x3da0c04, domain="smmu"),
) + tuple(
    Register(f"SMMU_{owner}_CB{bank}_{name}", 0x3dc0000 + bank * 0x1000 + offset,
             width, "smmu")
    for owner, bank in (("GPU", 0), ("GMU", 2))
    for name, offset, width in (
        ("FSR", 0x58, 32), ("FAR", 0x60, 64),
        ("FSYNR0", 0x68, 32), ("FSYNR1", 0x6c, 32),
        ("SCTLR", 0x0, 32), ("ACTLR", 0x4, 32),
        ("TTBR0", 0x20, 64), ("CONTEXTIDR", 0x34, 32),
    )
) + tuple(
    Register(f"SMMU_{owner}_CB{bank}_CBFRSYNRA", 0x3da1400 + bank * 4,
             domain="smmu")
    for owner, bank in (("GPU", 0), ("GMU", 2))
)

GX_REGISTERS = tuple(_gen7(name, word, "gx") for name, word in (
    ("GEN7_RBBM_INT_0_MASK", 0x38),
    ("GEN7_RBBM_STATUS", 0x210), ("GEN7_RBBM_STATUS3", 0x213),
    ("GEN7_CP_SQE_CNTL", 0x808), ("GEN7_CP_HW_FAULT", 0x821),
    ("GEN7_CP_INTERRUPT_STATUS", 0x823), ("GEN7_CP_PROTECT_STATUS", 0x824),
    ("GEN7_CP_STATUS_1", 0x825),
    ("GEN7_CP_SQE_INSTR_BASE_LO", 0x830), ("GEN7_CP_SQE_INSTR_BASE_HI", 0x831),
    ("GEN7_CP_RL_ERROR_DETAILS_0", 0x9b4), ("GEN7_CP_RL_ERROR_DETAILS_1", 0x9cf),
    ("GEN7_CP_AQE_INSTR_BASE_LO_0", 0xb70), ("GEN7_CP_AQE_INSTR_BASE_HI_0", 0xb71),
    ("GEN7_UCHE_CLIENT_PF", 0xe19),
    ("GEN7_RBBM_SECVID_TRUST_CNTL", 0xf400),
    ("GEN7_RBBM_SECVID_TSB_TRUSTED_BASE_LO", 0xf800),
    ("GEN7_RBBM_SECVID_TSB_TRUSTED_BASE_HI", 0xf801),
    ("GEN7_RBBM_SECVID_TSB_TRUSTED_SIZE", 0xf802),
    ("GEN7_RBBM_SECVID_TSB_CNTL", 0xf803),
    ("GEN7_RBBM_SECVID_TSB_STATUS_LO", 0xfc00),
    ("GEN7_RBBM_SECVID_TSB_STATUS_HI", 0xfc01),
))

HWSCHED_HOST_IRQ_MASK = 0x03400042  # adreno_gen7.h: AHB, ATB async/bus, UCHE OOB/trap
HFI_IRQ_MASK = 0x8006              # adreno_hfi.h; runtime MSGQ additionally bit 0
GMU_AO_IRQ_MASK = 0x29             # kgsl_gmu_core.h: watchdog, fence, AHB bus
SMMU_VALID_FAULT_MASK = 0xc00001fe  # FORMAT bits 10:9 do not indicate a fault
ALL_REGISTERS = (GX_POWER, AHB_FENCE) + CX_REGISTERS + VERSION_REGISTERS + SMMU_REGISTERS + GX_REGISTERS
MAX_READS = 2 + len(CX_REGISTERS) + len(VERSION_REGISTERS) + len(SMMU_REGISTERS) + 3 * len(GX_REGISTERS)


def _checkpoint(path, report):
    """Publish one complete JSON document; never truncate the last checkpoint."""
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class _ReadFailed(Exception):
    pass


def snapshot(live, report, output_path, phase, *, cx_ready=False,
             include_gx=False, gx_held=False):
    """Append and persist a snapshot; return its complete/skipped/failed record.

    cx_ready is the caller's explicit confirmation of live CX and SMMU clock
    prerequisites and all CX/version/SMMU mappings. include_gx confirms the
    configure-stage GX mappings; gx_held confirms an acknowledged OOB hold has
    not been released. They are prerequisites, never evidence of correctness.
    A failed transport read stops immediately without any further MMIO. Disk
    errors propagate so callers cannot continue on an unrecorded attempt.
    """
    if not isinstance(phase, str) or not phase or len(phase) > 80:
        raise ValueError("Snapshot phase must be a nonempty label of at most 80 characters")
    entry = {
        "phase": phase, "started_utc": datetime.now(timezone.utc).isoformat(),
        "status": "in_progress", "read_only": True, "reads": [],
        "max_reads": MAX_READS, "context_banks": {"gpu": 0, "gmu": 2},
        "prerequisites": {"cx_ready": bool(cx_ready), "include_gx": bool(include_gx),
                          "gx_held": bool(gx_held)},
        "gx": {"status": "not_started"},
        "limitations": ["sequential host observations; not an atomic crash dump",
                        "cannot capture after abrupt reset or USB 900E",
                        "no RBBM_INT_0_STATUS read; AO unmasked mirror only",
                        "preflight reads cannot replace a held power lease"],
    }
    report.setdefault("fault_snapshots", []).append(entry)
    _checkpoint(output_path, report)

    def read(register, purpose="diagnostic"):
        row = {"name": register.name, "address": hex(register.address),
               "width": register.width, "domain": register.domain,
               "purpose": purpose, "status": "pending"}
        entry["reads"].append(row)
        _checkpoint(output_path, report)
        try:
            value = live.read(register.address, register.width)
            if not isinstance(value, int) or not 0 <= value < (1 << register.width):
                raise ValueError("Transport returned an invalid register value")
        except Exception as error:
            row.update(status="failed", error=str(error))
            entry.update(status="failed", error=f"{register.name}: {error}")
            _checkpoint(output_path, report)
            raise _ReadFailed from error
        row.update(status="complete", value=hex(value))
        _checkpoint(output_path, report)
        return value

    try:
        if not cx_ready:
            entry.update(status="skipped", reason="CX/clock/mapping prerequisites not confirmed")
            entry["gx"] = {"status": "skipped", "reason": "CX prerequisites not confirmed"}
            return entry

        # Check GX access before any candidate GX register; these are CX/AO reads.
        power, fence = read(GX_POWER, "preflight"), read(AHB_FENCE, "preflight")
        for register in CX_REGISTERS + VERSION_REGISTERS + SMMU_REGISTERS:
            read(register)

        values = {row["name"]: int(row["value"], 16) for row in entry["reads"]}
        entry["smmu_faults"] = {
            owner: {"bank": bank, "fsr": hex(values[f"SMMU_{owner.upper()}_CB{bank}_FSR"]),
                    "valid_fault": bool(values[f"SMMU_{owner.upper()}_CB{bank}_FSR"] & SMMU_VALID_FAULT_MASK)}
            for owner, bank in (("gpu", 0), ("gmu", 2))
        }
        core = values["GMU_VERSION_CORE"]
        entry["firmware"] = {
            "core": hex(core), "hfi": hex(values["GMU_VERSION_HFI"]),
            "host_rbbm_irq_required_by_vendor": (core < 0x50010006
                                                  if core not in (0, 0xffffffff) else None),
            "hwsched_host_irq_mask": hex(HWSCHED_HOST_IRQ_MASK),
            "hfi_irq_mask_base": hex(HFI_IRQ_MASK), "ao_irq_mask": hex(GMU_AO_IRQ_MASK),
            "irq_handler_installed_by_snapshot": False,
        }
        reason = ("GX mapping not requested" if not include_gx else
                  "acknowledged OOB hold not confirmed" if not gx_held else
                  "GX power or clock is off" if power & 3 else
                  "AHB fence is not ALLOW" if fence != 0 else None)
        if reason:
            entry["gx"] = {"status": "skipped", "reason": reason}
        else:
            entry["gx"] = {"status": "in_progress"}
            for register in GX_REGISTERS:
                # A power/fence change cuts off the remaining GX reads. No retry.
                power = read(GX_POWER, "gx_guard")
                fence = read(AHB_FENCE, "gx_guard")
                if power & 3 or fence != 0:
                    entry["gx"] = {"status": "stopped", "before": register.name,
                                   "reason": "GX power/clock or AHB fence changed",
                                   "power": hex(power), "fence": hex(fence)}
                    break
                read(register)
            else:
                entry["gx"] = {"status": "complete"}
        entry["status"] = "complete"
    except _ReadFailed:
        if entry["gx"]["status"] == "in_progress":
            entry["gx"]["status"] = "failed"
    finally:
        entry["finished_utc"] = datetime.now(timezone.utc).isoformat()
        _checkpoint(output_path, report)
    return entry
