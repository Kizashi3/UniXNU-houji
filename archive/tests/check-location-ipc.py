#!/usr/bin/env python3
"""Run the real passive IPC observer with mock ports; verify no message mutation."""
from pathlib import Path
import subprocess
import tempfile

P=Path(__file__).resolve().parents[1]
prefix=r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#define LCK_GRP_DECLARE(name, label) int name
#define LCK_SPIN_DECLARE(name, group) int name
struct task { int pid; };
struct imp_task { struct task *iit_task; };
#define IIT_NULL NULL
struct ipc_space { bool active; struct task *is_task; };
struct port { bool active, ip_tempowner, in_space; unsigned type;
  struct { unsigned imq_msgcount; } ip_messages;
  struct ipc_space *space; uint32_t ip_receiver_name; struct imp_task *ip_imp_task; };
typedef struct port *ipc_port_t;
typedef struct ipc_space *ipc_space_t;
typedef uintptr_t thread_t;
typedef struct { int msgh_id; uint32_t untouched[7]; } mach_msg_header_t;
static int locks,port_locks,port_queries,requested,boot_queries;
static int current_pid=41;
static const char *current_name="locationd";
static void lck_spin_lock(int *p){(void)p;assert(!port_locks);locks++;}
static void lck_spin_unlock(int *p){(void)p;assert(locks==1);locks--;}
static void ip_mq_lock(ipc_port_t p){(void)p;assert(!locks&&!port_locks);port_locks++;port_queries++;}
static void ip_mq_unlock(ipc_port_t p){(void)p;assert(port_locks==1);port_locks--;}
static bool ip_active(ipc_port_t p){assert(port_locks);return p->active;}
static unsigned ip_kotype(ipc_port_t p){assert(port_locks);return p->type;}
static bool ip_in_transit(ipc_port_t p){assert(port_locks);return !p->in_space;}
static struct imp_task *ip_get_imp_task(ipc_port_t p){assert(port_locks);return p->ip_imp_task;}
static bool ip_in_a_space(ipc_port_t p){assert(port_locks);return p->in_space;}
static ipc_space_t ip_get_receiver(ipc_port_t p){assert(port_locks);return p->space;}
static bool is_active(ipc_space_t s){assert(port_locks);return s->active;}
static int task_pid(struct task *task){return task->pid;}
static struct task *current_task(void){static struct task task;task.pid=current_pid;return &task;}
#define HOST_MAX_SPECIAL_PORT 33
static struct { ipc_port_t special[34]; } realhost;
static void host_lock(void *p){(void)p;assert(!locks&&!port_locks);}
static void host_unlock(void *p){(void)p;assert(!locks&&!port_locks);}
static uint64_t thread_tid(thread_t thread){return thread;}
static void clock_get_uptime(uint64_t *time){*time=12345;}
static void PE_parse_boot_argn(const char *name,int *result,unsigned size){
 assert(!strcmp(name,"houji_location_ipc")&&size==sizeof(int));*result=requested;boot_queries++;
}
void proc_selfname(char *buf,int size){assert(!locks&&!port_locks);snprintf(buf,size,"%s",current_name);}
void proc_name(int pid,char *buf,int size){assert(!locks&&!port_locks);snprintf(buf,size,"peer-%d",pid);}
'''
suffix=r'''
static void send(ipc_port_t port,int id) {
  mach_msg_header_t header={.msgh_id=id,.untouched={1,2,3,4,5,6,7}},before=header;
  struct port original=*port;
  houji_location_ipc_observe(port,&header,876,0x1234);
  assert(!memcmp(&header,&before,sizeof(header))&&!memcmp(port,&original,sizeof(original)));
  assert(!locks&&!port_locks);
}
int main(void) {
 struct task server={55},location={41},other={99};
 struct ipc_space space={true,&server};
 struct port p={true,false,true,0,{3},&space,0x510b,NULL};
 requested=0;send(&p,1203);assert(!port_queries&&!houji_location_ipc.requests);
 requested=1;send(&p,1203);assert(!port_queries&&boot_queries==1);realhost.special[17]=&p; // option is cached
 houji_location_ipc_enabled=-1;
 send(&p,999);assert(!port_queries);
 current_name="unrelated";send(&p,1203);assert(!port_queries);
 current_name="locationd";send(&p,1203);
 assert(houji_location_ipc.requests==1&&houji_location_ipc.peer_pid==55&&houji_location_ipc.host_slot==17);
 assert(houji_location_ipc.peer_name==0x510b&&houji_location_ipc.peer_queued==3);
 assert(houji_location_ipc.location_pid==41&&houji_location_ipc.request_tid==876);
 current_name="service";current_pid=55;space.is_task=&other;send(&p,1303);
 assert(!houji_location_ipc.replies);
 space.is_task=&location;send(&p,1303);
 assert(houji_location_ipc.replies==1&&houji_location_ipc.reply_pid==55);
 current_name="locationd";current_pid=41;
 p.active=false;send(&p,1203);assert(houji_location_ipc.peer_pid==-1);
 p.active=true;p.ip_tempowner=true;send(&p,1203);assert(houji_location_ipc.peer_pid==-1);
 p.ip_tempowner=false;p.in_space=false;send(&p,1203);assert(houji_location_ipc.peer_pid==-1);
 p.in_space=true;space.active=false;send(&p,1203);assert(houji_location_ipc.peer_pid==-1);
 space.active=true;space.is_task=&server;send(&p,1203);houji_location_ipc_report();
 assert(houji_location_ipc.requests==6&&houji_location_ipc.replies==1);
 struct imp_task imp={&server};p.ip_tempowner=true;p.ip_imp_task=&imp;send(&p,1203);
 assert(houji_location_ipc.peer_pid==55&&houji_location_ipc.peer_state==1);
 assert(!houji_location_ipc_receiving(0x9999,55));
 bool tracked=houji_location_ipc_receiving(0x1234,55);assert(tracked);
 houji_location_ipc_received(tracked,0);assert(houji_location_ipc.receive_attempts==1&&houji_location_ipc.receive_results==1&&houji_location_ipc.receive_pid==55);
 houji_location_ipc_freed(0x1234);assert(!houji_location_ipc.freed_unreceived);
 send(&p,1203);houji_location_ipc_freed(0x8888);assert(!houji_location_ipc.freed_unreceived);
 houji_location_ipc_freed(0x1234);assert(houji_location_ipc.freed_unreceived==1&&!houji_location_ipc.request_token);
 assert(!houji_location_ipc_receiving(0x1234,55)); // allocator reuse after free
 send(&p,1203);tracked=houji_location_ipc_receiving(0x1234,55);houji_location_ipc_received(tracked,0x10000001);
 assert(houji_location_ipc.receive_status==0x10000001);houji_location_ipc_report();
 puts("PASS: passive routing, temporary owner, actual receipt/result, free/reuse guards, lock balance and no message/port mutation");
}
'''
with tempfile.TemporaryDirectory() as directory:
    d=Path(directory)
    source=prefix+(P/'native/location-ipc/HoujiLocationIpc.inc').read_text()+suffix
    (d/'check.c').write_text(source)
    subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Wno-format',
                    '-fsanitize=address,undefined',str(d/'check.c'),'-o',str(d/'check')],check=True)
    subprocess.run([str(d/'check')],check=True)
