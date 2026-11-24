from hashlib import sha256
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
BASE = Path(sys.argv[1])
OUT = Path(sys.argv[2])
src = BASE.read_bytes()
assert sha256(src).hexdigest() == "d3f76cb87ec50b94c497f461683df64c353883fa101c05bb13f32663ddf3713f"

segments = []
pos = 32
for _ in range(struct.unpack_from("<I", src, 16)[0]):
    typ, size = struct.unpack_from("<II", src, pos)
    if typ == 0x19:
        _, va, _, off, filesz = struct.unpack_from("<16sQQQQ", src, pos + 8)
        segments.append((va, off, filesz))
    pos += size

def location(addr, size):
    matches = [off + addr-va for va, off, fs in segments if va <= addr <= addr+size <= va+fs]
    assert len(matches) == 1
    return matches[0]

def extract(addr, size):
    start = location(addr, size)
    return src[start:start+size]

descriptor = extract(0xfffffff007041cc8, 0x277)
assert descriptor[:8] == bytes.fromhex("05 0d 09 04 a1 01 85 03") and descriptor[-1] == 0xc0
# Retain report 3 byte for byte. Report 2 contains three Consumer retentive bits.
consumer = bytes.fromhex(
    "05 0c 09 01 a1 01 85 02 09 30 09 e9 09 ea 15 00 25 01 "
    "75 01 95 03 81 02 75 05 95 01 81 03 c0"
)
(ROOT / "descriptor.bin").write_bytes(descriptor + consumer)

def run(*args):
    return subprocess.check_output(args, cwd=ROOT, text=True)

run("clang", "--target=aarch64-none-elf", "-mno-outline-atomics", "-mgeneral-regs-only",
    "-ffreestanding", "-fno-stack-protector", "-fno-unwind-tables", "-fno-pic",
    "-Wall", "-Wextra", "-Werror", "-Oz", "-c", "keys.c", "-o", "keys.o")
run("clang", "--target=aarch64-none-elf", "-c", "keys-hooks.S", "-o", "keys-hooks.o")
run("clang++", "--target=aarch64-none-elf", "-mgeneral-regs-only",
    "-ffreestanding", "-fno-exceptions", "-fno-rtti", "-fno-stack-protector",
    "-fno-unwind-tables", "-fno-pic", "-Wall", "-Wextra", "-Werror", "-Oz",
    "-c", "panel.cpp", "-o", "panel.o")
run("ld.lld", "-T", "keys.ld", "--no-undefined", "--fatal-warnings", "keys.o", "keys-hooks.o", "panel.o", "-o", "keys.elf")
run("llvm-objcopy", "--only-section=.payload", "-O", "binary", "keys.elf", "payload.bin")
symbols = {}
for row in run("llvm-nm", "-n", "keys.elf").splitlines():
    address, _, name = row.split()
    symbols[name] = int(address, 16)
payload = (ROOT / "payload.bin").read_bytes()
assert len(payload) <= 0x35b0 and payload.endswith(consumer)
buf = bytearray(src)
changes = []

def patch(addr, before, raw):
    assert len(raw) == len(before) and extract(addr, len(raw)) == before, hex(addr)
    i = location(addr, len(raw))
    changes.append((i, i+len(raw)))
    buf[i:i+len(raw)] = raw

def branch(addr, target):
    diff = symbols[target] - addr
    assert diff % 4 == 0 and -0x8000000 <= diff < 0x8000000
    return struct.pack("<I", 0x14000000 | ((diff >> 2) & 0x3ffffff))

for addr, expected, target in (
    (0xfffffff0079cb704, "80bbffb0", "keys_start_hook"),
    (0xfffffff00796a29c, "9f3f03d5", "present_done_hook"),
    (0xfffffff00796b024, "fc6fbca9", "display_observe_hook"),
    (0xfffffff0079caeb4, "a0b3fff0", "keys_descriptor_hook"),
):
    patch(addr, bytes.fromhex(expected), branch(addr, target))
patch(0xfffffff007a6ca50, bytes(len(payload)), payload)
last = 0
for start, end in sorted(changes):
    assert last <= start and buf[last:start] == src[last:start]
    last = end
assert buf[last:] == src[last:]
with OUT.open("xb") as out:
    out.write(buf)
print(f"{sha256(buf).hexdigest()} {OUT}")
