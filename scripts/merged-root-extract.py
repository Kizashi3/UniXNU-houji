import pathlib
import struct
import sys

src = pathlib.Path(sys.argv[1])
dst = pathlib.Path(sys.argv[2])

with src.open("rb") as f:
    head = f.read(1 << 20)
at = head.find(b"NXSB", 32)
assert at > 0, "NXSB not found in the first MiB"
base = at - 32
with src.open("rb") as f:
    f.seek(base + 36)
    block_size, = struct.unpack("<I", f.read(4))
    f.seek(base + 40)
    block_count, = struct.unpack("<Q", f.read(8))
total = block_size * block_count
assert 0 < total <= src.stat().st_size - base, (total, base)
print("APFS volume", total, "bytes; block", block_size, "count", block_count, "base", base)
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
