from pathlib import Path
import sys
path=Path(sys.argv[1]) if len(sys.argv)>1 else Path('scripts/unixnu/kernel.py')
text=path.read_text()
marker="    script = ctx.tree / 'scripts/build-xnu-4k-baseline.sh'\n"
insert="""    script = ctx.tree / 'scripts/build-xnu-4k-baseline.sh'
    # Stage the libdispatch kernel firehose header after tree assembly.
    baseline = script
    baseline_text = baseline.read_text()
    clone = "  git clone --shared refer/xnu .cache/xnu-work\\n"
    stage = clone + "  mkdir -p .cache/xnu-work/EXTERNAL_HEADERS/os\\n  firehose=$(find ../../feeds -path '*/os/firehose_buffer_private.h' -type f -print -quit 2>/dev/null || true)\\n  if [ -n \\\"$firehose\\\" ]; then cp \\\"$firehose\\\" .cache/xnu-work/EXTERNAL_HEADERS/os/firehose_buffer_private.h; fi\\n"
    if clone in baseline_text and "firehose=$(find ../../feeds" not in baseline_text:
        baseline_text = baseline_text.replace(clone, stage, 1)
    flag = 'EXTRA_CFLAGS=' + chr(34) + '$EXTRA_CFLAGS -DOS_FIREHOSE_SPI=1' + chr(34)
    anchor = 'EXTRA_CFLAGS=' + chr(34) + '$EXTRA_CFLAGS -DXNU_BOOT_PROGRESS=$BOOT_PROGRESS' + chr(34)
    if flag not in baseline_text and anchor in baseline_text:
        baseline_text = baseline_text.replace(anchor, flag + "\\n" + anchor, 1)
    baseline.write_text(baseline_text)
    # Firehose is compiled during bootstrap too; provide its archive to the first link.
    bootstrap = 'if [ \"$BOOTSTRAP\" = 1 ] && [ -f \"$KERNEL_SDKROOT/usr/local/lib/kernel/libfirehose_kernel.a\" ]; then\n  EXTRA_MAKE_ARGS+=(\"LD_KERNEL_ARCHIVES=-L$KERNEL_SDKROOT/usr/local/lib/kernel -lfirehose_kernel\")\nfi\n'
    anchor = 'if [ \"${XNU_SOURCE_CORECRYPTO14:-0}\" = 1 ]; then\n'
    if bootstrap not in baseline_text and anchor in baseline_text:
        baseline_text = baseline_text.replace(anchor, bootstrap + anchor, 1)
        baseline.write_text(baseline_text)
"""
if marker not in text: raise SystemExit(f'kernel build marker missing in {path}')
if 'firehose=$(find ../../feeds' not in text:
    text=text.replace(marker,insert,1)
    path.write_text(text)
print(f'patched {path}')