// SPDX-License-Identifier: BSD-2-Clause-Patent
// NX769J Adreno 750 command processor start (nx769j-gpu=9) and zap shader (nx769j-gpu=10), after GpuPower.cpp left the GMU
// running and GX on. Ported from UniXNU-sheng package/GpuPowerProbe.cpp gpuStart / gpuHwInit / zapAndSecure (2d4b58b7,
// SM8550 / A740), with the A750 branches of Linux v6.16 a6xx_gpu.c hw_init:
//   - no hwcg table: a6xx_set_hwcg takes the global clock-gating path (RBBM_CLOCK_CNTL_GLOBAL, CGC_GLOBAL_LOAD_CMD,
//     CGC_P2S_TRIG_CMD, wait CGC_P2S_STATUS.TXDONE, CLOCK_CNTL_GLOBAL 0) after the GMU CGC mode/delay/hysteresis writes
//   - RB_CMP_DBG_ECO_CNTL bit 19 (bit 11 is the a7xx default) and TPL1_DBG_ECO_CNTL1 0xc0700
// UBWC (a6xx_calc_ubwc_config, a740 family), CP protect (a730_protect), APRIV and the A7XX interrupt mask equal A740's.
//
// Steps, each reported as a line: GPU context (bank 0, ASID 2, SMR 0/1 for streams 0/1), SQE copy without its first dword,
// hw_init, ring 0 and the power-up list, CP_INIT with a fence, then CP_MEM_WRITE of a known word into the scratch page with a
// second fence. Interrupts are not attached: completion is polled.
#include <IOKit/IOLib.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <IOKit/IODeviceMemory.h>
#include <pexpert/pexpert.h>
#include <libkern/c++/OSSharedPtr.h>
#include <stdarg.h>

extern "C" {
#include "AdrenoPM4.h"
extern const uint8_t native_adreno_sqe_firmware_image[];
extern const uint64_t native_adreno_sqe_firmware_image_size;
extern const uint8_t native_adreno_zap_image[];
extern const uint64_t native_adreno_zap_image_size;
}
#include "NativeAdrenoGmuContext.h"
#include "NativeAdrenoGpuContext.h"
#include "NativeAdrenoRing.h"
#include "NativeAdrenoCpInit.h"
#include "NativeAdrenoPwrup.h"
#include "NativeAdrenoMemory.h"
#include "NativeAdrenoA740HwInit.h"
#include "GpuBridge.h"

namespace nx769j_gpu {
namespace {
// a6xx.xml (Linux v6.16), A7XX-only registers the A750 path uses beyond NativeAdrenoA740HwInit.h.
constexpr uint32_t kRbbmClockCntlGlobal = 0x000ad, kRbbmCgcGlobalLoadCmd = 0x0011e, kRbbmCgcP2sTrigCmd = 0x0011f;
constexpr uint32_t kRbbmCgcP2sStatus = 0x00122, kTpl1DbgEcoCntl1 = 0x0b602;
constexpr uint32_t kGmuCgcMode = 0x00020202;   // a6xx_catalog.c A750 gmu_cgc_mode

void say(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
void say(const char *fmt, ...)
{
	char text[168];
	va_list ap;
	va_start(ap, fmt);
	vsnprintf(text, sizeof(text), fmt, ap);
	va_end(ap);
	report(text);
}

NativeAdrenoGmuContextReport gContext;
NativeAdrenoGpuBuffer gBuffers[GpuBufferCount];
OSSharedPtr<IOMemoryMap> gMaps[GpuBufferCount];
volatile uint8_t *gCpu[GpuBufferCount];
NativeAdrenoRing gRing;
NativeAdrenoCpInit gCpInit;

void contextProgress(uint32_t s) { progress(0x90 + s); }

// Context bank 0 base in the SMMU window: banks follow 2^(NUMPAGENDXB+1) global pages.
size_t bank0()
{
	const uint32_t id1 = gContext.id1;
	if (!id1) {
		return 0;
	}
	const size_t page = (id1 >> 31) ? 0x10000 : 0x1000;
	const size_t base = page << (((id1 >> 28) & 7) + 1);
	return base + 0x800 <= smmuBytes() ? base : 0;
}

uint32_t fsr()
{
	const size_t b = bank0();
	return b ? *reinterpret_cast<volatile uint32_t *>(smmu() + b + 0x58) : 0xdead;
}

// MMU-500 ACTLR of the GPU bank: CMTLB | PREFETCH_DEEP with CPRE off (Linux arm_mmu500_reset clears CPRE in every bank), then a
// full TLB invalidate (TLBIALL +0x618, TLBSYNC +0x7f0, TLBSTATUS +0x7f4).
void setActlr()
{
	const size_t b = bank0();
	if (!b) {
		return;
	}
	volatile uint32_t *base = reinterpret_cast<volatile uint32_t *>(smmu());
	base[(b + 0x4) / 4] = 0x301;
	__builtin_arm_dsb(0xf);
	base[(b + 0x618) / 4] = 0;
	base[(b + 0x7f0) / 4] = 0;
	for (unsigned i = 0; i < 1000 && (base[(b + 0x7f4) / 4] & 1); ++i) {
		IODelay(1);
	}
}

void wr64(uint32_t reg, uint64_t value)
{
	gpuWrite(reg, uint32_t(value));
	gpuWrite(reg + 1, uint32_t(value >> 32));
}

// a6xx_set_hwcg(gpu, true) for a GPU without a hwcg table (A750).
bool setHwcg(uint32_t *polls)
{
	gmuWrite(A740_GPU_GMU_AO_GMU_CGC_MODE_CNTL, kGmuCgcMode);
	gmuWrite(A740_GPU_GMU_AO_GMU_CGC_DELAY_CNTL, 0x10111);
	gmuWrite(A740_GPU_GMU_AO_GMU_CGC_HYST_CNTL, 0x5555);
	gpuWrite(kRbbmClockCntlGlobal, 1);
	gpuWrite(kRbbmCgcGlobalLoadCmd, 1);
	gpuWrite(kRbbmCgcP2sTrigCmd, 1);
	bool done = false;
	for (*polls = 1; *polls <= 10 && !done; ++*polls) {
		done = gpuRead(kRbbmCgcP2sStatus) & 1;   // TXDONE
		if (!done) {
			IODelay(1);
		}
	}
	gpuWrite(kRbbmClockCntlGlobal, 0);
	return done;
}

// hw_init (a6xx_gpu.c v6.16), A750 branches, up to CP_SQE_INSTR_BASE; OOB GPU_SET is held by GpuPower.cpp.
bool hwInit()
{
	gpuWrite(A740_GBIF_HALT, 0);
	(void)gpuRead(A740_GBIF_HALT);
	gpuWrite(A740_RBBM_GBIF_HALT, 0);
	(void)gpuRead(A740_RBBM_GBIF_HALT);
	gpuWrite(A740_RBBM_SECVID_TSB_CNTL, 0);
	wr64(A740_RBBM_SECVID_TSB_TRUSTED_BASE, 0);
	gpuWrite(A740_RBBM_SECVID_TSB_TRUSTED_SIZE, 0);
	uint32_t polls = 0;
	// nx769j-gpu-nocgc=1 leaves clock gating at the reset default (every unit clocked): a bring-up A/B test for whether the
	// A750 global clock-gating config is starving a unit (graphics hangs at the CCU cache-flush event while compute is fine).
	unsigned nocgc = 0;
	PE_parse_boot_argn("nx769j-gpu-nocgc", &nocgc, sizeof(nocgc));
	const bool cgc = nocgc ? true : setHwcg(&polls);
	gpuWrite(A740_RBBM_GBIF_CLIENT_QOS_CNTL, 0x2120212);
	gpuWrite(A740_UCHE_GBIF_GX_CONFIG, 0x10240e0);
	gpuWrite(A740_RBBM_PERFCTR_GPU_BUSY_MASKED, 0xffffffff);
	wr64(A740_UCHE_TRAP_BASE, 0x1fffffffff000ull);
	wr64(A740_UCHE_WRITE_THRU_BASE, 0x1fffffffff000ull);
	wr64(A740_UCHE_GMEM_RANGE_MIN, 0x1000000);                    // a740 family: SZ_16M
	wr64(A740_UCHE_GMEM_RANGE_MAX, 0x1000000 + 3 * 0x100000 - 1);  // A750 gmem 3 MiB
	gpuWrite(A740_UCHE_CACHE_WAYS, 1u << 23);
	gpuWrite(A740_CP_AHB_CNTL, 0x1);
	gpuWrite(A740_RBBM_PERFCTR_CNTL, 0x1);
	gpuWrite(A740_RBBM_INTERFACE_HANG_INT_CNTL, (1u << 30) | 0xcfffff);
	gpuWrite(A740_UCHE_CLIENT_PF, (1u << 7) | 0x1);
	gpuWrite(A740_CP_PROTECT_CNTL, (1u << 0) | (1u << 1) | (1u << 3));
	for (unsigned i = 0; i < NATIVE_ADRENO_A740_PROTECT_COUNT; ++i) {
		gpuWrite(A740_CP_PROTECT + NativeAdrenoA740Protect[i][0], NativeAdrenoA740Protect[i][1]);
	}
	gpuWrite(A740_UCHE_CMDQ_CONFIG, (6u << 16) | (6u << 12) | (9u << 8) | (1u << 3) | (1u << 2) | 2u);
	gpuWrite(A740_CP_APRIV_CNTL, 0x6f);
	gpuWrite(A740_CP_BV_APRIV_CNTL, 0x0f);
	gpuWrite(A740_CP_LPAC_APRIV_CNTL, 0x0f);
	// A750: disable UBWC merged UFC requests, TP flag hint and performance settings.
	gpuWrite(A740_RB_CMP_DBG_ECO_CNTL, gpuRead(A740_RB_CMP_DBG_ECO_CNTL) | (1u << 19));
	gpuWrite(kTpl1DbgEcoCntl1, 0xc0700);
	// a6xx_set_ubwc_config, a740 family: UBWC 4.0, hbb 16, AMSBC, rgb565 predicator, uavflagprd_inv 2, macrotile.
	gpuWrite(A740_RB_NC_MODE_CNTL, (1u << 11) | (1u << 4) | (3u << 1));
	gpuWrite(A740_TPL1_NC_MODE_CNTL, 3u << 1);
	gpuWrite(A740_SP_NC_MODE_CNTL, (2u << 4) | (3u << 1));
	for (uint32_t pipe = 1; pipe <= 2; ++pipe) {   // PIPE_BR, PIPE_BV
		gpuWrite(A740_CP_APERTURE_CNTL_HOST, pipe << 12);
		gpuWrite(A740_GRAS_NC_MODE_CNTL, 3u << 5);
	}
	gpuWrite(A740_CP_APERTURE_CNTL_HOST, 0);
	gpuWrite(A740_UCHE_MODE_CNTL, 3u << 21);
	gpuWrite(A740_RBBM_NC_MODE_CNTL, 1);
	gpuWrite(A740_RBBM_INT_0_MASK, 0x33d283c2);   // A7XX_INT_MASK; polled, not attached
	wr64(A740_CP_SQE_INSTR_BASE, gBuffers[0].iova);
	say("hw init: cgc %s (%u polls) clock-cntl %08x eco %08x status %08x", cgc ? "txdone" : "TIMEOUT", polls,
	    gpuRead(A740_RBBM_CLOCK_CNTL), gpuRead(A740_RB_CMP_DBG_ECO_CNTL), gpuRead(A740_RBBM_STATUS));
	return cgc;
}

int ringBarrier(void *)
{
	__builtin_arm_dsb(0xf);
	return 0;
}
// Ring, memptrs and lists are Normal non-cacheable on both sides (GPU MAIR 0, CPU write-combine): ordering only.
int ringPublish(void *, const volatile uint32_t *, size_t)
{
	__builtin_arm_dsb(0xf);
	return 0;
}
int ringAcquire(void *, volatile uint32_t *, size_t)
{
	__builtin_arm_dsb(0xf);
	return 0;
}
uint64_t ringNow(void *) { return nowUs(); }
int ringIdle(void *)
{
	IODelay(20);
	return 0;
}

void cpLine(const char *what, uint32_t step)
{
	const volatile uint32_t *mem = reinterpret_cast<const volatile uint32_t *>(gCpu[2]);
	say("cp %u %s: RBBM_STATUS %08x INT %08x HW_FAULT %x rptr/wptr %x/%x shadow %x fence %x smmu-fsr %x", step, what,
	    gpuRead(A740_RBBM_STATUS), gpuRead(A740_RBBM_INT_0_STATUS), gpuRead(A740_CP_HW_FAULT), gpuRead(A740_CP_RB_RPTR),
	    gpuRead(A740_CP_RB_WPTR), mem ? mem[0] : 0, mem ? mem[1] : 0, fsr());
}

// ---- zap shader (mode 10): qcom_mdt_load + qcom_scm PAS calls, then CP_SET_SECURE_MODE 0 ----
struct ScmRes {
	int64_t a0;
	uint64_t a1;
};
// SIP SMC (qcom_scm-smc.c): x0 function, x1 arginfo, x2.. arguments. INTERRUPTED (1) resumes with x0 = 1 and the returned x6;
// V2_EBUSY (-12) retries after 30 ms, at most 20 times.
ScmRes scmCall(uint64_t fn, uint64_t arginfo, uint64_t p0, uint64_t p1, uint64_t p2)
{
	uint64_t first = fn, a6 = 0;
	for (unsigned resume = 0, busy = 0; resume < 10000;) {
		register uint64_t x0 asm("x0") = first, x1 asm("x1") = arginfo, x2 asm("x2") = p0, x3 asm("x3") = p1;
		register uint64_t x4 asm("x4") = p2, x5 asm("x5") = 0, x6 asm("x6") = a6, x7 asm("x7") = 0;
		asm volatile("smc #0" : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3), "+r"(x4), "+r"(x5), "+r"(x6), "+r"(x7)
		             :: "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17", "memory");
		if (x0 == 1) {
			first = 1;
			a6 = x6;
			++resume;
			continue;
		}
		if (int64_t(x0) == -12 && busy++ < 20) {
			first = fn;
			a6 = 0;
			IOSleep(30);
			continue;
		}
		return {int64_t(x0), x1};
	}
	return {-1000, 0};
}
constexpr uint64_t kScmPil(uint32_t cmd) { return 0x42000000u | (0x02u << 8) | cmd; }
constexpr uint32_t kGpuPasId = 13;                                // a6xx_gpu.h GPU_PAS_ID
constexpr uint64_t kZapPhys = 0x9b09a000, kZapBytes = 0x2000;     // vendor gpu_microcode_region@9b09a000
NativeAdrenoMemory gZapMetadata;
uint32_t rd32le(const uint8_t *p) { return uint32_t(p[0]) | uint32_t(p[1]) << 8 | uint32_t(p[2]) << 16 | uint32_t(p[3]) << 24; }
uint16_t rd16le(const uint8_t *p) { return uint16_t(p[0] | p[1] << 8); }

bool zapAndSecure()
{
	const uint8_t *fw = native_adreno_zap_image;
	const uint64_t size = native_adreno_zap_image_size;
	if (size < 52 || fw[0] != 0x7f || fw[1] != 'E' || fw[2] != 'L' || fw[3] != 'F' || fw[4] != 1) {
		say("zap: not an ELF32 image");
		return false;
	}
	const uint32_t phoff = rd32le(fw + 28);
	const unsigned phent = rd16le(fw + 42), phnum = rd16le(fw + 44);
	if (phent != 32 || phnum < 2 || phnum > 16 || phoff + uint64_t(phnum) * 32 > size) {
		say("zap: bad program headers");
		return false;
	}
	auto ph = [&](unsigned i, unsigned field) { return rd32le(fw + phoff + i * 32 + field * 4); };   // type off va pa filesz memsz flags
	unsigned hash = 0;
	for (unsigned i = 1; i < phnum && !hash; ++i) {
		if (((ph(i, 6) >> 24) & 7) == 2) {
			hash = i;
		}
	}
	uint64_t lo = ~0ull, hi = 0;
	bool relocate = false;
	for (unsigned i = 0; i < phnum; ++i) {
		if (ph(i, 0) != 1 || ((ph(i, 6) >> 24) & 7) == 2 || !ph(i, 5)) {
			continue;
		}
		relocate |= (ph(i, 6) & (1u << 27)) != 0;
		lo = lo < ph(i, 3) ? lo : ph(i, 3);
		const uint64_t end = (uint64_t(ph(i, 3)) + ph(i, 5) + 0xfff) & ~0xfffull;
		hi = hi > end ? hi : end;
	}
	const uint64_t ehdr = ph(0, 4), hashBytes = hash ? ph(hash, 4) : 0, hashOff = hash ? ph(hash, 1) : 0;
	if (ph(0, 0) == 1 || !hash || lo >= hi || hi - lo > kZapBytes || ehdr > size || hashOff + hashBytes > size ||
	    ehdr + hashBytes > 0x4000) {
		say("zap: layout refused (hash %u lo %llx hi %llx)", hash, (unsigned long long)lo, (unsigned long long)hi);
		return false;
	}
	const size_t metaBytes = size_t((ehdr + hashBytes + 0xfff) & ~0xfffull);
	if (gZapMetadata.allocate(metaBytes, 40, true, metaBytes) || gZapMetadata.spanCount() != 1) {
		say("zap: metadata allocation failed");
		return false;
	}
	uint8_t *meta = static_cast<uint8_t *>(gZapMetadata.mapping());
	for (uint64_t i = 0; i < ehdr; ++i) {
		meta[i] = fw[i];
	}
	for (uint64_t i = 0; i < hashBytes; ++i) {
		meta[ehdr + i] = fw[hashOff + i];
	}
	if (gZapMetadata.publishForDevice(0, metaBytes, true)) {
		say("zap: metadata publish failed");
		return false;
	}
	progress(0xa1);
	ScmRes init = scmCall(kScmPil(0x01), 2 | (2u << 6), kGpuPasId, gZapMetadata.spans()[0].physical, 0);
	ScmRes setup = {0, 0}, auth = {0, 0};
	if (!init.a0 && !init.a1 && relocate) {
		progress(0xa2);
		setup = scmCall(kScmPil(0x02), 3, kGpuPasId, kZapPhys, hi - lo);
	}
	if (!init.a0 && !init.a1 && !setup.a0 && !setup.a1) {
		IODeviceMemory *m = IODeviceMemory::withRange(kZapPhys, kZapBytes);
		OSSharedPtr<IOMemoryMap> map;
		if (m) {
			map = OSSharedPtr<IOMemoryMap>(m->map(kIOMapAnywhere | kIOMapWriteCombineCache), OSNoRetain);
			m->release();
		}
		if (!map) {
			say("zap: region not mapped");
			return false;
		}
		volatile uint8_t *region = reinterpret_cast<volatile uint8_t *>(map->getVirtualAddress());
		const uint64_t base = relocate ? lo : kZapPhys;
		for (unsigned i = 0; i < phnum; ++i) {
			if (ph(i, 0) != 1 || ((ph(i, 6) >> 24) & 7) == 2 || !ph(i, 5)) {
				continue;
			}
			const uint64_t at = uint64_t(ph(i, 3)) - base, file = ph(i, 4), mem = ph(i, 5), off = ph(i, 1);
			if (ph(i, 3) < base || at + mem > kZapBytes || file > mem || off + file > size) {
				say("zap: segment %u outside the region", i);
				return false;
			}
			for (uint64_t b = 0; b < file; ++b) {
				region[at + b] = fw[off + b];
			}
			for (uint64_t b = file; b < mem; ++b) {
				region[at + b] = 0;
			}
		}
		__builtin_arm_dsb(0xf);
		progress(0xa3);
		auth = scmCall(kScmPil(0x05), 1, kGpuPasId, 0, 0);
	}
	const bool loaded = !init.a0 && !init.a1 && !setup.a0 && !setup.a1 && !auth.a0 && !auth.a1;
	uint32_t secure = 99;
	if (loaded) {
		progress(0xa4);
		uint32_t words[2] = {}, fence = 0, seen = 0;
		if (AdrenoPM4Type7(0x66, 1, &words[0]) == AdrenoPM4Success && !gRing.submit(words, 2, &fence)) {   // CP_SET_SECURE_MODE 0
			const NativeAdrenoRingClock clock{nullptr, ringNow, ringIdle};
			secure = gRing.wait(fence, &clock, 200000, &seen);
		}
	}
	say("zap: init %lld/%llx mem-setup %lld/%llx (relocate %u, %llx bytes) auth %lld/%llx secure-mode-off %u",
	    (long long)init.a0, (unsigned long long)init.a1, (long long)setup.a0, (unsigned long long)setup.a1, relocate,
	    (unsigned long long)(hi - lo), (long long)auth.a0, (unsigned long long)auth.a1, secure);
	return loaded && secure == 0;
}
} // namespace

// Live GPU execution state, printed by the heartbeat once clients can submit (mode 11). The ring, CP read/write pointers and
// memptrs are the shared ring the published service submits on; fsr() is the GPU SMMU context-bank 0 fault status.
void execReport()
{
	const volatile uint32_t *mem = reinterpret_cast<const volatile uint32_t *>(gCpu[2]);
	// CP_INTERRUPT_STATUS 0x823: bit 0 opcode error, 1 ucode error, 2 hw fault, 3 register protection (0x824 holds the
	// register). On an opcode error CP_SQE_STAT_ADDR=1 then CP_SQE_STAT_DATA reads the offending opcode (a6xx_gpu.c).
	gpuWrite(A740_CP_SQE_STAT_ADDR, 1);
	const uint32_t opcode = gpuRead(A740_CP_SQE_STAT_DATA);
	const uint32_t rptr = gpuRead(A740_CP_RB_RPTR), wptr = gpuRead(A740_CP_RB_WPTR);
	const volatile uint32_t *ring = reinterpret_cast<const volatile uint32_t *>(gCpu[1]);
	const size_t rwords = gBuffers[1].bytes / 4;
	printf("NX769J GPU exec: RBBM_STATUS %08x INT %08x cp-int %05x protect %08x opcode %08x rptr/wptr %x/%x shadow %x "
	    "fence %x smmu-fsr %x\n",
	    gpuRead(A740_RBBM_STATUS), gpuRead(A740_RBBM_INT_0_STATUS), gpuRead(A740_CP_INTERRUPT_STATUS), gpuRead(0x824),
	    opcode, rptr, wptr, mem ? mem[0] : 0, mem ? mem[1] : 0, fsr());
	if (ring && rwords) {
		printf("NX769J GPU ring@%x:", rptr);
		for (int i = -2; i <= 5; ++i) {
			printf(" %08x", ring[(rptr + i) & (rwords - 1)]);
		}
		printf("\n");
	}
}

NativeAdrenoRing *commandRing() { return &gRing; }
NativeAdrenoRingClock commandClock() { return NativeAdrenoRingClock{nullptr, ringNow, ringIdle}; }

bool
commandStart(bool zap)
{
	// 1. The GPU's own context bank (arm-smmu-qcom gives the GPU bank 0; iommus streams 0 and 1).
	progress(0x90);
	if (!smmu()) {
		say("gpu context: no SMMU window");
		return false;
	}
	const IOReturn ctx = NativeAdrenoGpuContextBringup(smmu(), smmuBytes(), 0, 2, 0, 0, 1, 1, contextProgress, &gContext);
	say("gpu context: step %u status %x program %u/%u phase %u enabled %u route %u verified %u spans %u", gContext.step,
	    unsigned(ctx), gContext.program_status, gContext.route_status, gContext.program_phase, gContext.program_enabled,
	    gContext.route_phase, gContext.routes_verified, gContext.spans);
	if (ctx) {
		return false;
	}
	setActlr();
	if (NativeAdrenoGpuContextBuffers(gBuffers)) {
		say("gpu context: buffers refused");
		return false;
	}
	for (unsigned i = 0; i < GpuBufferCount; ++i) {
		IODeviceMemory *m = IODeviceMemory::withRange(gBuffers[i].physical, gBuffers[i].bytes);
		if (m) {
			gMaps[i] = OSSharedPtr<IOMemoryMap>(m->map(kIOMapAnywhere | kIOMapWriteCombineCache), OSNoRetain);
			m->release();
		}
		if (!gMaps[i]) {
			say("gpu context: buffer %u not mapped", i);
			return false;
		}
		gCpu[i] = reinterpret_cast<volatile uint8_t *>(gMaps[i]->getVirtualAddress());
	}
	// 2. SQE: adreno_fw_create_bo copies the firmware without its first dword.
	progress(0xb2);
	const uint64_t sqe = native_adreno_sqe_firmware_image_size;
	if (sqe < 8 || sqe - 4 > gBuffers[0].bytes) {
		say("sqe: %llu bytes do not fit the %llu-byte buffer", (unsigned long long)sqe, (unsigned long long)gBuffers[0].bytes);
		return false;
	}
	for (uint64_t i = 4; i < sqe; ++i) {
		gCpu[0][i - 4] = native_adreno_sqe_firmware_image[i];
	}
	__builtin_arm_dsb(0xf);
	for (uint64_t i = 4; i < sqe; ++i) {
		if (gCpu[0][i - 4] != native_adreno_sqe_firmware_image[i]) {
			say("sqe: readback differs at %llx", (unsigned long long)i);
			return false;
		}
	}
	// 3. hw_init.
	progress(0xb3);
	hwInit();
	// 4. Ring 0 (32 KiB), memptrs, BV rptr shadow, SQE start.
	progress(0xb4);
	const NativeAdrenoRingIo rio{nullptr, gpuWrite32, gpuRead32, ringBarrier, nullptr, nullptr};
	const NativeAdrenoRingCache cache{nullptr, ringPublish, ringAcquire};
	const IOReturn attached = gRing.attach(&rio, &cache, const_cast<uint8_t *>(gCpu[1]), gBuffers[1].bytes, gBuffers[1].iova,
	    const_cast<uint8_t *>(gCpu[2]), gBuffers[2].bytes, gBuffers[2].iova);
	if (attached) {
		say("ring: attach %x", unsigned(attached));
		return false;
	}
	wr64(A740_CP_BV_RB_RPTR_ADDR, gBuffers[2].iova + 8);
	gpuWrite(A740_CP_SQE_CNTL, 1);
	// 5. Power-up list (preemption registers; IFPC off) and CP_INIT.
	progress(0xb5);
	size_t written = 0;
	const IOReturn list = NativeAdrenoPwrupList::buildA740(gpuRead32, nullptr, const_cast<uint8_t *>(gCpu[3]),
	    gBuffers[3].bytes, &written);
	if (list) {
		say("pwrup list: %x", unsigned(list));
		return false;
	}
	__builtin_arm_dsb(0xf);
	const NativeAdrenoCpInitConfig config{gBuffers[0].iova, gBuffers[3].iova, 1};
	uint32_t fence = 0, seen = 0;
	const IOReturn init = gCpInit.run(&rio, &gRing, &config, &fence);
	if (init) {
		say("cp init: refused %x", unsigned(init));
		return false;
	}
	const NativeAdrenoRingClock clock{nullptr, ringNow, ringIdle};
	progress(0xb6);
	const uint32_t cpWait = gRing.wait(fence, &clock, 200000, &seen);
	cpLine(cpWait ? "CP_INIT fence timeout" : "CP_INIT done", 6);
	if (cpWait) {
		return false;
	}
	// 6. CP_MEM_WRITE (opcode 0x3d: address lo/hi, data) into the scratch page, then its fence.
	progress(0xb7);
	volatile uint32_t *scratch = reinterpret_cast<volatile uint32_t *>(gCpu[4]);
	scratch[0] = 0;
	__builtin_arm_dsb(0xf);
	uint32_t words[4] = {};
	if (AdrenoPM4Type7(0x3d, 3, &words[0]) != AdrenoPM4Success) {
		say("pm4: encode failed");
		return false;
	}
	words[1] = uint32_t(gBuffers[4].iova);
	words[2] = uint32_t(gBuffers[4].iova >> 32);
	words[3] = 0x5e9a750;
	if (gRing.submit(words, 4, &fence)) {
		say("mem write: submit refused");
		return false;
	}
	const uint32_t writeWait = gRing.wait(fence, &clock, 200000, &seen);
	const uint32_t word = scratch[0];
	const bool ok = !writeWait && word == 0x5e9a750;
	cpLine(ok ? "GPU WROTE MEMORY" : writeWait ? "mem write fence timeout" : "mem write missing", 7);
	say("mem write: scratch %08x (want 05e9a750) fence %u seen %u", word, fence, seen);
	if (ok) {
		markVerified();
	}
	if (!ok || !zap) {
		return ok;
	}
	progress(0xa0);
	return zapAndSecure();
}
} // namespace nx769j_gpu
