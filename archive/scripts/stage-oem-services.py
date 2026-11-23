#!/usr/bin/env python3
"""Stage the phone's own foundation DXEs and their exact dependency conjunctions.

The PE images remain outside Git. The default profile tests shared services;
power-bootstrap adds CmdDb, PwrUtils and NPA; clock-bootstrap additionally tests
Rpmh, Vcs and Clock. storage-services then adds HALIOMMU and ICB, without UFS.
Unsupported dependency syntax fails.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import uuid

MODULES = (
    'SmemDxe', 'DALSys', 'HWIODxeDriver', 'ChipInfo',
    'PlatformInfoDxeDriver', 'ULogDxe', 'ShmBridgeDxeLA', 'ScmDxeCompat',
)
POWER_BOOTSTRAP = ('CmdDbDxe', 'PwrUtilsDxe', 'NpaDxe')
CLOCK_BOOTSTRAP = ('RpmhDxe', 'VcsDxe', 'ClockDxe')
STORAGE_SERVICES = ('HALIOMMU', 'ICBDxe')
DAL = 'ae37b942-457f-4c91-a196-d9669fd347a3'
CHIP = 'b0760469-970c-487a-a4b5-28db7b45cef1'
SHM_BRIDGE = '9c1eb71f-dd6c-4ed5-9f6a-5cc0ca789f16'
CMD_DB = '1c34f691-d33d-4e14-b8f8-32c6c029e95b'
PWR_UTILS = '3c50e0f7-7d40-4a86-9067-11a2372bfc3d'
NPA = '79d6c870-725e-489e-a0a1-27e7a5d0cb35'
RPMH = 'e1d0b573-f29f-495d-9352-ca0dd42a0a74'
VCS = '5b844124-1f5a-4e10-9992-daf11cbef386'
CLOCK = '241afae6-885f-4f6c-a7ea-c28eab79c3e5'
ENV_SERVICES = '0389b776-625f-11eb-83be-c741a913de34'
IOMMU = '54b6d3b4-5d33-4f91-8600-6c41d5deb19a'
ICB = '5824f9de-17d2-4b1f-a5fe-5eb77fa53093'
PROVIDERS = dict(zip(POWER_BOOTSTRAP + CLOCK_BOOTSTRAP,
                     (CMD_DB, PWR_UTILS, NPA, RPMH, VCS, CLOCK)))
PROVIDERS.update(HALIOMMU=IOMMU, ICBDxe=ICB)


def conjunction(data):
    """Accept only TRUE/END or a strict postfix conjunction of GUID pushes."""
    if data == b'\x06\x08':
        return []
    offset, depth, guids, and_count = 0, 0, [], 0
    while offset < len(data):
        opcode = data[offset]
        offset += 1
        if opcode == 2 and offset + 16 <= len(data):
            guids.append(str(uuid.UUID(bytes_le=data[offset:offset + 16])))
            offset += 16
            depth += 1
        elif opcode == 3 and depth >= 2:
            depth -= 1
            and_count += 1
        elif opcode == 8 and offset == len(data) and depth == 1 and and_count == len(guids) - 1:
            return guids
        else:
            raise ValueError('Unsupported or malformed OEM DEPEX')
    raise ValueError('Missing DEPEX END')


def c_guid(value):
    u = uuid.UUID(value)
    return ('{0x%08x, 0x%04x, 0x%04x, {%s}}' %
            (u.time_low, u.time_mid, u.time_hi_version,
             ', '.join('0x%02x' % b for b in u.bytes[8:])))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dump', type=Path, required=True)
    parser.add_argument('--source-image', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--header', type=Path, required=True)
    parser.add_argument('--profile', choices=('foundation', 'power-bootstrap', 'clock-bootstrap', 'storage-services'), default='foundation')
    args = parser.parse_args()
    modules = MODULES + (POWER_BOOTSTRAP if args.profile != 'foundation' else ())
    if args.profile in ('clock-bootstrap', 'storage-services'):
        modules += CLOCK_BOOTSTRAP
    if args.profile == 'storage-services':
        modules += STORAGE_SERVICES
    matches = {}
    for ui in args.dump.rglob('*.ui'):
        name = ui.read_bytes().decode('utf-16le').rstrip('\0')
        if name in modules:
            if name in matches:
                raise ValueError('Ambiguous OEM module: ' + name)
            matches[name] = ui.parent
    if set(matches) != set(modules):
        raise ValueError('Missing foundation modules')
    args.output.mkdir(parents=True, exist_ok=True)
    records, header = [], ['// Generated from this phone; PE binaries remain local.']
    for name in modules:
        directory = matches[name]
        pes, deps = list(directory.glob('*.pe')), list(directory.glob('*.dxe.depex'))
        if len(pes) != 1 or len(deps) > 1 or pes[0].read_bytes()[:2] != b'MZ':
            raise ValueError('Unexpected section layout: ' + name)
        # These OEM APRIORI images have no DEPEX section. SCM still requires
        # real ChipInfo and ShmBridge providers (LocateProtocol at RVA 0x1e0c).
        if not deps and name not in ('ScmDxeCompat', 'ShmBridgeDxeLA'):
            raise ValueError('DEPEX absent: ' + name)
        requirements = conjunction(deps[0].read_bytes()) if deps else []
        extra = [CHIP, SHM_BRIDGE] if name == 'ScmDxeCompat' else ([DAL] if name in ('ULogDxe', 'NpaDxe') else [])
        # Actual LocateProtocol paths and the reference APRIORI order require
        # these providers beyond the original (incomplete) DEPEX expressions.
        if name == 'VcsDxe':
            extra += [NPA, PWR_UTILS, RPMH]
        elif name == 'ClockDxe':
            extra += [NPA, PWR_UTILS, RPMH, VCS]
        elif name == 'HALIOMMU':
            # Actual LocateProtocol in HALIOMMU 0x51b8, provided by the
            # original EnvDxeEnhanced InstallMultiple call at 0x2c5c.
            extra += [ENV_SERVICES]
        elif name == 'ICBDxe':
            extra += [NPA, RPMH, CLOCK]
        for guid in extra:
            if guid not in requirements:
                requirements.append(guid)
        header.append('STATIC EFI_GUID mDeps%s[] = {%s};' %
                      (name, ', '.join(c_guid(g) for g in requirements) if requirements else '{0}'))
        provides = PROVIDERS.get(name)
        if provides:
            header.append('STATIC EFI_GUID mProvides%s = %s;' % (name, c_guid(provides)))
        target = args.output / (name + '.efi')
        shutil.copyfile(pes[0], target)
        assert target.read_bytes() == pes[0].read_bytes()
        records.append({'name': name, 'source': str(pes[0]), 'bytes': target.stat().st_size,
                        'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                        'depex_hex': deps[0].read_bytes().hex() if deps else None,
                        'requirements': requirements, 'extra_guards': extra,
                        'provides': provides, 'patched': False})
    header.append('STATIC OEM_SERVICE mServices[] = {')
    for record in records:
        name = record['name']
        provider = '&mProvides' + name if record['provides'] else 'NULL'
        header.append('  {L"%s", L"\\\\Drivers\\\\%s.efi", mDeps%s, %d, %s},' %
                      (name, name, name, len(record['requirements']), provider))
    header.append('};\n')
    args.header.write_text('\n'.join(header))
    manifest = {'profile': args.profile, 'modules': records,
                'source_image': str(args.source_image),
                'source_image_sha256': hashlib.sha256(args.source_image.read_bytes()).hexdigest()}
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Staged unmodified OEM services:', ', '.join(modules))


if __name__ == '__main__':
    main()
