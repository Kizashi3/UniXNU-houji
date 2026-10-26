"""Bounded reader for OnePlus SIPA 1.0.5 data; does not access hardware.

Layout and scene/action numbers: OnePlusOSS sm8650 commit
453d8875f815bf9dfad9035982861226a4823a6c, vendor/oplus/kernel/audio/codecs/sipa/
sipa_parameter.h, sipa_parameter.c, sipa_common.h and sipa_regmap.c.
Proprietary register values remain in the user's local firmware file.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib

VERSION = 0x10005
MAX_BYTES = 1024 * 1024
MAX_NODES = 4096
MAX_DELAY_US = 1000000
SCENES = ('playback', 'voice', 'voip', 'receiver', 'factory', 'fm')
STOCK_SHA256 = 'c888598d7c8eeb4ed3b46fd5e612f39cff4838a6b6c69808605204d4c497a0dc'
SOURCE_COMMIT = '453d8875f815bf9dfad9035982861226a4823a6c'


def _words(data, offset, count):
    if offset < 0 or count < 0 or offset + count * 4 > len(data):
        raise ValueError('SIPA record exceeds data bounds')
    return struct.unpack_from('<' + str(count) + 'I', data, offset)


def _list(data, descriptor, size):
    offset, count, stride = descriptor
    if (count > MAX_NODES or offset > len(data)
            or (count and stride != size)
            or (not count and stride not in (0, size))
            or count * size > len(data) - offset):
        raise ValueError('Invalid SIPA list bounds/count/stride')
    return [_words(data, offset + i * size, size // 4) for i in range(count)]


def _registers(rows, width, *, proc=False, sram=False):
    result = []
    for row in rows:
        addr = row[0]
        values = row[5:] if proc else row[2:]
        if addr >= 255 or any(v >= (1 << (32 if sram else width)) for v in values):
            raise ValueError('Invalid SIPA register address/value')
        record = {'address': addr, 'visible': row[3] if proc else row[1],
                  'values': list(values)}
        if proc:
            mask, action, delay = row[1], row[2], row[4]
            if mask >= 1 << width or action > 3 or delay > MAX_DELAY_US:
                raise ValueError('Invalid SIPA mask/action/delay')
            record.update(mask=mask, action=action, delay_us=delay)
        result.append(record)
    return result


def _chip(data, row):
    chip_type, addr_width, width, id_address = row[:4]
    if addr_width != 8 or width not in (8, 16) or id_address >= 255:
        raise ValueError('Unsupported SIPA register width/address')
    ranges = _list(data, row[4:7], 8)
    if not ranges or any(lo > hi or hi >= 1 << width for lo, hi in ranges):
        raise ValueError('Invalid SIPA chip ID range')
    result = {'chip_type': chip_type, 'address_bits': addr_width,
              'value_bits': width, 'firmware_chip_id_address': id_address,
              'chip_id_ranges': [list(r) for r in ranges],
              'owi_modes': list(row[7:13]), 'chip_enable': list(row[13:16]),
              'trim_crc_bits': row[25], 'pvdd_limit': list(row[35:41]),
              'sram_addresses': list(row[41:43]),
              'dynamic_vdd': row[46], 'dynamic_pvdd': row[47]}
    for name, start, stride, proc in (
            ('init', 16, 32, False), ('startup', 19, 44, True),
            ('shutdown', 22, 44, True), ('trim_efuse', 26, 44, True),
            ('trim_crc', 29, 44, True), ('trim_fallback', 32, 44, True),
            ('sram', 43, 32, False)):
        result[name] = _registers(_list(data, row[start:start+3], stride),
                                  width, proc=proc, sram=name == 'sram')
    if result['trim_efuse']:
        bits = sum(r['mask'].bit_count() for r in result['trim_efuse'])
        crc_bits = sum(r['mask'].bit_count() for r in result['trim_crc'])
        if bits > 256 or row[25] not in (4, 8, 16) or crc_bits != row[25]:
            raise ValueError('Invalid SIPA trim bit packing')
    if not result['init'] or not result['startup'] or not result['shutdown']:
        raise ValueError('Missing SIPA initialization/start/stop program')
    return result


def parse_sipa(data):
    """Validate CRC, layout, every enabled chip and all nested list boundaries."""
    if not isinstance(data, bytes) or not 188 <= len(data) <= MAX_BYTES:
        raise ValueError('Invalid SIPA file size/type')
    crc, version = _words(data, 0, 2)
    if version != VERSION:
        raise ValueError('Unsupported SIPA firmware version')
    if zlib.crc32(data[4:]) != crc:
        raise ValueError('SIPA CRC32 mismatch')
    layouts = [n for n in (4, 8) if len(data) >= 12 + 44*n
               and _words(data, 8 + 44*n, 1)[0] == len(data) - 12 - 44*n]
    if len(layouts) != 1:
        raise ValueError('Invalid or ambiguous SIPA channel layout/data size')
    count = layouts[0]
    payload = data[12 + 44*count:]
    channels = []
    for channel in range(count):
        enabled = _words(data, 8 + 4*channel, 1)[0]
        if enabled not in (0, 1):
            raise ValueError('Invalid SIPA channel enable flag')
        rows = _list(payload, _words(data, 8 + 4*count + 12*channel, 3), 192)
        if bool(rows) != bool(enabled):
            raise ValueError('SIPA channel enable/list mismatch')
        chips = [_chip(payload, row) for row in rows]
        if len({c['chip_type'] for c in chips}) != len(chips):
            raise ValueError('Duplicate SIPA chip configuration')
        extra = _words(data, 8 + 16*count + 28*channel, 7)
        channels.append({'channel': channel, 'enabled': bool(enabled),
                         'extra': list(extra), 'chips': chips})
    return {'version': version, 'bytes': len(data), 'crc32': crc,
            'sha256': hashlib.sha256(data).hexdigest(), 'channel_count': count,
            'channels': channels}


def verify_sipa(path, expected_sha256=STOCK_SHA256):
    """Verify the supplied firmware against a caller-selected trusted SHA pin."""
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > MAX_BYTES:
        raise ValueError('Invalid SIPA file')
    with path.open('rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    result = parse_sipa(data)
    if expected_sha256 != result['sha256']:
        raise ValueError('SIPA SHA256 does not match trusted pin')
    return result


def playback_program(parsed):
    """Select scene 0 for the two board amplifiers. This is not an APM graph."""
    channels = []
    enabled = [c for c in parsed['channels'] if c['enabled']]
    if [c['channel'] for c in enabled] != [0, 1]:
        raise ValueError('Giulia requires enabled SIPA channels 0 and 1 only')
    for c in enabled:
        chips = [p for p in c['chips'] if p['chip_type'] == 11]
        if len(chips) != 1:
            raise ValueError('Missing SIA9177 configuration')
        chip = chips[0]
        if chip['address_bits'] != 8 or chip['value_bits'] != 16:
            raise ValueError('SIA9177 register width mismatch')
        trim_bits = sum(r['mask'].bit_count() for r in chip['trim_efuse'])
        if chip['trim_crc_bits'] != 8 or not 48 <= trim_bits <= 256 or chip['sram']:
            raise ValueError('Unsupported SIA9177 trim/SRAM program')
        # BSP uses reg_map_info_table, NOT firmware_chip_id_address (zero in ROM).
        item = {'channel': c['channel'], 'i2c_address': 0x6c + c['channel'],
                'reset_gpio': (173, 178)[c['channel']], 'reset_assert_level': 1,
                'chip_id_address': 6, 'chip_id_ranges':
                [[0x5880, 0x5880], [0x5890, 0x5891], [0x58a0, 0x58a1]],
                'trim_crc_bits': chip['trim_crc_bits']}
        for name in ('init', 'startup', 'shutdown', 'trim_efuse', 'trim_crc', 'trim_fallback'):
            item[name] = [dict({k: v for k, v in r.items() if k != 'values'},
                               value=r['values'][0]) for r in chip[name]]
        channels.append(item)
    return {'firmware_sha256': parsed['sha256'], 'source_commit': SOURCE_COMMIT,
            'scene': 'playback', 'backend': 'MI2S-LPAIF-RX-SECONDARY',
            'rate_hz': 48000, 'channels': channels, 'physical_bits': 32,
            'pal_bits': 24, 'speaker_protection_required': True,
            'startup_prerequisites': ['ADSP/SPF ready', 'calibrated APM graph running',
                                      'secondary MI2S clocks and PCM DMA running'],
            'hardware_executed': False, 'playback_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('firmware', type=Path)
    parser.add_argument('--sha256', default=STOCK_SHA256,
                        help='trusted SHA256 (default: local 16.0.3.500 stock pin)')
    parser.add_argument('--program', action='store_true', help='emit scene-0 registers for inspection')
    args = parser.parse_args()
    try:
        parsed = verify_sipa(args.firmware, args.sha256)
        result = playback_program(parsed) if args.program else {
            k: parsed[k] for k in ('version', 'bytes', 'crc32', 'sha256', 'channel_count')}
        if not args.program:
            result['enabled_channels'] = [c['channel'] for c in parsed['channels'] if c['enabled']]
        print(json.dumps(result, indent=2))
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
