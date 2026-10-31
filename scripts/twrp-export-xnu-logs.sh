#!/system/bin/sh
# Read XNU's DT panic/console region through recovery's pstore interface.
# This script never writes a phone partition; it only copies records out.
set -u

OUT=${1:-/sdcard/UniXNU/xnu-logs}
PRAM_BASE=${PRAM_BASE:-0xA7000000}
PRAM_SIZE=${PRAM_SIZE:-0x400000}
mkdir -p "$OUT" || exit 1
mount -t pstore pstore /sys/fs/pstore 2>/dev/null || true

manifest="$OUT/manifest.txt"
printf 'source=/sys/fs/pstore\nexport=%s\n' "$OUT" > "$manifest"
printf 'time=' >> "$manifest"
date -u 2>/dev/null >> "$manifest" || printf 'unknown\n' >> "$manifest"
: > "$OUT/xnu-readable.log"
found=0

for file in /sys/fs/pstore/*; do
    [ -f "$file" ] || continue
    name=$(basename "$file")
    cp -f "$file" "$OUT/$name" || continue
    printf 'record=%s bytes=' "$name" >> "$manifest"
    wc -c < "$file" >> "$manifest"
    if command -v strings >/dev/null 2>&1; then
        strings "$file" >> "$OUT/xnu-readable.log"
    else
        tr -cd '\11\12\15\40-\176' < "$file" >> "$OUT/xnu-readable.log"
        printf '\n' >> "$OUT/xnu-readable.log"
    fi
    found=1
done

# XNU's embedded_panic_header is not Linux's persistent_ram_buffer format, so
# a recovery kernel may expose no /sys/fs/pstore file even though the reserved
# physical region contains the log.  Read the reserved region only when the
# recovery exposes /dev/mem; never write it and never touch UFS.  The raw dump
# is retained for diagnosis, while xnu-readable.log receives only the bounded
# header-declared XNU log when the magic and lengths are valid.
if [ "$found" -eq 0 ] && [ -r /dev/mem ]; then
    page=4096
    base_pages=$((PRAM_BASE / page))
    pages=$((PRAM_SIZE / page))
    if dd if=/dev/mem of="$OUT/xnu-pram.bin" bs=$page skip=$base_pages count=$pages 2>/dev/null; then
        magic=$(od -An -tx1 -N4 "$OUT/xnu-pram.bin" 2>/dev/null | tr -d ' \n')
        if [ "$magic" = "4b4e5546" ]; then
            set -- $(od -An -tu4 -j16 -N8 "$OUT/xnu-pram.bin" 2>/dev/null)
            log_offset=${1:-0}
            log_length=${2:-0}
            if [ "$log_offset" -ge 32 ] && [ "$log_length" -le $((PRAM_SIZE - log_offset)) ]; then
                dd if="$OUT/xnu-pram.bin" of="$OUT/xnu-readable.log" bs=1 \
                    skip="$log_offset" count="$log_length" 2>/dev/null || true
                found=1
                printf 'raw_pram_base=%s\nraw_pram_size=%s\nlog_offset=%s\nlog_length=%s\n' \
                    "$PRAM_BASE" "$PRAM_SIZE" "$log_offset" "$log_length" >> "$manifest"
            fi
        fi
    fi
fi

if [ -r /proc/last_kmsg ]; then
    cp -f /proc/last_kmsg "$OUT/last_kmsg" 2>/dev/null || true
    found=1
fi
if [ -r /dev/pmsg0 ]; then
    cp -f /dev/pmsg0 "$OUT/pmsg0" 2>/dev/null || true
fi

if command -v sha256sum >/dev/null 2>&1; then
    : > "$OUT/SHA256SUMS"
    for item in "$OUT"/*; do
        [ -f "$item" ] || continue
        [ "$(basename "$item")" = SHA256SUMS ] && continue
        sha256sum "$item" >> "$OUT/SHA256SUMS" 2>/dev/null || true
    done
fi
sync
if [ "$found" -eq 0 ]; then
    printf 'status=NO_PSTORE_RECORD\n' >> "$manifest"
    echo "XNU log export: no pstore record found" >&2
    exit 2
fi
printf 'status=OK\n' >> "$manifest"
echo "XNU logs exported to $OUT"
