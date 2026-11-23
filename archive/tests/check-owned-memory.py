#!/usr/bin/env python3
"""Run the loader's full-word pattern loop with corruption and boundary cases."""
from pathlib import Path
import hashlib
import json
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1] / 'native/high-memory'
header = (root / 'OwnedMemoryTest.h').read_bytes()
assert hashlib.sha256(header).hexdigest() == json.loads(
    (root / 'manifest.json').read_text())['owned_test_sha256']
program = r'''
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
HEADER
static unsigned flushes, corrupt;
static void flush(void *p, unsigned long long n) {
  assert(n == 2*1024*1024); ++flushes;
  if (corrupt) ((unsigned long long *)p)[n/8-1] ^= 1;
}
int main(void) {
  void *p = malloc(2*1024*1024); assert(p);
  assert(DarwinTestOwnedMemory(p,2*1024*1024/8,flush)); assert(flushes==2);
  corrupt=1; assert(!DarwinTestOwnedMemory(p,2*1024*1024/8,flush));
  assert(!DarwinTestOwnedMemory(0,1,flush));
  assert(!DarwinTestOwnedMemory(p,0,flush));
  assert(!DarwinTestOwnedMemory(p,0x40000001ULL,flush));
  assert(!DarwinTestOwnedMemory(p,1,0));
  free(p); puts("Full pattern loop, corruption and bounds PASS");
}
'''.replace('HEADER', header.decode())
with tempfile.TemporaryDirectory() as directory:
    source = Path(directory) / 'check.c'
    binary = Path(directory) / 'check'
    source.write_text(program)
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
