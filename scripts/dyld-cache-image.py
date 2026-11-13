"""Resolve a dyld shared cache virtual address to its image and offset.

usage: dyld-cache-image.py CACHE_BASE_FILE VA [VA...]

Three image-table layouts are tried and the one with the most plausible
entries wins:
  A. dyld_cache_image_text_info array  (header +0x88 offset, +0x90 count, 40 B)
  B. dyld_cache_image_info array       (header +0x1C0/+0x1C4, 32 B)
  C. legacy dyld_cache_image_info      (header +0x18/+0x1C, 32 B)
"""
import pathlib
import struct
import sys

NUL = bytes([0])
LO = 0x180000000
HI = 0x1C0000000


def valid_images(entries):
    good = 0
    for load, size, name in entries:
        if LO <= load < HI and 0 < size < 0x10000000 and name.startswith("/"):
            good += 1
    return good


def parse_text_table(f, off, cnt, fsize):
    if not off or not cnt or cnt > 20000 or off + cnt * 40 > fsize:
        return []
    f.seek(off)
    table = f.read(cnt * 40)
    out = []
    for i in range(cnt):
        uuid = table[i * 40:i * 40 + 16]
        load, size, po, pad = struct.unpack_from("<QQII", table, i * 40 + 16)
        name = read_path(f, po, fsize)
        out.append((load, size, name))
    return out


def parse_image_array(f, off, cnt, fsize):
    if not off or not cnt or cnt > 20000 or off + cnt * 32 > fsize:
        return []
    f.seek(off)
    table = f.read(cnt * 32)
    out = []
    for i in range(cnt):
        load, mtime, ino, po, pad = struct.unpack_from("<QQQII", table, i * 32)
        name = read_path(f, po, fsize)
        out.append((load, 0x800000, name))
    return out


def read_path(f, po, fsize):
    if not po or po >= fsize:
        return ""
    f.seek(po)
    raw = f.read(256)
    return raw.split(NUL, 1)[0].decode("utf-8", "replace")


def tables_of(path):
    fsize = path.stat().st_size
    with open(path, "rb") as f:
        head = f.read(0x400)
        if head[:7] != b"dyld_v1":
            return []
        cands = []
        text_off, text_cnt = struct.unpack_from("<QQ", head, 0x88)
        cands.append(("text@0x88", parse_text_table(f, text_off, text_cnt, fsize)))
        new_off, new_cnt = struct.unpack_from("<II", head, 0x1C0)
        cands.append(("images@0x1C0", parse_image_array(f, new_off, new_cnt, fsize)))
        old_off, old_cnt = struct.unpack_from("<II", head, 0x18)
        cands.append(("images@0x18", parse_image_array(f, old_off, old_cnt, fsize)))
        best = None
        for tag, entries in cands:
            score = valid_images(entries)
            print("candidate %s: %d entries, %d plausible" % (tag, len(entries), score))
            if entries and (best is None or score > best[0]):
                best = (score, tag, entries)
        if best is None:
            return []
        print("using %s (%d plausible)" % (best[1], best[0]))
        return best[2]


def main():
    base = pathlib.Path(sys.argv[1])
    vas = [int(x, 0) for x in sys.argv[2:]]
    files = [base] + sorted(base.parent.glob(base.name + ".*"))
    tables = []
    for f in files:
        if not f.is_file():
            continue
        try:
            table = tables_of(f)
        except OSError:
            table = []
        if table:
            tables.append((f.name, table))
    for va in vas:
        hit = None
        for fname, table in tables:
            for load, size, name in table:
                if load <= va < load + size:
                    hit = (fname, name, va - load)
                    break
            if hit:
                break
        if hit:
            print("VA %#x -> %s (%s) + %#x" % (va, hit[1] or "<no name>", hit[0], hit[2]))
        else:
            print("VA %#x -> not found" % va)


if __name__ == "__main__":
    main()
