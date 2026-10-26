"""Generate a host-only TCR oracle from pinned Linux helpers, never kernel code."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fetch',action='store_true',help='Explicitly fetch missing pinned test inputs')
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    pins=json.loads((ROOT/'hardware/gpu-smmu-oracle.json').read_text())
    texts=[]
    for entry in pins['files']:
        file=ROOT/'.cache/gpu-oracle-source'/entry['path']
        if not file.exists() and a.fetch:
            with urllib.request.urlopen(entry['url'],timeout=60) as response:data=response.read()
            if hashlib.sha256(data).hexdigest()!=entry['sha256']:raise ValueError('Source download hash mismatch')
            file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(data)
        data=file.read_bytes()
        if len(data)!=entry['bytes'] or hashlib.sha256(data).hexdigest()!=entry['sha256']:
            raise ValueError('Oracle source mismatch: '+entry['path'])
        texts.append(data.decode())
    header,table=texts
    functions=[]
    for name in ('arm_smmu_lpae_tcr','arm_smmu_lpae_tcr2'):
        matches=re.findall(r'static inline u32 '+name+r'\([^\n]+\)\n\{[\s\S]*?\n\}',header)
        if len(matches)!=1:raise ValueError('Ambiguous original helper: '+name)
        functions.append(matches[0])
    macros=[]
    for name in sorted(set(re.findall(r'ARM_SMMU_[A-Z0-9_]+','\n'.join(functions)))):
        matches=re.findall(r'^#define\s+'+name+r'\s+[^\n]+',header,re.M)
        if len(matches)!=1:raise ValueError('Ambiguous original field: '+name)
        macros.append(matches[0])
    quirks=re.findall(r'^\s*#define IO_PGTABLE_QUIRK_ARM_TTBR1\s+[^\n]+',table,re.M)
    if len(quirks)!=1:raise ValueError('Missing original TTBR1 quirk')
    prelude='''/* Host-only test extraction from the pinned Linux sources; GPL-2.0-only. */
#include <stdint.h>
typedef uint32_t u32;
#define BIT(n) (UINT32_C(1)<<(n))
#define GENMASK(h,l) ((UINT32_MAX>>(31-(h))) & (UINT32_MAX<<(l)))
#define FIELD_PREP(mask,val) (((uint32_t)(val)<<__builtin_ctz((uint32_t)(mask))) & (mask))
struct io_pgtable_cfg {unsigned quirks;struct {struct {unsigned tg,sh,orgn,irgn,tsz,ips;} tcr;} arm_lpae_s1_cfg;};
'''
    harness='''
uint32_t source_tcr(unsigned bits,unsigned upper,unsigned coherent) {
 struct io_pgtable_cfg c={0};c.quirks=upper?IO_PGTABLE_QUIRK_ARM_TTBR1:0;
 c.arm_lpae_s1_cfg.tcr.tg=upper?2:0;c.arm_lpae_s1_cfg.tcr.sh=coherent?3:2;
 c.arm_lpae_s1_cfg.tcr.orgn=coherent?1:0;c.arm_lpae_s1_cfg.tcr.irgn=coherent?1:0;
 c.arm_lpae_s1_cfg.tcr.tsz=64-bits;return arm_smmu_lpae_tcr(&c);
}
uint32_t source_tcr2(unsigned output_code) {
 struct io_pgtable_cfg c={0};c.arm_lpae_s1_cfg.tcr.ips=output_code;
 return arm_smmu_lpae_tcr2(&c);
}
'''
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(prelude+'\n'.join(quirks+macros+functions)+harness,newline='\n')
    print('Pinned Linux TCR helpers extracted for independent host comparison')


if __name__=='__main__':main()
