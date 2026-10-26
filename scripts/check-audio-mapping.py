#!/usr/bin/env python3
"""Check/generate the audio map and optionally verify local DTS, BSP or firmware."""
import argparse
import json
from pathlib import Path
from ios16_audio import HEADER, load_mapping, render_header, verify_dts, verify_files


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--write-header', action='store_true')
    p.add_argument('--dts', type=Path, help='Captured numeric running-device.dts')
    p.add_argument('--source-dir', type=Path, help='Cache root with repository/path source files')
    p.add_argument('--firmware-dir', type=Path, help='Directory of original split adsp/adsp_dtb files')
    args = p.parse_args()
    try:
        data = load_mapping()
        expected = render_header(data)
        if args.write_header:
            HEADER.write_text(expected, encoding='utf-8', newline='\n')
        elif HEADER.read_text(encoding='utf-8') != expected:
            raise ValueError('Audio header is stale; run with --write-header')
        result = {'stage': 'board-mapping-only', 'regions': len(data['regions']),
                  'hardware_access': False, 'playback': False, 'recording': False}
        if args.dts:
            result['dt_properties_verified'] = verify_dts(data, args.dts)
        if args.source_dir:
            result['source_files_verified'] = verify_files(args.source_dir, data['source_files'])
        if args.firmware_dir:
            from ios16_audio_firmware import verify_firmware
            firmware = verify_firmware(args.firmware_dir, data['firmware'])
            result['firmware_files_verified'] = firmware['file_count']
            result['firmware_bytes_verified'] = firmware['total_bytes']
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyError) as error:
        p.exit(1, str(error)+'\n')


if __name__ == '__main__':
    main()
