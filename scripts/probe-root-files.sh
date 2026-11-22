#!/bin/bash
# Read-only survey of the iOS 16.7.16 volumes on a macOS runner.
#
# Our own APFS reader mangles small decmpfs files (the extracted LaunchDaemon
# plists start with a stray byte and no longer parse), so the files that decide
# the Setup/activation behaviour have to come from a real Darwin mount instead.
# This script also lifts the prelinked Setup/purplebuddy/mobileactivation
# binaries out of the dyld shared cache with dyld_shared_cache_util and greps
# them for the keys that could gate the Hello page.  Nothing is modified and no
# Apple binary is published: only text reports and the plists we cannot read.
set -x

SRC=${1:?system-source directory required}
OUT=${OUT:-/tmp/root-probe}
TOKENS='SetupDone|SetupFinishedAllSteps|daemonizeNeedsToRun|MiniBuddy|ActivationState|activation-state|should_hactivate|IsActivated|isActivated|LoginSession|setup-ui|purplebuddy|mobileactivationd|SilentICDPUpgrade|SetupVersion|CloudConfiguration'

rm -rf "$OUT"
mkdir -p "$OUT/plists" "$OUT/bin" "$OUT/report"

summary() {
  echo "----- $*" >>"$OUT/report/summary.txt"
}

echo "volumes:" >"$OUT/report/volumes.txt"
ls -la "$SRC/ipsw/20H392/" >>"$OUT/report/volumes.txt" 2>&1

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
    count=$(ls "$D" | wc -l)
    echo "LaunchDaemons count=$count" >>"$OUT/report/$name-root.txt"
    for k in mobileactivationd mobile.lockdown purplebuddy.budd SpringBoard watchdogd \
             backupd mobileactivation \
             ; do
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
    (cd "$D" && tar cf - --exclude='*.dylib' . 2>/dev/null | gzip -1) >"$OUT/plists/$name-launchdaemons.tar.gz"
  fi

  # LaunchAgents are what the mobile user domain actually sees.
  A="$MNT/System/Library/LaunchAgents"
  if [ -d "$A" ]; then
    ls -l "$A" >"$OUT/report/$name-launchagents-ls.txt" 2>&1
    for k in purplebuddy SpringBoard UserEventAgent; do
      f="$A/com.apple.$k.plist"
      [ -f "$f" ] && { echo "===== agent com.apple.$k"; plutil -p "$f" 2>&1; } >>"$OUT/report/$name-plists.txt"
    done
  fi

  # The stock private/var is the skeleton our 2 GiB seed copies; know its size.
  {
    echo "===== $name private/var"
    find "$MNT/private/var" -maxdepth 4 \( -type f -o -type l \) 2>/dev/null | head -80
    find "$MNT/private/var" -type f 2>/dev/null | wc -l
    du -sk "$MNT/private/var" 2>/dev/null
  } >"$OUT/report/$name-privvar.txt" 2>&1

  # The launchd job inventory the port is known to edit.
  for f in "$MNT/System/Library/xpc/launchd.plist" "$MNT/private/etc/launchd.conf"; do
    [ -f "$f" ] && { echo "===== $f"; ls -l "$f"; plutil -p "$f" 2>&1 | head -60; } >>"$OUT/report/$name-launchd-inventory.txt"
  done

  # Are the Setup binaries real files or shared-cache stubs?
  {
    echo "===== on-disk binaries"
    ls -l "$MNT/usr/libexec/mobileactivationd" "$MNT/usr/libexec/purplebuddy.budd" \
           "$MNT/usr/libexec/lockdownd" 2>&1
    ls -ld "$MNT/System/Library/CoreServices/Setup.app" "$MNT/System/Library/CoreServices/SpringBoard.app" 2>&1
    ls -l "$MNT/System/Library/CoreServices/Setup.app/" 2>&1 | head -20
    file "$MNT/usr/libexec/mobileactivationd" 2>&1
  } >"$OUT/report/$name-binaries.txt" 2>&1

  # Pull the prelinked images out of the shared cache and grep them.
  CD="$MNT/System/Library/Caches/com.apple.dyld"
  cache=""
  for c in "$CD"/dyld_shared_cache_arm64e "$CD"/dyld_shared_cache_arm64e.* ; do
    [ -f "$c" ] && { cache="$c"; break; }
  done
  echo "cache=$cache" >>"$OUT/report/$name-cache.txt"
  ls -la "$CD" >>"$OUT/report/$name-cache.txt" 2>&1
  if [ -n "$cache" ]; then
    dyld_shared_cache_util -list "$cache" >"$OUT/report/$name-cache-list.txt" 2>&1
    grep -iE 'Setup\.app|purplebuddy|MobileActivation|SpringBoard\.app|Prototype|BackBoardServices|BoardServices' \
      "$OUT/report/$name-cache-list.txt" | head -40 >"$OUT/report/$name-cache-targets.txt" 2>&1
    n=0
    while read -r path; do
      [ -n "$path" ] || continue
      case "$path" in /*) ;; *) continue ;; esac
      [ -d "$MNT$path" ] || [ -f "$MNT$path" ] || true
      out="$OUT/bin/$(basename "$path")"
      if dyld_shared_cache_util -extract "$path" -output "$OUT/bin" "$cache" 2>>"$OUT/report/$name-cache.txt"; then
        :
      fi
      n=$((n + 1))
      [ $n -ge 8 ] && break
    done < <(awk '{print $NF}' "$OUT/report/$name-cache-targets.txt" 2>/dev/null)
    for b in "$OUT/bin"/*; do
      [ -f "$b" ] || continue
      strings -a "$b" 2>/dev/null | grep -iE "$TOKENS" | sort -u >"$OUT/report/strings-$(basename "$b").txt"
    done
    ls -la "$OUT/bin" >>"$OUT/report/$name-cache.txt" 2>&1
    rm -f "$OUT/bin"/*
  fi

  hdiutil detach "$MNT" || true
done

{
  echo "== report files"
  ls -la "$OUT/report" "$OUT/plists"
  echo "== gate token hits"
  grep -l . "$OUT/report"/strings-*.txt 2>/dev/null
  echo "== activation plist grep"
  cat "$OUT/report"/*-activation-plists.txt 2>/dev/null
  echo "== mobileactivationd plist"
  cat "$OUT/report"/*-plists.txt 2>/dev/null | head -200
} >"$OUT/report/INDEX.txt" 2>&1

du -sk "$OUT"
echo PROBE_ROOT_FILES_DONE
