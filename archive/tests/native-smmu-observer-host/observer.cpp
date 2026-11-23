#include "HoujiNativeSmmuReadPolicy.h"
#include "ArmSmmu4KStreams.h"
#include <cstdio>
#include <cstdlib>
#define CHECK(x) do {if(!(x)){fprintf(stderr,"%d: %s\n",__LINE__,#x);abort();}}while(0)
static ArmSmmu4KContextImage image;static unsigned writes,reads,denied;static size_t max_route;static int fault,conflict;
static int rd(void*,size_t at,uint32_t *v){++reads;if(!houjiNativeSmmuRead32Offset(at)){++denied;return 1;}
 switch(at){case 0:*v=0x2f0406;return 0;case 0x20:*v=0x4c017e18;return 0;case 0x24:*v=0x40000016;return 0;case 0x28:*v=0x5511;return 0;case 0x48:*v=fault;return 0;case 0x1000:*v=image.cbar;return 0;case 0x1800:*v=image.cba2r;return 0;case 0x20000:*v=image.sctlr&~0x1000;return 0;case 0x20010:*v=image.tcr2|0x60;return 0;case 0x20030:*v=image.tcr;return 0;case 0x20038:*v=image.mair0;return 0;case 0x2003c:*v=image.mair1;return 0;case 0x20058:case 0x207f4:*v=0;return 0;}
 if(at>=0x800 && at<0x860){size_t slot=(at-0x800)/4;if(slot>max_route)max_route=slot;*v=slot==0?0x80000005:slot<=2?0x80000000u+slot-1:conflict&&slot==23?0x80000000:0;return 0;}
 if(at>=0xc00 && at<0xc60){size_t slot=(at-0xc00)/4;*v=slot==0?2:slot<=2?0:conflict&&slot==23?0:2<<16;return 0;}return 1;
}
static int rd64(void*,size_t at,uint64_t*v){if(at==0x20020){*v=image.ttbr0;return 0;}if(at==0x20028){*v=image.ttbr1;return 0;}return 1;}
static int wr(void*,size_t,uint32_t){++writes;return 1;}static int wr64(void*,size_t,uint64_t){++writes;return 1;}static int bar(void*){return 0;}
int main(){ArmSmmu4KConfig cfg={32,36,0x8c3000000,524288};ArmSmmu4KResult tables={cfg.table_physical,0xff44,1027,1567,1,0};ArmSmmu4KContextConfig context={&cfg,nullptr,&tables,nullptr,0x4c017e18,0x5511,0x751,0,0,0,1};CHECK(!ArmSmmu4KEncodeContext(&context,&image));
 ArmSmmu4KIo io={nullptr,0x40000,rd,rd64,wr,wr64,bar};ArmSmmu4KStream routes[]={{1,0},{2,1}};ArmSmmu4KStreamState state{};ArmSmmu4KStreamResult result{};
 CHECK(!ArmSmmu4KAdoptStreams(&io,&state,routes,2,0,&context,&result));CHECK(state.attached && reads>100 && !denied && !writes && max_route==23);
 fault=1;CHECK(ArmSmmu4KObserveStreams(&io,&state,&context,&result)==ArmSmmu4KFault);fault=0;
 conflict=1;CHECK(ArmSmmu4KObserveStreams(&io,&state,&context,&result)==ArmSmmu4KBusy);conflict=0;
 const size_t bad[]={1,0x7fc,0x860,0xbfc,0xc60,0x20004,0x22000,0x100000000ull};for(auto at:bad)CHECK(!houjiNativeSmmuRead32Offset(at));
 CHECK(!writes);printf("PASS original Streams/Context observer complete namespace, all24 routes, fault/conflict refusal,8 unauthorized offsets; reads=%u writes=%u\n",reads,writes);
}
