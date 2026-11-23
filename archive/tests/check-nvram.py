#!/usr/bin/env python3
"""Validate the ADT proxy using checksum functions from the actual XNU source.

No kernel edits or device operations. Extracted Apple source is compiled only
in a temporary directory; it is not copied into the port repository.
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile


def function(source, name):
    start = source.index(name + '(')
    opening = source.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--xnu', type=Path, required=True)
    p.add_argument('--adt', type=Path, required=True)
    p.add_argument('--adt-tools', type=Path, required=True)
    a = p.parse_args()
    sys.path.insert(0, str(a.adt_tools))
    import adt
    tree, used = adt.parse(a.adt.read_bytes())
    assert used == a.adt.stat().st_size
    chosen = next(n for n in tree.children if n.name == 'chosen')
    assert chosen.prop('nvram-bank-size') == (8192).to_bytes(4, 'little')
    assert chosen.prop('nvram-bank-count') == (1).to_bytes(4, 'little')
    assert chosen.prop('nvram-current-bank') == bytes(4)
    image = chosen.prop('nvram-proxy-data')
    assert len(image) == 8192
    source = (a.xnu / 'iokit/Kernel/IONVRAMCHRPHandler.cpp').read_text()
    structs = source[source.index('typedef struct chrp_nvram_header'):source.index('typedef struct {')]
    program = r'''
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#define nullptr NULL
#define NVRAM_CHRP_APPLE_HEADER_NAME_V1 "nvram"
#define NVRAM_CHRP_APPLE_HEADER_NAME_V2 "2nvram"
#define kNVRAMVersion1 1
#define kNVRAMVersion2 2
#define kIOReturnError 1
#define kIOReturnSuccess 0
#define require(c, label) do { if (!(c)) goto label; } while (0)
#define DEBUG_INFO(...) ((void)0)
typedef int IOReturn;
'''
    program += structs
    for kind, name in [('const char *', 'get_bank_version_string'),
                       ('uint32_t', 'adler32'), ('uint32_t', 'adler32_with_version'),
                       ('uint8_t', 'chrp_checksum'), ('IOReturn', 'nvram_validate_header_v1v2')]:
        program += '\nstatic ' + kind + '\n' + function(source, name) + '\n'
    program += r'''
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "failed line %d\n", __LINE__); return 1; } } while(0)
int main(int argc, char **argv) {
    uint8_t buf[8192];
    CHECK(argc == 2);
    FILE *f = fopen(argv[1], "rb"); CHECK(f != NULL);
    CHECK(fread(buf, 1, sizeof(buf), f) == sizeof(buf)); CHECK(fgetc(f) == EOF); fclose(f);
    CHECK(nvram_validate_header_v1v2(buf, NULL, kNVRAMVersion1) == kIOReturnSuccess);
    CHECK(nvram_validate_header_v1v2(buf, NULL, kNVRAMVersion2) != kIOReturnSuccess);
    uint32_t stored; memcpy(&stored, buf + 16, 4);
    CHECK(stored == adler32_with_version(buf, sizeof(buf), kNVRAMVersion1));
    const char *names[] = {"nvram", "common", "free"};
    size_t at = 0;
    for (size_t i = 0; i < 3; i++) {
        CHECK(at + sizeof(chrp_nvram_header_t) <= sizeof(buf));
        const chrp_nvram_header_t *h = (const void *)(buf + at);
        CHECK(h->cksum == chrp_checksum(h)); CHECK(strcmp(h->name, names[i]) == 0);
        size_t length = h->len * 16;
        CHECK(length >= 16 && length <= sizeof(buf) - at);
        if (i == 1) CHECK(at == 32 && length - 16 == 2048);
        at += length;
    }
    CHECK(at == sizeof(buf));
    buf[100] ^= 1;
    CHECK(stored != adler32_with_version(buf, sizeof(buf), kNVRAMVersion1));
    buf[100] ^= 1; buf[1] ^= 1;
    CHECK(nvram_validate_header_v1v2(buf, NULL, kNVRAMVersion1) != kIOReturnSuccess);
    puts("Actual XNU CHRP validation passed: header checksums, Adler32, bounded partitions, common region, corruption rejection.");
    return 0;
}
'''
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        (temp / 'check.c').write_text(program)
        (temp / 'nvram.bin').write_bytes(image)
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-fsanitize=address,undefined',
                        str(temp / 'check.c'), '-o', str(temp / 'check')], check=True)
        subprocess.run([str(temp / 'check'), str(temp / 'nvram.bin')], check=True)


if __name__ == '__main__':
    main()
