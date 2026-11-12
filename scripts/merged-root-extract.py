"""Slice the raw APFS volume out of a GPT disk image (or a bare volume).

Locate the Apple_APFS partition through the GPT, fall back to scanning the
first 64 MiB for the NXSB superblock, then stream the volume out.
"""
import pathlib
import struct
import sys

src = pathlib.Path(sys.argv[1])
dst = pathlib.Path(sys.argv[2])
APFS_TYPE = bytes.fromhex("ef57347c0000aa11aa1100306543ecac")

with src.open("rb") as f:
    head = f.read(1 << 20)

base = total = None

# GPT: protective MBR at LBA0, header at LBA1.
if head[512:520] == b"EFI PART":
    entry_lba, = struct.unpack_from("<Q", head, 512 + 0x48)
    count, = struct.unpack_from("<I", head, 512 + 0x50)
    esize, = struct.unpack_from("<I", head, 512 + 0x58)
    with src.open("rb") as f:
        f.seek(entry_lba * 512)
        table = f.read(count * esize)
    for i in range(count):
        e = table[i * esize:(i + 1) * esize]
        if e[:16] == APFS_TYPE:
            start_lba, = struct.unpack_from("<Q", e, 0x20)
            blocks, = struct.unpack_from("<Q", e, 0x28)
            cand = start_lba * 512
            with src.open("rb") as f:
                f.seek(cand + 32)
                if f.read(4) == b"NXSB":
                    base = cand
                    f.seek(cand + 36)
                    block_size, = struct.unpack("<I", f.read(4))
                    f.seek(cand + 40)
                    block_count, = struct.unpack("<Q", f.read(8))
                    total = block_size * block_count
                    print("GPT APFS partition", cand, total, "blocks", blocks * 512)
                    break

if base is None:
    with src.open("rb") as f:
        blob = f.read(64 << 20)
    at = blob.find(b"NXSB", 32)
    while at > 0:
        cand = at - 32
        if cand % 4096 == 0:
            block_size, = struct.unpack_from("<I", blob, cand + 36)
            block_count, = struct.unpack_from("<Q", blob, cand + 40)
            if block_size == 4096 and block_count:
                base, total = cand, block_size * block_count
                print("scanned APFS volume", cand, total)
                break
        at = blob.find(b"NXSB", at + 4)

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
