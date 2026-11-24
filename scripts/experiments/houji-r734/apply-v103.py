from hashlib import sha256
from pathlib import Path
from struct import unpack_from

old = Path("../houji-v101/kernel-keys.macho").read_bytes()
new = Path("trial-raw.macho").read_bytes()
stable = Path("../houji-v101/kernel-run734-apfs.macho").read_bytes()
assert len(old) == len(new) == len(stable) == 57618432
assert sha256(stable).hexdigest() == "400464b5cc422a027634f7c744a8ce29e9e56bb244cad47082f4e0a5e3514425"
segments = []
pos = 32
for _ in range(unpack_from("<I", stable, 16)[0]):
    kind, size = unpack_from("<II", stable, pos)
    if kind == 0x19:
        _, address, _, offset, filesz = unpack_from("<16sQQQQ", stable, pos + 8)
        segments.append((address, offset, filesz))
    pos += size

def locate(address, length):
    matches = [start + address - va for va, start, size in segments
               if va <= address and address + length <= va + size]
    offset, = matches
    return offset, offset + length

changes = [
    locate(0xfffffff00796a29c, 4),
    locate(0xfffffff00796b024, 4),
    locate(0xfffffff0079caeb4, 4),
    locate(0xfffffff0079cb704, 4),
    locate(0xfffffff007a6ca50, len(Path("payload.bin").read_bytes())),
]
result = bytearray(stable)
last = 0
for lo, hi in sorted(changes):
    assert last <= lo and old[last:lo] == new[last:lo]
    assert stable[lo:hi] == old[lo:hi], hex(lo)
    result[lo:hi] = new[lo:hi]
    last = hi
assert old[last:] == new[last:]
with Path("kernel-panel-intermediate.macho").open("xb") as out:
    out.write(result)
print(sha256(result).hexdigest(), len(result))
