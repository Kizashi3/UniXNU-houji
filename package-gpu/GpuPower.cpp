// SPDX-License-Identifier: BSD-2-Clause-Patent
// NX769J Adreno 750 bring-up, staged and gated (boot-arg nx769j-gpu=<mode>, default 0 = off). A port of the first eight
// modes of UniXNU-sheng package/GpuPowerProbe.cpp (2d4b58b7, SM8550 / A740) to SM8650 / A750; Linux runs both GPUs
// through the same a740-family GMU and HFI code. Each stage runs only when the previous one showed its prerequisite,
// because reading a block whose clock or power domain is off can hang the bus instead of failing.
//
//   1  read GCC GPU branches, GPUCC GDSCs and branches, GPU SMMU global space 0 (and RBBM_STATUS only if GX is on)
//   2  + enable gcc_gpu_cfg_ahb_clk, the one write Linux's gcc-sm8650 probe makes
//   3  + gdsc.c enable of gpu_cc_cx_gdsc, gpu_cc_ahb_clk and gpu_cc_hlos1_vote_gpu_smmu_clk
//   4  + the GMU's own native-4K SMMU context (bank 1, ASID 1, SMR/S2CR slot 2, stream 5) with the a6xx_gmu.c payloads
//   5  + read the GMU clock tree; parse the AOP command DB into the HFI startup table (ACD and IFPC off)
//   6  + GMU clocks: GPLL0 GPU votes, gpucc PLL0/PLL1, hub 200 MHz, gmu 260 MHz, the GMU branches
//   7  + GMU cold start: RSC/PDC setup, gmu_gen70900.bin load and readback, CM3 release, firmware and HFI ready,
//        then the HFI startup messages
//   8  + HFI GX_BW_PERF_VOTE at the lowest OPP and OOB GPU_SET, which makes the GMU power GX; then RBBM_STATUS
//   9  + GpuCommand.cpp: the GPU's SMMU context, SQE, hw_init, ring, CP_INIT and one CP_MEM_WRITE with its fence
//  10  + GpuCommand.cpp: the zap shader through TrustZone and CP_SET_SECURE_MODE 0 (nx769j-gpu-zap=0 skips it)
//  11  + GpuPublish.cpp: the NativeAdrenoPublish user-client service and the IOAcceleratorES accelerator for Metal/Turnip
//
// It runs in a thread a few seconds after bsd_init. The lines are printed as they happen and again by the heartbeat
// (nx769j_gpu_report), so a photo shows the last stage reached.
#include <IOKit/IOLib.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <IOKit/IODeviceMemory.h>
#include <libkern/c++/OSSharedPtr.h>
#include <libkern/crypto/sha2.h>
#include <pexpert/pexpert.h>
#include <stdarg.h>
#include <string.h>

extern "C" {
#include "GpuPowerBoard.h"
#include "ShengGmu.h"
#include "ShengGmuCommandDb.h"
#include "ShengGmuVotes.h"
#include "AdrenoHfi.h"
kern_return_t kernel_thread_start(thread_continue_t continuation, void *parameter, thread_t *new_thread);
void thread_deallocate(thread_t thread);
uint64_t mach_absolute_time(void);
void absolutetime_to_nanoseconds(uint64_t abstime, uint64_t *result);
extern const uint8_t native_adreno_firmware_image[];
extern const uint64_t native_adreno_firmware_image_size;
void nx769j_gpu_start(void);
void nx769j_gpu_report(void);
}
#include "NativeAdrenoGmuContext.h"
#include "GpuBridge.h"

namespace {
constexpr unsigned kLines = 32, kWidth = 168, kMaxMode = 11;
char gLines[kLines][kWidth];
unsigned gCount, gMode;
unsigned gVerified;   // line index of the last mode 9 line once the GPU wrote memory; nx769j-quiet=1 prints from there
volatile unsigned gStage;   // last stage started, printed by the heartbeat

void line(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
void line(const char *fmt, ...)
{
	va_list ap;
	va_start(ap, fmt);
	char *out = gLines[gCount < kLines ? gCount : kLines - 1];
	vsnprintf(out, kWidth, fmt, ap);
	va_end(ap);
	if (gCount < kLines) {
		gCount++;
	}
	printf("NX769J GPU %s\n", out);
}

void stage(unsigned s)
{
	gStage = s;
	printf("NX769J GPU stage %x\n", s);
}

// ---- Stages 1-3: GCC, GPUCC, SMMU global space, through the gpb_io adapter ----
constexpr uint64_t kPhys[5] = {GPB_GCC_GPU_PAGE, GPB_GCC_VOTE_PAGE, GPB_GPUCC_BASE, GPB_SMMU_BASE, GPB_GPU_BASE};
constexpr uint64_t kLen[5] = {0x1000, 0x1000, GPB_GPUCC_SIZE, GPB_SMMU_GR0_SIZE, GPB_GPU_WINDOW};
OSSharedPtr<IOMemoryMap> gMaps[5];
uintptr_t gVa[5];

void delayUs(void *, unsigned us) { IODelay(us); }

int rd(void *, unsigned w, uint32_t off, uint32_t *out)
{
	if (w > 4 || !gVa[w] || off >= kLen[w] || (off & 3)) {
		return -1;
	}
	*out = *reinterpret_cast<volatile uint32_t *>(gVa[w] + off);
	return 0;
}

// Mode 6: the registers gpb_gmu_clocks_on names.
bool clockWrite(unsigned w, uint32_t off)
{
	if (w == GPB_WIN_GCC_VOTE) {
		return off == GPB_GCC_PLL_VOTE;
	}
	if (w == GPB_WIN_GCC_GPU) {
		return off == GPB_GCC_DDRSS_GPU_AXI || off == GPB_GCC_GPU_MEMNOC_GFX;
	}
	if (w != GPB_WIN_GPUCC) {
		return false;
	}
	return off < GPB_CC_PLL1 + 0x40 || off == GPB_CC_GMU_RCGR || off == GPB_CC_GMU_RCGR + 4 || off == GPB_CC_HUB_RCGR ||
	       off == GPB_CC_HUB_RCGR + 4 || off == GPB_CC_CXO_AON_CLK || off == GPB_CC_DEMET_CLK || off == GPB_CC_CX_GMU_CLK ||
	       off == GPB_CC_CXO_CLK || off == GPB_CC_HUB_CX_INT_CLK;
}

int wr(void *, unsigned w, uint32_t off, uint32_t value)
{
	const bool gcc = w == GPB_WIN_GCC_GPU && off == GPB_GCC_GPU_CFG_AHB;
	const bool cc = w == GPB_WIN_GPUCC && (off == GPB_CC_CX_GDSCR || off == GPB_CC_AHB_CLK || off == GPB_CC_SMMU_VOTE_CLK);
	if (w > 4 || !gVa[w] || off >= kLen[w] || (off & 3)) {
		return -1;
	}
	if (!((gcc && gMode >= 2) || (cc && gMode >= 3) || (gMode >= 6 && clockWrite(w, off)))) {
		return -1;
	}
	*reinterpret_cast<volatile uint32_t *>(gVa[w] + off) = value;
	__builtin_arm_dsb(0xf);
	return 0;
}

const gpb_io gIo = {nullptr, rd, wr, delayUs};
gpb_result gPower;

void powerStages()
{
	stage(0x10);
	unsigned have = 0;
	for (unsigned w = 0; w < 5; ++w) {
		IODeviceMemory *memory = IODeviceMemory::withRange(kPhys[w], kLen[w]);
		if (!memory) {
			continue;
		}
		gMaps[w] = OSSharedPtr<IOMemoryMap>(memory->map(kIOMapAnywhere | kIOMapInhibitCache), OSNoRetain);
		memory->release();
		if (gMaps[w]) {
			gVa[w] = static_cast<uintptr_t>(gMaps[w]->getVirtualAddress());
			have |= 1u << w;
		}
	}
	stage(0x11);
	gpb_run(&gIo, gMode, have, &gPower);
	const gpb_result &r = gPower;
	line("m%u map %02x gcc=%s cc=%s smmu=%s gpu=%s io=%d powered cx%u clk%u", r.mode, have, gpb_state_text(r.gcc),
	    gpb_state_text(r.cc), gpb_state_text(r.smmu), gpb_state_text(r.gpu), r.io_error, r.powered_cx, r.powered_clocks);
	line("gcc ahb %08x>%08x memnoc %08x dvm %08x pll %08x | cc cx %08x>%08x gx %08x ahb %08x smmuclk %08x gmu %08x",
	    r.cfg_ahb, r.cfg_ahb_after, r.memnoc, r.dvm, r.pll_vote, r.cx_before, r.cx_gdscr, r.gx_gdscr, r.cc_ahb, r.cc_smmu,
	    r.cc_gmu);
	line("smmu scr0 %08x id0 %08x id1 %08x id2 %08x gfsr %08x smr-valid %u | rbbm %08x", r.scr0, r.id0, r.id1, r.id2,
	    r.gfsr, r.smr_valid, r.rbbm_status);
}

// ---- Stage 4: the GMU's SMMU context ----
constexpr unsigned kGmuBank = 1, kGmuAsid = 1, kGmuSlot = 2, kGmuSid = 5;   // gmu iommus <&adreno_smmu 5 0x0>
constexpr uint64_t kSmmuWindow = 0x40000;
OSSharedPtr<IOMemoryMap> gSmmuMap;
NativeAdrenoGmuContextReport gContext;

void contextProgress(uint32_t s) { stage(0x40 + s); }

bool gmuContext()
{
	const gpb_result &r = gPower;
	if (r.smmu != GPB_DONE || r.io_error || !gpb_gdsc_on(r.cx_gdscr) || r.smr_valid) {
		line("gmu context: skipped (smmu %s cx %u smr-valid %u)", gpb_state_text(r.smmu), gpb_gdsc_on(r.cx_gdscr),
		    r.smr_valid);
		return false;
	}
	IODeviceMemory *memory = IODeviceMemory::withRange(GPB_SMMU_BASE, kSmmuWindow);
	if (memory) {
		gSmmuMap = OSSharedPtr<IOMemoryMap>(memory->map(kIOMapAnywhere | kIOMapInhibitCache), OSNoRetain);
		memory->release();
	}
	if (!gSmmuMap) {
		line("gmu context: smmu window not mapped");
		return false;
	}
	NativeAdrenoGmuContextReport &g = gContext;
	const IOReturn status = NativeAdrenoGmuContextBringup(reinterpret_cast<volatile uint8_t *>(gSmmuMap->getVirtualAddress()),
	    kSmmuWindow, kGmuBank, kGmuAsid, kGmuSlot, kGmuSid, contextProgress, &g);
	line("gmu context: step %u status %x program %u/%u id2 %x phase %u writes %u readback %u enabled %u route %u/%u verified %u "
	    "spans %u mismatch %x", g.step, static_cast<unsigned>(status), g.program_status, g.route_status, g.id2,
	    g.program_phase, g.program_writes, g.program_readback_valid, g.program_enabled, g.route_phase, g.route_writes,
	    g.routes_verified, g.spans, g.mismatch);
	line("gmu context: ttbr0 %016llx sctlr %08x s2cr %08x smr %08x cbar %08x", static_cast<unsigned long long>(g.ttbr0),
	    g.sctlr, g.s2cr, g.smr, g.cbar);
	return !status && g.step == NativeAdrenoGmuContext::Ready;
}

// ---- Stages 5-6: GMU clocks, command DB ----
constexpr uint64_t kCmdDbBase = 0x81c60000, kCmdDbBytes = 0x20000;
uint8_t *gCmdDb;
ShengGmuVoteInputs gVoteInputs;
AdrenoHfiStartupConfig gStartup;
OSSharedPtr<IOMemoryMap> gCmdDbMap;
gpb_gmu_clocks gClocks;
gpb_gmu_clock_on gClockOn;

volatile uint32_t *mapWords(uint64_t phys, uint64_t len, OSSharedPtr<IOMemoryMap> &keep, bool readOnly)
{
	IODeviceMemory *memory = IODeviceMemory::withRange(phys, len);
	if (!memory) {
		return nullptr;
	}
	keep = OSSharedPtr<IOMemoryMap>(memory->map(kIOMapAnywhere | kIOMapInhibitCache | (readOnly ? kIOMapReadOnly : 0)),
	    OSNoRetain);
	memory->release();
	return keep ? reinterpret_cast<volatile uint32_t *>(keep->getVirtualAddress()) : nullptr;
}

void clockLine(const char *tag, const gpb_gmu_clocks &k)
{
	line("%s: pll1 %08x/%x l %08x gmu-rcg %x/%03x hub-rcg %x/%03x branches cxgmu%x cxo%x hub%x demet%x axi%x memnoc%x gpll0 %x",
	    tag, k.pll1_mode, k.pll1_opmode, k.pll1_l, k.gmu_cmd >> 31, k.gmu_cfg & 0x7ff, k.hub_cmd >> 31, k.hub_cfg & 0x7ff,
	    gpb_branch_digit(k.cx_gmu), gpb_branch_digit(k.cxo), gpb_branch_digit(k.hub_cx_int), gpb_branch_digit(k.demet),
	    gpb_branch_digit(k.axi), gpb_branch_digit(k.memnoc), (k.gpll0_vote >> 15) & 3);
}

// Returns true when the GMU clocks run and the startup table was built.
bool gmuPrerequisites(unsigned &parse, unsigned &build)
{
	gpb_result scratch = gPower;
	stage(0x51);
	gpb_read_gmu_clocks(&gIo, &scratch, &gClocks);
	clockLine("clocks", gClocks);
	if (gMode >= 6 && gClocks.done) {
		stage(0x61);
		gpb_gmu_clocks_on(&gIo, &scratch, &gClocks, &gClockOn);
		const gpb_gmu_clock_on &o = gClockOn;
		line("clocks on: step %u failed %u lock-polls %u rcg-polls %u/%u pll1 %08x/%x hub %03x gmu %03x", o.step, o.failed,
		    o.lock_polls, o.hub_polls, o.gmu_polls, o.pll1_mode, o.pll1_opmode, o.hub_cfg & 0x7ff, o.gmu_cfg & 0x7ff);
		gpb_gmu_clocks after;
		gpb_read_gmu_clocks(&gIo, &scratch, &after);
		clockLine("clocks after", after);
		gClocks.cx_gmu = after.cx_gmu;
	}
	stage(0x52);
	parse = 9;
	build = 9;
	uint32_t version = 0, magic = 0;
	if (!gCmdDb) {
		gCmdDb = static_cast<uint8_t *>(IOMallocData(kCmdDbBytes));
	}
	volatile uint32_t *db = gCmdDb ? mapWords(kCmdDbBase, kCmdDbBytes, gCmdDbMap, true) : nullptr;
	if (db) {
		for (uint64_t i = 0; i < kCmdDbBytes / 4; ++i) {
			const uint32_t w = db[i];
			memcpy(gCmdDb + 4 * i, &w, 4);
		}
		memcpy(&version, gCmdDb, 4);
		memcpy(&magic, gCmdDb + 4, 4);
		gVoteInputs = {};
		gVoteInputs.chip_id = 0x43051401;
		parse = ShengGmuCommandDbInputs(gCmdDb, kCmdDbBytes, version, &gVoteInputs);
		if (parse == ShengGmuDbSuccess) {
			build = ShengGmuBuildStartup(&gVoteInputs, &gStartup);
		}
	}
	line("cmd-db: version %x magic %08x parse %u build %u gmxc %u", version, magic, parse, build, gVoteInputs.gmxc_present);
	return gClockOn.step == 7 && !gClockOn.failed && parse == ShengGmuDbSuccess && build == AdrenoHfiStartupSuccess;
}

// ---- Stage 7: GMU cold start ----
constexpr uint64_t kColdPhys[5] = {0x03d6a000, 0x03d50000, 0x0b280000, 0x03d00000, 0x03d9e000};
constexpr uint64_t kColdLen[5] = {0x35000, 0x10000, 0x10000, 0x40000, 0x2000};
constexpr uint32_t kGmuReg(uint32_t dword) { return dword * 4 - 0x6a000; }
constexpr uint32_t kGmuSysReset = kGmuReg(0x1f800), kGmuHfiStatus = kGmuReg(0x1f980);
constexpr uint32_t kRsccSeqBusy = 0x101 * 4, kCxMiscTcmRet = 0x39 * 4;
constexpr uint32_t kAoIrqClr = kGmuReg(0x23b04), kAoIrqMask = kGmuReg(0x23b06);
constexpr uint32_t kAoFatal = (1u << 0) | (1u << 3) | (1u << 5);   // WDOG_BITE, FENCE_ERR, HOST_AHB_BUS_ERROR
OSSharedPtr<IOMemoryMap> gColdMaps[5], gPayloadMaps[5];
ShengGmuMmio gColdMmio;
ShengGmuDevice gColdDevice;
ShengGmuConfig gColdConfig;
ShengGmuStartupResult gColdResult;

int coldSha256(void *, const void *data, size_t bytes, uint8_t digest[32])
{
	if (!data || !bytes || !digest) {
		return 1;
	}
	SHA256_CTX ctx;
	SHA256_Init(&ctx);
	SHA256_Update(&ctx, data, bytes);
	SHA256_Final(digest, &ctx);
	return 0;
}

int coldNow(void *, uint64_t *us)
{
	uint64_t ns = 0;
	absolutetime_to_nanoseconds(mach_absolute_time(), &ns);
	*us = ns / 1000;
	return 0;
}

int coldWait(void *, unsigned us)
{
	IODelay(us);
	return 0;
}

void gmuState(uint32_t out[4])
{
	volatile uint8_t *core = gColdMmio.windows[0].cpu, *rscc = gColdMmio.windows[1].cpu, *misc = gColdMmio.windows[4].cpu;
	out[0] = *reinterpret_cast<volatile uint32_t *>(core + kGmuSysReset);
	out[1] = *reinterpret_cast<volatile uint32_t *>(misc + kCxMiscTcmRet);
	out[2] = *reinterpret_cast<volatile uint32_t *>(rscc + kRsccSeqBusy);
	out[3] = *reinterpret_cast<volatile uint32_t *>(core + kGmuHfiStatus);
}

bool gmuColdStart()
{
	stage(0x71);
	for (unsigned w = 0; w < 5; ++w) {
		IODeviceMemory *memory = IODeviceMemory::withRange(kColdPhys[w], kColdLen[w]);
		if (memory) {
			gColdMaps[w] = OSSharedPtr<IOMemoryMap>(memory->map(kIOMapAnywhere | kIOMapInhibitCache), OSNoRetain);
			memory->release();
		}
		if (!gColdMaps[w]) {
			line("cold start: window %u not mapped", w);
			return false;
		}
		gColdMmio.windows[w] = {reinterpret_cast<volatile unsigned char *>(gColdMaps[w]->getVirtualAddress()), kColdPhys[w],
		                        kColdLen[w]};
	}
	NativeAdrenoGmuPayload payloads[5];
	const IOReturn got = NativeAdrenoGmuContextPayloads(payloads);
	if (got) {
		line("cold start: payloads %x", static_cast<unsigned>(got));
		return false;
	}
	ShengGmuMemory *memory[5] = {&gColdConfig.icache, &gColdConfig.dummy, &gColdConfig.debug, &gColdConfig.log, &gColdConfig.hfi};
	for (unsigned i = 0; i < 5; ++i) {
		IODeviceMemory *m = IODeviceMemory::withRange(payloads[i].physical, payloads[i].bytes);
		if (m) {
			gPayloadMaps[i] = OSSharedPtr<IOMemoryMap>(m->map(kIOMapAnywhere | kIOMapWriteCombineCache), OSNoRetain);
			m->release();
		}
		if (!gPayloadMaps[i]) {
			line("cold start: payload %u not mapped", i);
			return false;
		}
		*memory[i] = {reinterpret_cast<volatile uint32_t *>(gPayloadMaps[i]->getVirtualAddress()), payloads[i].bytes,
		              payloads[i].iova};
	}
	ShengGmuDevice &d = gColdDevice;
	d = {};
	if (ShengGmuBindMmio(&gColdMmio, &d.io)) {
		line("cold start: window binding refused");
		return false;
	}
	d.services = {nullptr, coldSha256, coldNow, coldWait};
	gColdConfig.chip_id = 0x43051401;
	gColdConfig.firmware = native_adreno_firmware_image;
	gColdConfig.firmware_bytes = static_cast<size_t>(native_adreno_firmware_image_size);
	gColdConfig.poll_budget = 200;
	// a6xx_gmu_resume, before a6xx_gmu_fw_start: clear every AO interrupt and unmask only the fatal ones.
	d.io.write32(d.io.cookie, ShengGmuCore, kAoIrqClr, ~0u);
	d.io.write32(d.io.cookie, ShengGmuCore, kAoIrqMask, ~kAoFatal);
	d.io.barrier(d.io.cookie);
	uint32_t before[4], after[4];
	gmuState(before);
	if (before[0] != 1 || before[1] || before[2] || before[3]) {
		line("cold start: GMU not in reset and idle (sysreset %x tcm-ret %x rsc-busy %x hfi %x)", before[0], before[1],
		    before[2], before[3]);
		return false;
	}
	const ShengGmuStartupLimits limits = {1000, 100, 50000, 2000000};
	stage(0x72);
	const ShengGmuStatus status = ShengGmuColdStart(&d, &gColdConfig, &gStartup, &limits, &gColdResult);
	gmuState(after);
	const ShengGmuResult &l = gColdResult.load;
	const AdrenoHfiStartupResult &p = gColdResult.protocol;
	line("cold start: status %u phase %u hash %u fw-init %x hfi %x ready fw%u hfi%u ao-fault %x cm3 %x reset %u | "
	    "gmu %x/%x/%x/%x > %x/%x/%x/%x", status, l.phase, l.complete_hash_verified, l.firmware_init_result, l.hfi_status,
	    l.firmware_ready_observed, l.hfi_ready_observed, l.ao_fault_status, l.cm3_fault_status, l.reset_verified, before[0],
	    before[1], before[2], before[3], after[0], after[1], after[2], after[3]);
	const AdrenoHfi &q = gColdDevice.hfi;
	line("hfi: protocol %u stage %u acked %x fw-error %x transport %u commands %u %llu ms skipped %u (%x/%x)",
	    gColdResult.protocol_status, p.stage, p.acknowledged_stages, p.firmware_error, p.transport_status,
	    p.published_commands, static_cast<unsigned long long>(p.elapsed_us / 1000), q.skipped, q.skipped_header,
	    q.skipped_ret);
	return status == ShengGmuSuccess;
}

// ---- Stage 8: GX on ----
constexpr uint32_t kG2hClr = kGmuReg(0x1f991), kG2hInfo = kGmuReg(0x1f992), kG2hMask = kGmuReg(0x1f993);
constexpr uint32_t kH2gSet = kGmuReg(0x1f994), kGxStatus = kGmuReg(0x1f8d0);   // GMU_SPTPRAC_PWR_CLK_STATUS (A7XX)
constexpr uint32_t kRbbmStatus = 0x0210 * 4, kGbifHalt = 0x3c45 * 4;

int hfiWait(void *)
{
	IODelay(100);
	return 0;
}

bool gpuOn()
{
	ShengGmuIo &io = gColdDevice.io;
	auto rd32 = [&](unsigned w, uint32_t at) {
		uint32_t v = 0xdeadbeef;
		io.read32(io.cookie, w, at, &v);
		return v;
	};
	stage(0x81);
	io.write32(io.cookie, ShengGmuCore, kG2hClr, ~0u);
	io.write32(io.cookie, ShengGmuCore, kG2hMask, ~(1u << 23));   // only CM3_FAULT
	io.barrier(io.cookie);
	const uint32_t gxBefore = rd32(ShengGmuCore, kGxStatus);
	unsigned bw = 1;
	const unsigned perf = ShengGmuPerfVote(1, &bw);
	const uint32_t vote[3] = {1, perf, bw};
	uint32_t out[16], error = 0;
	size_t count = 0;
	const unsigned voted = AdrenoHfiExchange(&gColdDevice.hfi, 30, vote, 3, 1000, hfiWait, out, 16, &count, &error);
	unsigned polls = 0;
	stage(0x82);
	if (!voted) {
		io.write32(io.cookie, ShengGmuCore, kH2gSet, 1u << 30);   // OOB GPU_SET request
		io.barrier(io.cookie);
		for (polls = 1; polls <= 100; ++polls) {
			if (rd32(ShengGmuCore, kG2hInfo) & (1u << 31)) {
				break;
			}
			IODelay(100);
		}
		io.write32(io.cookie, ShengGmuCore, kG2hClr, 1u << 31);
		io.barrier(io.cookie);
	}
	const uint32_t gxAfter = rd32(ShengGmuCore, kGxStatus);
	const uint32_t gdscr = gVa[GPB_WIN_GPUCC] ? *reinterpret_cast<volatile uint32_t *>(gVa[GPB_WIN_GPUCC] + GPB_CC_GX_GDSCR) : 0;
	const bool gx = polls && polls <= 100 && !(gxAfter & 3);   // a7xx_gmu_gx_is_on: GDSC power-off and clock-off bits clear
	stage(0x83);
	if (gx) {
		line("GX ON: vote %u/%x perf %u bw %u oob-polls %u gx %x>%x gx-gdscr %08x RBBM_STATUS %08x GBIF_HALT %x", voted, error,
		    perf, bw, polls, gxBefore, gxAfter, gdscr, rd32(ShengGmuGpu, kRbbmStatus), rd32(ShengGmuGpu, kGbifHalt));
	} else {
		line("GX off: vote %u/%x perf %u bw %u oob-polls %u gx %x>%x gx-gdscr %08x", voted, error, perf, bw, polls, gxBefore,
		    gxAfter, gdscr);
	}
	return gx;
}

void worker(void *, wait_result_t)
{
	IOSleep(8000);
	powerStages();
	if (gMode < 4 || !gmuContext() || gMode < 5) {
		stage(0xf4);
		return;
	}
	unsigned parse = 9, build = 9;
	const bool ready = gmuPrerequisites(parse, build);
	if (gMode < 7) {
		stage(0xf6);
		return;
	}
	if (!ready) {
		line("cold start: skipped (clocks step %u failed %u, cmd-db parse %u build %u)", gClockOn.step, gClockOn.failed, parse,
		    build);
		stage(0xf7);
		return;
	}
	if (!gmuColdStart() || gMode < 8) {
		stage(0xf7);
		return;
	}
	if (!gpuOn() || gMode < 9) {
		stage(0xf8);
		return;
	}
	unsigned zap = 1;
	PE_parse_boot_argn("nx769j-gpu-zap", &zap, sizeof(zap));
	const bool started = nx769j_gpu::commandStart(gMode >= 10 && zap);
	if (!started || gMode < 11) {
		stage(started ? 0xfa : 0xf9);
		return;
	}
	stage(nx769j_gpu::publish() ? 0xfc : 0xfb);
}
} // namespace

// Accessors for GpuCommand.cpp, valid after a successful cold start (stage 7).
namespace nx769j_gpu {
void report(const char *text) { line("%s", text); }
void markVerified() { gVerified = gCount ? gCount : 1; }
void progress(unsigned s) { stage(s); }
int gpuRead32(void *, uint32_t dword, uint32_t *value)
{
	return gColdDevice.io.read32(gColdDevice.io.cookie, ShengGmuGpu, size_t(dword) * 4, value);
}
int gpuWrite32(void *, uint32_t dword, uint32_t value)
{
	return gColdDevice.io.write32(gColdDevice.io.cookie, ShengGmuGpu, size_t(dword) * 4, value);
}
uint32_t gpuRead(uint32_t dword)
{
	uint32_t v = 0xdeadbeef;
	gpuRead32(nullptr, dword, &v);
	return v;
}
void gpuWrite(uint32_t dword, uint32_t value) { gpuWrite32(nullptr, dword, value); }
void gmuWrite(uint32_t gpuDword, uint32_t value)
{
	gColdDevice.io.write32(gColdDevice.io.cookie, ShengGmuCore, kGmuReg(gpuDword), value);
}
volatile uint8_t *smmu() { return gSmmuMap ? reinterpret_cast<volatile uint8_t *>(gSmmuMap->getVirtualAddress()) : nullptr; }
size_t smmuBytes() { return kSmmuWindow; }
uint64_t nowUs()
{
	uint64_t us = 0;
	coldNow(nullptr, &us);
	return us;
}
} // namespace nx769j_gpu

void
nx769j_gpu_start(void)
{
	gMode = 0;
	PE_parse_boot_argn("nx769j-gpu", &gMode, sizeof(gMode));
	if (!gMode) {
		return;
	}
	if (gMode > kMaxMode) {
		gMode = kMaxMode;
	}
	thread_t thread;
	if (kernel_thread_start(worker, nullptr, &thread) == KERN_SUCCESS) {
		thread_deallocate(thread);
	}
}

void
nx769j_gpu_report(void)
{
	if (!gMode) {
		return;
	}
	// nx769j-quiet=1: once mode 9 has completed (verified on the device), repeat only its last line and what follows.
	static int quiet = -1;
	if (quiet < 0) {
		quiet = 0;
		PE_parse_boot_argn("nx769j-quiet", &quiet, sizeof(quiet));
	}
	printf("NX769J GPU mode %u stage %x\n", gMode, gStage);
	if (gStage == 0xfc) {
		nx769j_gpu::publishReport();
		nx769j_gpu::execReport();
	}
	for (unsigned i = quiet && gVerified ? gVerified - 1 : 0; i < gCount; i++) {
		printf("NX769J GPU %s\n", gLines[i]);
	}
}
