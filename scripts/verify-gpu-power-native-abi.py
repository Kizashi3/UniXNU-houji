"""Bind GPU mode 3 to the audited, unchanged giulia ClockDxe implementation."""
import argparse
import hashlib
import json
import re
from pathlib import Path


CLOCK_PINS = {
    'b1608ab9a4759dbbc50e5e5836ee402ff832d8076011e5145460e4af97ba7686',
    '53c18b9e1569cebbcb9837c1d773cc5e836fb7e902df7c29b27b485a13d4fdfc',
}


def verify(uefi):
    directory = uefi / 'Binaries/giulia/QcomPkg/Drivers/ClockDxe'
    names = re.findall(r'^\s*PE32\|([^|\r\n]+)\|', (directory / 'ClockDxe.inf').read_text(), re.M)
    if len(names) != 1:
        raise ValueError('Ambiguous GPU ClockDxe binary')
    binary = (directory / names[0]).resolve()
    if not binary.is_relative_to(directory.resolve()):
        raise ValueError('GPU ClockDxe path escapes module')
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    if digest not in CLOCK_PINS:
        raise ValueError('Unverified GPU ClockDxe implementation: ' + digest)
    return {'ClockDxe_sha256': digest, 'protocol_version': '0x1000a',
            'native_polling_patched': False, 'provider_waits_preemptible': False,
            'configured_gmu_hz': 625000000, 'configured_hub_hz': 200000000,
            'frequency_is_measured': False, 'hardware_verified': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--uefi', type=Path, required=True)
    a = p.parse_args()
    try:
        print(json.dumps(verify(a.uefi), indent=2))
    except (ValueError, OSError) as error:
        p.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
