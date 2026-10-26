"""Bind RPMh, clock and Command DB layouts to the board firmware inspected."""
import argparse
import hashlib
from pathlib import Path
import re

PINS={
    'ClockDxe': {'b1608ab9a4759dbbc50e5e5836ee402ff832d8076011e5145460e4af97ba7686',
                 '53c18b9e1569cebbcb9837c1d773cc5e836fb7e902df7c29b27b485a13d4fdfc'},
    'RpmhDxe': {'cdebce5c9f96d16e71a0db8f9c4dbf591ed314dd94a6543b08c238902df65267'},
    'CmdDbDxe': {'5c58d445f356af9f8497ea6f449ba534fd7920b045067cd3b02ad997863077bf'},
}

def verify(uefi):
    result={}
    for name,allowed in PINS.items():
        directory=uefi/'Binaries/giulia/QcomPkg/Drivers'/name
        lines=(directory/(name+'.inf')).read_text()
        names=re.findall(r'^\s*PE32\|([^|\r\n]+)\|',lines,re.M)
        if len(names)!=1:raise ValueError('Ambiguous native firmware binary: '+name)
        path=(directory/names[0]).resolve()
        if not path.is_relative_to(directory.resolve()):raise ValueError('Firmware path escapes module directory')
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if digest not in allowed:raise ValueError('Unverified native Wi-Fi firmware ABI: '+name+' '+digest)
        result[name]=digest
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--uefi',type=Path,required=True)
    p.add_argument('--when-enabled',action='store_true')
    a=p.parse_args()
    if a.when_enabled:
        header=a.uefi/'Platforms/OnePlus/giuliaPkg/Drivers/GiuliaInitrdDxe/PayloadIdentity.h'
        if not re.search(r'^#define GIULIA_WIFI_PCIE 1\s*$',header.read_text(),re.M):
            print('Native PCIe adapter disabled; no ABI requirement')
            raise SystemExit(0)
    for name,digest in verify(a.uefi).items():print(name+' ABI binary verified: '+digest)
