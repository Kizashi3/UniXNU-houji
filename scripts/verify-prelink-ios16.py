#!/usr/bin/env python3
"""Regression checks against the pinned iPhone X 20H392 kernelcache."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import tomllib

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--kit", required=True, type=Path)
parser.add_argument("--kernelcache", required=True, type=Path)
parser.add_argument("--board", required=True, type=Path)
parser.add_argument("--output", type=Path)
args = parser.parse_args()
sys.path.insert(0, str(args.kit.resolve()))
import emit_prelink as ep
from native_prelink import backed_offset, macho, unserialize_xml

EXPECTED_CACHE = "2ec297bac95bcba01046fd0148e97e7e5885c05a6c18827f39f534ba375c1221"
POOL_DIGEST = "73df5b757c53532583e3686b7d93df11ec1f5dd8c201d05502654a7812cc385f"
INIT_DIGEST = "3a7c782c190e6615797d7b2bc2471e4e5d8599e6d5cc7e539d21305943760551"
data = args.kernelcache.read_bytes()
assert hashlib.sha256(data).hexdigest() == EXPECTED_CACHE, "Unexpected kernelcache"
config = tomllib.loads(args.board.read_text())["kernel"]["prelink"]
assert config["early_security_init"] == "com.apple.driver.AppleMobileFileIntegrity=0xfffffff005703c54"
parent = macho(data)["segments"]
info = next(s for s in parent if s["name"] == "__PRELINK_INFO")
at = backed_offset(parent, info["va"], info["filesize"], len(data))
metadata = unserialize_xml(data[at:at + info["filesize"]])
entries = {e["CFBundleIdentifier"]: e for e in metadata["_PrelinkInfoDictionary"]}
pending, seen, modules = list(config["roots"]), set(), {}
while pending:
    name = pending.pop()
    if name in seen:
        continue
    seen.add(name)
    entry = entries[name]
    if entry.get("OSKernelResource"):
        continue
    pending.extend(entry.get("OSBundleLibraries") or {})
    if entry.get("_PrelinkExecutableLoadAddr"):
        at = backed_offset(parent, entry["_PrelinkExecutableLoadAddr"], 32, len(data))
        modules[name] = macho(data, at)

def must_reject(blob, marker):
    try:
        ep.instruction_inventory(blob, parent, modules)
    except ValueError as error:
        assert marker in str(error), str(error)
        return str(error)
    raise AssertionError("Unexpectedly accepted an unrecognized/external encoding")

pools = ep.MATH_LITERAL_POOLS
try:
    ep.MATH_LITERAL_POOLS = tuple(p for p in pools if p[2] != POOL_DIGEST)
    reproduced = must_reject(data, "0xfffffff005b8c1cc")
finally:
    ep.MATH_LITERAL_POOLS = pools
report = ep.instruction_inventory(data, parent, modules)
pool = next(item for item in report["known_inline_data"] if item["sha256"] == POOL_DIGEST)
assert pool["module"] == "com.apple.kec.Libm"
assert (pool["va"], pool["size"]) == (0xfffffff005b8c054, 1228)
# Keep prefix and the problematic encoding intact. A change elsewhere in the
# table must invalidate the full digest and bring back the original rejection.
mutated = bytearray(data)
at = backed_offset(parent, pool["va"] + 32, 1, len(data))
mutated[at] ^= 1
digest_guard = must_reject(bytes(mutated), "0xfffffff005b8c1cc")
# Ensure the instruction immediately after the table is still checked.
after_pool = pool["va"] + pool["size"]
assert after_pool == 0xfffffff005b8c520
mutated = bytearray(data)
at = backed_offset(parent, after_pool, 4, len(data))
struct.pack_into("<I", mutated, at, 0x15ffffff)  # branch far outside selected extents
boundary_guard = must_reject(bytes(mutated), hex(after_pool))
init = 0xfffffff005703c54
amfi = modules["com.apple.driver.AppleMobileFileIntegrity"]
assert entries["com.apple.driver.AppleMobileFileIntegrity"]["AppleSecurityExtension"] is True
assert any(s["name"] == "__TEXT_EXEC" and s["initprot"] == 5 and
           s["va"] <= init < init + 0x420 <= s["va"] + s["filesize"]
           for s in amfi["segments"])
at = backed_offset(parent, init, 0x420, len(data))
assert hashlib.sha256(data[at:at + 0x420]).hexdigest() == INIT_DIGEST
result = {
    "kernelcache_sha256": EXPECTED_CACHE, "components": len(modules),
    "original_failure_reproduced": reproduced,
    "constant_table_digest_guard": digest_guard,
    "next_function_still_checked": boundary_guard,
    "instruction_inventory": report,
    "early_security_initializer": hex(init),
    "initializer_bytes_sha256": INIT_DIGEST,
    "runtime_qualified": False,
}
text = json.dumps(result, indent=2) + "\n"
if args.output:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text)
print(f"PASS: {len(modules)} components, {report['pc_relative_encodings_preserved']} PC-relative encodings; digest/boundary/initializer checks")
