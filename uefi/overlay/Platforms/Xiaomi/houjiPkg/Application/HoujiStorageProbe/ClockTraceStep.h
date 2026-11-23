/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Pure control-flow emulation for the diagnostic's exact supported opcodes.
 * No register except PC and BL/BLR's LR is changed; NZCV and SP are untouched.
 */
STATIC BOOLEAN
ClockTraceStep (UINT32 Op, UINT64 Pc, UINT64 R0, UINT64 R8, UINT64 *NextPc, UINT64 *Lr)
{
  if ((Op & 0xFC000000U) == 0x94000000U) {
    // Sign extend imm26 without left-shifting a negative signed value.
    INT64 Offset = (INT64)(Op & 0x03FFFFFFU);
    if (Offset & 0x02000000) { Offset -= 0x04000000; }
    *NextPc = Pc + (UINT64)(Offset * 4);
    *Lr = Pc + 4;
    return TRUE;
  }
  if (Op == 0xD63F0100U) { // BLR X8, the original DAL HWIO call
    if (!R8 || (R8 & 3)) { return FALSE; }
    *NextPc = R8;
    *Lr = Pc + 4;
    return TRUE;
  }
  if ((Op & 0x7E00001FU) == 0x34000000U) { // CBZ/CBNZ W0 or X0
    INT64 Offset = (INT64)((Op >> 5) & 0x7FFFFU);
    if (Offset & 0x40000) { Offset -= 0x80000; }
    UINT64 Value = (Op & 0x80000000U) ? R0 : (UINT32)R0;
    BOOLEAN Taken = (Value != 0) == ((Op & 0x01000000U) != 0);
    *NextPc = Taken ? Pc + (UINT64)(Offset * 4) : Pc + 4;
    return TRUE;
  }
  return FALSE;
}
