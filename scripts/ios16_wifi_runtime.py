"""Check the compiled Wi-Fi/display implementation and locally embedded assets."""
import hashlib
import re
import struct
from pathlib import Path


def check_runtime(kernel, report):
    marker = b'GIULIA WIFI: PCIe/MHI/QMI/WMI ready;'
    if marker not in kernel:
        if report.get('wifi_runtime_included'):
            raise ValueError('Runtime metadata without compiled Wi-Fi driver')
        return None
    if not report.get('wifi_runtime_included') or not report.get('wifi_firmware'):
        raise ValueError('Wi-Fi kernel requires verified local firmware embedding')
    if b'GIULIA FB: native panel 1264x2780 full coverage;' not in kernel:
        raise ValueError('Wi-Fi/display integration kernel mismatch')
    if b'GIULIA WIFI: firmware pack mapped read-only and digest verified' not in kernel:
        raise ValueError('Wi-Fi kernel lacks the explicit firmware RAM mapping')
    if len(kernel) < 32:
        raise ValueError('Truncated Mach-O')
    magic, cpu, subtype, _, count, command_bytes = struct.unpack_from('<6I', kernel)
    if (magic, cpu, subtype) != (0xfeedfacf, 0x100000c, 0) or count > 128 or command_bytes > len(kernel)-32:
        raise ValueError('Invalid Mach-O header')
    at, end, found = 32, 32+command_bytes, None
    for _ in range(count):
        if at+8 > end:
            raise ValueError('Truncated Mach-O command')
        cmd, size = struct.unpack_from('<II', kernel, at)
        if size < 8 or size % 8 or size > end-at:
            raise ValueError('Invalid Mach-O command')
        if cmd == 0x19:
            if size < 72:
                raise ValueError('Truncated segment')
            _, _, name, va, vm, offset, length, maximum, protection, sections, flags = struct.unpack_from('<II16sQQQQiiII', kernel, at)
            if name.rstrip(b'\0') == b'__WIFI_FW':
                if found or size != 72 or sections or flags or maximum != 1 or protection != 1 or length > vm or offset > len(kernel) or length > len(kernel)-offset:
                    raise ValueError('Invalid Wi-Fi firmware segment')
                found = dict(segment='__WIFI_FW', virtual_address=hex(va), virtual_bytes=vm,
                             file_offset=offset, bytes=length,
                             sha256=hashlib.sha256(kernel[offset:offset+length]).hexdigest())
        at += size
    if at != end or found != report['wifi_firmware']:
        raise ValueError('Firmware segment metadata mismatch')
    pin = (Path(__file__).resolve().parents[1]/'ios16/wifi/giulia_wifi_firmware_pin.h').read_text()
    digest = bytes(int(x, 16) for x in re.findall(r'0x([0-9a-f]{2})\b', pin))
    if len(digest) != 32 or found['sha256'] != digest.hex() or digest not in kernel[:found['file_offset']]:
        raise ValueError('Compiled firmware pin mismatch')
    result = {'firmware': found, 'scan_transport': 'WCN7850 PCIe/MHI/QRTR/QMI/CE/HTC/WMI',
            'interface': 'iOS16 IO80211 en0', 'scan_mode': 'passive 2.4/5 GHz',
            'association_data_path': False, 'hardware_verified': False,
            'display': {'native': [1264, 2780], 'canvas': [1125, 2436], 'presentation': 'full-panel'}}
    # This versioned declaration belongs to gn_start. Classify the compiled
    # implementation only; a firmware payload cannot supply the declaration.
    # Retain the exact old report for existing scan-only kernels and bundles.
    station = b'GIULIA WIFI PROFILE: 20H392; station=1; legacy20=1; security=open,wpa2,sae-pmf; data=htt-tcl-reo'
    if station in kernel[:found['file_offset']]:
        result.update(association_data_path=True,
                      scan_mode='regulatory passive/directed/background 2.4/5 GHz',
                      compiled_station={'abi': '20H392',
                                        'data_transport': 'HTT/TCL/WBM/RXDMA/REO',
                                        'security': ['open', 'WPA2-PSK/CCMP', 'WPA3-SAE/CCMP/PMF'],
                                        'channel_width_mhz': 20})
    return result
