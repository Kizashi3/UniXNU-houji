/* SPDX-License-Identifier: GPL-2.0-only */
/* SM8550 video clock controller (videocc at 0xaaf0000) and the GCC video branches the VPU needs: the two Lucid OLE PLLs, the MVS0
 * root, the MVS0C and MVS0 power domains, the branch clocks and the bus reset. The sequences follow the mainline videocc-sm8550,
 * clk-alpha-pll (Lucid EVO/OLE), clk-rcg2, clk-branch and gdsc drivers. Register access goes through callbacks, so host tests run the
 * same code against a register model. */
#ifndef SM8550_VIDEO_CC_H
#define SM8550_VIDEO_CC_H
#include <stdbool.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#define SM8550_GCC_BASE 0x00100000ULL
#define SM8550_GCC_SIZE 0x001f0000ULL
#define SM8550_VIDEO_CC_BASE 0x0aaf0000ULL
#define SM8550_VIDEO_CC_SIZE 0x00010000ULL

/* Offsets of one window each: GCC from SM8550_GCC_BASE, videocc from SM8550_VIDEO_CC_BASE. */
enum sm8550_video_cc_window {Sm8550VideoGcc = 0, Sm8550VideoCc = 1};
struct sm8550_video_cc_io {
    void *context;
    uint32_t (*read)(void *context, enum sm8550_video_cc_window window, uint32_t offset);
    void (*write)(void *context, enum sm8550_video_cc_window window, uint32_t offset, uint32_t value);  /* completes the store */
    void (*delay_us)(void *context, unsigned us);
};

/* The step that failed, for the caller's diagnostics. */
enum sm8550_video_cc_step {
    Sm8550VideoStepNone = 0,
    Sm8550VideoStepPll0Lock, Sm8550VideoStepPll1Lock, Sm8550VideoStepRcg, Sm8550VideoStepMvs0cGdsc,
    Sm8550VideoStepMvs0Gdsc, Sm8550VideoStepAxiClock, Sm8550VideoStepCtrlClock, Sm8550VideoStepHwClock,
    Sm8550VideoStepRate, Sm8550VideoStepHwMode,
};
struct sm8550_video_cc_state {
    bool configured;        /* the PLLs were configured and the always-on branches turned on */
    bool controller_on;     /* MVS0C domain, bus reset pulsed, AXI and controller clocks */
    bool hardware_on;       /* MVS0 domain and core clock */
    uint32_t mvs0_hz;       /* the MVS0 root rate programmed */
    uint32_t mvs0_div;      /* the fixed MVS0 core divider read back (divide-by value) */
    uint32_t mvs0c_div;     /* the fixed MVS0C controller divider read back (divide-by value) */
    uint32_t failed_step;   /* enum sm8550_video_cc_step */
    uint32_t failed_value;  /* the register value at the failure */
};

/* The rates of the MVS0 root from PLL0 (videocc-sm8550 ftbl_video_cc_mvs0_clk_src). The VPU core clock is this rate divided by the
 * read-only MVS0 divider. Returns false for a rate outside the table. */
bool sm8550_video_cc_mvs0_rate_supported(uint32_t hz);

/* videocc probe: the always-on branches (GCC video AHB and XO, videocc AHB, XO and sleep) and both PLLs configured (left in standby,
 * as clk_lucid_ole_pll_configure leaves them). PLL0 is configured for mvs0_hz so the root needs no later rate change. */
bool sm8550_video_cc_configure(const struct sm8550_video_cc_io *, struct sm8550_video_cc_state *, uint32_t mvs0_hz);
/* iris_vpu_power_on_controller: MVS0C domain on, GCC_VIDEO_AXI0 reset pulsed, AXI clock, controller clock (PLL0 and the MVS0 root
 * enabled under it). */
bool sm8550_video_cc_controller_on(const struct sm8550_video_cc_io *, struct sm8550_video_cc_state *);
/* iris_vpu_power_on_hw: MVS0 domain on and the VPU core clock. */
bool sm8550_video_cc_hardware_on(const struct sm8550_video_cc_io *, struct sm8550_video_cc_state *);
/* iris_vpu_switch_to_hwmode / power off: the MVS0 domain under hardware control (true) or software control (false). */
bool sm8550_video_cc_hardware_mode(const struct sm8550_video_cc_io *, struct sm8550_video_cc_state *, bool hardware);
/* iris_vpu_power_off_hw and iris_vpu_power_off_controller: the clocks off, then the domains. */
void sm8550_video_cc_hardware_off(const struct sm8550_video_cc_io *, struct sm8550_video_cc_state *);
void sm8550_video_cc_controller_off(const struct sm8550_video_cc_io *, struct sm8550_video_cc_state *);
#ifdef __cplusplus
}
#endif
#endif
