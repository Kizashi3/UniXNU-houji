#!/system/bin/sh
# Read PCIe0 through the OnePlus pci-msm debugfs interface. No MMIO writes,
# reset, link retraining, enumeration, firmware upload or partition access.
# Requires an already running Android Wi-Fi device and root.
set -eu
dbg=/sys/kernel/debug/pci-msm
test -r "$dbg/case"
test -d /sys/bus/pci/devices/0000:01:00.0
test "$(cat /sys/bus/pci/devices/0000:01:00.0/vendor)" = 0x17cb
test "$(cat /sys/bus/pci/devices/0000:01:00.0/device)" = 0x1107
# Validate the running driver's menu instead of assuming its case numbering.
grep -Eq '12:.*READ (A )?PCIE REGISTER' "$dbg/case"
power=/sys/bus/pci/devices/0000:01:00.0/power/control
old_power=$(cat "$power")
old_rc=$(sed -n 's/Current rc_sel: \([0-9]*\).*/\1/p' "$dbg/rc_sel")
old_base=$(sed -n 's/Current base_sel: \([0-9]*\).*/\1/p' "$dbg/base_sel")
old_offset=$(cat "$dbg/wr_offset")
test -n "$old_rc"
test -n "$old_base"
restore() {
  printf '%s\n' "$old_power" > "$power"
  printf '%s\n' "$old_rc" > "$dbg/rc_sel"
  # The vendor setter rejects zero even if it was the initial selector.
  if [ "$old_base" != 0 ]; then printf '%s\n' "$old_base" > "$dbg/base_sel"; fi
  printf '%s\n' "$old_offset" > "$dbg/wr_offset"
}
trap restore EXIT
# Hold a normal runtime-PM reference while the driver's read interface is
# used; restore the original policy afterward. No raw clock/reset writes.
printf 'on\n' > "$power"
test "$(cat /sys/bus/pci/devices/0000:01:00.0/power/runtime_status)" = active
printf '1\n' > "$dbg/rc_sel"
for base in 1 2 3 4 7; do
  case "$base" in
    1) offsets='0 0x20 0x24 0x28 0x40 0x174 0x180 0x1b0 0x2b0 0x2c4 0x4d0 0x4d4 0x1000';;
    2) offsets='0x1f8 0x200 0x214 0x218 0x21c 0x240 0x244 0xed0 0x16d0 0xedc 0x16dc 0x11e0 0x19e0';;
    3) offsets='0 0x7c 0x80 0x710 0x714 0x80c 0x890 0x8a8 0x8ac';;
    4) offsets='4 8';;
    7) offsets='0x1040 0x1048 0x1070 0x1078 0x1080 0x1088 0x1090';;
  esac
  printf '%s\n' "$base" > "$dbg/base_sel"
  for offset in $offsets; do
    printf '%s\n' "$offset" > "$dbg/wr_offset"
    printf '12\n' > "$dbg/case"
  done
done
for clock in gcc_pcie_0_aux_clk gcc_pcie_0_pipe_clk gcc_pcie_0_phy_rchng_clk gcc_pcie_0_mstr_axi_clk gcc_pcie_0_cfg_ahb_clk; do
  printf '\nCLOCK %s\n' "$clock"
  cat "/sys/kernel/debug/clk/$clock/clk_print_regs"
  cat "/sys/kernel/debug/clk/$clock/clk_rate"
done
for domain in 16b004 16c000; do
  printf '\nDOMAIN %s\n' "$domain"
  cat "/sys/kernel/debug/regmap/$domain.qcom,gdsc/registers"
done
# Filter out unrelated kernel messages; the vendor log labels physical
# addresses with the DBI base even for other regions, so retain base/offset.
dmesg | grep -E 'msm_pcie_access_reg|wr_offset:|^base:'
