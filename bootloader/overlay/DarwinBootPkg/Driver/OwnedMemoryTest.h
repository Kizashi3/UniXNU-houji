// SPDX-License-Identifier: BSD-2-Clause-Patent
#ifndef DARWINBOOT_OWNED_MEMORY_TEST_H
#define DARWINBOOT_OWNED_MEMORY_TEST_H

// Called only after AllocateAddress owns the entire range. Address-dependent
// patterns detect aliasing; flushing each pass forces the reads through PoC.
static inline int DarwinTestOwnedMemory(volatile unsigned long long *words,
    unsigned long long count,
    void (*flush)(void *, unsigned long long)) {
  if (!words || !count || count > 0x40000000ULL || !flush) return 0;
  for (unsigned pass = 0; pass < 2; ++pass) {
    unsigned long long seed = pass ? 0xa55a0ff0f00f5aa5ULL : 0x5aa5f00f0ff0a55aULL;
    for (unsigned long long i = 0; i < count; ++i)
      words[i] = seed ^ (unsigned long long)(words + i);
    flush((void *)words, count * sizeof(*words));
    for (unsigned long long i = 0; i < count; ++i)
      if (words[i] != (seed ^ (unsigned long long)(words + i))) return 0;
  }
  return 1;
}
#endif
