"""Slice the APFS volume out of a GPT disk image and stream it into parts.

Reads the Apple_APFS partition straight from the converted UDRW image and
writes fixed-size parts, so no second 9.5 GiB raw file is ever created (the
runner disk cannot hold DMGs + sparse + UDRW + raw + parts at once).

Usage: merged-root-extract.py SRC OUTDIR [PART_MIB] [REPORT] [RUN]
"""
import hashlib
import json
import os
import pathlib
import struct
import sys

src = pathlib.Path(sys.argv[1])
outdir = pathlib.Path(sys.argv[2])
part_mib = int(sys.argv[3]) if len(sys.argv) > 3 else 1900
report_path = pathlib.Path(sys.argv[4]) if len(sys.argv) > 4 else None
run = sys.argv[5] if len(sys.argv) > 5 else ""
APFS_TYPE = bytes.fromhex("ef57347c0000aa11aa1100306543ecac")

size = src.stat().st_size
print("source", src, size, "bytes")
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
                    print("GPT APFS partition at", cand, "container", total,
                          "partition bytes", blocks * 512, "block", block_size)
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
                print("scanned APFS volume at", cand, "container", total)
                break
        at = blob.find(b"NXSB", at + 4)

if base is None or not total:
    print("FATAL: no NXSB found; file", size, "first8", head[:8].hex())
    sys.exit(1)
if total > size - base:
    print("FATAL: container", total, "exceeds file remainder", size - base,
          "(base", base, "size", size, ")")
    sys.exit(1)

outdir.mkdir(parents=True, exist_ok=True)
limit = part_mib << 20
digest = hashlib.sha256()
parts = []
idx = 0
written = 0
part = None
part_bytes = 0
part_digest = None

def close_part():
    global part, part_bytes, part_digest
    if part is None:
        return
    part.close()
    parts.append({"name": part.name.split(os.sep)[-1], "bytes": part_bytes,
                  "sha256": part_digest.hexdigest()})
    print("closed", part.name, part_bytes)
    part = None
    part_bytes = 0
    part_digest = None

with src.open("rb") as fi:
    fi.seek(base)
    left = total
    while left:
        chunk = fi.read(min(8 << 20, left))
        if not chunk:
            print("FATAL: short read, left", left)
            sys.exit(1)
        off = 0
        while off < len(chunk):
            if part is None:
                part = (outdir / f"part-{idx:02d}").open("wb")
                part_digest = hashlib.sha256()
                idx += 1
            take = min(limit - part_bytes, len(chunk) - off)
            piece = chunk[off:off + take]
            part.write(piece)
            part_digest.update(piece)
            digest.update(piece)
            part_bytes += take
            written += take
            off += take
            if part_bytes >= limit:
                close_part()
        left -= len(chunk)
        if written % (512 << 20) < (8 << 20):
            print("streamed", written, "of", total, flush=True)
close_part()

assert written == total, (written, total)
for p in parts:
    assert (outdir / p["name"]).stat().st_size == p["bytes"]
report = {
    "bytes": total,
    "sha256": digest.hexdigest(),
    "run": run,
    "part_mib": part_mib,
    "parts": parts,
}
if report_path is not None:
    report_path.write_text(json.dumps(report, indent=1) + "\n")
print(json.dumps(report, indent=1))
print("SPLIT_DONE", written)
