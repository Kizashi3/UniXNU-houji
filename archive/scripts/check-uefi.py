#!/usr/bin/env python3
"""Gate the stage-1 firmware profile before compilation; never invokes fastboot."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import tomllib


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--uefi', type=Path, required=True)
    p.add_argument('--vendor', type=Path, required=True)
    args = p.parse_args()
    platform = args.uefi / 'Platforms/Xiaomi/houjiPkg'
    config = tomllib.loads((args.uefi / 'Resources/Configs/houji.toml').read_text())
    assert config['uefi_fd'] == {'base': 0xA7100000, 'size': 0x300000}
    assert config['boot_image']['header_version'] == 4
    fdf = (platform / 'houji.fdf').read_text()
    assert '!include QcomPkg/Extra.fdf.inc' not in fdf
    assert '!include Include/RAW.inc' not in fdf
    includes = re.findall(r'!include\s+(\S+)', fdf)
    assert includes == ['Include/APRIORI.inc', 'Include/DXE.inc', 'Include/RAM.inc', 'SiliciumPkg/Common.fdf.inc'], includes
    ram = (platform / 'Include/RAM.inc').read_text()
    assert '!if $(WITH_PAYLOAD) == 1' in ram
    assert re.findall(r'^\s*INF\s+(\S+)', ram, re.M) == [
        'houjiPkg/Drivers/HoujiRamDiskDxe/HoujiRamDiskDxe.inf',
        'MdeModulePkg/Universal/Disk/DiskIoDxe/DiskIoDxe.inf',
        'MdeModulePkg/Universal/Disk/UnicodeCollation/EnglishDxe/EnglishDxe.inf',
        'FatPkg/EnhancedFatDxe/Fat.inf']
    ram_source = (platform / 'Drivers/HoujiRamDiskDxe/HoujiRamDiskDxe.c').read_text()
    assert 'mMedia.ReadOnly = TRUE;' in ram_source and 'return EFI_WRITE_PROTECTED;' in ram_source
    for token in ['UFSDxe', 'SetVariable', 'WriteBlocks', 'Flash', 'ProcessCapsule']:
        assert token not in ram_source
    dxe = (platform / 'Include/DXE.inc').read_text()
    prohibited = ['UFSDxe', 'SdccDxe', 'DiskIoDxe', 'PartitionDxe', 'UsbMsd', 'MassStorage', 'Capsule', 'Fastboot', 'FvbServices']
    no_capsule = 'houjiPkg/Drivers/NoCapsuleRuntimeDxe/NoCapsuleRuntimeDxe.inf'
    checked_dxe = dxe.replace('INF ' + no_capsule, '')
    for token in prohibited:
        assert token.lower() not in checked_dxe.lower(), 'Storage/updater present: ' + token
    modules = re.findall(r'^\s*INF\s+(\S+)', dxe, re.M)
    assert 'UniXNUPkg/Application/UniXNU/UniXNU.inf' in modules
    assert modules.count('HoujiVendorPkg/EnvDxeEnhanced/EnvDxeEnhanced.inf') == 1
    assert modules.count(no_capsule) == 1
    reject = (platform / 'Drivers/NoCapsuleRuntimeDxe/NoCapsuleRuntimeDxe.c').read_text()
    assert reject.count('return EFI_UNSUPPORTED;') == 2
    assert 'gRT->UpdateCapsule = RejectUpdateCapsule;' in reject
    for token in ['WriteBlocks', 'SetVariable', 'ResetSystem', 'ProcessCapsuleImage', 'Fmp']:
        assert token not in reject
    # The inherited variable implementation must remain in RAM emulation mode.
    common = (args.uefi / 'Silicon/Silicium/SiliciumPkg/SiliciumPkg.dsc.inc').read_text()
    assert 'PcdEmuVariableNvModeEnable|TRUE' in common
    dsc = (platform / 'houji.dsc').read_text()
    zero_guid = '{' + ','.join(['0x00'] * 16) + '}'
    assert 'PcdDriverHealthConfigureForm|' + zero_guid in dsc
    vendor = args.vendor / 'HoujiVendorPkg/EnvDxeEnhanced'
    pe = (vendor / 'EnvDxeEnhanced.efi').read_bytes()
    assert pe[:2] == b'MZ'
    pe_off = struct.unpack_from('<I', pe, 0x3c)[0]
    assert pe[pe_off:pe_off + 4] == b'PE\0\0'
    assert struct.unpack_from('<H', pe, pe_off + 4)[0] == 0xaa64, 'Not AArch64'
    manifest = json.loads((args.vendor / 'manifest.json').read_text())
    entry = next(x for x in manifest if x['name'] == 'EnvDxeEnhanced')
    assert hashlib.sha256(pe).hexdigest() == entry['inputs'][0]['sha256']
    mmap = (platform / 'Library/MemoryMapLib/MemoryMapLib.c').read_text()
    assert '0xFC400000, 0x02B00000' in mmap
    assert '0xD5100000' not in mmap
    assert '0xA7100000, 0x00300000' in mmap
    assert '"FD_Reserved", 0xA7000000, 0x00100000' in mmap
    pei = (args.uefi / 'Silicon/Qualcomm/QcomPkg/Library/PlatformPeiLib/XblProtocols.c').read_text()
    assert 'LocateMemoryRegionByName ("FD_Reserved", &ReservedFd)' in pei
    print('Checks passed: houji FD/GOP, OEM provenance, RAM variables; optional payload exposes only a read-only RAM disk.')


if __name__ == '__main__':
    main()
