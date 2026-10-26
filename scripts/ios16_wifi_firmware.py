"""Validate and select original Kiwi assets; no device access or firmware upload."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct

MAX_FILE_BYTES=16*1024*1024
MAX_BUNDLE_BYTES=64*1024*1024
ELF32=struct.Struct('<16sHHIIIIIHHHHHH')
PHDR32=struct.Struct('<8I')

def safe_name(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*',value):
        raise ValueError('Invalid firmware path')
    if any(p in ('.','..') for p in PurePosixPath(value).parts):
        raise ValueError('Firmware path traversal')
    return value

def elf_info(data):
    if not data.startswith(b'\x7fELF'):return None
    if len(data)<ELF32.size:raise ValueError('Truncated firmware ELF')
    h=ELF32.unpack_from(data)
    if h[0][4:7]!=b'\x01\x01\x01' or h[1]!=2 or h[2] not in (3,40):
        raise ValueError('Unsupported Kiwi ELF encoding/type/machine')
    phoff,ehsize,phsize,phnum=h[5],h[8],h[9],h[10]
    if ehsize!=ELF32.size or phsize!=PHDR32.size or not 1<=phnum<=64:
        raise ValueError('Invalid firmware ELF header sizes')
    if phoff<ehsize or phoff+phsize*phnum>len(data):
        raise ValueError('Truncated firmware program table')
    for i in range(phnum):
        segment=PHDR32.unpack_from(data,phoff+i*phsize)
        offset,length=segment[1],segment[4]
        if length and (offset>len(data) or length>len(data)-offset):
            raise ValueError('Firmware segment escapes image')
    return {'class':32,'endian':'little','machine':h[2],'entry':h[4],
            'program_headers':phnum,'bytes_preserved':True}

def inspect_asset(data,name):
    safe_name(name)
    if not 0<len(data)<=MAX_FILE_BYTES:raise ValueError('Invalid firmware size')
    info=elf_info(data)
    if (name.endswith(('amss.bin','amss20.bin','.elf','.b0c')) or re.search(r'\.e[0-9a-f]{2}$',name)) and info is None:
        raise ValueError('Expected original ELF firmware: '+name)
    result={'path':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
    if info:result['elf']=info
    return result

def load_bundle(directory):
    directory=Path(directory).resolve()
    catalog=json.loads((directory/'manifest.json').read_text())
    if catalog.get('schema')!=1 or catalog.get('pci_id')!='17cb:1107':
        raise ValueError('Unsupported firmware bundle')
    if catalog.get('project')!=23851 or catalog.get('region')!='CN':
        raise ValueError('Firmware package is not the pinned PKG110 CN profile')
    entries=catalog.get('files',[])
    if not isinstance(entries,list) or not 1<=len(entries)<=128:
        raise ValueError('Invalid firmware asset count')
    seen=set();total=0
    for entry in entries:
        name=safe_name(entry['path'])
        if name in seen:raise ValueError('Duplicate firmware asset')
        seen.add(name)
        file=directory/name
        if file.is_symlink() or not file.resolve().is_relative_to(directory):
            raise ValueError('Firmware path escapes bundle')
        size=file.stat().st_size
        total+=size
        if size!=entry['bytes'] or size>MAX_FILE_BYTES or total>MAX_BUNDLE_BYTES:
            raise ValueError('Firmware asset size mismatch/limit')
        actual=inspect_asset(file.read_bytes(),name)
        if any(actual.get(k)!=entry.get(k) for k in ('bytes','sha256','elf')):
            raise ValueError('Firmware digest/format mismatch: '+name)
    return catalog

def select_files(catalog,*,soc_hw_version,board_id,chip_id,project,region):
    """Use observed BAR+0x224 and QMI capability IDs, never an assumed revision.

    CNSS masks the silicon major to four bits; board 0xff on project 23851
    uses OnePlus's regional BDF. Missing variants fail instead of falling back.
    """
    for value in (soc_hw_version,board_id,chip_id,project):
        if isinstance(value,bool) or not isinstance(value,int) or not 0<=value<=0xffffffff:
            raise ValueError('Invalid observed hardware identity')
    if soc_hw_version in (0,0xffffffff) or board_id>0xffff:
        raise ValueError('Hardware identity is unavailable')
    if project!=catalog['project'] or region!=catalog['region']:
        raise ValueError('Board/region does not match firmware package')
    major=(soc_hw_version>>8)&15
    if major not in (1,2):raise ValueError('Unsupported Kiwi silicon revision')
    prefix='bdwlang' if chip_id&0x10 else 'bdwlan'
    if board_id==0xff:
        board=prefix+'.b0c'
    elif board_id<0xff:
        board=f'{prefix}.e{board_id:02x}'
    else:
        # This spelling follows cnss_get_bdf_file_name's 16-bit board-ID case.
        board=f'bdwlan{board_id>>8:02x}.e{board_id&255:02x}'
    selected={
        'main':'kiwi/'+('amss20.bin' if major==2 else 'amss.bin'),
        'phy':'kiwi/'+('phy_ucode20.elf' if major==2 else 'phy_ucode.elf'),
        'board':'kiwi/'+board,'regdb':'kiwi/regdb.bin',
    }
    available={entry['path'] for entry in catalog['files']}
    if set(selected.values())-available:
        raise ValueError('Exact board/chip firmware variant is absent')
    return selected
