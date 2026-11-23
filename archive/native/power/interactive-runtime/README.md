# r210: interaction policy and Edge placement

This overlay follows the exact linked r209 inputs in `before/`. The manifest
records every changed source. Hardware qualification is pending.

r209 actually selected XNU's Edge scheduler. Its generic initializer gives all
thread-group QoS buckets the boot cluster as their preference. Houji boots on
the A520 E cluster. Edge's default E-to-P edge denies migration and stealing;
no board CLPC supplies different recommendations. Merely registering six P
cores therefore does not direct foreground work to them.

The board-specific initializer now prefers a registered-topology P cluster for
fixed-priority, foreground, initiated and default buckets, and E for utility
and background. The lookup falls back to the boot pset while the preferred
pset is not yet registered. Explicit thread binding, normal Edge eligibility,
queue ownership and later perfcontrol updates retain their original behavior.

The current [sheng governor](https://github.com/UniXNU/UniXNU-sheng/blob/08cde20edc3254ed6f7df8d0f5384fb887786e8f/package/CpuFreqProbe.cpp)
adds P-core touch boost, render-activity retention, a quiet threshold and
requested-versus-controller-state observations to the basic load governor.
This overlay adapts those policy decisions to houji's four existing EPSS
domains and previously validated factory caps. It keeps max-per-core load,
the four-window downshift hysteresis and the verified ishtar downshift fix.
P cores use their qualified cap for one second after touch; sustained submits
keep a 60-percent floor for 300 ms; otherwise a half-cap P floor expires after
twelve quiet 20 ms windows. No new voltage, PLL, L3 or bandwidth register is
written. The GPU's existing 231/500 MHz HFI table remains unchanged; a 50 ms
wake hold and the reference's 50-percent utilization target improve initial
work handling within those two levels.

Bounded, append-only five-second histories record per-core scheduler busy
time, mean requested CPU frequency, controller-state minima/maxima, low-state
under-load counts, interaction windows, GPU XO busy time, acknowledged GPU
level residency and governor sampling delays. They are cached during use and
printed at the terminal checkpoint. The controller state is not a cycle
measurement, HFI ACKs are not measured GPU clocks, and these are not panel FPS.

The GPU/VM synchronization, framebuffer ownership, native 1200x2670 pixels,
Metal plugin, root volume and actual maximum frequency tables are unchanged.
The source changes require kernel compilation and a supervised hardware trial;
the host governor check only verifies selection, bounds and downshift behavior.
