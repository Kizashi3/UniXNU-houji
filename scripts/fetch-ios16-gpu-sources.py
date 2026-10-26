"""Fetch the exact OnePlus GPU source blobs recorded in hardware/sm8650-gpu.json."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
from ios16_gpu import ROOT, digest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    pins = json.loads((ROOT/'hardware/sm8650-gpu.json').read_text())
    a.out.mkdir(parents=True, exist_ok=True)
    for entry in pins['vendor_sources']:
        dest = a.out/entry['file']
        if dest.exists():
            data = dest.read_bytes()
        else:
            with urllib.request.urlopen(entry['url'], timeout=60) as response:
                data = response.read()
        blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if digest(data) != entry['sha256'] or blob != entry['git_blob']:
            raise ValueError('Pinned source mismatch: ' + entry['file'])
        if not dest.exists():
            dest.write_bytes(data)
    print(f"Verified {len(pins['vendor_sources'])} OnePlus source blobs")


if __name__ == '__main__':
    main()
