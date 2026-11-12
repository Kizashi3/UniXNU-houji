"""Stream an APFS volume into fixed-size parts.

Accepts either a raw volume on stdin ("-") or a GPT disk image / bare volume
path. Stdin mode is used with `dd` from the attached APFS slice, so no full
9.5 GiB intermediate file is ever created and no GPT parsing is involved.

Usage: merged-root-extract.py SRC|- OUTDIR [PART_MIB] [REPORT] [RUN]
"""
import hashlib
import json
import os
import pathlib
import struct
import sys

src = sys.argv[1]
outdir = pathlib.Path(sys.argv[2])
part_mib = int(sys.argv[3]) if len(sys.argv) > 3 else 1900
report_path = pathlib.Path(sys.argv[4]) if len(sys.argv) > 4 else None
run = sys.argv[5] if len(sys.argv) > 5 else ""
APFS_TYPE = bytes.fromhex("ef57347c0000aa11aa1100306543ecac")

base = 0
left = None
if src == "-":
    reader = sys.stdin.buffer
    print("streaming stdin")
else:
    size = os.path.getsize(src)
    print("source", src, size, "bytes")
    with open(src, "rb") as f:
        head = f.read(1 << 20)
    total = None
    if head[512:520] == b"EFI PART":
        entry_lba, = struct.unpack_from("<Q", head, 512 + 0x48)
        count, = struct.unpack_from("<I", head, 512 + 0x50)
        esize, = struct.unpack_from("<I", head, 512 + 0x58)
        with open(src, "rb") as f:
            f.seek(entry_lba * 512)
            table = f.read(count * esize)
        for i in range(count):
            e = table[i * esize:(i + 1) * esize]
            if e[:16] == APFS_TYPE:
                start_lba, = struct.unpack_from("<Q", e, 0x20)
                blocks, = struct.unpack_from("<Q", e, 0x28)
                cand = start_lba * 512
                with open(src, "rb") as f:
                    f.seek(cand + 32)
                    if f.read(4) == b"NXSB":
                        base = cand
                        f.seek(cand + 36)
                        block_size, = struct.unpack("<I", f.read(4))
                        f.seek(cand + 40)
                        block_count, = struct.unpack("<Q", f.read(8))
                        total = block_size * block_count
                        print("GPT APFS partition at", cand, "container", total)
                        break
    if total is None and head[32:36] == b"NXSB":
        block_size, = struct.unpack_from("<I", head, 36)
        block_count, = struct.unpack_from("<Q", head, 40)
        total = block_size * block_count
        print("bare APFS volume", total)
    if total is None:
        print("FATAL: no APFS superblock in", src, "first8", head[:8].hex())
        sys.exit(1)
    if total > size - base:
        print("FATAL: container", total, "exceeds file remainder", size - base)
        sys.exit(1)
    left = total
    f = open(src, "rb")
    f.seek(base)
    reader = f

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
    print("closed", part.name, part_bytes, flush=True)
    part = None
    part_bytes = 0
    part_digest = None


while True:
    want = 8 << 20 if left is None else min(8 << 20, left)
    if want <= 0:
        break
    chunk = reader.read(want)
    if not chunk:
        break
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
    if left is not None:
        left -= len(chunk)
    if written % (1 << 30) < (8 << 20):
        print("streamed", written, flush=True)
close_part()

if left not in (None, 0):
    print("FATAL: short stream, left", left)
    sys.exit(1)
if written < (1 << 30):
    print("FATAL: stream too small", written)
    sys.exit(1)

report = {
    "bytes": written,
    "sha256": digest.hexdigest(),
    "run": run,
    "part_mib": part_mib,
    "parts": parts,
}
if report_path is not None:
    report_path.write_text(json.dumps(report, indent=1) + "\n")
print(json.dumps(report, indent=1))
print("SPLIT_DONE", written)
