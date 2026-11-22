#!/bin/bash
# Mount the root volume that is actually flashed on the phone and answer one
# question: does it still carry the files launchd needs for the Setup/activation
# path?  merged-root-<N> releases hold the raw APFS container of the OS window in
# six slices, so concatenating them reproduces /dev/md0 byte for byte.
set -x

OUT=${OUT:-/tmp/merged-root-probe}
REPO=${REPO:-$GITHUB_REPOSITORY}
TAG=${1:-merged-root-23}
rm -rf "$OUT"
mkdir -p "$OUT"
df -h "$RUNNER_TEMP" >"$OUT/df.txt" 2>&1
cat "$OUT/df.txt"

ROOT="$RUNNER_TEMP/merged.raw"
rm -f "$ROOT"; : >"$ROOT"
# Download one slice at a time: the container is 9.8 GiB and holding both the
# slices and the concatenation does not fit every runner image.
for n in 00 01 02 03 04 05 06 07; do
  rm -rf "$RUNNER_TEMP/one"; mkdir -p "$RUNNER_TEMP/one"
  if ! gh release download "$TAG" --repo "$REPO" --pattern "part-$n" --dir "$RUNNER_TEMP/one"; then
    break
  fi
  cat "$RUNNER_TEMP/one/part-$n" >>"$ROOT"
  rm -rf "$RUNNER_TEMP/one"
  df -h "$RUNNER_TEMP" | tail -1
done
ls -la "$ROOT" >"$OUT/parts.txt" 2>&1
cat "$OUT/parts.txt"

MNT="$RUNNER_TEMP/mnt"
mkdir -p "$MNT"
{
  echo "== attach and mount the raw container"
  hdiutil attach -imagekey diskimage-class=CRawDiskImage -nobrowse -readonly \
    -mountpoint "$MNT" "$ROOT"
} >"$OUT/attach.txt" 2>&1
if ! grep -q "$MNT" "$OUT/attach.txt"; then
  echo "ATTACH FAILED; see attach.txt" >>"$OUT/verdict.txt"
  tail -20 "$OUT/attach.txt" >>"$OUT/verdict.txt"
  exit 0
fi

{
  echo "===== merged root $TAG ($ROOT)"
  ls -la "$MNT" | head -20
  echo "-- SystemVersion"
  plutil -p "$MNT/System/Library/CoreServices/SystemVersion.plist" 2>&1 | head -12

  echo "-- LaunchDaemons"
  if [ -d "$MNT/System/Library/LaunchDaemons" ]; then
    echo "count=$(ls "$MNT/System/Library/LaunchDaemons" | wc -l)"
    ls -l "$MNT/System/Library/LaunchDaemons" | grep -E \
      'mobileactivationd|purplebuddy|mobile\.lockdown|SpringBoard|apsd|watchdogd|CommCenter'
    echo "-- decoded mobileactivationd job as the flashed root holds it"
    plutil -p "$MNT/System/Library/LaunchDaemons/com.apple.mobileactivationd.plist" 2>&1
  else
    echo "NO /System/Library/LaunchDaemons DIRECTORY"
  fi

  echo "-- prefab launchd inventory"
  INV="$MNT/System/Library/xpc/launchd.plist"
  if [ -f "$INV" ]; then
    ls -l "$INV"
    plutil -convert json -o - "$INV" 2>/dev/null | python3 -c '
import json, sys
d = json.load(sys.stdin)
print("top level keys:", list(d))
jobs = d.get("LaunchDaemons", {})
print("LaunchDaemons entries:", len(jobs))
for probe in ("mobileactivationd", "purplebuddy", "mobile.lockdown", "SpringBoard", "apsd"):
    hits = [k for k in jobs if probe in k]
    print("  %-18s %d %s" % (probe, len(hits), hits[:2]))
one = [k for k in jobs if "mobileactivationd" in k]
if one:
    v = dict(jobs[one[0]])
    print("mobileactivationd entry keys:", sorted(v))
    for key in ("Label", "MachServices", "RunAtLoad", "UserName", "ProgramArguments", "EnableTransactions"):
        if key in v:
            print("   ", key, "=", v[key])
' 2>&1
  else
    echo "NO /System/Library/xpc/launchd.plist"
  fi

  echo "-- MobileGestalt cache and activation places on the root"
  ls -l "$MNT/System/Library/MobileGestalt" 2>&1 | head -5
  find "$MNT/private/var" -maxdepth 3 2>/dev/null | head -20
  echo "-- cryptex overlay present?"
  ls -ld "$MNT/System/Library/Caches/com.apple.dyld" 2>&1
  ls -l "$MNT/usr/libexec/mobileactivationd" 2>&1
} >"$OUT/verdict.txt" 2>&1

hdiutil detach "$MNT" || true
du -sh "$OUT"
echo PROBE_MERGED_ROOT_DONE
