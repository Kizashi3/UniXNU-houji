#!/usr/bin/env python3
"""Apply the pinned stock-canvas comparison layer after display refresh support."""
import argparse
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--xnu', type=Path, required=True)
args = parser.parse_args()
layer = Path(__file__).resolve().parents[1] / 'native/display/stock-canvas-runtime'
manifest = json.loads((layer / 'manifest.json').read_text())
pending = []
for relative, proof in manifest['files'].items():
    source = args.xnu / relative
    expected = layer / 'after' / relative
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assert hashlib.sha256(expected.read_bytes()).hexdigest() == proof['after_sha256'], relative
    assert digest in (proof['before_sha256'], proof['after_sha256']), relative
    if digest == proof['before_sha256']:
        pending.append((source, expected))
for source, expected in pending:
    source.write_bytes(expected.read_bytes())
print(f'Stock-canvas layer verified: {len(manifest["files"])} inputs, {len(pending)} applied; hardware pending')
