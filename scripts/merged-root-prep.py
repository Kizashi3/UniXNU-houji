import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
out = pathlib.Path(sys.argv[2])
cache = root / "ipsw" / "20H392"
recs = json.loads((root / "system-inputs.json").read_text())
os_dmg = sys_dmg = None
for r in recs:
    name = pathlib.Path(r["member"]).name
    if r["component"] == "OS":
        os_dmg = cache / name
    elif str(r["component"]).startswith("Cryptex1,SystemOS"):
        sys_dmg = cache / name
assert os_dmg and os_dmg.is_file(), os_dmg
assert sys_dmg and sys_dmg.is_file(), sys_dmg
out.write_text(f"{os_dmg}\n{sys_dmg}\n")
print("OS dmg:", os_dmg)
print("SystemOS dmg:", sys_dmg)
