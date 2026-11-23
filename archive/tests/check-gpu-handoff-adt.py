#!/usr/bin/env python3
"""Real ADT roundtrip + actual freestanding scalar transport, ASAN/UBSAN.

No loader/device changes. Record semantic/CRC qualification remains the
caller's hph_decode responsibility; this test checks only bounded transport.
"""
import importlib.util
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

P = Path(__file__).resolve().parents[1]
HERE = P / 'native/gpu/handoff'
SCRIPT = HERE / 'make-houji-gpu-power-handoff-adt.py'
spec = importlib.util.spec_from_file_location('handoff_generator', SCRIPT)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


def prop(key, value, flags=0):
    return key.encode().ljust(32, b'\0') + struct.pack('<I', len(value) | flags) + value + bytes(-len(value) & 3)


def node(name, props=(), children=(), name_last=False):
    entries = [prop('name', name.encode() + b'\0')]
    entries = list(props) + entries if name_last else entries + list(props)
    return struct.pack('<II', len(entries), len(children)) + b''.join(entries) + b''.join(children)


slot = prop(generator.PROPERTY, bytes(generator.RECORD_BYTES))


def tree(chosen=None, others=(), root_props=()):
    return node('device-tree', root_props, [chosen or node('chosen', [slot]), *others])


harness = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "GpuPowerHandoffAdt.h"
#include "GpuPowerOnlyHandoff.h"
typedef char same_record_size[HPA_RECORD_BYTES==HPH_RECORD_BYTES?1:-1];
#define CHECK(x) do {if(!(x)){fprintf(stderr,"line %u case %u: %s\n",(unsigned)__LINE__,cases,#x);abort();}}while(0)
static unsigned cases;
static unsigned char record[HPA_RECORD_BYTES];
static uint32_t u32(FILE*f) {unsigned char b[4];CHECK(fread(b,1,4,f)==4);return hpa_u32(b);}
static void check_case(const unsigned char *original,size_t bytes,int valid) {
 unsigned char *data=(unsigned char*)malloc(bytes+64);CHECK(data);memcpy(data,original,bytes);memset(data+bytes,0xa5,64);
 struct hpa_slot out={SIZE_MAX,17},bound={SIZE_MAX,19};
 int found=hpa_find(data,bytes,&out);CHECK((found==0)==valid);
 CHECK(!memcmp(data,original,bytes));for(unsigned i=0;i<64;++i)CHECK(data[bytes+i]==0xa5);
 if(!valid)CHECK(out.offset==SIZE_MAX && out.bytes==17);
 unsigned char record_copy[HPA_RECORD_BYTES];memcpy(record_copy,record,sizeof(record));
 int result=hpa_bind(data,bytes,record,sizeof(record),&bound);CHECK((result==0)==valid);
 CHECK(!memcmp(record,record_copy,sizeof(record)));
 if(valid) {
  CHECK(out.bytes==1376 && bound.bytes==1376 && out.offset==bound.offset && out.offset<=bytes && 1376<=bytes-out.offset);
  CHECK(!memcmp(data,original,out.offset));CHECK(!memcmp(data+out.offset,record,1376));
  CHECK(!memcmp(data+out.offset+1376,original+out.offset+1376,bytes-out.offset-1376));
  unsigned char *bound_copy=(unsigned char*)malloc(bytes);CHECK(bound_copy);memcpy(bound_copy,data,bytes);
  out.offset=SIZE_MAX;out.bytes=29;CHECK(hpa_find(data,bytes,&out)==HPA_NONZERO && out.offset==SIZE_MAX && out.bytes==29);
  CHECK(hpa_bind(data,bytes,record,sizeof(record),NULL)==HPA_NONZERO && !memcmp(data,bound_copy,bytes));
  free(bound_copy);
  memcpy(data,original,bytes);CHECK(!hpa_bind(data,bytes,record,sizeof(record),NULL));CHECK(!memcmp(data+bound.offset,record,1376));
 } else {CHECK(bound.offset==SIZE_MAX && bound.bytes==19 && !memcmp(data,original,bytes));}
 for(unsigned i=0;i<64;++i)CHECK(data[bytes+i]==0xa5);free(data);++cases;
}
static void aliases(const unsigned char *original,size_t bytes) {
 unsigned char *data=(unsigned char*)malloc(bytes);CHECK(data);memcpy(data,original,bytes);
 struct hpa_slot out={SIZE_MAX,31};CHECK(!hpa_find(data,bytes,&out));size_t offset=out.offset;
 CHECK(hpa_find(NULL,bytes,&out)==HPA_ARGUMENT);CHECK(hpa_find(data,bytes,NULL)==HPA_ARGUMENT);
 CHECK(hpa_find(data,0,&out)==HPA_ARGUMENT);CHECK(hpa_find(data,HPA_MAX_ADT_BYTES+1,&out)==HPA_ARGUMENT);
 CHECK(hpa_find((const void*)(UINTPTR_MAX-8),16,&out)==HPA_ARGUMENT);
 CHECK(hpa_find(data,bytes,(struct hpa_slot*)(UINTPTR_MAX-4))==HPA_ARGUMENT);
 CHECK(hpa_find(data,bytes,(struct hpa_slot*)(void*)(data+4))==HPA_ALIAS);
 CHECK(hpa_bind(data,bytes,NULL,1376,&out)==HPA_ARGUMENT);
 CHECK(hpa_bind(NULL,bytes,record,1376,&out)==HPA_ARGUMENT);
 CHECK(hpa_bind(data,bytes,(void*)(UINTPTR_MAX-8),1376,&out)==HPA_ARGUMENT);
 for(size_t length=0;length<=1377;++length)if(length!=1376){CHECK(hpa_bind(data,bytes,record,length,&out)==HPA_ARGUMENT);CHECK(!memcmp(data,original,bytes));++cases;}
 CHECK(hpa_bind(data,bytes,data+offset,1376,&out)==HPA_ALIAS);
 CHECK(hpa_bind(data,bytes,record,1376,(struct hpa_slot*)(void*)(data+4))==HPA_ALIAS);
 CHECK(hpa_bind(data,bytes,record,1376,(struct hpa_slot*)(void*)(record+4))==HPA_ALIAS);
 CHECK(!memcmp(data,original,bytes));free(data);cases+=13;
}
int main(int argc,char **argv) {
 CHECK(argc==3);for(unsigned i=0;i<1376;++i)record[i]=(unsigned char)(29*i+7);
 FILE *f=fopen(argv[1],"rb");CHECK(f);uint32_t count=u32(f);
 for(uint32_t i=0;i<count;++i){uint32_t bytes=u32(f),valid=u32(f);unsigned char *b=(unsigned char*)malloc(bytes?bytes:1);CHECK(b && fread(b,1,bytes,f)==bytes);check_case(b,bytes,(int)valid);free(b);}
 CHECK(fgetc(f)==EOF);fclose(f);
 f=fopen(argv[2],"rb");CHECK(f && !fseek(f,0,SEEK_END));long size=ftell(f);CHECK(size>0 && !fseek(f,0,SEEK_SET));
 unsigned char *base=(unsigned char*)malloc((size_t)size),*mutated=(unsigned char*)malloc((size_t)size);CHECK(base && mutated && fread(base,1,(size_t)size,f)==(size_t)size);fclose(f);aliases(base,(size_t)size);
 // Deterministic bit-mutation corpus: validity may change for unrelated value
 // bytes; the actual parser decides. Every failed bind must stay byte-exact.
 uint32_t seed=0x1401376u;
 for(unsigned iteration=0;iteration<4096;++iteration){
  memcpy(mutated,base,(size_t)size);for(unsigned change=0;change<=iteration%5;++change){seed=seed*1664525u+1013904223u;size_t at=seed%(size_t)size;seed=seed*1664525u+1013904223u;mutated[at]^=(unsigned char)(1u<<(seed&7));}
  struct hpa_slot found={0,0};int valid=!hpa_find(mutated,(size_t)size,&found);check_case(mutated,(size_t)size,valid);
 }
 free(base);free(mutated);printf("PASS: actual ADT helper %u bounds/full-tree/duplicate/zero-slot/copy/alias/mutation cases (ASAN/UBSAN); scalar transport only\n",cases);return 0;
}
'''


def main():
    source = generator.DEFAULT_INPUT.read_bytes()
    assert hashlib.sha256(source).hexdigest() == generator.SOURCE_SHA256
    generated, report = generator.generate(source)
    assert report['slot_bytes'] == 1376 and len(generated) - len(source) == 36 + 1376
    _, nodes, chosen = generator.parse(generated)
    prop_slots = [(n, p) for n in nodes for p in n['props'] if p['key'] == generator.PROPERTY]
    assert len(prop_slots) == 1 and prop_slots[0][0] is chosen
    target = prop_slots[0][1]
    # Independent pre-existing ADT tool verifies semantic and byte roundtrip.
    sys.path.insert(0, str(P / '.cache/ios16-reference/vermeer/tools'))
    import adt
    parsed, used = adt.parse(generated)
    assert used == len(generated) and adt.serialize(parsed) == generated
    actual_chosen = next(n for n in parsed.children if n.name == 'chosen')
    assert actual_chosen.prop(generator.PROPERTY) == bytes(1376)
    actual_chosen.props = [(k, f, v) for k, f, v in actual_chosen.props if k != generator.PROPERTY]
    assert adt.serialize(parsed) == source

    fixtures = [(tree(), True), (generated, True), (source, False),
        (tree(node('chosen', [slot], name_last=True)), True),
        (tree(node('chosen', [prop('arbitrary', b'123'), slot])), True)]
    bad = [b'', b'\0' * 8, tree() + b'\0', tree(node('not-chosen', [slot])),
        node('wrong-root', children=[node('chosen', [slot])]),
        tree(node('chosen', [slot, slot])), tree(others=[node('chosen')]),
        tree(others=[node('other', [slot])]), tree(root_props=[slot]),
        node('device-tree', children=[node('wrapper', children=[node('chosen', [slot])])]),
        tree(node('chosen', [slot, prop('duplicate', b'a'), prop('duplicate', b'b')])),
        tree(node('chosen', [slot, prop('name', b'chosen\0')])),
        tree(node('chosen', [prop(generator.PROPERTY, bytes(1376), 0x80000000)])),
        tree(node('chosen', [prop(generator.PROPERTY, bytes(1375))])),
        tree(node('chosen', [prop(generator.PROPERTY, bytes(1377))]))]
    minimal = tree()
    for at, value in [(0, 0xffffffff), (4, 0xffffffff), (8 + 32, 0x7fffffff), (8 + 32, 0x8000000c)]:
        b = bytearray(minimal);struct.pack_into('<I', b, at, value);bad.append(bytes(b))
    # Every real property's flag/length/name field is independently malformed.
    for n in nodes:
        for p in n['props']:
            for value in (0x80000000 | p['bytes'], 0x7fffffff):
                b = bytearray(generated);struct.pack_into('<I', b, p['header'] + 32, value);bad.append(bytes(b))
            b = bytearray(generated);b[p['header']:p['header'] + 32] = b'A' * 32;bad.append(bytes(b))
            terminator = len(p['key'])
            if terminator < 31:
                b = bytearray(generated);b[p['header'] + terminator + 1] = 1;bad.append(bytes(b))
            if p['key'] == 'name':
                b = bytearray(generated);b[p['offset'] + p['bytes'] - 1] = 1;bad.append(bytes(b))
            if p['end'] > p['offset'] + p['bytes']:
                b = bytearray(generated);b[p['end'] - 1] = 1;bad.append(bytes(b))
    for offset in range(1376):
        b = bytearray(generated);b[target['offset'] + offset] = 1;bad.append(bytes(b))
    # Truncate at every structural/value boundary and its immediate neighbors,
    # including after the target was already found: full-tree validation wins.
    cuts = {0, 1, 7, len(generated) - 1}
    for n in nodes:
        for at in (n['start'], n['start'] + 8, n['props_end'], n['end']):
            cuts.update(x for x in (at - 1, at, at + 1) if 0 <= x < len(generated))
        for p in n['props']:
            for at in (p['header'], p['offset'], p['offset'] + p['bytes'], p['end']):
                cuts.update(x for x in (at - 1, at, at + 1) if 0 <= x < len(generated))
    bad.extend(generated[:cut] for cut in sorted(cuts))
    chain = node('leaf')
    for _ in range(63):
        chain = node('branch', children=[chain])
    fixtures.append((tree(others=[chain]), True))  # deepest node at64
    bad.append(tree(others=[node('branch', children=[chain])]))
    many = [slot] + [prop('p%03u' % i, b'') for i in range(254)]
    fixtures.append((tree(node('chosen', many)), True))  # name+255 props
    bad.append(tree(node('chosen', many + [prop('one-more', b'')])))
    # Name and nonzero alignment-pad variants of a small independent fixture.
    b = bytearray(tree(node('chosen', [slot, prop('short', b'x')])));b[-1] = 1;bad.append(bytes(b))
    fixtures.extend((b, False) for b in bad)

    with tempfile.TemporaryDirectory(prefix='houji-handoff-adt-') as directory:
        tmp = Path(directory)
        output, report_path = tmp / 'candidate.adt', tmp / 'candidate.json'
        command = [sys.executable, str(SCRIPT), '--output', str(output), '--report', str(report_path)]
        subprocess.run(command, check=True, stdout=subprocess.PIPE)
        assert output.read_bytes() == generated and json.loads(report_path.read_text()) == report
        # Generator never overwrites existing files and rejects changed input.
        assert subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode
        assert output.read_bytes() == generated
        wrong = tmp / 'wrong.adt';wrong.write_bytes(source[:-1] + bytes([source[-1] ^ 1]))
        absent = tmp / 'must-not-exist.adt'
        assert subprocess.run([sys.executable, str(SCRIPT), '--input', str(wrong), '--output', str(absent)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode
        assert not absent.exists() and not absent.with_suffix('.adt.json').exists()
        corpus = tmp / 'corpus.bin'
        with corpus.open('wb') as stream:
            stream.write(struct.pack('<I', len(fixtures)))
            for blob, valid in fixtures:
                stream.write(struct.pack('<II', len(blob), valid));stream.write(blob)
        path = tmp / 'test.c';path.write_text(harness)
        for compiler, language, standard in [('clang', 'c', 'c11'), ('clang++', 'c++', 'c++14')]:
            executable = tmp / ('test-' + language.replace('+', 'p'))
            subprocess.run([compiler, '-x', language, '-std=' + standard, '-Wall', '-Wextra', '-Werror',
                            '-O1', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                            '-I' + str(HERE), '-I' + str(P / 'native/gpu/uefi'), str(path), '-o', str(executable)], check=True)
            subprocess.run([str(executable), str(corpus), str(output)], check=True)
    assert hashlib.sha256(generator.DEFAULT_INPUT.read_bytes()).hexdigest() == generator.SOURCE_SHA256
    print('PASS: pinned real ADT generator, independent semantic/exact-byte roundtrip, exclusive output and rejected changed source; candidate remains unintegrated')


if __name__ == '__main__':
    main()
