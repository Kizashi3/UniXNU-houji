#include "ArmSmmu4KContext.h"
#include <stdlib.h>
#include <stdio.h>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"line%d %s\n",__LINE__,#x);abort();}}while(0)
int main(){ArmSmmu4KConfig g={32,36,0x8c3000000,524288};ArmSmmu4KResult t={g.table_physical,0xff44,1027,1567,1,0};ArmSmmu4KContextConfig c={&g,0,&t,0,0x4c017e18,0x5511,0x751,0,0,0,1};ArmSmmu4KContextImage x,y;CHECK(!ArmSmmu4KEncodeContext(&c,&x) && x.sctlr==0x1027);y=x;y.sctlr=0x27;CHECK(!ArmSmmu4KValidateContextReadback(&c,&y));y.sctlr=0x67;CHECK(ArmSmmu4KValidateContextReadback(&c,&y)==ArmSmmu4KStateMismatch);c.polling_faults=0;CHECK(!ArmSmmu4KEncodeContext(&c,&x) && x.sctlr==0x1067);CHECK(!ArmSmmu4KValidateContextReadback(&c,&y));y.sctlr=0x27;CHECK(ArmSmmu4KValidateContextReadback(&c,&y)==ArmSmmu4KStateMismatch);c.polling_faults=2;CHECK(ArmSmmu4KEncodeContext(&c,&x)==ArmSmmu4KArgument);puts("PASS 6 exact IRQ/polling context profiles; fault reporting retained, no broad readback masks");}
