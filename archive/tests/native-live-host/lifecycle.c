#define main legacy_test_main
#include "${HOUJI_PORT_ROOT}/tests/check-gpu-host-ring.c"
#undef main
static int keep(void*c,struct hhr_result*r){(void)c;assert(!r->code && r->phase==7 && r->writebacks==2);return 1;}
static int decline(void*c,struct hhr_result*r){(void)c;(void)r;return 0;}
static int invalid_keep(void*c,struct hhr_result*r){(void)c;(void)r;return 2;}
static int failed_keep(void*c,struct hhr_result*r){(void)c;r->code=HHR_POST_INIT;return 0;}
int main(){int(*callbacks[])(void*,struct hhr_result*)={keep,decline,invalid_keep,failed_keep};
for(unsigned i=0;i<4;i++){struct model m={0};struct hhr_result r={0};struct hhr_io io=ops(&m);io.retain_live=callbacks[i];unsigned code=hhr_run(&io,&r);
if(i==0)assert(!code && r.retained && !r.stopped && !m.stops && m.sqe==1);
else {assert(!r.retained && r.stopped && m.stops==1);assert((i==3)==!!code);}}
puts("PASS4 actual HHR lifecycle: retained differs from stopped, decline/invalid/failure preserve original stop; register peer only, no GPU emulation");}
