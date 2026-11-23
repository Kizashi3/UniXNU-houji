/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * App-owned diagnostic text only. No claim to capture other images' DebugLib.
 * Append never allocates, calls Boot Services or performs I/O, including in BRK.
 */
STATIC CHAR8 mProbeLog[512 * 1024];
STATIC UINTN mProbeLogLength;
STATIC BOOLEAN mProbeLogTruncated, mProbeLogFrozen;

STATIC VOID
ProbeLogAppend (CONST UINT8 *Bytes, UINTN Length)
{
  if (mProbeLogFrozen) { return; }
  UINTN Available = sizeof (mProbeLog) - mProbeLogLength;
  if (Length > Available) { Length = Available; mProbeLogTruncated = TRUE; }
  CopyMem (mProbeLog + mProbeLogLength, Bytes, Length);
  mProbeLogLength += Length;
}

// Normal stopped-report context only. Export the existing app-owned append
// buffer to other translation units without invoking ConOut or SerialPortLib.
// The maximum-width line is 134 bytes including LF; the buffer has headroom.
VOID EFIAPI
ProbeTraceAppendRecord (UINT64 Sequence, UINT32 Step, UINT64 Counter,
                        UINT64 Address, UINT64 Value)
{
  if (mProbeLogFrozen || mProbeLogTruncated) { return; }
  CHAR8 Text[192];
  UINTN Length = AsciiSPrint (Text, sizeof (Text),
    "HOUJI GPU CALL: seq=%lu step=%u counter=%lu address=%016lx value=%016lx\n",
    Sequence, Step, Counter, Address, Value);
  if (Length >= sizeof (Text)) { mProbeLogTruncated = TRUE; return; }
  ProbeLogAppend ((CONST UINT8 *)Text, Length);
}

UINTN EFIAPI
ProbePrint (CONST CHAR16 *Format, ...)
{
  CHAR16 Text[2048];
  VA_LIST Args;
  VA_START (Args, Format);
  UINTN Length = UnicodeVSPrint (Text, sizeof (Text), Format, Args);
  VA_END (Args);
  for (UINTN I = 0; I < Length; I++) {
    UINT8 Ch = Text[I] <= 0x7F ? (UINT8)Text[I] : '?';
    ProbeLogAppend (&Ch, 1);
  }
  // In the SQE critical RAM-only profile, retain the message above but avoid
  // ConOut's framebuffer/cache path. A stopped recorder/fatal still displays.
  if (!HoujiGpuCallTraceConsoleSuppressed () && gST->ConOut) {
    gST->ConOut->OutputString (gST->ConOut, Text);
  }
  return Length;
}

STATIC UINTN EFIAPI
ProbeSerialWrite (UINT8 *Bytes, UINTN Length)
{
  ProbeLogAppend (Bytes, Length);
  return SerialPortWrite (Bytes, Length);
}

#define Print ProbePrint
#define SerialPortWrite ProbeSerialWrite
