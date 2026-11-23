#!/usr/bin/env python3
"""Exercise actual passive exit observer: status/reason propagation, no mutation."""
from pathlib import Path
import subprocess,tempfile
P=Path(__file__).resolve().parents[1]
prefix=r'''
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>
#include <assert.h>
#define LCK_GRP_DECLARE(name,label) int name
#define LCK_SPIN_DECLARE(name,group) int name
struct proc { char p_comm[17]; int pid; };
typedef struct proc *proc_t;
struct os_reason { uint32_t osr_namespace;uint64_t osr_code; };
struct task { uint64_t mach_header_vm_address; };
typedef struct task *task_t;
static struct task mock_task={0x100010000};
typedef struct { uint64_t pc,lr; } arm_saved_state_t;
static arm_saved_state_t regs={0x12345678,0x87654321};
static task_t proc_task(proc_t p){(void)p;return &mock_task;}
static task_t current_task(void){return &mock_task;}
uint64_t houji_task_mach_header(task_t task){return task->mach_header_vm_address;}
static void *current_thread(void){return NULL;}
static arm_saved_state_t *find_user_regs(void *t){(void)t;return &regs;}
static bool is_saved_state64(arm_saved_state_t *r){return r==&regs;}
static uint64_t get_saved_state_pc(arm_saved_state_t *r){return r->pc;}
static uint64_t get_saved_state_lr(arm_saved_state_t *r){return r->lr;}
static unsigned locks,requested;
static int copyinstr(user_addr_t from, char *to, size_t size, size_t *length){assert(!locks);if(!from)return 14;size_t n=strlen((const char *)from)+1;if(n>size)n=size;memcpy(to,(const char *)from,n);*length=n;return 0;}
static void lck_spin_lock(int *p){(void)p;assert(!locks);locks++;}
static void lck_spin_unlock(int *p){(void)p;assert(locks==1);locks--;}
static void PE_parse_boot_argn(const char *name,int *value,unsigned size){assert(!strcmp(name,"houji_location_ipc")&&size==sizeof(int));*value=requested;}
static int proc_getpid(proc_t p){return p->pid;}
static void clock_get_uptime(uint64_t *value){*value=12345;}
'''
suffix=r'''
int main(void) {
 struct proc p={"fairplayd.H2",101},before=p;
 struct os_reason why={3,0x1234},saved=why;
 houji_location_exit_observe(&p,0x900,&why);assert(!houji_exit_records[0].count);
 requested=1;houji_exit_enabled=-1;
 houji_location_exit_observe(&p,0x900,&why);
 assert(!memcmp(&p,&before,sizeof(p))&&!memcmp(&why,&saved,sizeof(why)));
 assert(houji_exit_records[0].count==1&&houji_exit_records[0].pid==101);
 assert(houji_exit_records[0].status==0x900&&houji_exit_records[0].reason_namespace==3&&houji_exit_records[0].reason_code==0x1234);
 strcpy(p.p_comm,"unrelated");houji_location_exit_observe(&p,1,&why);assert(houji_exit_records[0].count==1);
 strcpy(p.p_comm,"com.apple.migra");houji_location_exit_observe(&p,0,NULL);assert(houji_exit_records[4].count==1&&!houji_exit_records[4].reason_namespace);
 for(unsigned i=1;i<4;i++) {
  snprintf(p.p_comm,sizeof(p.p_comm),"%s",houji_exit_names[i]);houji_location_exit_observe(&p,9,&why);assert(houji_exit_records[i].count==1);
 }
 strcpy(p.p_comm,"fairplayd.H2");
 for(unsigned i=0;i<50;i++)houji_location_syscall_observe(&p,100+i,i%5,i,~i,0);
 houji_location_exit_observe(&p,0,NULL);
 assert(houji_exit_last_call_count==24&&houji_exit_last_calls[0].code==126&&houji_exit_last_calls[23].code==149);
 assert(houji_exit_records[0].mach_header==0x100010000&&houji_exit_records[0].pc==0x12345678);
 p.pid=102;houji_location_syscall_observe(&p,77,12,5,6,0);houji_location_exit_observe(&p,0,NULL);
 assert(houji_exit_last_call_count==1&&houji_exit_last_calls[0].code==77&&houji_exit_last_calls[0].error==12);
 const char *path="/private/var/test/missing";
 for(unsigned i=0;i<10;i++)houji_location_syscall_observe(&p,5,2,0,0,(uintptr_t)path);
 houji_location_exit_observe(&p,0,NULL);assert(houji_exit_last_open_count==8);
 assert(!strcmp(houji_exit_last_opens[7].path,path)&&houji_exit_last_opens[7].error==2);
 assert(!strcmp(path,"/private/var/test/missing"));
 houji_location_exit_report();assert(!locks);
 puts("PASS: disabled/filter paths, exact exit status/reason, no proc/reason mutation, balanced locks");
}
'''
with tempfile.TemporaryDirectory() as directory:
 d=Path(directory);(d/'check.c').write_text(prefix+(P/'native/location-ipc/HoujiExitObserver.inc').read_text()+suffix)
 subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Wno-unused-variable','-Wno-format','-fsanitize=address,undefined',str(d/'check.c'),'-o',str(d/'check')],check=True)
 subprocess.run([str(d/'check')],check=True)
