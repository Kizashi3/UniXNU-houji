#!/usr/bin/env python3
"""Actual Driver import helper + real hph producer/decoder, host peers only."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
P = HERE.parents[2]
DRIVER = Path('${HOUJI_ARTIFACTS}/native-port/DarwinBoot/DarwinBootPkg/Driver')
spec = importlib.util.spec_from_file_location('handoff_generator', HERE / 'make-houji-gpu-power-handoff-adt.py')
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)

# Actual portable producer + actual source policies with only hardware peers.
# Reuse its real gpp_prepare -> hph_run path instead of forge-completing fields.
fixture = (P / 'tests/check-gpu-power-only-handoff.c').read_text()
fixture = fixture[:fixture.index('static void failed(')]

peer = r'''
#include <stdlib.h>
#include <stdarg.h>
#include <wchar.h>
typedef void VOID;typedef unsigned char UINT8;typedef uint32_t UINT32;
typedef size_t UINTN;typedef uint64_t UINT64;typedef char CHAR8;typedef int BOOLEAN;
typedef uint64_t EFI_STATUS;
typedef struct {uint32_t Data1;uint16_t Data2,Data3;uint8_t Data4[8];} EFI_GUID;
typedef struct {EFI_GUID VendorGuid;VOID *VendorTable;} EFI_CONFIGURATION_TABLE;
typedef struct {UINTN NumberOfTableEntries;EFI_CONFIGURATION_TABLE *ConfigurationTable;} EFI_SYSTEM_TABLE;
static EFI_SYSTEM_TABLE *gST;
#define STATIC static
#define CONST const
#define TRUE 1
#define FALSE 0
#define MAX_UINTN SIZE_MAX
#define ALIGN_VALUE(x,a) (((x)+(a)-1)&~((size_t)(a)-1))
#define EFI_SUCCESS UINT64_C(0)
#define EFI_INVALID_PARAMETER UINT64_C(0x8000000000000002)
#define EFI_COMPROMISED_DATA UINT64_C(0x8000000000000021)
static unsigned prints;
static void Print(const wchar_t *format,...){assert(format);++prints;}
static void *ScanMem8(const VOID*p,UINTN n,UINT8 c){return (void*)memchr(p,c,n);}
static int AsciiStrCmp(const CHAR8*a,const CHAR8*b){return strcmp(a,b);}
static int CompareGuid(const EFI_GUID*a,const EFI_GUID*b){return !memcmp(a,b,sizeof(*a));}
#include "DarwinBootGpuHandoff.h"
#define CHECK(x) do {if(!(x)){fprintf(stderr,"line%u case%u: %s\n",(unsigned)__LINE__,cases,#x);abort();}}while(0)
static EFI_CONFIGURATION_TABLE tables[3];static EFI_SYSTEM_TABLE system_table;
static const EFI_GUID expected=HOUJI_GPU_POWER_HANDOFF_GUID;
static const EFI_GUID unrelated={0xabcdef01,2,3,{4,5,6,7,8,9,10,11}};
static unsigned char *zero_tree,*old_tree;static size_t zero_bytes,old_bytes;
static unsigned char *load(const char *path,size_t *bytes){FILE*f=fopen(path,"rb");CHECK(f && !fseek(f,0,SEEK_END));long n=ftell(f);CHECK(n>0 && !fseek(f,0,SEEK_SET));*bytes=(size_t)n;unsigned char*p=malloc(*bytes);CHECK(p && fread(p,1,*bytes,f)==*bytes);fclose(f);return p;}
static void setup(const void *record,unsigned count){
 memset(tables,0,sizeof(tables));tables[0].VendorGuid=expected;tables[0].VendorTable=(void*)record;
 tables[1]=tables[0];tables[2].VendorGuid=unrelated;tables[2].VendorTable=(void*)1;
 system_table.NumberOfTableEntries=count;system_table.ConfigurationTable=tables;gST=&system_table;prints=0;
}
static void trial(const unsigned char *original,size_t bytes,EFI_STATUS status,const struct hph_record *good){
 unsigned char *tree=malloc(bytes+32);CHECK(tree);memcpy(tree,original,bytes);memset(tree+bytes,0xa5,32);
 EFI_STATUS actual=DarwinGpuBindPowerHandoff(tree,bytes);
 if(actual!=status)fprintf(stderr,"actual=%llx expected=%llx\n",(unsigned long long)actual,(unsigned long long)status);
 CHECK(actual==status);
 if(status || !good){CHECK(!memcmp(tree,original,bytes) && !prints);}
 else {
  struct hpa_slot slot;CHECK(!hpa_find(original,bytes,&slot));
  CHECK(prints==1 && !memcmp(tree,original,slot.offset) && !memcmp(tree+slot.offset,good,sizeof(*good)));
  CHECK(!memcmp(tree+slot.offset+sizeof(*good),original+slot.offset+sizeof(*good),bytes-slot.offset-sizeof(*good)));
  struct hph_record decoded;CHECK(hph_decode(tree+slot.offset,1376,&decoded) && decoded.complete==1);
  CHECK(!memcmp(&decoded,good,1376));
  // Tree no longer references the producer object: later producer mutation
  // cannot affect the already copied scalar snapshot.
 }
 for(unsigned i=0;i<32;++i)CHECK(tree[bytes+i]==0xa5);free(tree);++cases;
}
int main(int argc,char**argv){
 CHECK(argc==3);zero_tree=load(argv[1],&zero_bytes);old_tree=load(argv[2],&old_bytes);
 CHECK(expected.Data1==0x02bec0e7 && expected.Data2==0xe434 && expected.Data3==0x48c6);
 const unsigned char tail[8]={0xba,0x89,0x3b,0x35,0xb5,0xb6,0x1e,0x47};CHECK(!memcmp(expected.Data4,tail,8));
 struct gpp_report p=power();struct mock m=initial();struct hph_record good={0},bad;
 CHECK(!run(&m,&p,&good) && good.complete && hph_record_valid(&good));
 setup(&good,1);trial(zero_tree,zero_bytes,EFI_SUCCESS,&good);
 setup(&good,3);tables[1].VendorGuid=unrelated;trial(zero_tree,zero_bytes,EFI_SUCCESS,&good);
 unsigned char unaligned[1377];memcpy(unaligned+1,&good,1376);setup(unaligned+1,1);trial(zero_tree,zero_bytes,EFI_SUCCESS,&good);
 setup(NULL,0);system_table.ConfigurationTable=NULL;trial(old_tree,old_bytes,EFI_SUCCESS,NULL);
 setup(NULL,1);tables[0].VendorGuid=unrelated;trial(old_tree,old_bytes,EFI_SUCCESS,NULL);
 // This old tree passes legacy AdtNode: bytes after a property-name NUL were
 // ignored there. Without the new property/GUID the transport remains a no-op.
 unsigned char *legacy=malloc(old_bytes);CHECK(legacy);memcpy(legacy,old_tree,old_bytes);legacy[8+31]=0xa5;
 setup(NULL,0);trial(legacy,old_bytes,EFI_SUCCESS,NULL);free(legacy);
 setup(NULL,0);trial(zero_tree,zero_bytes,EFI_COMPROMISED_DATA,NULL);
 setup(NULL,1);trial(zero_tree,zero_bytes,EFI_COMPROMISED_DATA,NULL);
 setup(&good,2);trial(zero_tree,zero_bytes,EFI_COMPROMISED_DATA,NULL);
 setup(&good,2);tables[1].VendorTable=NULL;trial(zero_tree,zero_bytes,EFI_COMPROMISED_DATA,NULL);
 setup(&good,1);tables[0].VendorGuid=unrelated;trial(zero_tree,zero_bytes,EFI_COMPROMISED_DATA,NULL);
 setup(&good,1);trial(old_tree,old_bytes,EFI_COMPROMISED_DATA,NULL);
 setup((void*)1,1);trial(old_tree,old_bytes,EFI_COMPROMISED_DATA,NULL); // no source read without a slot
 setup((void*)(UINTPTR_MAX-8),1);trial(zero_tree,zero_bytes,EFI_COMPROMISED_DATA,NULL);
 setup(&good,1);system_table.ConfigurationTable=NULL;trial(zero_tree,zero_bytes,EFI_INVALID_PARAMETER,NULL);
 setup(&good,1);gST=NULL;trial(zero_tree,zero_bytes,EFI_INVALID_PARAMETER,NULL);
 setup(&good,1);system_table.NumberOfTableEntries=SIZE_MAX;trial(zero_tree,zero_bytes,EFI_INVALID_PARAMETER,NULL);
 setup(&good,1);system_table.ConfigurationTable=(void*)(UINTPTR_MAX-8);trial(zero_tree,zero_bytes,EFI_INVALID_PARAMETER,NULL);
 setup(&good,1);CHECK(DarwinGpuBindPowerHandoff(NULL,zero_bytes)==EFI_INVALID_PARAMETER && !prints);++cases;
 setup(&good,1);CHECK(DarwinGpuBindPowerHandoff(zero_tree,0)==EFI_INVALID_PARAMETER && !prints);++cases;
 setup(&good,1);CHECK(DarwinGpuBindPowerHandoff((void*)(UINTPTR_MAX-8),16)==EFI_INVALID_PARAMETER && !prints);++cases;
 // Every record byte must survive exact actual CRC/semantic decode.
 for(unsigned i=0;i<1376;++i){bad=good;((unsigned char*)&bad)[i]^=1;setup(&bad,1);trial(zero_tree,zero_bytes,EFI_COMPROMISED_DATA,NULL);}
 // A CRC-valid failed record is deliberately decodable for diagnostics, but
 // the loader must never qualify it as a completed power handoff.
 m=initial();m.fail_hub=1;memset(&bad,0,sizeof(bad));CHECK(run(&m,&p,&bad) && hph_record_valid(&bad) && !bad.complete);
 struct hph_record decoded;CHECK(hph_decode(&bad,1376,&decoded));setup(&bad,1);trial(zero_tree,zero_bytes,EFI_COMPROMISED_DATA,NULL);
 struct hpa_slot slot;CHECK(!hpa_find(zero_tree,zero_bytes,&slot));
 unsigned char *changed=malloc(zero_bytes);CHECK(changed);
 for(unsigned i=0;i<1376;++i){memcpy(changed,zero_tree,zero_bytes);changed[slot.offset+i]=1;setup(&good,1);trial(changed,zero_bytes,EFI_COMPROMISED_DATA,NULL);}
 memcpy(changed,zero_tree,zero_bytes);changed[HANDOFF_LATE_NODE_OFFSET]=1;setup(&good,1);trial(changed,zero_bytes,EFI_COMPROMISED_DATA,NULL);
 memcpy(changed,zero_tree,zero_bytes);changed[slot.offset-4+3]|=0x80;setup(&good,1);trial(changed,zero_bytes,EFI_COMPROMISED_DATA,NULL);
 memcpy(changed,zero_tree,zero_bytes);changed[slot.offset-4]^=1;setup(&good,1);trial(changed,zero_bytes,EFI_COMPROMISED_DATA,NULL);
 // Reject aliasing the config-table source with the private ADT.
 memcpy(changed,zero_tree,zero_bytes);setup(changed+slot.offset,1);
 CHECK(DarwinGpuBindPowerHandoff(changed,zero_bytes)==EFI_COMPROMISED_DATA && !memcmp(changed,zero_tree,zero_bytes) && !prints);++cases;
 // Already copied tree is not a writable zero slot, even with the same record.
 memcpy(changed,zero_tree,zero_bytes);CHECK(!hpa_bind(changed,zero_bytes,&good,1376,NULL));setup(&good,1);trial(changed,zero_bytes,EFI_COMPROMISED_DATA,NULL);
 // Demonstrate snapshot independence and that no source pointer is substituted.
 memcpy(changed,zero_tree,zero_bytes);setup(&good,1);CHECK(!DarwinGpuBindPowerHandoff(changed,zero_bytes));
 bad=good;memset(&good,0,sizeof(good));CHECK(!memcmp(changed+slot.offset,&bad,1376));++cases;
 free(changed);free(zero_tree);free(old_tree);printf("PASS: actual DarwinBoot helper %u unique-GUID/complete-record/CRC/legacy/scalar-copy/zero-slot/fail-before-write cases (ASAN/UBSAN); no EFI pointer in ADT\n",cases);return 0;
}
'''


def main():
    manifest = json.loads((HERE / 'darwinboot-power-handoff-manifest.json').read_text())
    for entry in manifest['files']:
        assert hashlib.sha256((DRIVER / entry['name']).read_bytes()).hexdigest() == entry['after_sha256'], entry['name']
        if entry.get('source'):
            assert (DRIVER / entry['name']).read_bytes() == Path(entry['source']).read_bytes()
    source = (DRIVER / 'DarwinBoot.c').read_text()
    before = (HERE / 'darwinboot-power-handoff-before.c').read_text()
    added_include = '#include "DarwinBootGpuHandoff.h"\n'
    added_call = '  Status = DarwinGpuBindPowerHandoff (Tree, TreeSize);\n  if (EFI_ERROR (Status)) { goto Fail; }\n'
    assert source.count(added_include) == source.count(added_call) == 1
    assert source.replace(added_include, '').replace(added_call, '') == before
    validate = source.index('  if (!AdtNode (Tree, TreeSize,')
    bind = source.index(added_call)
    allocate = source.index('  Status = AllocateWindow (&Kernel, WindowSize, &Address);')
    copied = source.index('  CopyMem ((VOID *)(UINTN)TreeAddress, Tree, TreeSize);')
    exit_bs = source.index('gBS->ExitBootServices')
    assert validate < bind < allocate < copied < exit_bs
    generated, _ = generator.generate(generator.DEFAULT_INPUT.read_bytes())
    _, nodes, _ = generator.parse(generated)
    late_child_count = nodes[-1]['start'] + 4
    with tempfile.TemporaryDirectory(prefix='darwinboot-power-handoff-') as directory:
        tmp = Path(directory)
        (tmp / 'zero.adt').write_bytes(generated)
        cpp = tmp / 'test.c';cpp.write_text(fixture + peer)
        binary = tmp / 'test'
        subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O1',
                        '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                        '-DHANDOFF_LATE_NODE_OFFSET=' + str(late_child_count),
                        '-I' + str(DRIVER), str(cpp), '-o', str(binary)], check=True)
        subprocess.run([str(binary), str(tmp / 'zero.adt'), str(generator.DEFAULT_INPUT)], check=True)
    print('PASS: actual integration ordering and exact original Request/window/remaining loader bytes; current imported source hashes agree')


if __name__ == '__main__':
    main()
