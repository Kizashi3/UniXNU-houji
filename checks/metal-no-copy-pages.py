#!/usr/bin/env python3
"""Validate real VM identity queries and bounded remap notes; no GPU execution."""
from pathlib import Path
import subprocess,tempfile,sys
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='houji-vm-identity-') as tmp:
    out=Path(tmp)
    if sys.platform=='darwin':
        abi=out/'abi.c';abi.write_text('''#include <stddef.h>
#include <mach/vm_region.h>
_Static_assert(sizeof(vm_region_submap_short_info_data_64_t)==48,"short region size");
_Static_assert(_Alignof(vm_region_submap_short_info_data_64_t)==4,"short region alignment");
_Static_assert(offsetof(vm_region_submap_short_info_data_64_t,offset)==12,"object offset");
_Static_assert(offsetof(vm_region_submap_short_info_data_64_t,object_id)==40,"object id");
_Static_assert(VM_REGION_SUBMAP_SHORT_INFO_COUNT_64==12,"short region word count");
int main(void){return 0;}
''')
        subprocess.run(['clang','-std=c11','-Werror',str(abi),'-o',str(out/'abi')],check=True)
        subprocess.run([str(out/'abi')],check=True)
    source=ROOT/'graphics/metal/AdrenoMetal/bridge/NativeMetalPages.rs'
    subprocess.run(['rustc','--edition=2024','--test',str(source),'-o',str(out/'pages')],check=True)
    subprocess.run([str(out/'pages'),'--test-threads=1'],check=True,timeout=30)
print('PASS: actual VM identity walker and remap notes; ABI, overflow/gaps, bounded walks/cache, failed observations, and live fixed-address remaps preserve old pages on macOS; GPU correctness still needs device readback')
