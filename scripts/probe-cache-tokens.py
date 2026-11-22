#!/usr/bin/env python3
"""Find which prelinked image of a split dyld shared cache contains a string.

dyld_shared_cache_util cannot be relied on here, and the shipped cache is split
into per-region files, so this reads the region headers itself: every region file
starts with its own dyld_v1 header carrying address/size/fileOffset mappings, and
each cached Mach-O keeps its LC_ID_DYLIB install name in place.  A file offset is
therefore enough to name the owning image.

    probe-cache-tokens.py <cache dir> <report file> <regex of tokens>
"""
import mmap
import os
import re
import struct
import sys

MH_MAGIC_64 = 0xFEEDFACF
LC_ID_DYLIB = 0xD
LC_SEGMENT_64 = 0x19

CACHE_DIR = sys.argv[1]
REPORT = sys.argv[2]
TOKENS = sys.argv[3] if len(sys.argv) > 3 else (
    'SetupDone|SetupFinishedAllSteps|daemonizeNeedsToRun|ShouldRun\\w+MiniBuddy|'
    'should_hactivate|ActivationState|activation-state|IsActivated|isActivated|'
    'com\\.apple\\.springboard\\.setup-ui|LoginSession|BBSSetLoginSession|'
    'com\\.apple\\.mobileactivationd|bypassActivation|NeedsActivation|'
    'setupComplete|isSetupComplete|SetupVersion|SilentICDPUpgrade')

pat = re.compile(TOKENS.encode())
out = open(REPORT, 'w')


def log(*a):
    line = ' '.join(str(x) for x in a)
    print(line)
    out.write(line + '\n')
    out.flush()


def headers_of(mm):
    """[(file offset, vm address of the header, install name)] for cached Mach-O files."""
    found = []
    at = mm.find(b'\xcf\xfa\xed\xfe')
    while at >= 0:
        name = None
        try:
            magic, cputype, cpusub, filetype, ncmds, sizeofcmds, _flags, _res = struct.unpack_from(
                '<IiiIIIII', mm, at)
            if ncmds and ncmds < 512 and 32 < sizeofcmds < 0x40000:
                p = at + 32
                end = at + 32 + sizeofcmds
                for _ in range(ncmds):
                    if p + 8 > end or p + 32 > len(mm):
                        break
                    cmd, cmdsize = struct.unpack_from('<II', mm, p)
                    if cmdsize < 8 or cmdsize > 0x10000:
                        break
                    if cmd == LC_ID_DYLIB:
                        name = mm[p + 8:p + 160].split(b'\0')[0].decode('utf-8', 'replace')
                    p += cmdsize
        except struct.error:
            pass
        if name and name.startswith('/'):
            found.append((at, name))
        at = mm.find(b'\xcf\xfa\xed\xfe', at + 4)
    return found


def region_maps(mm, path):
    head = mm[:0x400]
    if head[:7] != b'dyld_v1':
        log('  %s: not a cache region' % os.path.basename(path))
        return []
    moff, mcnt = struct.unpack_from('<II', head, 0x10)
    maps = []
    for i in range(mcnt):
        a, s, o, mx, ini = struct.unpack_from('<QQQII', mm, moff + i * 32)
        maps.append((a, s, o))
    return maps


files = sorted(f for f in os.listdir(CACHE_DIR) if f.startswith('dyld_shared_cache_arm64'))
log('region files: %s' % files[:60])
total = 0
for name in files:
    path = os.path.join(CACHE_DIR, name)
    if os.path.getsize(path) < 0x1000:
        continue
    f = open(path, 'rb')
    mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    maps = region_maps(mm, path)
    if not maps:
        mm.close()
        f.close()
        continue
    hdrs = headers_of(mm)
    log('== %s size=%#x maps=%s macho=%d' % (name, len(mm),
                                             [(hex(a), hex(s)) for a, s, o in maps], len(hdrs)))
    offs = [h[0] for h in hdrs]
    import bisect

    def owner(off):
        i = bisect.bisect_right(offs, off) - 1
        return hdrs[i][1] if i >= 0 else '?'

    def va_of(off):
        for a, s, o in maps:
            if o <= off < o + s:
                return a + (off - o)
        return None

    seen = set()
    step = 64 << 20
    pos = 0
    while pos < len(mm):
        chunk = mm[pos:pos + step + 4096]
        for m in pat.finditer(chunk):
            off = pos + m.start()
            key = (m.group(0), owner(off))
            if key in seen:
                continue
            seen.add(key)
            va = va_of(off)
            total += 1
            if total > 4000:
                log('... output cap reached')
                break
            lo = max(0, m.start() - 60)
            log('  %-34s %-58s off=%#x va=%s' % (
                m.group(0).decode('utf-8', 'replace'), owner(off)[:58], off,
                hex(va) if va else '?'))
            log('      %r' % chunk[lo:m.start() + 90])
        if total > 4000:
            break
        pos += step
    mm.close()
    f.close()

log('total distinct token/owner pairs: %d' % total)
out.close()
