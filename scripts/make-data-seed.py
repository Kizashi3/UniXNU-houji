"""Create a bigger APFS Data seed from the verified read-only OS attachment.

Fork of the upstream prepare-owner-data-fixture.py with three changes:
  * 512 MiB container instead of 32 MiB (services ran out of space at 32 MiB),
  * attached with ownership enabled and run as root, so the copied tree keeps
    the original uid/gid (mobile stays 501),
  * the runtime directory skeleton is completed explicitly.
"""
import argparse
import hashlib
import json
import os
import pathlib
import plistlib
import shutil
import stat
import subprocess

SIZE_MIB = 512
SIZE = SIZE_MIB << 20

p = argparse.ArgumentParser()
p.add_argument("--output", type=pathlib.Path, required=True)
args = p.parse_args()
fixture = args.output.resolve()
image = fixture / f"owner-data-{SIZE_MIB}.cdr"
if image.exists():
    raise SystemExit("Refuse to overwrite an existing Data seed")
source_root = pathlib.Path(".cache/firmware/target-volumes/os-mount")
if hashlib.sha256((source_root / "sbin/launchd").read_bytes()).hexdigest() != \
        "8cec9a3c44a443b08e977ccc5d577850316ad428c575dc01f09b018dbd5b6a25":
    raise SystemExit("Require the unchanged supplied original OS mount")
fixture.mkdir(parents=True, exist_ok=True)
subprocess.run(["hdiutil", "create", "-size", f"{SIZE_MIB}m", "-layout", "NONE", "-fs", "APFS",
                "-volname", "OwnerData", "-type", "UDTO", str(image)], check=True)
target = fixture / "mount"
target.mkdir(exist_ok=True)
attached = plistlib.loads(subprocess.check_output([
    "hdiutil", "attach", "-nobrowse", "-owners", "on",
    "-mountpoint", str(target), "-plist", str(image)]))
device = attached["system-entities"][0]["dev-entry"]
volume_uuid = None
count = total = 0
source = source_root / "private/var"
try:
    volumes = [e for e in attached["system-entities"] if e.get("mount-point") == str(target)]
    if len(volumes) != 1:
        raise SystemExit("Require exactly one newly formatted scratch volume")
    info = plistlib.loads(subprocess.check_output(["diskutil", "info", "-plist", volumes[0]["dev-entry"]]))
    volume_uuid = info["VolumeUUID"]

    def carry_owner(src, dst):
        st = os.stat(src, follow_symlinks=False)
        os.chown(dst, st.st_uid, st.st_gid, follow_symlinks=False)

    for current, dirs, files in os.walk(source, followlinks=False):
        dirs[:] = [name for name in dirs if name != "staged_system_apps"]
        dest = target / pathlib.Path(current).relative_to(source)
        dest.mkdir(exist_ok=True)
        os.chmod(dest, stat.S_IMODE(pathlib.Path(current).stat().st_mode))
        carry_owner(current, dest)
        for name in list(dirs) + files:
            src, dst = pathlib.Path(current) / name, dest / name
            if src.is_symlink():
                os.symlink(os.readlink(src), dst)
                if name in dirs:
                    dirs.remove(name)
            elif src.is_file():
                shutil.copy2(src, dst)
                carry_owner(src, dst)
                count += 1
                total += src.stat().st_size
    for name in ("keybags", "mobile/tmp", "mobile/Library/Preferences", "tmp", "run",
                 "db/dyld", "cores", "logs", "spool", "lib", "preferences",
                 "containers/Data", "containers/Shared", "containers/Bundle"):
        (target / name).mkdir(parents=True, exist_ok=True)
    os.chmod(target / "tmp", 0o1777)
    os.chmod(target / "mobile/tmp", 0o1777)
    for name in ("mobile",):
        for current, dirs, files in os.walk(target / name):
            for entry in dirs + files:
                os.chown(os.path.join(current, entry), 501, 501, follow_symlinks=False)
            os.chown(current, 501, 501, follow_symlinks=False)
    for name in ("keybags", "db", "run", "lib", "preferences", "cores", "logs", "spool", "containers"):
        os.chown(target / name, 0, 0)
finally:
    subprocess.run(["hdiutil", "detach", device], check=True)
data = image.read_bytes()
if len(data) != SIZE or data[32:36] != b"NXSB":
    raise SystemExit(f"host formatting produced {len(data)} bytes, expected {SIZE}")
report = dict(volume_uuid=volume_uuid, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
              source_regular_files=count, source_regular_bytes=total, guest_mutable=True,
              seed="Original private/var excluding staged_system_apps; owners preserved; "
                   "runtime skeleton added")
(fixture / "seed.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
