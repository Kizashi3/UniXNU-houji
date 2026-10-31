#!/system/bin/sh
# Export XNU's DT reserved-memory log from Android recovery/TWRP.
# The script only reads pstore or the reserved region and copies records to
# shared storage; it never writes UFS, userdata, or any boot partition.
set -u

OUT=${1:-/sdcard/UniXNU/xnu-logs}
PRAM_BASE=${PRAM_BASE:-0xA7000000}
PRAM_SIZE=${PRAM_SIZE:-0x400000}
# embedded_panic_header is packed and is 168 bytes in the XNU tree used here.
HEADER_MIN=${HEADER_MIN:-168}
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

# XNU embedded_panic_header is not Linux persistent_ram_buffer format.  If
# pstore has no record, read the reserved physical region through /dev/mem.
# The header fields are little-endian: panic_log_offset at byte 20 and
# panic_log_len at byte 24.  Earlier bytes 16..23 contain the high half of
# the flags field and the offset, so reading at 16 would silently misparse it.
if [ "$found" -eq 0 ] && [ -r /dev/mem ]; then
    page=4096
    base_pages=$((PRAM_BASE / page))
    pages=$((PRAM_SIZE / page))
    if dd if=/dev/mem of="$OUT/xnu-pram.bin" bs=$page skip=$base_pages count=$pages 2>/dev/null; then
        magic=$(od -An -tx1 -N4 "$OUT/xnu-pram.bin" 2>/dev/null | tr -d ' \n')
        if [ "$magic" = "4b4e5546" ]; then
            set -- $(od -An -tu4 -j20 -N8 "$OUT/xnu-pram.bin" 2>/dev/null)
            log_offset=${1:-0}
            log_length=${2:-0}
            printf 'panic_magic=FUNK\npanic_log_offset=%s\npanic_log_length=%s\n' \
                "$log_offset" "$log_length" >> "$manifest"
            if [ "$log_offset" -ge "$HEADER_MIN" ] &&
               [ "$log_offset" -le "$PRAM_SIZE" ] &&
               [ "$log_length" -le $((PRAM_SIZE - log_offset)) ]; then
                dd if="$OUT/xnu-pram.bin" of="$OUT/xnu-readable.log" bs=1 \
                    skip="$log_offset" count="$log_length" 2>/dev/null || true
                found=1
                printf 'raw_pram_base=%s\nraw_pram_size=%s\n' \
                    "$PRAM_BASE" "$PRAM_SIZE" >> "$manifest"
            else
                printf 'status=INVALID_LOG_RANGE\n' >> "$manifest"
            fi
        else
            printf 'raw_pram_magic=%s\n' "$magic" >> "$manifest"
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
    printf 'status=NO_PSTORE_OR_XNU_RECORD\n' >> "$manifest"
    echo "XNU log export: no pstore or XNU reserved-memory record found" >&2
    exit 2
fi
printf 'status=OK\n' >> "$manifest"
echo "XNU logs exported to $OUT"
