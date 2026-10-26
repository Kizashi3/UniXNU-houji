"""Isolate the existing RAW watch's MMIO reads without publishing an HFI packet.

Reviewed source: ios16/gpu/giulia_gpu_platform_impl.h:platformWatch/platformSnapshot,
ios16/gpu/giulia_gpu_power.h:ggp_observe, GiuliaGPU.cpp:readRegister. These fixed
addresses deliberately include the previously unobserved secure CB3 diagnostics;
they are candidates to test, not a declaration that every read is safe. Each
pending read is fsynced on the host before execution. No device import, mapping,
write, HFI staging, enqueue, doorbell, or kernel development operation occurs here.

Caller must retain acknowledged OOB and all configure-stage mappings, with CX
clocks and secure context active. After success the caller may separately request
OP14 to test the kernel mapping path; OP14 itself never submits RAW.
"""

from datetime import datetime, timezone

from gpu_terminal_diagnostics import Register, _checkpoint


# Same register set and width as platformPower's ggp_observe; the fixed
# predicates retain its fail-before-later-window behavior.
POWER_REGISTERS = (
    Register("GCC_GPU_CFG_AHB_CBCR", 0x171004),
    Register("GCC_GPU_MEMNOC_GFX_CBCR", 0x171010),
    Register("GCC_GPU_SNOC_DVM_GFX_CBCR", 0x171018),
    Register("GPU_CC_CX_GDSCR", 0x3d99108),
    Register("GPU_CC_CX_GDSC_HW_CTRL", 0x3d99168),
    Register("GPU_CC_AHB_CBCR", 0x3d9911c),
    Register("GPU_CC_HLOS1_VOTE_GPU_SMMU_CLK", 0x3d97000),
    Register("GPU_CC_CX_GMU_CBCR", 0x3d9913c),
    Register("SMMU_SCR0", 0x3da0000),
    Register("SMMU_ID0", 0x3da0020),
    Register("SMMU_ID1", 0x3da0024),
    Register("SMMU_ID2", 0x3da0028),
    Register("SMMU_GFSR", 0x3da0048),
)
POWER_EXPECTED = {
    0x171004: (1, 1), 0x171010: (0x80000001, 1),
    0x171018: (0x80000001, 1), 0x3d99108: (1, 0),
    0x3d99168: (0x80000000, 0x80000000),
    0x3d9911c: (0x80000000, 0), 0x3d97000: (0x80000001, 1),
    0x3da0020: (0xffffffff, 0x4c017e18),
}
GX_POWER = Register("GEN7_GMU_GFX_PWR_CLK_STATUS", 0x3d7e340)
AHB_FENCE = Register("GEN7_GMU_AO_AHB_FENCE_CTRL", 0x3d8ec40)
AO_REGISTERS = (
    GX_POWER, AHB_FENCE,
    Register("GEN7_GMU_GMU2HOST_INTR_INFO", 0x3d7e648),
    Register("GEN7_GMU_AO_HOST_INTERRUPT_STATUS", 0x3d8ec14),
    Register("GEN7_GMU_AHB_FENCE_STATUS", 0x3d8ec4c),
    Register("GEN7_GMU_RBBM_INT_UNMASKED_STATUS", 0x3d8ec54),
    Register("GEN7_GPU_GMU_AO_GPU_CX_BUSY_STATUS", 0x3d8ec30),
    Register("SMMU_GFSR", 0x3da0048),
    Register("SMMU_GPU_CB0_FSR", 0x3dc0058),
    Register("SMMU_GPU_CB0_FAR_LO", 0x3dc0060),
    Register("SMMU_GPU_CB0_FAR_HI", 0x3dc0064),
    Register("SMMU_GPU_CB0_FSYNR0", 0x3dc0068),
    Register("SMMU_GMU_CB2_FSR", 0x3dc2058),
    Register("SMMU_GMU_CB2_FAR_LO", 0x3dc2060),
    Register("SMMU_GMU_CB2_FAR_HI", 0x3dc2064),
    Register("SMMU_GMU_CB2_FSYNR0", 0x3dc2068),
    Register("SMMU_SECURE_CB3_FSR", 0x3dc3058),
    Register("SMMU_SECURE_CB3_FAR_LO", 0x3dc3060),
    Register("SMMU_SECURE_CB3_FAR_HI", 0x3dc3064),
    Register("SMMU_SECURE_CB3_FSYNR0", 0x3dc3068),
    Register("SMMU_GPU_CB0_CBFRSYNRA", 0x3da1400),
    Register("SMMU_GMU_CB2_CBFRSYNRA", 0x3da1408),
    Register("SMMU_SECURE_CB3_CBFRSYNRA", 0x3da140c),
)
GX_REGISTERS = (
    Register("GEN7_RBBM_INT_0_MASK", 0x3d000e0, domain="gx"),
    Register("GEN7_CP_HW_FAULT", 0x3d02084, domain="gx"),
    Register("GEN7_CP_INTERRUPT_STATUS", 0x3d0208c, domain="gx"),
    Register("GEN7_CP_PROTECT_STATUS", 0x3d02090, domain="gx"),
    Register("GEN7_RBBM_SECVID_TRUST_CNTL", 0x3d3d000, domain="gx"),
)
MAX_READS = len(POWER_REGISTERS) + 2 + len(AO_REGISTERS) + 3 * len(GX_REGISTERS)


def _now():
    return datetime.now(timezone.utc).isoformat()


def audit_watch_reads(live, report, output_path, phase="watch_preflight", *,
                      cx_ready=False, gx_held=False):
    """Persist each exact 32-bit read, return complete entry, or propagate failure.

    raw_cp_submitted describes this audit, not earlier/later caller operations.
    Existing report evidence is retained. The prior host snapshot comparison is
    evidence of past reads only; it does not establish future accessibility.
    """
    if not isinstance(phase, str) or not phase or len(phase) > 80:
        raise ValueError("phase must be a nonempty string of at most 80 characters")
    baseline = next((item for item in reversed(report.get("fault_snapshots", []))
                     if item.get("status") == "complete"), {})
    prior = [row for row in baseline.get("reads", []) if row.get("status") == "complete"]
    entry = {
        "phase": phase, "status": "in_progress", "started_utc": _now(),
        "read_only": True, "raw_cp_submitted": False, "kernel_snapshot_requested": False,
        "prerequisites": {"cx_ready": bool(cx_ready), "gx_held": bool(gx_held)},
        "baseline_phase": baseline.get("phase"), "reads": [], "max_reads": MAX_READS,
        "source": ["ios16/gpu/giulia_gpu_platform_impl.h:platformWatch/platformSnapshot",
                   "ios16/gpu/giulia_gpu_power.h:ggp_observe", "ios16/gpu/GiuliaGPU.cpp:readRegister"],
        "limitations": ["host reg.read path; kernel mapping requires separate OP14",
                        "prior completed reads are not an accessibility guarantee",
                        "no HFI enqueue, doorbell, RAW, or kernel watch operation"],
    }
    report.setdefault("watch_read_audits", []).append(entry)
    _checkpoint(output_path, report)

    def read(register, stage, expected=None, reject_all_ones=False):
        observed = "not_observed"
        for old in prior:
            address, width = int(old["address"], 16), old["width"]
            if address == register.address and width == 32:
                observed = "exact_32bit_read"
                break
            if width == 64 and address <= register.address < address + 8:
                observed = "covered_by_64bit_read_only"
        row = {"name": register.name, "address": hex(register.address), "width": 32,
               "stage": stage, "prior_host_observation": observed,
               "status": "pending", "pending_utc": _now()}
        entry["reads"].append(row)
        _checkpoint(output_path, report)
        try:
            value = live.read(register.address, 32)
            if type(value) is not int or not 0 <= value <= 0xffffffff:
                raise ValueError("Transport returned an invalid 32-bit register value")
            row.update(status="complete", value=hex(value), completed_utc=_now())
            _checkpoint(output_path, report)
            if reject_all_ones and value == 0xffffffff:
                raise RuntimeError("Power register returned all ones")
            if expected is not None:
                mask, wanted = expected
                row["prerequisite"] = {"mask": hex(mask), "expected": hex(wanted),
                                       "matched": value & mask == wanted}
                _checkpoint(output_path, report)
                if not row["prerequisite"]["matched"]:
                    raise RuntimeError("Power/fence prerequisite changed at " + register.name)
            return value
        except Exception as error:
            # Preserve a successful read separately from a failed prerequisite.
            if row["status"] == "pending":
                row["status"] = "failed"
            row["error"] = str(error)
            entry.update(failure_stage=stage, failure_address=hex(register.address),
                         failure_register=register.name)
            raise

    def gx_guard(stage):
        read(GX_POWER, stage, (3, 0))
        read(AHB_FENCE, stage, (0xffffffff, 0))

    try:
        if not (cx_ready and gx_held):
            entry["failure_stage"] = "caller_prerequisites"
            raise ValueError("Confirmed CX/mappings and held acknowledged GX OOB are required")
        for register in POWER_REGISTERS:
            read(register, "platform_power", POWER_EXPECTED.get(register.address), True)
        gx_guard("watch_preconditions")
        for register in AO_REGISTERS:
            expected = ((3, 0) if register == GX_POWER else
                        (0xffffffff, 0) if register == AHB_FENCE else None)
            read(register, "snapshot_ao", expected)
        for register in GX_REGISTERS:
            gx_guard("snapshot_gx_guard")
            read(register, "snapshot_gx")
        entry["status"] = "complete"
        return entry
    except Exception as error:
        entry.update(status="failed", error=str(error))
        raise
    finally:
        entry["finished_utc"] = _now()
        _checkpoint(output_path, report)
