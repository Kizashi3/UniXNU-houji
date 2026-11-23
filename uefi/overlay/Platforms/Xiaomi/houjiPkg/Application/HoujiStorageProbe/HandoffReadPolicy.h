/* SPDX-License-Identifier: BSD-2-Clause-Patent */
STATIC BOOLEAN
HandoffAddressAllowed (UINT64 Address)
{
  return !(Address & 3) && ((Address >= 0x01D84000 && Address < 0x01D87000) ||
    (Address >= 0x15000000 && Address < 0x150D0000));
}

STATIC BOOLEAN
HandoffFaultExpected (BOOLEAN Armed, UINT64 ExpectedPc, UINT64 Address,
                       UINT64 Pc, UINT64 Esr, UINT64 Far, UINT32 Instruction)
{
  // Same-EL synchronous external read abort, valid FAR, not a page-table walk.
  return Armed && HandoffAddressAllowed (Address) && ExpectedPc == Pc && Far == Address &&
    ((Esr >> 26) & 0x3F) == 0x25 && (Esr & 0x7FF) == 0x10 &&
    Instruction == 0xB9400000U; // exact LDR W0,[X0]
}
