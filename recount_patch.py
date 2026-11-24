import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
lines = path.read_text().splitlines(keepends=True)
out = []
delta = 0
i = 0
header = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$')
while i < len(lines):
    match = header.match(lines[i].rstrip('\n'))
    if not match:
        out.append(lines[i])
        i += 1
        continue
    old_start = int(match.group(1))
    new_start = old_start + delta
    j = i + 1
    old_count = 0
    new_count = 0
    while j < len(lines) and not lines[j].startswith('@@ ') and not lines[j].startswith('diff --git '):
        line = lines[j]
        if line.startswith(' '):
            old_count += 1
            new_count += 1
        elif line.startswith('-'):
            old_count += 1
        elif line.startswith('+'):
            new_count += 1
        elif line.startswith('\\ No newline'):
            pass
        else:
            break
        j += 1
    old_field = str(old_count) if old_count != 1 else ''
    new_field = str(new_count) if new_count != 1 else ''
    out.append(f'@@ -{old_start},{old_field} +{new_start},{new_field} @@{match.group(5)}\n')
    out.extend(lines[i + 1:j])
    delta += new_count - old_count
    i = j
path.write_text(''.join(out))
print(path, 'recounted delta', delta)
