#!/usr/bin/env python3
"""Candidate-only profile tests using the copied, unchanged actual core peer."""
from pathlib import Path
import ast
import hashlib
import json
import subprocess

p = Path(__file__).resolve().parents[1]
build = p / 'build' / 'nc-profile'
build.mkdir(parents=True, exist_ok=True)
original = p / 'tests/check-gmu-external-canary.py'
tree = ast.parse(original.read_text())
assignment = next(n for n in tree.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == 'program' for t in n.targets))
call = assignment.value
assert isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
assert call.func.attr == 'replace' and isinstance(call.func.value, ast.Constant)
program = call.func.value.value.replace('FIXTURE', str(p / 'tests/check-gpu-power-only-handoff.c'))
commands = []

def run(args, name):
    commands.append(args)
    result = subprocess.run(args, text=True, capture_output=True)
    (build / (name + '.log')).write_text(result.stdout + result.stderr)
    print(result.stdout, end='')
    if result.returncode:
        print(result.stderr, end='')
        raise SystemExit(result.returncode)

vendor = p / 'native/gpu/vendor/ArmSmmu4K'
sources = [vendor / (name + '.c') for name in
           ['ArmSmmu4K', 'ArmSmmu4KAudit', 'ArmSmmu4KContext', 'ArmSmmu4KProgram']]
flags = ['-std=c11', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
         '-fno-omit-frame-pointer', '-I', str(vendor), '-I', str(p / 'native/gpu/xnu'),
         '-I', str(p / 'native/gpu/uefi'), '-I', str(p / 'native/gpu')]

# This TU uses the exact old core header. No candidate profile/ABI struct is
# passed across its boundary: only the unchanged gec_result byte representation.
baseline = program.replace('#define main handoff_fixture_main', '#define main baseline_handoff_fixture_main')
baseline = baseline.replace('#include "GmuExternalCanary.h"', '#include "' + str(p / 'tests/fixtures/gmu-external-writeback-baseline.h') + '"')
baseline = baseline.replace('int main(void){', 'int baseline_suite_main(void){')
baseline += r'''
size_t baseline_result_bytes(void){return sizeof(struct gec_result);}
unsigned baseline_result(unsigned cpu,unsigned ones,unsigned high,unsigned mode,void*out,size_t bytes){
 struct gpp_report power_good=power();good_bus=initial();memset(&good_record,0,sizeof(good_record));assert(run(&good_bus,&power_good,&good_record)==0);
 assert(bytes==sizeof(t.result));init(cpu,ones);if(high)high_pa();
 if(mode==1)t.expected_fault=1;if(mode==2)t.partial_dma=1;if(mode==3)t.bad_mailbox=3;
 if(mode==4){t.expected_fault=1;t.frame_damage=1;}if(mode==5)t.fail_publish=1;
 if(mode==6)t.fail_finish=1;if(mode==7)t.fail_read=10;
 unsigned code=run_exec();memcpy(out,&t.result,bytes);return code;
}
'''
(build / 'baseline.c').write_text(baseline)

extra = r'''
extern size_t baseline_result_bytes(void);
extern unsigned baseline_result(unsigned,unsigned,unsigned,unsigned,void*,size_t);
static void rebuild_profile(unsigned profile){
 t.memory.memory_profile=profile;
 t.memory.owned.range.writeback=profile==GEC_MEMORY_WRITEBACK;
 assert(ArmSmmu4KBuild(&t.memory.owned.config,&t.memory.owned.range,1,(uint64_t*)table_cpu,3,&t.memory.owned.built)==0);
}
static void input_only(void){
 assert(run_exec()==GEC_INPUT);check();
 assert(!t.reads && !t.writes && !t.barriers && !t.freshes && !t.owners && !t.commits && !t.memory_checks && !t.publishes && !t.finishes);
 assert(t.result.retained && t.result.table_held && !t.result.possible_execution && !t.result.safe_to_save);
}
static void profile_cases(void){
 unsigned before=cases;
 /* All bytes of the unchanged result remain identical for default profile0:
  * both terminal forms, CPU4K/16K, low/high PA, zero/ones TCM, and refusals. */
 static unsigned char old_result[sizeof(struct gec_result)];
 const size_t old_bytes=baseline_result_bytes();assert(old_bytes==offsetof(struct gec_result,memory_profile));
 for(unsigned cpu=4096;cpu<=16384;cpu*=4)for(unsigned ones=0;ones<2;ones++)
  for(unsigned high=0;high<2;high++)for(unsigned mode=0;mode<8;mode++){
   unsigned old_code=baseline_result(cpu,ones,high,mode,old_result,old_bytes);
   init(cpu,ones);if(high)high_pa();rebuild_profile(GEC_MEMORY_WRITEBACK);
   if(mode==1)t.expected_fault=1;if(mode==2)t.partial_dma=1;if(mode==3)t.bad_mailbox=3;
   if(mode==4){t.expected_fault=1;t.frame_damage=1;}if(mode==5)t.fail_publish=1;
   if(mode==6)t.fail_finish=1;if(mode==7)t.fail_read=10;
   assert(run_exec()==old_code);check();assert(!memcmp(old_result,&t.result,old_bytes));
   for(size_t byte=old_bytes;byte<sizeof(t.result);byte++)assert(!((const unsigned char*)&t.result)[byte]);
  }
 /* Both profiles retain identical tables/walk attributes/context images;
  * exactly one data leaf AttrIndx changes. The PRR zero is never a new IOVA. */
 for(unsigned cpu=4096;cpu<=16384;cpu*=4)for(unsigned high=0;high<2;high++){
  uint64_t wb_tables[1536],wb_context[9];
  init(cpu,0);if(high)high_pa();rebuild_profile(GEC_MEMORY_WRITEBACK);
  memcpy(wb_tables,table_cpu,sizeof(wb_tables));assert(run_exec()==0);check();memcpy(wb_context,t.result.context_image,sizeof(wb_context));
  init(cpu,0);if(high)high_pa();rebuild_profile(GEC_MEMORY_NORMAL_NC);
  const uint64_t*nc=(const uint64_t*)table_cpu;
  for(unsigned i=0;i<1536;i++)assert(nc[i]==(i==1024?(wb_tables[i]&~UINT64_C(0x1c)):wb_tables[i]));
  assert(((wb_tables[1024]>>2)&7)==1 && ((nc[1024]>>2)&7)==0 && !nc[1025] && !nc[1026]);
  assert(gec_memory_valid(&t.memory) && gec_tables_valid(&t.memory));
  assert(run_exec()==0);check();assert(!memcmp(wb_context,t.result.context_image,sizeof(wb_context)));
  assert(t.result.context_image[7]==0xff44 && t.result.context_image[8]==0);
 }
 for(unsigned cpu=4096;cpu<=16384;cpu*=4)for(unsigned profile=0;profile<2;profile++){
  init(cpu,0);rebuild_profile(profile);t.memory.memory_profile=2;input_only();
  init(cpu,0);rebuild_profile(profile);t.memory.memory_profile=UINT32_MAX;input_only();
  init(cpu,0);rebuild_profile(profile);t.memory.owned.range.writeback^=1;input_only();
  /* The requested range alone cannot bless a stale, opposite-profile table. */
  init(cpu,0);rebuild_profile(profile^1);t.memory.memory_profile=profile;t.memory.owned.range.writeback=profile==GEC_MEMORY_WRITEBACK;
  assert(gec_memory_valid(&t.memory) && !gec_tables_valid(&t.memory));
  assert(run_exec()==GEC_TABLE);check();assert(t.memory_checks==1 && !t.reads && !t.writes && !t.commits && !t.publishes && !t.finishes);
 }
 /* Explicit NC CPU16K ownership must still cover all rounded bytes and be
  * disjoint in both PA and VA. No mutation can get as far as a callback. */
 for(unsigned kind=0;kind<10;kind++){
  init(16384,0);rebuild_profile(GEC_MEMORY_NORMAL_NC);
  if(kind==0)t.memory.data_owned_bytes=4096;if(kind==1)t.memory.zero_owned_bytes=4096;
  if(kind==2)t.memory.table_owned_bytes=12288;if(kind==3)t.memory.owned.data_physical+=4096;
  if(kind==4)t.memory.zero_physical=t.memory.owned.data_physical;if(kind==5)t.memory.zero_cpu=data_cpu;
  if(kind==6)t.memory.owned.data=data_cpu+4096;if(kind==7)t.memory.zero_physical=(UINT64_C(1)<<36)-16384;
  if(kind==8)t.memory.cpu_page_bytes=8192;if(kind==9)t.memory.owned.range.shareability=0;
  input_only();
 }
 /* A prepared NC table cannot be damaged before device execution. */
 init(16384,0);rebuild_profile(GEC_MEMORY_NORMAL_NC);t.commit_table_damage=2;
 assert(run_exec()!=0);check();assert(!t.release_writes && t.result.retained && t.result.table_held);
 /* NC ordered acquisition/restore is explicit. It cannot be forged using
  * old invalidated=true or incomplete/wrong-profile cache proof fields. */
 for(unsigned bad=1;bad<=10;bad++){
  init(16384,0);rebuild_profile(GEC_MEMORY_NORMAL_NC);bad_nc_proof=bad;
  assert(run_exec()==GEC_CPU);check();assert(t.finishes==1 && t.commits==2 && !t.result.safe_to_save && !t.result.complete && t.result.retained && t.result.table_held);
 }
 init(16384,0);rebuild_profile(GEC_MEMORY_NORMAL_NC);assert(run_exec()==0);check();
 assert(!t.result.cpu.invalidated && t.result.memory_profile==1 && t.result.nc_acquired==6 && t.result.nc_restore_published==1 && t.result.nc_table_invalidated==1);
 {const struct gec_result good_nc=t.result;
  for(unsigned bad=0;bad<7;bad++){
   t.result=good_nc;if(bad==0)t.result.cpu.invalidated=1;if(bad==1)t.result.memory_profile=0;if(bad==2)t.result.memory_profile=2;
   if(bad==3)t.result.nc_acquired=0;if(bad==4)t.result.nc_acquired=7;if(bad==5)t.result.nc_restore_published=2;if(bad==6)t.result.nc_table_invalidated=7;
   assert(!gec_complete_proof(&t.result));cases++;
  }
 }
 /* Once is authoritative even if the caller later changes its profile. */
 init(16384,0);rebuild_profile(GEC_MEMORY_NORMAL_NC);assert(run_exec()==0);check();
 {const struct gec_result saved=t.result;unsigned reads=t.reads,writes=t.writes;
  t.memory.memory_profile=UINT32_MAX;assert(run_exec()==GEC_REUSED);
  assert(!memcmp(&saved,&t.result,sizeof(saved)) && t.reads==reads && t.writes==writes);cases++;}
 printf("PASS %u additional profile/old-result-byte-differential cases\n",cases-before);
}
'''

# A second complete run of the original assertions uses NC range semantics.
# Only the initializer and the existing "wrong cache attribute" mutation vary.
# The unchanged original Python/C source is separately executed as the WB gate.
needle = 'm->owned.range=(ArmSmmu4KRange){0x60000000,m->owned.data_physical,4096,ArmSmmu4KRead|ArmSmmu4KWrite,1,3};'
assert program.count(needle) == 1
nc_program = program.replace(needle, needle + '\n m->memory_profile=GEC_MEMORY_NORMAL_NC;m->owned.range.writeback=0;')
needle = 'if(kind==5)t.memory.owned.range.writeback=0;'
assert nc_program.count(needle) == 1
nc_program = nc_program.replace(needle, 'if(kind==5)t.memory.owned.range.writeback=1;')
needle = 'static struct test_state t;'
assert nc_program.count(needle) == 1
nc_program = nc_program.replace(needle, needle + '\nstatic unsigned bad_nc_proof;')
needle = 'memset(&t,0,sizeof(t));'
assert nc_program.count(needle) == 1
nc_program = nc_program.replace(needle, needle + 'bad_nc_proof=0;')
needle = 'r->invalidated=1;uint32_t*d='
assert nc_program.count(needle) == 1
nc_program = nc_program.replace(needle, '''r->invalidated=m->memory_profile==GEC_MEMORY_WRITEBACK;
 if(m->memory_profile==GEC_MEMORY_NORMAL_NC){x->result.nc_acquired=6;x->result.nc_restore_published=1;x->result.nc_table_invalidated=1;}
 uint32_t*d=''')
needle = 'r->padding_checked=1;r->verified=1;d[2]=0;r->restored=1;return 0;'
assert nc_program.count(needle) == 1
nc_program = nc_program.replace(needle, '''r->padding_checked=1;r->verified=1;d[2]=0;r->restored=1;
 if(bad_nc_proof==1)r->invalidated=1;if(bad_nc_proof==2)x->result.nc_acquired=2;
 if(bad_nc_proof==3)x->result.nc_acquired=7;if(bad_nc_proof==4)x->result.nc_restore_published=0;
 if(bad_nc_proof==5)x->result.nc_table_invalidated=0;if(bad_nc_proof==6)x->result.memory_profile=2;
 if(bad_nc_proof==7)x->result.memory_profile=0;if(bad_nc_proof==8)x->result.nc_restore_published=2;
 if(bad_nc_proof==9)x->result.nc_table_invalidated=7;if(bad_nc_proof==10)x->result.nc_acquired=0;
 return 0;''')
assert nc_program.count('int main(void){') == 1
nc_program = nc_program.replace('int main(void){', extra + '\nint main(void){')
needle = ' printf("PASS %u actual core/observer cases,'
assert nc_program.count(needle) == 1
nc_program = nc_program.replace(needle, ' profile_cases();\n' + needle)
(build / 'nc.c').write_text(nc_program)
baseline_obj = build / 'baseline.o'
run(['clang', *flags, '-c', str(build / 'baseline.c'), '-o', str(baseline_obj)], 'compile-baseline')
exe = build / 'test-nc'
run(['clang', *flags, str(build / 'nc.c'), str(baseline_obj), *map(str, sources), '-o', str(exe)], 'compile-nc')
run([str(exe)], 'run-nc')
result = {
    'hardware_tested': False,
    'original_test_sha256': hashlib.sha256(original.read_bytes()).hexdigest(),
    'old_header_sha256': hashlib.sha256((p / 'tests/fixtures/gmu-external-writeback-baseline.h').read_bytes()).hexdigest(),
    'candidate_header_sha256': hashlib.sha256((p / 'native/gpu/xnu/GmuExternalCanary.h').read_bytes()).hexdigest(),
    'nc_test_c_sha256': hashlib.sha256(nc_program.encode()).hexdigest(),
    'baseline_test_c_sha256': hashlib.sha256(baseline.encode()).hexdigest(),
    'commands': commands,
    'command_sha256': hashlib.sha256(json.dumps(commands, separators=(',', ':')).encode()).hexdigest(),
    'all_original_assertions_retained': True,
    'nc_derivative_changes': ['initializer selects NC profile and range', 'wrong-cache mutation selects WB', 'CPU finish peer reports explicit NC proof instead of WB invalidation', 'additional profile cases appended'],
    'default_wb_result_differential_cases': 64,
    'status': 'PASS',
}
(build / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
