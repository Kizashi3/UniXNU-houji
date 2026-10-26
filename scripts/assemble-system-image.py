"""Assemble verified OS/SystemOS raw inputs into the upstream SHNGROOT layout.

Creates a new host file only. No userdata geometry or flash command is assumed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

p=argparse.ArgumentParser()
p.add_argument('--os',type=Path,required=True)
p.add_argument('--os-report',type=Path,required=True)
p.add_argument('--systemos',type=Path,required=True)
p.add_argument('--systemos-report',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
args=p.parse_args()
MiB=1<<20
partial=args.output.with_suffix(args.output.suffix+'.partial')
if args.output.exists() or partial.exists(): raise SystemExit('Output already exists')
inputs=[('OS',args.os,args.os_report),('SystemOS',args.systemos,args.systemos_report)]
layout=[]; cursor=MiB
for name,path,report_path in inputs:
    report=json.loads(report_path.read_text())
    if not path.is_file() or path.stat().st_size!=report['bytes']:
        raise SystemExit(f'{name}: source size mismatch')
    layout.append({'name':name,'path':path,'offset':cursor,'size':report['bytes'],'sha256':report['sha256']})
    cursor+=(report['bytes']+MiB-1)//MiB*MiB
args.output.parent.mkdir(parents=True,exist_ok=True)
with partial.open('xb') as output:
    output.truncate(cursor)
    for item in layout:
        output.seek(item['offset']); digest=hashlib.sha256()
        with item['path'].open('rb') as source:
            while chunk:=source.read(8*MiB):
                output.write(chunk); digest.update(chunk)
        if digest.hexdigest()!=item['sha256']:
            raise SystemExit(f'{item["name"]}: source digest mismatch')
        print(f'Copied and verified {item["name"]}',flush=True)
    header=bytearray(4096)
    header[:8]=b'SHNGROOT'
    struct.pack_into('<IIQ',header,8,1,len(layout),cursor)
    for i,item in enumerate(layout):
        struct.pack_into('<32sQQII32s40s',header,24+i*128,item['name'].encode(),item['offset'],
                         item['size'],512,1,bytes.fromhex(item['sha256']),bytes(40))
    header[4064:]=hashlib.sha256(header[:4064]).digest()
    output.seek(0); output.write(header)
with partial.open('rb') as f: sha=hashlib.file_digest(f,'sha256').hexdigest()
partial.rename(args.output)
report={'image_bytes':cursor,'image_sha256':sha,'manifest_sha256':hashlib.sha256(header).hexdigest(),
        'windows':[{k:v for k,v in i.items() if k!='path'} for i in layout],
        'hardware_tested':False,'ready_to_flash':False,
        'remaining':['XNU storage driver qualification','live userdata geometry verification','Data volume preparation']}
args.output.with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
