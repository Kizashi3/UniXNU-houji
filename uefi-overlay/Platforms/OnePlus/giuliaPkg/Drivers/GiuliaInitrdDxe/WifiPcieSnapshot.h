/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Read-only failure snapshot, sampled with resources still enabled.
 * GCC/PARF/PHY offsets: OnePlus SM8650 gcc-pineapple.c, pci-msm.c and
 * captured PCIe0 qcom,phy-debug-reg. Never interpret as a runtime report.
 */
#ifndef GIULIA_WIFI_PCIE_SNAPSHOT_H
#define GIULIA_WIFI_PCIE_SNAPSHOT_H
#define GW_SNAPSHOT_MAGIC 0x31535047u
#define GW_TRACE_MAGIC 0x32535047u
/* v2: magic, stage|(valid_phase_mask<<16), error; eight phase records of
   RCHNG_CFG, RCHNG_CMD, AUX_CFG; then fifteen final registers.
   The format stays 168 bytes but uses giulia_pcid2, never giulia_wifi5. */
enum gw_clock_phase {GW_BEFORE_RATE,GW_AFTER_RATE,GW_AFTER_ENABLE,
  GW_BEFORE_CESTA,GW_AFTER_CESTA,GW_AFTER_CORE_RESET,GW_AFTER_RESETS,
  GW_AFTER_PHY, GW_CLOCK_PHASES};
static const unsigned gw_snapshot_regs[39][2]={
  {GW_GCC,0x6b004},{GW_GCC,0x6b008},{GW_GCC,0x6c000},{GW_GCC,0x6c004},
  {GW_GCC,0x6b000},{GW_GCC,0x6c01c},{GW_GCC,0x6b03c},{GW_GCC,0x6b048},
  {GW_GCC,0x6b038},{GW_GCC,0x6b02c},{GW_GCC,0x6b020},{GW_GCC,0x6b01c},
  {GW_GCC,0x6b054},{GW_GCC,0x6b070},{GW_GCC,0x6b034},{GW_GCC,0x6b030},
  {GW_GCC,0x6b058},{GW_GCC,0x6b05c},
  {GW_PARF,0},{GW_PARF,0x20},{GW_PARF,0x24},{GW_PARF,0x28},
  {GW_PARF,0x40},{GW_PARF,0x174},{GW_PARF,0x1b0},{GW_PARF,0x2b0},
  {GW_PARF,0x2c4},{GW_PARF,0x4d0},{GW_PARF,0x4d4},{GW_PARF,0x1000},
  {GW_PHY,0x200},{GW_PHY,0x240},{GW_PHY,0x244},{GW_PHY,0xed0},
  {GW_PHY,0x16d0},{GW_PHY,0xedc},{GW_PHY,0x16dc},{GW_PHY,0x11e0},{GW_PHY,0x19e0}
};
#endif
