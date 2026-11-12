"""Stream an APFS container into fixed-size parts.

Modes:
  merged-root-extract.py FILE OUTDIR [PART_MIB] [REPORT] [RUN]
  merged-root-extract.py - OUTDIR ...            # raw container on stdin
  merged-root-extract.py --devices dev1,dev2,... OUTDIR ...

Device mode opens each candidate (e.g. /dev/disk5s2 the Apple_APFS partition,
the APFS container node, or the whole disk) and locates the container
superblock (NXSB) at a 4096-aligned offset in the first 64 MiB. APFS volume
nodes such as /dev/disk6s1 refuse raw reads, so every candidate is tried.
"""
import hashlib
import json
import os
import pathlib
import struct
import sys


def locate(f):
    f.seek(0)
    head = f.read(1 << 20)
    if len(head) >= 4096 and head[32:36] == b"NXSB":
        bs, = struct.unpack_from("<I", head, 36)
        bc, = struct.unpack_from("<Q", head, 40)
        if bs in (4096, 16384) and bc:
            return 0, bs * bc, "bare"
    f.seek(0)
    blob = f.read(64 << 20)
    at = blob.find(b"NXSB", 32)
    while at > 0:
        cand = at - 32
        if cand % 4096 == 0:
            bs, = struct.unpack_from("<I", blob, cand + 36)
            bc, = struct.unpack_from("<Q", blob, cand + 40)
            if bs in (4096, 16384) and bc:
                return cand, bs * bc, "scanned"
        at = blob.find(b"NXSB", at + 4)
    return None


def main():
    src = sys.argv[1]
    if src == "--devices":
        outdir = pathlib.Path(sys.argv[3])
        part_mib = int(sys.argv[4]) if len(sys.argv) > 4 else 1900
        report_path = pathlib.Path(sys.argv[5]) if len(sys.argv) > 5 else None
        run = sys.argv[6] if len(sys.argv) > 6 else ""
        reader = None
        base = 0
        total = None
        for cand in sys.argv[2].split(","):
            cand = cand.strip()
            if not cand:
                continue
            try:
                f = open(cand, "rb")
            except OSError as e:
                print("candidate", cand, "open failed:", e)
                continue
            found = locate(f)
            if not found:
                head = (lambda g: (g.seek(0), g.read(64))[1])(f)
                print("candidate", cand, "no NXSB, first bytes", head[:8].hex())
                f.close()
                continue
            base, total, how = found
            print("using", cand, how, "base", base, "container", total)
            reader = f
            break
        if reader is None:
            print("FATAL: no candidate carried an APFS superblock")
            sys.exit(1)
        left = total
    else:
        outdir = pathlib.Path(sys.argv[2])
        part_mib = int(sys.argv[3]) if len(sys.argv) > 3 else 1900
        report_path = pathlib.Path(sys.argv[4]) if len(sys.argv) > 4 else None
        run = sys.argv[5] if len(sys.argv) > 5 else ""
        if src == "-":
            reader = sys.stdin.buffer
            print("streaming stdin")
            base = 0
            left = None
        else:
            size = os.path.getsize(src)
            print("source", src, size, "bytes")
            with open(src, "rb") as f:
                found = locate(f)
            if not found:
                print("FATAL: no APFS superblock in", src)
                sys.exit(1)
            base, total, how = found
            print("file", how, "base", base, "container", total)
            if base + total > size:
                print("FATAL: container exceeds file", base, total, size)
                sys.exit(1)
            f = open(src, "rb")
            reader = f
            left = total

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
        nonlocal part, part_bytes, part_digest
        if part is None:
            return
        part.close()
        parts.append({"name": part.name.split(os.sep)[-1], "bytes": part_bytes,
                      "sha256": part_digest.hexdigest()})
        print("closed", part.name, part_bytes, flush=True)
        part = None
        part_bytes = 0
        part_digest = None

    try:
        reader.seek(base)
    except (OSError, ValueError):
        pass
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
    if written < int(os.environ.get("HOUJI_MIN_BYTES", str(1 << 30))):
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


if __name__ == "__main__":
    main()

# run trigger
