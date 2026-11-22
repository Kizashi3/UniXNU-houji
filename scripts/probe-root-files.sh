#!/bin/bash
# Read-only survey of the iOS 16.7.16 volumes on a macOS runner.
#
# Our own APFS reader mangles small decmpfs files (the extracted LaunchDaemon
# plists start with a stray byte and no longer parse), so the files that decide
# the Setup/activation behaviour have to come from a real Darwin mount instead.
# The Setup/purplebuddy code itself lives in the dyld shared cache, which on
# iPhone OS is split into per-region files, so probe-cache-tokens.py names the
# owning image of every gate-looking string by reading the region headers.
# Nothing is modified and no Apple binary is published: only text reports plus
# the handful of plists we cannot decode ourselves.
set -x

SRC=${1:?system-source directory required}
OUT=${OUT:-/tmp/root-probe}
TOKENS='SetupDone|SetupFinishedAllSteps|daemonizeNeedsToRun|ShouldRun[A-Za-z]*MiniBuddy|should_hactivate|ActivationState|activation-state|IsActivated|isActivated|com\.apple\.springboard\.setup-ui|LoginSession|BBSSetLoginSession|com\.apple\.mobileactivationd|bypassActivation|NeedsActivation|setupComplete|isSetupComplete|SetupVersion|SilentICDPUpgrade'

rm -rf "$OUT"
mkdir -p "$OUT/plists" "$OUT/report"

for dmg in "$SRC"/ipsw/20H392/*.dmg; do
  name=$(basename "$dmg" .dmg)
  MNT="$SRC/mnt-$name"
  mkdir -p "$MNT"
  if ! hdiutil attach -readonly -nobrowse -mountpoint "$MNT" "$dmg"; then
    echo "attach failed for $dmg" >>"$OUT/report/summary.txt"
    continue
  fi

  {
    echo "===== volume $name"
    ls -la "$MNT" | head -40
    echo "-- SystemVersion"
    plutil -p "$MNT/System/Library/CoreServices/SystemVersion.plist" 2>&1 | head -20
  } >"$OUT/report/$name-root.txt" 2>&1

  # Every LaunchDaemon plist, plus the ones that decide the boot experience.
  D="$MNT/System/Library/LaunchDaemons"
  if [ -d "$D" ]; then
    ls -l "$D" >"$OUT/report/$name-launchdaemons-ls.txt" 2>&1
    echo "LaunchDaemons count=$(ls "$D" | wc -l)" >>"$OUT/report/$name-root.txt"
    for k in mobileactivationd mobile.lockdown purplebuddy.budd SpringBoard watchdogd apsd; do
      f="$D/com.apple.$k.plist"
      if [ -f "$f" ]; then
        cp "$f" "$OUT/plists/$name-com.apple.$k.plist"
        {
          echo "===== com.apple.$k"
          ls -l "$f"
          plutil -p "$f" 2>&1
        } >>"$OUT/report/$name-plists.txt"
      fi
    done
    grep -il 'mobileactivation' "$D"/*.plist >"$OUT/report/$name-activation-plists.txt" 2>&1
    (cd "$D" && tar cf - . 2>/dev/null | gzip -1) >"$OUT/plists/$name-launchdaemons.tar.gz"
  fi

  A="$MNT/System/Library/LaunchAgents"
  if [ -d "$A" ]; then
    ls -l "$A" >"$OUT/report/$name-launchagents-ls.txt" 2>&1
    echo "LaunchAgents count=$(ls "$A" | wc -l)" >>"$OUT/report/$name-root.txt"
  fi

  # The stock private/var is the skeleton our 2 GiB seed copies.
  {
    echo "===== $name private/var"
    find "$MNT/private/var" -maxdepth 4 \( -type f -o -type l \) 2>/dev/null | head -80
    echo "regular files: $(find "$MNT/private/var" -type f 2>/dev/null | wc -l)"
    du -sk "$MNT/private/var" 2>/dev/null
  } >"$OUT/report/$name-privvar.txt" 2>&1

  # The launchd job inventory, in a greppable form.
  INV="$MNT/System/Library/xpc/launchd.plist"
  if [ -f "$INV" ]; then
    {
      echo "===== $INV"
      ls -l "$INV"
      plutil -convert json -o - "$INV" 2>/dev/null | python3 -c '
import json, sys
d = json.load(sys.stdin)
print("top level keys:", list(d))
for k, v in d.items():
    if isinstance(v, dict):
        print("  %-22s entries=%d" % (k, len(v)))
        for probe in ("mobileactivationd", "purplebuddy", "SpringBoard"):
            hits = [n for n in v if probe.lower() in n.lower()]
            if hits:
                print("      %s -> %d matches: %s" % (probe, len(hits), sorted(hits)[:4]))
' 2>&1
      echo "-- service names mentioning mobileactivation anywhere in the inventory"
      plutil -convert json -o - "$INV" 2>/dev/null | grep -o 'com\.apple\.mobileactivationd[a-z.]*' | sort | uniq -c
    } >"$OUT/report/$name-launchd-inventory.txt" 2>&1
  fi

  # Where do the Setup binaries physically live?
  {
    echo "===== $name setup binaries"
    ls -l "$MNT/usr/libexec/mobileactivationd" "$MNT/usr/libexec/lockdownd" 2>&1
    find "$MNT" -maxdepth 7 \( -name 'budd' -o -name 'Setup.app' -o -name 'SetupAssistant.framework' \) 2>/dev/null | head -20
  } >"$OUT/report/$name-binaries.txt" 2>&1

  # Name the owning image of every Setup/activation-looking string in the cache.
  CD="$MNT/System/Library/Caches/com.apple.dyld"
  if [ -d "$CD" ]; then
    ls -la "$CD" >"$OUT/report/$name-cache.txt" 2>&1
    base=$(ls "$CD" 2>/dev/null | grep -E '^dyld_shared_cache_arm64(e)?$' | head -1)
    echo "base=$base" >>"$OUT/report/$name-cache.txt"
    if [ -n "$base" ]; then
      dyld_shared_cache_util -list "$CD/$base" >>"$OUT/report/$name-cache-list.txt" 2>&1
      echo "cached images: $(grep -c '^/' "$OUT/report/$name-cache-list.txt" 2>/dev/null)" >>"$OUT/report/$name-cache.txt"
      grep -iE 'SetupAssistant|purplebuddy|Setup\.app|MobileActivation|BackBoardServices|BoardServices|SpringBoard' \
        "$OUT/report/$name-cache-list.txt" >"$OUT/report/$name-cache-targets.txt" 2>&1
      python3 "$GITHUB_WORKSPACE/scripts/probe-cache-tokens.py" "$CD" \
        "$OUT/report/$name-cache-tokens.txt" "$TOKENS" >>"$OUT/report/$name-cache.txt" 2>&1
    fi
  fi

  hdiutil detach "$MNT" || true
done

{
  echo "== report files"
  ls -la "$OUT/report" "$OUT/plists"
  echo "== tokens by image"
  cat "$OUT/report"/*-cache-tokens.txt 2>/dev/null | grep -oE '^[^ ]+ +/[^ ]+' | sort | uniq -c | sort -rn | head -60
} >"$OUT/report/INDEX.txt" 2>&1

du -sk "$OUT"
echo PROBE_ROOT_FILES_DONE
