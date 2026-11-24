from hashlib import sha256
from pathlib import Path
from struct import unpack_from, pack_into
import sys

source, output = map(Path, sys.argv[1:])
original = source.read_bytes()
assert sha256(original).hexdigest() == "d2a04e8f4da925aac1d4ece59a92c7e77a944daef0de969b2c8c4d04f5b57094"
result = bytearray(original)
offset = 32
segments = {}
for _ in range(unpack_from("<I", original, 16)[0]):
    command, size = unpack_from("<II", original, offset)
    if command == 0x19:
        name, va, _, file_offset, file_size = unpack_from("<16sQQQQ", original, offset + 8)
        segments[name.rstrip(b"\0")] = (va, file_offset, file_size)
    offset += size
va, file_offset, file_size = segments[b"__TEXT_EXEC"]
start, end = 0xfffffff0079bbdd4, 0xfffffff0079bd024
assert va <= start < end <= va + file_size
sleep = 0xfffffff0078ac554
changes = []
for address in range(start, end-4, 4):
    index = file_offset + address - va
    load, branch = unpack_from("<II", original, index)
    if load not in (0x528ea600, 0x5282ee00) or branch >> 26 != 0b100101:
        continue
    relative = branch & 0x3ffffff
    relative -= (relative & 0x2000000) << 1
    if address + 4 + relative * 4 != sleep:
        continue
    delay = 1000 if load == 0x528ea600 else 100
    pack_into("<I", result, index, 0x52800000 | delay << 5)
    changes.append(address)
assert changes == [0xfffffff0079bbe10, 0xfffffff0079bbe24, 0xfffffff0079bbe5c,
                   0xfffffff0079bbebc, 0xfffffff0079bbf0c, 0xfffffff0079bc0cc,
                   0xfffffff0079bc104, 0xfffffff0079bc140, 0xfffffff0079bc198,
                   0xfffffff0079bc778, 0xfffffff0079bcbfc]
# Earlier HID publication also advances the start of the PMIC key worker.
# Keep its 20 ms sampler running across the full 300-second recovery trial.
key_limit = file_offset + 0xfffffff007a6cc60 - va
assert unpack_from("<I", original, key_limit)[0] == 0x52855f13
pack_into("<I", result, key_limit, 0x52800013 | 14000 << 5)
with output.open("xb") as file:
    file.write(result)
print(f"{sha256(result).hexdigest()} {output}")
