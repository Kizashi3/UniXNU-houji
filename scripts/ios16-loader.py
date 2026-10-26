"""Apply the Darwin 22 boot ABI to a separate DarwinBoot source checkout."""
import argparse
from pathlib import Path

def replace(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f'Loader source drift: {old}')
    return text.replace(old, new)

def main():
    p = argparse.ArgumentParser()
    p.add_argument('driver', type=Path)
    args = p.parse_args()
    header = args.driver / 'BootArgs.h'
    source = args.driver / 'DarwinBoot.c'
    h, c = header.read_text(), source.read_text()
    for old, new in [('Darwin 23', 'Darwin 22'), ('CommandLine[1024]', 'CommandLine[608]'),
                     ('== 0x478', '== 0x2d8'), ('== 0x480', '== 0x2e0')]:
        h = replace(h, old, new)
    c = replace(c, 'CommandLine[1024]', 'CommandLine[608]')
    c = replace(c, '#define BLOCK_SIZE   SIZE_2MB', '#define BLOCK_SIZE   SIZE_32MB')
    c = replace(c, '  if (!Executable || (Kernel->Entry & 3)',
                '  Kernel->Base &= ~((UINT64)SIZE_32MB - 1);\n  if (!Executable || (Kernel->Entry & 3)')
    c = replace(c, '(Kernel->Base & EFI_PAGE_MASK)', '(Kernel->Base & (SIZE_16KB - 1))')
    c = replace(c, 'TreeAddress = ArgsAddress + EFI_PAGE_SIZE;', 'TreeAddress = ArgsAddress + SIZE_16KB;')
    c = replace(c, 'ALIGN_VALUE (TreeAddress + TreeSize, EFI_PAGE_SIZE)',
                'ALIGN_VALUE (TreeAddress + TreeSize, SIZE_16KB)')
    c = replace(c, 'ALIGN_VALUE (KeepPacked ? Request->RamdiskSize : RamdiskExpandedSize, EFI_PAGE_SIZE)',
                'ALIGN_VALUE (KeepPacked ? Request->RamdiskSize : RamdiskExpandedSize, SIZE_16KB)')
    c = replace(c, 'UINT64 *WindowSize, BOOLEAN *KeepPacked)',
                'UINT64 *WindowSize, BOOLEAN *KeepPacked, UINTN *DramBaseOffset, UINTN *DramSizeOffset)')
    c = replace(c, '  UINTN  MemoryCandidate;',
                '  UINTN  MemoryCandidate;\n  UINTN  DramBaseCandidate;\n  UINTN  DramSizeCandidate;')
    c = replace(c, '  MemoryCandidate = MAX_UINTN;',
                '  MemoryCandidate = MAX_UINTN;\n  DramBaseCandidate = MAX_UINTN;\n  DramSizeCandidate = MAX_UINTN;')
    c = replace(c, '    *Offset += Length;', '''    if (AsciiStrCmp ((CONST CHAR8 *)(Data + *Offset - 36), "dram-base") == 0) {
      if ((DramBaseCandidate != MAX_UINTN) || (Length != 8)) { return FALSE; }
      DramBaseCandidate = *Offset;
    }
    if (AsciiStrCmp ((CONST CHAR8 *)(Data + *Offset - 36), "dram-size") == 0) {
      if ((DramSizeCandidate != MAX_UINTN) || (Length != 8)) { return FALSE; }
      DramSizeCandidate = *Offset;
    }
    *Offset += Length;''')
    c = replace(c, '  if (MemoryCandidate != MAX_UINTN) {', '''  if (DramBaseCandidate != MAX_UINTN) {
    if ((Path != 1) || (*DramBaseOffset != MAX_UINTN) || (U64 (Data + DramBaseCandidate) != 0)) { return FALSE; }
    *DramBaseOffset = DramBaseCandidate;
  }
  if (DramSizeCandidate != MAX_UINTN) {
    if ((Path != 1) || (*DramSizeOffset != MAX_UINTN) || (U64 (Data + DramSizeCandidate) != 0)) { return FALSE; }
    *DramSizeOffset = DramSizeCandidate;
  }
  if (MemoryCandidate != MAX_UINTN) {''')
    c = replace(c, 'WindowSize, KeepPacked))',
                'WindowSize, KeepPacked, DramBaseOffset, DramSizeOffset))')
    c = replace(c, '  UINTN                           TrustCacheOffset;',
                '  UINTN                           TrustCacheOffset;\n  UINTN                           DramBaseOffset;\n  UINTN                           DramSizeOffset;')
    c = replace(c, '  TrustCacheOffset = MAX_UINTN;',
                '  TrustCacheOffset = MAX_UINTN;\n  DramBaseOffset = MAX_UINTN;\n  DramSizeOffset = MAX_UINTN;')
    c = replace(c, '&WindowSize, &KeepPacked) || (Offset != TreeSize)',
                '&WindowSize, &KeepPacked, &DramBaseOffset, &DramSizeOffset) || (Offset != TreeSize) || '
                '(DramBaseOffset == MAX_UINTN) || (DramSizeOffset == MAX_UINTN)')
    c = replace(c, '  CopyMem ((VOID *)(UINTN)TreeAddress, Tree, TreeSize);', '''  CopyMem ((VOID *)(UINTN)TreeAddress, Tree, TreeSize);
  // Keep the ADT and boot_args consistent with the owned contiguous window.
  WriteUnaligned64 ((UINT64 *)(UINTN)(TreeAddress + DramBaseOffset), Args->PhysicalBase);
  WriteUnaligned64 ((UINT64 *)(UINTN)(TreeAddress + DramSizeOffset), Args->MemorySize);''')
    header.write_text(h)
    source.write_text(c)

if __name__ == '__main__':
    main()
