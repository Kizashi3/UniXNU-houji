/* SPDX-License-Identifier: GPL-2.0-only */
#include "Sm8550VideoCc.h"

/* GCC branches (gcc-sm8550): video AHB and XO are critical clocks turned on at GCC probe; AXI0 is the VPU's bus clock and its
 * reset (GCC_VIDEO_AXI0_CLK_ARES) lives in the same CBCR. */
enum {
    GccVideoAhbCbcr = 0x32004, GccVideoXoCbcr = 0x32030, GccVideoAxi0Cbcr = 0x32018,
};
/* videocc-sm8550 */
enum {
    Pll0 = 0x0000, Pll1 = 0x1000,
    Mvs0Rcg = 0x8000,                 /* video_cc_mvs0_clk_src */
    Mvs0cGdscr = 0x804c, Mvs0Gdscr = 0x80a4,
    Mvs0cCbcr = 0x8064, Mvs0cDiv = 0x8070,
    Mvs0Cbcr = 0x80b8, Mvs0Div = 0x80c4,
    AhbCbcr = 0x80f4, XoCbcr = 0x8124, SleepCbcr = 0x8140,
};
/* clk-alpha-pll, Lucid OLE layout */
enum {
    PllMode = 0x00, PllOpmode = 0x04, PllLVal = 0x10, PllAlpha = 0x14, PllUserCtl = 0x18, PllUserCtlU = 0x1c,
    PllConfigCtl = 0x20, PllConfigCtlU = 0x24, PllConfigCtlU1 = 0x28, PllTestCtl = 0x2c, PllTestCtlU = 0x30,
    PllTestCtlU1 = 0x34, PllTestCtlU2 = 0x38,
};
#define PLL_OUTCTRL (1u << 0)
#define PLL_RESET_N (1u << 2)
#define PLL_LOCK_DET (1u << 31)
#define PLL_STANDBY 0u
#define PLL_RUN 1u
#define PLL_OUT_MASK 7u
#define LUCID_EVO_ENABLE_VOTE_RUN (1u << 25)
#define TRION_PLL_CAL_VAL 0x44u
#define LUCID_EVO_PLL_CAL_L_VAL_SHIFT 16
#define LUCID_OLE_PLL_RINGOSC_CAL_L_VAL_SHIFT 24
/* clk-rcg2 */
#define RCG_CMD_UPDATE (1u << 0)
#define RCG_CMD_ROOT_EN (1u << 1)
#define RCG_CMD_ROOT_OFF (1u << 31)
#define RCG_CFG 0x4u
#define RCG_CFG_SRC_SEL_SHIFT 8
#define RCG_CFG_MASK (0x1fu | (7u << 8) | (3u << 12) | (1u << 20))  /* hid (5 bits), source, mode, hw clock control */
/* clk-branch */
#define CBCR_ENABLE (1u << 0)
#define CBCR_HWCG (1u << 1)
#define CBCR_ARES (1u << 2)
#define CBCR_CLK_OFF (1u << 31)
/* gdsc */
#define GDSC_SW_COLLAPSE (1u << 0)
#define GDSC_HW_CONTROL (1u << 1)
#define GDSC_SW_OVERRIDE (1u << 2)
#define GDSC_RETAIN_FF_ENABLE (1u << 11)
#define GDSC_WAIT_MASK ((0xfu << 20) | (0xfu << 16) | (0xfu << 12))
#define GDSC_CFG 0x4u
#define GDSC_POWER_UP_COMPLETE (1u << 16)
#define GDSC_POWER_DOWN_COMPLETE (1u << 15)
#define GDSC_POLL_US 2000u

#define XO_HZ 19200000u

static uint32_t rd(const struct sm8550_video_cc_io *io, enum sm8550_video_cc_window w, uint32_t offset)
{
    return io->read(io->context, w, offset);
}
static void wr(const struct sm8550_video_cc_io *io, enum sm8550_video_cc_window w, uint32_t offset, uint32_t value)
{
    io->write(io->context, w, offset, value);
}
static void update(const struct sm8550_video_cc_io *io, enum sm8550_video_cc_window w, uint32_t offset, uint32_t mask, uint32_t value)
{
    wr(io, w, offset, (rd(io, w, offset) & ~mask) | (value & mask));
}
static bool fail(struct sm8550_video_cc_state *s, enum sm8550_video_cc_step step, uint32_t value)
{
    s->failed_step = (uint32_t)step;
    s->failed_value = value;
    return false;
}

/* ftbl_video_cc_mvs0_clk_src (SM8550): every entry runs PLL0 at the rate, divider 1. */
static const uint32_t mvs0_rates[] = {720000000u, 1014000000u, 1098000000u, 1332000000u, 1600000000u};
bool sm8550_video_cc_mvs0_rate_supported(uint32_t hz)
{
    for (unsigned i = 0; i < sizeof mvs0_rates / sizeof mvs0_rates[0]; ++i)
        if (mvs0_rates[i] == hz) return true;
    return false;
}

struct pll_config {
    uint32_t l, alpha, config_ctl, config_ctl_hi, config_ctl_hi1, test_ctl, test_ctl_hi, test_ctl_hi1, test_ctl_hi2,
        user_ctl, user_ctl_hi;
};
/* video_cc_pll0_config / video_cc_pll1_config: only L and the 16-bit alpha differ. */
static struct pll_config pll_config(uint32_t hz)
{
    const uint64_t l = hz / XO_HZ, rest = hz % XO_HZ;
    struct pll_config c = {(uint32_t)l, (uint32_t)((rest << 16) / XO_HZ), 0x20485699, 0x00182261, 0x82aa299c, 0x00000000,
                           0x00000003, 0x00009000, 0x00000034, 0x00000000, 0x00000005};
    return c;
}

/* clk_lucid_ole_pll_configure: clk_alpha_pll_write_config skips zero values. */
static void pll_configure(const struct sm8550_video_cc_io *io, uint32_t pll, const struct pll_config *c)
{
    const uint32_t lval = c->l | TRION_PLL_CAL_VAL << LUCID_EVO_PLL_CAL_L_VAL_SHIFT | TRION_PLL_CAL_VAL << LUCID_OLE_PLL_RINGOSC_CAL_L_VAL_SHIFT;
    const struct {uint32_t offset, value;} writes[] = {
        {PllLVal, lval}, {PllAlpha, c->alpha}, {PllConfigCtl, c->config_ctl}, {PllConfigCtlU, c->config_ctl_hi},
        {PllConfigCtlU1, c->config_ctl_hi1}, {PllUserCtl, c->user_ctl}, {PllUserCtlU, c->user_ctl_hi}, {PllTestCtl, c->test_ctl},
        {PllTestCtlU, c->test_ctl_hi}, {PllTestCtlU1, c->test_ctl_hi1}, {PllTestCtlU2, c->test_ctl_hi2},
    };
    for (unsigned i = 0; i < sizeof writes / sizeof writes[0]; ++i)
        if (writes[i].value) wr(io, Sm8550VideoCc, pll + writes[i].offset, writes[i].value);
    update(io, Sm8550VideoCc, pll + PllMode, PLL_OUTCTRL, 0);
    wr(io, Sm8550VideoCc, pll + PllOpmode, PLL_STANDBY);
    update(io, Sm8550VideoCc, pll + PllMode, PLL_RESET_N, PLL_RESET_N);
}

static bool pll_enabled(const struct sm8550_video_cc_io *io, uint32_t pll)
{
    return (rd(io, Sm8550VideoCc, pll + PllOpmode) & PLL_RUN) && (rd(io, Sm8550VideoCc, pll + PllMode) & PLL_OUTCTRL);
}

static bool pll_wait_lock(const struct sm8550_video_cc_io *io, uint32_t pll)
{
    for (unsigned i = 0; i < 1500; ++i) {
        if (rd(io, Sm8550VideoCc, pll + PllMode) & PLL_LOCK_DET) return true;
        io->delay_us(io->context, 1);
    }
    return (rd(io, Sm8550VideoCc, pll + PllMode) & PLL_LOCK_DET) != 0;
}

/* alpha_pll_lucid_evo_enable (not in FSM mode: user_ctl leaves ENABLE_VOTE_RUN clear) */
static bool pll_enable(const struct sm8550_video_cc_io *io, uint32_t pll)
{
    if (rd(io, Sm8550VideoCc, pll + PllUserCtl) & LUCID_EVO_ENABLE_VOTE_RUN) return false;
    if (pll_enabled(io, pll)) return true;
    update(io, Sm8550VideoCc, pll + PllMode, PLL_RESET_N, PLL_RESET_N);
    wr(io, Sm8550VideoCc, pll + PllOpmode, PLL_RUN);
    if (!pll_wait_lock(io, pll)) return false;
    update(io, Sm8550VideoCc, pll + PllUserCtl, PLL_OUT_MASK, PLL_OUT_MASK);
    update(io, Sm8550VideoCc, pll + PllMode, PLL_OUTCTRL, PLL_OUTCTRL);
    return true;
}

/* _alpha_pll_lucid_evo_disable without reset */
static void pll_disable(const struct sm8550_video_cc_io *io, uint32_t pll)
{
    if (rd(io, Sm8550VideoCc, pll + PllUserCtl) & LUCID_EVO_ENABLE_VOTE_RUN) return;
    update(io, Sm8550VideoCc, pll + PllMode, PLL_OUTCTRL, 0);
    io->delay_us(io->context, 1);
    update(io, Sm8550VideoCc, pll + PllUserCtl, PLL_OUT_MASK, 0);
    wr(io, Sm8550VideoCc, pll + PllOpmode, PLL_STANDBY);
}

static bool rcg_wait(const struct sm8550_video_cc_io *io, uint32_t rcg, uint32_t mask, uint32_t value)
{
    for (unsigned i = 0; i < 500; ++i) {
        if ((rd(io, Sm8550VideoCc, rcg) & mask) == value) return true;
        io->delay_us(io->context, 1);
    }
    return (rd(io, Sm8550VideoCc, rcg) & mask) == value;
}
/* clk_rcg2_shared_ops: the configuration is written with the root forced on (clk_rcg2_set_force_enable waits for ROOT_OFF to clear),
 * then latched by update_config. Source index 1 is PLL0, 0 the XO safe source; the hid field holds 2 * pre_div - 1. */
static bool rcg_shared_set(const struct sm8550_video_cc_io *io, uint32_t rcg, uint32_t cfg)
{
    update(io, Sm8550VideoCc, rcg, RCG_CMD_ROOT_EN, RCG_CMD_ROOT_EN);
    bool ok = rcg_wait(io, rcg, RCG_CMD_ROOT_OFF, 0);
    if (ok) {
        update(io, Sm8550VideoCc, rcg + RCG_CFG, RCG_CFG_MASK, cfg);
        update(io, Sm8550VideoCc, rcg, RCG_CMD_UPDATE, RCG_CMD_UPDATE);
        ok = rcg_wait(io, rcg, RCG_CMD_UPDATE, 0);
    }
    update(io, Sm8550VideoCc, rcg, RCG_CMD_ROOT_EN, 0);
    return ok;
}
static bool rcg_configure(const struct sm8550_video_cc_io *io, uint32_t rcg, uint32_t source, uint32_t pre_div)
{
    return rcg_shared_set(io, rcg, source << RCG_CFG_SRC_SEL_SHIFT | (2 * pre_div - 1));
}
/* clk_rcg2_shared_disable: parked on the safe source (XO). */
static void rcg_park(const struct sm8550_video_cc_io *io, uint32_t rcg)
{
    rcg_shared_set(io, rcg, 0);
}

/* clk_branch2 enable/disable; halt_check: 0 BRANCH_HALT (wait for CLK_OFF to follow), 1 BRANCH_HALT_SKIP. The wait is skipped in
 * hardware clock gating mode, as clk_branch_in_hwcg_mode does. */
static bool branch(const struct sm8550_video_cc_io *io, enum sm8550_video_cc_window w, uint32_t cbcr, bool on, bool skip, bool hwcg)
{
    update(io, w, cbcr, CBCR_ENABLE, on ? CBCR_ENABLE : 0);
    if (skip || (hwcg && (rd(io, w, cbcr) & CBCR_HWCG))) return true;
    for (unsigned i = 0; i < 200; ++i) {
        const bool off = (rd(io, w, cbcr) & CBCR_CLK_OFF) != 0;
        if (off != on) return true;
        io->delay_us(io->context, 1);
    }
    return false;
}

/* qcom_reset assert/deassert of a CBCR ARES bit with its udelay. */
static void ares_pulse(const struct sm8550_video_cc_io *io, enum sm8550_video_cc_window w, uint32_t cbcr, unsigned us)
{
    update(io, w, cbcr, CBCR_ARES, CBCR_ARES);
    io->delay_us(io->context, us);
    update(io, w, cbcr, CBCR_ARES, 0);
    io->delay_us(io->context, us);
}

/* gdsc_init for both video domains: no hardware control, no software override, wait values 2/2/6. */
static void gdsc_init(const struct sm8550_video_cc_io *io, uint32_t gdscr)
{
    update(io, Sm8550VideoCc, gdscr, GDSC_HW_CONTROL | GDSC_SW_OVERRIDE | GDSC_WAIT_MASK, 2u << 20 | 2u << 16 | 6u << 12);
}
/* gdsc_check_status with POLL_CFG_GDSCR */
static bool gdsc_poll(const struct sm8550_video_cc_io *io, uint32_t gdscr, bool on)
{
    const uint32_t bit = on ? GDSC_POWER_UP_COMPLETE : GDSC_POWER_DOWN_COMPLETE;
    for (unsigned i = 0; i < GDSC_POLL_US; ++i) {
        if (rd(io, Sm8550VideoCc, gdscr + GDSC_CFG) & bit) return true;
        io->delay_us(io->context, 1);
    }
    return (rd(io, Sm8550VideoCc, gdscr + GDSC_CFG) & bit) != 0;
}
/* gdsc_enable: collapse bit cleared, power-up polled, 1 us before clocks, flip-flop retention on (RETAIN_FF_ENABLE). */
static bool gdsc_on(const struct sm8550_video_cc_io *io, uint32_t gdscr)
{
    update(io, Sm8550VideoCc, gdscr, GDSC_SW_COLLAPSE, 0);
    if (!gdsc_poll(io, gdscr, true)) return false;
    io->delay_us(io->context, 1);
    update(io, Sm8550VideoCc, gdscr, GDSC_RETAIN_FF_ENABLE, GDSC_RETAIN_FF_ENABLE);
    return true;
}
static bool gdsc_off(const struct sm8550_video_cc_io *io, uint32_t gdscr)
{
    update(io, Sm8550VideoCc, gdscr, GDSC_SW_COLLAPSE, GDSC_SW_COLLAPSE);
    return gdsc_poll(io, gdscr, false);
}

bool sm8550_video_cc_configure(const struct sm8550_video_cc_io *io, struct sm8550_video_cc_state *s, uint32_t mvs0_hz)
{
    if (!io || !s || !sm8550_video_cc_mvs0_rate_supported(mvs0_hz)) return false;
    if (s->configured) return s->mvs0_hz == mvs0_hz;
    s->failed_step = Sm8550VideoStepNone;
    /* gcc-sm8550 probe: qcom_branch_set_clk_en for the critical video branches */
    update(io, Sm8550VideoGcc, GccVideoAhbCbcr, CBCR_ENABLE, CBCR_ENABLE);
    update(io, Sm8550VideoGcc, GccVideoXoCbcr, CBCR_ENABLE, CBCR_ENABLE);
    /* videocc-sm8550 probe: PLLs configured, then the critical branches */
    const struct pll_config p0 = pll_config(mvs0_hz), p1 = pll_config(1050000000u);
    pll_configure(io, Pll0, &p0);
    pll_configure(io, Pll1, &p1);
    update(io, Sm8550VideoCc, AhbCbcr, CBCR_ENABLE, CBCR_ENABLE);
    update(io, Sm8550VideoCc, XoCbcr, CBCR_ENABLE, CBCR_ENABLE);
    update(io, Sm8550VideoCc, SleepCbcr, CBCR_ENABLE, CBCR_ENABLE);
    gdsc_init(io, Mvs0cGdscr);
    gdsc_init(io, Mvs0Gdscr);
    s->mvs0_div = (rd(io, Sm8550VideoCc, Mvs0Div) & 0xf) + 1;
    s->mvs0c_div = (rd(io, Sm8550VideoCc, Mvs0cDiv) & 0xf) + 1;
    s->mvs0_hz = mvs0_hz;
    s->configured = true;
    return true;
}

bool sm8550_video_cc_controller_on(const struct sm8550_video_cc_io *io, struct sm8550_video_cc_state *s)
{
    if (!io || !s || !s->configured) return false;
    if (s->controller_on) return true;
    if (!gdsc_on(io, Mvs0cGdscr)) return fail(s, Sm8550VideoStepMvs0cGdsc, rd(io, Sm8550VideoCc, Mvs0cGdscr + GDSC_CFG));
    ares_pulse(io, Sm8550VideoGcc, GccVideoAxi0Cbcr, 1000);
    if (!branch(io, Sm8550VideoGcc, GccVideoAxi0Cbcr, true, true, true))
        return fail(s, Sm8550VideoStepAxiClock, rd(io, Sm8550VideoGcc, GccVideoAxi0Cbcr));
    if (!pll_enable(io, Pll0)) return fail(s, Sm8550VideoStepPll0Lock, rd(io, Sm8550VideoCc, Pll0 + PllMode));
    if (!rcg_configure(io, Mvs0Rcg, 1, 1)) return fail(s, Sm8550VideoStepRcg, rd(io, Sm8550VideoCc, Mvs0Rcg));
    if (!branch(io, Sm8550VideoCc, Mvs0cCbcr, true, false, false))
        return fail(s, Sm8550VideoStepCtrlClock, rd(io, Sm8550VideoCc, Mvs0cCbcr));
    s->controller_on = true;
    return true;
}

bool sm8550_video_cc_hardware_on(const struct sm8550_video_cc_io *io, struct sm8550_video_cc_state *s)
{
    if (!io || !s || !s->controller_on) return false;
    if (s->hardware_on) return true;
    if (!gdsc_on(io, Mvs0Gdscr)) return fail(s, Sm8550VideoStepMvs0Gdsc, rd(io, Sm8550VideoCc, Mvs0Gdscr + GDSC_CFG));
    if (!branch(io, Sm8550VideoCc, Mvs0Cbcr, true, true, true))
        return fail(s, Sm8550VideoStepHwClock, rd(io, Sm8550VideoCc, Mvs0Cbcr));
    s->hardware_on = true;
    return true;
}

/* gdsc_set_hwmode: a hardware/software switch takes a power cycle; back in software mode the domain is polled on again. */
bool sm8550_video_cc_hardware_mode(const struct sm8550_video_cc_io *io, struct sm8550_video_cc_state *s, bool hardware)
{
    if (!io || !s || !s->hardware_on) return false;
    update(io, Sm8550VideoCc, Mvs0Gdscr, GDSC_HW_CONTROL, hardware ? GDSC_HW_CONTROL : 0);
    io->delay_us(io->context, 1);
    if (!hardware && !gdsc_poll(io, Mvs0Gdscr, true)) return fail(s, Sm8550VideoStepHwMode, rd(io, Sm8550VideoCc, Mvs0Gdscr + GDSC_CFG));
    return true;
}

void sm8550_video_cc_hardware_off(const struct sm8550_video_cc_io *io, struct sm8550_video_cc_state *s)
{
    if (!io || !s || !s->hardware_on) return;
    sm8550_video_cc_hardware_mode(io, s, false);
    branch(io, Sm8550VideoCc, Mvs0Cbcr, false, true, true);
    gdsc_off(io, Mvs0Gdscr);
    s->hardware_on = false;
}

void sm8550_video_cc_controller_off(const struct sm8550_video_cc_io *io, struct sm8550_video_cc_state *s)
{
    if (!io || !s || !s->controller_on || s->hardware_on) return;
    branch(io, Sm8550VideoCc, Mvs0cCbcr, false, false, false);
    branch(io, Sm8550VideoGcc, GccVideoAxi0Cbcr, false, true, true);
    rcg_park(io, Mvs0Rcg);
    pll_disable(io, Pll0);
    gdsc_off(io, Mvs0cGdscr);
    s->controller_on = false;
}
