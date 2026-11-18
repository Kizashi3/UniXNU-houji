import pathlib
import struct
import sys

src = pathlib.Path(sys.argv[1])
dst = pathlib.Path(sys.argv[2])

with src.open("rb") as f:
    head = f.read(2 << 20)

base = total = None
at = head.find(b"NXSB", 32)
if at > 0:
    base = at - 32
    block_size, = struct.unpack_from("<I", head, base + 36)
    block_count, = struct.unpack_from("<Q", head, base + 40)
    total = block_size * block_count
    print("APFS volume", total, "bytes; block", block_size, "count", block_count, "base", base)
elif head[1024:1026] in (b"H+", b"HX"):
    base = 0
    block_size, = struct.unpack_from(">I", head, 1024 + 40)
    total_blocks, = struct.unpack_from(">I", head, 1024 + 44)
    total = block_size * total_blocks
    print("HFS volume", total, "bytes; block", block_size, "count", total_blocks, "base", base)

if base is None:
    # hdiutil's GPT puts the APFS container behind an EFI System Partition, so the
    # superblock can sit well past the first 2 MiB.  Walk the GPT for the Apple_APFS
    # partition instead of guessing where the container starts.
    with src.open("rb") as f:
        f.seek(512)
        header = f.read(512)
        if header[:8] == b"EFI PART":
            entries_lba, = struct.unpack_from("<Q", header, 72)
            count, entry_size = struct.unpack_from("<II", header, 80)
            f.seek(entries_lba * 512)
            table = f.read(count * entry_size)
            apfs = bytes.fromhex("ef57347c0000aa11aa1100306543ecac")
            for i in range(count):
                entry = table[i * entry_size:(i + 1) * entry_size]
                if entry[:16] == apfs:
                    first, = struct.unpack_from("<Q", entry, 32)
                    last, = struct.unpack_from("<Q", entry, 40)
                    base = first * 512
                    total = (last - first + 1) * 512
                    f.seek(base + 32)
                    print("GPT APFS partition", total, "bytes at", base, "magic", f.read(4))
                    break

assert base is not None and total and 0 < total <= src.stat().st_size - base, (base, total)

with src.open("rb") as fi, dst.open("wb") as fo:
    fi.seek(base)
    left = total
    while left:
        b = fi.read(min(8 << 20, left))
        if not b:
            break
        fo.write(b)
        left -= len(b)
assert dst.stat().st_size == total, (dst.stat().st_size, total)
print("raw volume written:", dst, dst.stat().st_size)
