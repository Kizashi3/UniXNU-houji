#!/usr/bin/env python3
"""Audit the actual UEFI request string against the declared trial policy."""
import argparse,json,re,hashlib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--efi',type=Path,required=True);p.add_argument('--policy',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
s=a.source.read_text();matches=re.findall(r'BaseBootArgs = L"([^"\\]*)"',s);assert len(matches)==1
base=matches[0];assert (base+'\0').encode('utf-16le') in a.efi.read_bytes()
buffers=re.findall(r'CHAR16 BootArgs\[(\d+)\]',s);assert len(buffers)==1;capacity=int(buffers[0]);assert capacity==608
assert 'L"%s houji_touch=%u",BaseBootArgs,mTouchHandoffReady?1:0' in s
maximum=len(base)+len(' houji_touch=1')+1;assert maximum<=capacity
j=json.loads(a.policy.read_text());dynamic=set(j.get('dynamic_boot_args',{}));assert dynamic=={'houji_touch'}
expected=[x for x in j['development_boot_args']if x.split('=')[0]not in dynamic];actual=base.split();assert sorted(expected)==sorted(actual),(set(expected)-set(actual),set(actual)-set(expected))
keys=[x.split('=')[0] for x in actual];assert len(keys)==len(set(keys))
sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest();result={'status':'PASS','source_sha256':sha(a.source),'actual_efi_sha256':sha(a.efi),'policy_sha256':sha(a.policy),'base_arguments':actual,'base_literal_found_in_actual_EFI':True,'maximum_formatted_characters_with_NUL':maximum,'UEFI_and_Darwin22_command_capacity':capacity,'dynamic_touch_value_not_assumed':True,'hardware_execution_claim':False};a.output.write_text(json.dumps(result,indent=2)+'\n');print('Actual compiled UEFI args PASS',len(actual),'static args,',maximum,'of',capacity,'characters including NUL')
