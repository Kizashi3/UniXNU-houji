from hashlib import sha256
from pathlib import Path
import struct

stable = Path("../houji-v101/kernel-run734-apfs.macho").read_bytes()
lock = Path("../houji-v106-lock-policy/kernel-v106.macho").read_bytes()
intermediate = Path("kernel-panel-intermediate.macho").read_bytes()
assert len(stable) == len(lock) == len(intermediate) == 57618432
assert sha256(lock).hexdigest() == "45876212658230c2c1d1e9741a0a68b22e611497739175ad7fdff211466494cc"
start = 0x1c289
end = start + 503
assert stable[:start] == lock[:start] and stable[end:] == lock[end:]
assert intermediate[start:end] == stable[start:end]
result = bytearray(intermediate)
result[start:end] = lock[start:end]

# Reserve 24 bytes for the mailbox by extending the zero-filled section,
# entirely within the writable tail already included in the __DATA segment.
offset = 32
patched = False
for _ in range(struct.unpack_from("<I", result, 16)[0]):
    kind, size = struct.unpack_from("<II", result, offset)
    if kind == 0x19:
        segment, base, extent = struct.unpack_from("<16sQQ", result, offset + 8)
        if segment.rstrip(b"\x00") == b"__DATA":
            maximum = base + extent
            sections = struct.unpack_from("<I", result, offset + 64)[0]
            for index in range(sections):
                section = offset + 72 + index * 80
                name, _, address, length = struct.unpack_from("<16s16sQQ", result, section)
                if name.rstrip(b"\x00") == b"__bss":
                    flags = struct.unpack_from("<I", result, section + 64)[0]
                    assert flags & 0xff == 1 and index == sections - 1
                    assert address + length == 0xfffffff0083febb0
                    assert address + length + 24 <= maximum
                    assert result[section:section+80] == stable[section:section+80]
                    struct.pack_into("<Q", result, section + 40, length + 24)
                    patched = True
    offset += size
assert patched
with Path("kernel-wake-frame.macho").open("xb") as out:
    out.write(result)
print(sha256(result).hexdigest(), len(result))
