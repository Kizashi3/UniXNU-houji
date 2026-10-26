"""Qualify the pinned upstream patches for a build without the legacy display driver."""
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])/'patches/xnu/offline-component-load-probes.patch'
text = path.read_text()
old = '+\tint legacy_register = 0;\n'
end = '+\tint client_probe = 0;\n'
if '+#if defined(XNU_NATIVE_LEGACY_DISPLAY) && XNU_NATIVE_LEGACY_DISPLAY\n' + old not in text:
    if text.count(old) != 1 or text.count(end) != 1:
        raise SystemExit('Unexpected upstream legacy display probe patch')
    text = text.replace(old, '+#if defined(XNU_NATIVE_LEGACY_DISPLAY) && XNU_NATIVE_LEGACY_DISPLAY\n'+old)
    text = text.replace(end, '+#endif\n'+end)
    # Recount changed unified-diff hunks, including subsequent new-line offsets.
    lines = text.splitlines(keepends=True)
    delta = 0
    for i, line in enumerate(lines):
        if line.startswith(('diff --git ', '--- a/')):
            delta = 0
        match = re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)',line)
        if not match:
            continue
        old_start, old_count, new_start, new_count, context = match.groups()
        previous_count = int(new_count or 1)
        body = []
        for item in lines[i+1:]:
            if item.startswith(('@@ ', 'diff --git ', '--- a/')):
                break
            if item.startswith((' ', '+', '-')):
                body.append(item)
        before = sum(item[0] in ' -' for item in body)
        after = sum(item[0] in ' +' for item in body)
        if before != int(old_count or 1):
            raise SystemExit('Unexpected old hunk size')
        lines[i] = f'@@ -{old_start},{before} +{int(new_start)+delta},{after} @@{context}\n'
        delta += after-previous_count
    path.write_text(''.join(lines))
print('Legacy display probe is conditional on its configured driver')

# Bind the retained diagnostic framebuffer as soon as the VM is ready. This
# board-local hook does not enable the unrelated sheng BootProgress feature.
path = Path(sys.argv[1])/'patches/xnu/zzz-boot-progress.patch'
text = path.read_text()
if 'giulia_early_console' not in text:
    marker = '+\tboot_progress_stage("arm_vm_init returned");\n'
    hunk = '@@ -529,7 +531,9 @@'
    if text.count(marker) != 1 or text.count(hunk) != 1:
        raise SystemExit('Unexpected upstream arm_vm_init observation hunk')
    hook = ('+#if GIULIA_EARLY_CONSOLE\n+\t{\n'
            '+\t\textern void giulia_early_console(void);\n'
            '+\t\tgiulia_early_console();\n+\t}\n+#endif\n')
    path.write_text(text.replace(marker, marker + hook).replace(hunk, '@@ -529,7 +531,15 @@'))
path = Path(sys.argv[1])/'scripts/build-xnu-4k-baseline.sh'
text = path.read_text()
if '-DGIULIA_EARLY_CONSOLE=' not in text:
    marker = 'EXTRA_CFLAGS="$EXTRA_CFLAGS -DXNU_BOOT_PROGRESS=$BOOT_PROGRESS"'
    if text.count(marker) != 1:
        raise SystemExit('Unexpected kernel compiler flag setup')
    replacement = (marker + '\nEXTRA_CFLAGS="$EXTRA_CFLAGS -DGIULIA_EARLY_CONSOLE=$ARM_DT_PLATFORM"\n'
                   '# This object changes between the archive-free bootstrap and platform link.\n'
                   'rm -f "$ROOT/build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/osfmk/DEVELOPMENT/arm_init.o"')
    path.write_text(text.replace(marker, replacement))
print('Giulia framebuffer hook runs after arm_vm_init when the real platform archive is linked')
