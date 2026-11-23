#!/usr/bin/env python3
"""Modify only explicit text entries in the pinned houji OrangeFox newc archive.

No archive member is extracted or followed as a host filesystem path.
"""
import argparse,hashlib,json,struct
from pathlib import Path

def parse(data):
 out=[];at=0
 while at+110<=len(data):
  magic=data[at:at+6]
  if magic!=b'070701':raise ValueError('Expected newc without CRC extension')
  values=[int(data[at+6+i*8:at+14+i*8],16) for i in range(13)]
  ns=values[11];size=values[6]
  if ns<1 or ns>4096:raise ValueError('CPIO name bounds')
  name=data[at+110:at+110+ns]
  if len(name)!=ns or name[-1:]!=b'\0':raise ValueError('CPIO name terminator')
  name=name[:-1].decode('utf-8');start=(at+110+ns+3)&~3
  payload=data[start:start+size]
  if len(payload)!=size:raise ValueError('Truncated CPIO member')
  out.append([name,values,payload]);at=(start+size+3)&~3
  if name=='TRAILER!!!':return out
 raise ValueError('Missing CPIO trailer')

def encode(entries):
 out=bytearray()
 for name,fields,payload in entries:
  fields=list(fields);fields[6]=len(payload);n=name.encode()+b'\0';fields[11]=len(n)
  out+=b'070701'+b''.join(f'{v:08x}'.encode() for v in fields)+n
  out+=bytes((-len(out))%4);out+=payload;out+=bytes((-len(out))%4)
 return bytes(out)+bytes((-len(out))%512)

def transform(entries):
 names=[e[0] for e in entries]
 if len(names)!=len(set(names)):raise ValueError('Duplicate archive members')
 files={e[0]:e for e in entries};changes={}
 f=files['system/etc/recovery.fstab'];old=f[2]
 lines=old.decode().splitlines(keepends=True)
 selected=[x for x in lines if not x.lstrip().startswith('#') and len(x.split())>=2 and x.split()[1]=='/data']
 if len(selected)!=1:raise ValueError('Unexpected data fstab configuration')
 f[2]=''.join('# houji native rescue: userdata deliberately not mounted\n' if x in selected else x for x in lines).encode()
 f=files['prop.default'];oldprop=f[2]
 if b'ro.houji.native_rescue=' in oldprop:raise ValueError('Already patched')
 f[2]=oldprop+b'\nro.houji.native_rescue=1\n'
 f=files['system/etc/init/hw/init.rc'];f[2]+=b'\n# houji native port: only mount the diagnostic FAT, always read-only.\non boot\n    mkdir /dev/logfs 0755 root root\n    wait /dev/block/by-name/logfs 10\n    mount vfat /dev/block/by-name/logfs /dev/logfs ro\n    setprop sys.houji.rescue.ready 1\n'
 for e in entries:e[1][6]=len(e[2])
 return entries

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 original=a.input.read_bytes();before=parse(original);hashes={e[0]:hashlib.sha256(e[2]).hexdigest() for e in before}
 after=transform(parse(original));packed=encode(after);checked=parse(packed)
 if any(x!=y for x,y in zip(after,checked)) or len(after)!=len(checked):raise ValueError('Roundtrip differs')
 changes=[{'name':e[0],'before_sha256':hashes[e[0]],'after_sha256':hashlib.sha256(e[2]).hexdigest()} for e in checked if hashes[e[0]]!=hashlib.sha256(e[2]).hexdigest()]
 if {c['name'] for c in changes}!={'system/etc/recovery.fstab','prop.default','system/etc/init/hw/init.rc'}:raise ValueError('Unexpected changed member')
 if a.output.exists():raise ValueError('Refusing output overwrite')
 a.output.write_bytes(packed);a.output.with_suffix('.json').write_text(json.dumps({'input_sha256':hashlib.sha256(original).hexdigest(),'output_sha256':hashlib.sha256(packed).hexdigest(),'members':len(checked),'changes':changes,'automatic_userdata_mount':False,'logfs_mount':'read-only','device_verified':False},indent=2)+'\n')
 print('Verified:',len(checked),'CPIO members; only 3 intended text entries differ.')
if __name__=='__main__':main()
