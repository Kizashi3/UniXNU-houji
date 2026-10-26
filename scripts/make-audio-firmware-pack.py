"""Build the pinned giulia ADSP/DTB package locally; never loads firmware."""
import argparse
import hashlib
import json
from pathlib import Path

from ios16_audio_pack import build_pack, pin_header


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware-dir', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--pin-header', type=Path,
                        help='Explicitly regenerate the compiled package pin')
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'hardware/sm8650-audio.json').read_text(encoding='utf-8'))
    pack = build_pack(args.firmware_dir, manifest['firmware'])
    header = pin_header(pack)
    if args.out.exists() and args.out.read_bytes() != pack:
        raise ValueError('Refusing to replace a different audio firmware pack')
    if args.pin_header:
        args.pin_header.parent.mkdir(parents=True, exist_ok=True)
        args.pin_header.write_text(header, encoding='utf-8', newline='\n')
    elif (ROOT / 'ios16/audio/giulia_audio_firmware_pin.h').read_text(encoding='utf-8') != header:
        raise ValueError('Audio pack differs from compiled kernel pin')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(pack)
    print(f'Audio pack: {len(pack)} bytes, SHA256 {hashlib.sha256(pack).hexdigest()}')


if __name__ == '__main__':
    main()
