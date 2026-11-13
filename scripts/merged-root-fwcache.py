"""Pack/unpack the 20H392 firmware DMGs for the release-based CI cache.

Release assets are capped at 2 GiB, so the 7.5 GB OS dmg is split into
1900 MiB chunks plus a manifest; the workflow downloads the release and
rebuilds the exact DMGs before the merge.

Usage: merged-root-fwcache.py pack SRC STAGE
       merged-root-fwcache.py unpack STAGE SRC
"""
import json
import pathlib
import shutil
import sys

CHUNK = 1900 << 20


def pack(src, stage):
    src = pathlib.Path(src)
    stage = pathlib.Path(stage)
    stage.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for dmg in sorted((src / "ipsw" / "20H392").glob("*.dmg")):
        parts = []
        with dmg.open("rb") as f:
            idx = 0
            while True:
                chunk = f.read(CHUNK)
                if not chunk:
                    break
                p = stage / f"{dmg.name}.{idx:02d}"
                p.write_bytes(chunk)
                parts.append(p.name)
                idx += 1
        manifest[dmg.name] = parts
        print("split", dmg.name, parts)
    (stage / "manifest.json").write_text(json.dumps(manifest, indent=1))
    shutil.copyfile(src / "system-inputs.json", stage / "system-inputs.json")


def unpack(stage, src):
    stage = pathlib.Path(stage)
    src = pathlib.Path(src)
    manifest = json.loads((stage / "manifest.json").read_text())
    out = src / "ipsw" / "20H392"
    out.mkdir(parents=True, exist_ok=True)
    for name, parts in manifest.items():
        target = out / name
        with target.open("wb") as f:
            for part in parts:
                with (stage / part).open("rb") as g:
                    shutil.copyfileobj(g, f, 16 << 20)
        print("rebuilt", name, target.stat().st_size)
    shutil.copyfile(stage / "system-inputs.json", src / "system-inputs.json")


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "pack":
        pack(sys.argv[2], sys.argv[3])
    elif mode == "unpack":
        unpack(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit("pack|unpack")
