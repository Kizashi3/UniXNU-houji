#!/usr/bin/env python3
"""Execute the actual map C under host stubs; compare old/new feature variants.

This checks map composition against OEM ClockBSP/DAL and FDT children. It does
not execute ARM page tables or access peripherals.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from fdt import parse, cells, strings


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--uefi', type=Path, required=True)
    p.add_argument('--original', type=Path, required=True)
    p.add_argument('--fdt', type=Path, required=True)
    p.add_argument('--oem-dal', type=Path, required=True)
    p.add_argument('--oem-clock', type=Path, required=True)
    a = p.parse_args()
    board = a.uefi / 'Platforms/Xiaomi/houjiPkg'
    root_ram = (board / 'Include/Protocol/HoujiRootRAM.h').read_text()
    constants = {name: re.search(r'#define\s+' + name + r'\s+(0x[0-9A-Fa-f]+)', root_ram)[1]
                 for name in ('HOUJI_ROOT_RAM_LOW', 'HOUJI_ROOT_RAM_HIGH')}
    root, _ = parse(a.fdt.read_bytes())
    wanted = {'qcom,pineapple-gcc': 'Houji_Clock_GCC',
              'qcom,pineapple-camcc-v2': 'Houji_Clock_CAMCC',
              'qcom,pineapple-dispcc': 'Houji_Clock_DISPCC',
              'qcom,pineapple-gpucc': 'Houji_Clock_GPUCC',
              'qcom,pineapple-videocc-v2': 'Houji_Clock_VIDEOCC'}
    children = {}
    for _, node in root.walk():
        if 'compatible' not in node.properties:
            continue
        compatible = strings(node.properties['compatible'])[0]
        if compatible in wanted:
            base, length = cells(node.properties['reg'])
            assert base % 4096 == 0 and length > 0
            children[wanted[compatible]] = (base, (length + 4095) & ~4095)
    assert len(children) == 5
    # Clock_InitBases uses the actual BSP's 24-byte base/size/output records.
    # The reference to 0x2bba8 is installed at ClockDxe 0x7970..0x7998; the
    # loop at 0x3c80 loads its first pointer/count and advances by 0x18.
    clock = a.oem_clock.read_bytes()
    assert hashlib.sha256(clock).hexdigest() == 'f498e08bf978b36af750a3958c83b788d39f786069d31d6483d4df66d4ce69ba'
    first, count = struct.unpack_from('<QQ', clock, 0x2bba8)
    assert (first, count) == (0x20280, 8)
    banks = [struct.unpack_from('<QQQ', clock, first + 24 * i) for i in range(count)]
    dal = a.oem_dal.read_bytes()
    assert hashlib.sha256(dal).hexdigest() == '949984d39680c9a4034eeabb66aa743d500f837dbd1c0133721ae19495be6635'
    parents = [('APSS_HM', 0x40db0, None),
               ('CLK_CTL', 0x40298, 'Houji_Clock_GCC'),
               ('CORE_TOP_CSR', 0x40a40, None),
               ('GFX', 0x40a68, 'Houji_Clock_GPUCC'),
               ('IRIS', 0x40c48, 'Houji_Clock_VIDEOCC'),
               ('MDSS', 0x40c98, 'Houji_Clock_DISPCC'),
               ('PCIE_RSCC', 0x409c8, 'Houji_Clock_PCIE_RSCC'),
               ('TITAN_SS', 0x40c70, 'Houji_Clock_CAMCC')]
    expected = {}
    for (base, size, output), (name, offset, map_name) in zip(banks, parents):
        name_rva, dal_base, dal_size = struct.unpack_from('<QQQ', dal, offset)
        assert dal[name_rva:name_rva+len(name)+1] == name.encode() + b'\0'
        assert (base, size) == (dal_base, dal_size), name
        assert base % 4096 == size % 4096 == 0 and 0x35000 <= output < len(clock) - 8
        if map_name:
            expected[map_name] = (base, size)
    for name, (child, length) in children.items():
        base, size = expected[name]
        assert base <= child and child + length <= base + size, name
    # GPU power uses only the board's AOSS descriptor and APSS IPCC page.
    # Derive these additions independently from the captured FDT.
    for compatible, name, exact in [('qcom,aoss-qmp', 'Houji_GPU_QMP', (0xc300000, 0x400)),
                                    ('qcom,ipcc', 'Houji_GPU_IPCC', (0x406000, 0x1000))]:
        matches = [node for _, node in root.walk()
                   if 'compatible' in node.properties and compatible in strings(node.properties['compatible'])
                   and cells(node.properties.get('reg', b'')) == list(exact)]
        assert len(matches) == 1
        base, size = cells(matches[0].properties['reg'])
        assert (base, size) == exact
    name_rva, ufs_base, ufs_size = struct.unpack_from('<QQQ', dal, 0x409f0)
    assert dal[name_rva:].split(b'\0', 1)[0] == b'UFS_MEM_UFS_2LANE_G5_REGS'
    assert (ufs_base, ufs_size) == (0x1d80000, 0x40000)
    ufs_nodes = [node for path, node in root.walk() if path.endswith('/ufshc@1d84000')]
    assert len(ufs_nodes) == 1
    regs = cells(ufs_nodes[0].properties['reg'])
    assert len(regs) % 2 == 0
    assert all(ufs_base <= base and base + size <= ufs_base + ufs_size
               for base, size in zip(regs[::2], regs[1::2]))
    app = (board / 'Application/HoujiStorageProbe/HoujiStorageProbe.c').read_text()
    probe = app.split('mClockBanks[] = {', 1)[1].split('};', 1)[0]
    probe_banks = re.findall(r'\{L"([A-Z0-9_]+)",\s*(0x[0-9A-Fa-f]+),\s*(0x[0-9A-Fa-f]+)\}', probe)
    assert [(name, int(base, 16), int(size, 16)) for name, base, size in probe_banks] == [
        (parent[0], bank[0], bank[1]) for parent, bank in zip(parents, banks)]
    header = '''#ifndef HOUJI_HOST_MAP_STUB
#define HOUJI_HOST_MAP_STUB
#include <stdint.h>
#include <string.h>
typedef uint8_t UINT8;
typedef struct { const char *Name; uint64_t Address, Length; unsigned Hob, Resource;
  uint64_t Flags; unsigned MemoryType, Attr; } EFI_MEMORY_REGION_DESCRIPTOR;
#define STATIC static
#define CONST const
#define VOID void
#define OUT
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
enum { AddMem, NoHob, AddDev };
enum { WRITE_BACK, WRITE_BACK_XN, UNCACHED_UNBUFFERED_XN, WRITE_THROUGH_XN, NS_DEVICE };
enum { EfiReservedMemoryType=0, EfiConventionalMemory=7 };
extern int high_flag, probe_flag, clock_flag, ufs_flag;
#define PcdHoujiHighRAMEnable high_flag
#define PcdHoujiHighRAMProbeEnable probe_flag
#define PcdHoujiClockMmioEnable clock_flag
#define PcdHoujiUfsMmioEnable ufs_flag
#define FeaturePcdGet(x) (x)
#define CopyMem memcpy
#endif
'''
    harness = '''
#include <stdio.h>
#include <stdlib.h>
int high_flag, probe_flag, clock_flag, ufs_flag;
#include SOURCE_PATH
int main(int argc, char **argv) {
  if(argc!=2) return 2;
  int v=atoi(argv[1]); clock_flag=v&1; high_flag=(v>>1)&1; probe_flag=(v>>2)&1; ufs_flag=(v>>3)&1;
  EFI_MEMORY_REGION_DESCRIPTOR *map; UINT8 count; GetMemoryMap(&map,&count);
  printf("[");
  for(unsigned i=0;i<count;i++) { EFI_MEMORY_REGION_DESCRIPTOR *d=&map[i];
    printf("%s[\\"%s\\",%llu,%llu,%u,%u,%llu,%u,%u]",i?",":"",d->Name,
      (unsigned long long)d->Address,(unsigned long long)d->Length,d->Hob,d->Resource,
      (unsigned long long)d->Flags,d->MemoryType,d->Attr);
  } printf("]\\n"); return 0;
}
'''
    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        for name in ('Library/MemoryMapLib.h', 'Library/PcdLib.h', 'Library/BaseMemoryLib.h'):
            path = temp / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(header)
        protocol = temp / 'Protocol/HoujiRootRAM.h'
        protocol.parent.mkdir()
        protocol.write_text('\n'.join(f'#define {k} {v}ULL' for k, v in constants.items()))
        programs = []
        for index, source in enumerate((a.original, board / 'Library/MemoryMapLib/MemoryMapLib.c')):
            c = temp / f'map-{index}.c'
            c.write_text('#define SOURCE_PATH ' + json.dumps(str(source.resolve())) + '\n' + harness)
            output = temp / f'map-{index}'
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-I', str(temp), str(c), '-o', str(output)], check=True)
            programs.append(output)
        for flags in (0, 1, 2, 3, 4, 5, 8, 9, 10, 11, 12, 13):
            old, new = [json.loads(subprocess.check_output([str(exe), str(flags)])) for exe in programs]
            assert any(row[1] <= 0x406000 and 0x407000 <= row[1]+row[2]
                       and row[6:] == [11, 4] for row in old), 'IPCC must use its existing device mapping'
            assert any(row[1] <= 0xc300000 and 0xc301000 <= row[1]+row[2]
                       and row[6:] == [11, 4] for row in old), 'AOSS QMP must use its existing device mapping'
            assert len(old) == (42 if flags & 6 else 41)
            if not flags & 9:
                assert new == old, 'Default map changed'
            else:
                assert new[:len(old)] == old, 'Existing regions changed'
                added = new[len(old):]
                wanted = dict(expected) if flags & 1 else {}
                if flags & 8:
                    wanted['Houji_UFS'] = (ufs_base, ufs_size)
                assert len(added) == len(wanted)
                assert {row[0]: tuple(row[1:3]) for row in added} == wanted
                assert all(row[3:] == [2, 1, 0x400, 11, 4] for row in added)
                for base, size, _ in banks if flags & 1 else []:
                    assert any(row[1] <= base and base + size <= row[1] + row[2] and
                               row[6:] == [11, 4] for row in new), (hex(base), hex(size))
            for i, left in enumerate(new):
                assert left[1] % 4096 == 0 and left[2] % 4096 == 0 and left[2] > 0
                for right in new[i+1:]:
                    assert max(left[1], right[1]) >= min(left[1]+left[2], right[1]+right[2]), (left[0], right[0])
    print('PASS: 12 compiled feature combinations; original regions unchanged; ClockBSP and UFS windows match pinned DAL/FDT, with device attributes and no overlap.')


if __name__ == '__main__':
    main()
