"""Resolve a dyld shared cache virtual address to its image and offset.

usage: dyld-cache-image.py CACHE_BASE_FILE VA [VA...]

CACHE_BASE_FILE is dyld_shared_cache_arm64 (the main file). Subcaches are
searched when the main file's image table does not cover the address.
"""
import pathlib
import struct
import sys

TEXT_INFO = struct.Struct("<16sQQII")


def images_of(path):
    with open(path, "rb") as f:
        head = f.read(0x400)
        if head[:7] != b"dyld_v1":
            return []
        text_off, = struct.unpack_from("<Q", head, 0x88)
        text_cnt, = struct.unpack_from("<Q", head, 0x90)
        if not text_off or not text_cnt or text_cnt > 20000:
            return []
        f.seek(text_off)
        table = f.read(text_cnt * TEXT_INFO.size)
        out = []
        for i in range(text_cnt):
            uuid, load_addr, text_size, path_off, _ = TEXT_INFO.unpack_from(table, i * TEXT_INFO.size)
            f.seek(path_off)
            raw = f.read(512)
            name = raw.split(b"\0", 1)[0].decode("utf-8", "replace")
            out.append((load_addr, text_size, name))
        return out


def main():
    base = pathlib.Path(sys.argv[1])
    vas = [int(x, 0) for x in sys.argv[2:]]
    files = [base] + sorted(base.parent.glob(base.name + ".*"))
    tables = []
    for f in files:
        if not f.is_file():
            continue
        try:
            table = images_of(f)
        except OSError:
            table = []
        if table:
            print(f"table {f.name}: {len(table)} images")
            tables.append((f, table))
    for va in vas:
        hit = None
        for f, table in tables:
            for load_addr, text_size, name in table:
                if load_addr <= va < load_addr + text_size:
                    hit = (name, va - load_addr)
                    break
            if hit:
                break
        if hit:
            print(f"VA {va:#x} -> {hit[0]} + {hit[1]:#x}")
        else:
            print(f"VA {va:#x} -> not found")


if __name__ == "__main__":
    main()
