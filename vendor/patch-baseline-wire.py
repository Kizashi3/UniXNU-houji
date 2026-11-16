"""Inject the Sweet worktree-wiring call into the kernel baseline build script
so it runs on .cache/xnu-work after the clone and patch loop, before the make.

Idempotent: inserting the call twice is impossible because the presence of the
string 'wire-sweet-worktree' short-circuits the edit.
"""
from pathlib import Path

path = Path('scripts/build-xnu-4k-baseline.sh')
if not path.is_file():
    raise SystemExit('patch-baseline-wire: missing %s' % path)

text = path.read_text()
marker = 'python3 scripts/prepare-xnu-source.py\n'
if marker not in text:
    raise SystemExit('patch-baseline-wire: prepare-xnu-source marker not found')

if 'wire-sweet-worktree' in text:
    print('baseline: already wired')
else:
    text = text.replace(
        marker,
        'python3 scripts/wire-sweet-worktree.py\n' + marker,
        1,
    )
    path.write_text(text)
    print('baseline: wired wire-sweet-worktree before prepare-xnu-source')
