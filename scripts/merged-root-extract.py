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
