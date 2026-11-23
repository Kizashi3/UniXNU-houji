// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <assert.h>
#include <stdio.h>
#include "GpuSharedMemory.h"
int main(void){
 uint32_t request[]={0x00900b14,1,0,0,0x33f,2,0,2,0,4096,0};struct hsc_slice s;unsigned cases=0;
 uint32_t rw=3*HSC_CLASS_BYTES;
 assert(!hsc_resource_plan(request,11,rw,&s) && s.offset==rw && s.bytes==4096 && s.next==rw+4096);cases++;
 request[5]=request[7]=14;assert(!hsc_resource_plan(request,11,rw+4096,&s) && s.offset==rw+4096 && s.bytes==4096);cases++;
 request[4]=0x339;request[5]=request[7]=15;assert(!hsc_resource_plan(request,11,0,&s) && !s.offset && s.bytes==4096);cases++;
 // Packed wire sizes remain logical; the arena consumes full pages.
 request[5]=3;request[9]=24;assert(!hsc_resource_plan(request,11,8192,&s) && s.bytes==4096 && request[9]==24);cases++;
 request[9]=0x37d000;assert(hsc_resource_plan(request,11,0,&s));cases++;
 request[9]=4096;
 for(unsigned kind=0;kind<32;kind++){
  request[5]=kind;int unsupported=kind>=26 || kind==5 || kind==11 || kind==12 || kind==13 || kind==19 || kind==20 || kind==22 || kind==23;
  assert((hsc_resource_plan(request,11,0,&s)!=0)==unsupported);cases++;
 }
 request[5]=2;
 for(unsigned bit=0;bit<32;bit++){
  request[4]^=1u<<bit;unsigned cls=hsc_resource_class(request[4]);
  assert((hsc_resource_plan(request,11,cls<HSC_CLASSES?cls*HSC_CLASS_BYTES:0,&s)==0)==(bit==1 || bit==2 || bit==6 || bit==8 || bit==9));
  request[4]^=1u<<bit;cases++;
 }
 for(unsigned va=0;va<=21;va++)for(unsigned size=0;size<=21;size++) {
  request[10]=va|(size<<8);int status=hsc_resource_plan(request,11,4096,&s);
  if(va>20 || size>20)assert(status);
  else if(!status){assert(!((HSC_POOL_IOVA+s.offset)&((1u<<va)-1)) && !(s.bytes&((1u<<size)-1)) && !(s.offset&4095) && !(s.bytes&4095) && s.offset>=4096 && s.next<=HSC_CLASS_BYTES);}
  cases++;
 }
 request[10]=0;
 for(unsigned cls=0;cls<HSC_CLASSES;cls++)for(unsigned cursor=cls*HSC_CLASS_BYTES;cursor<=(cls+1)*HSC_CLASS_BYTES;cursor+=4096){
  request[4]=0x339|(cls<<1);int status=hsc_resource_plan(request,11,cursor,&s);assert((status!=0)==(cursor==(cls+1)*HSC_CLASS_BYTES));if(!status)assert(s.offset==cursor && s.next==cursor+4096);cases++;
 }
 request[4]=0x339;request[9]=HSC_CLASS_BYTES;assert(!hsc_resource_plan(request,11,0,&s) && s.next==HSC_CLASS_BYTES && hsc_resource_plan(request,11,4096,&s));cases++;
 request[9]=0;assert(hsc_resource_plan(request,11,0,&s));cases++;
 // Captured GMU-only CMD_BUFFER: no GPU address is granted, even though
 // another arena has real GPU mappings. Preserve its logical wire fields.
 request[4]=0x178;request[5]=request[7]=16;request[9]=32768;uint32_t response[11];
 assert(!hsc_gmu_only_plan(request,11,0,&s) && s.bytes==32768 && s.next==32768);
 assert(!hsc_resource_response(request,11,&s,response) && !response[2] && !response[3] &&
  response[8]==HSC_GMU_ONLY_IOVA && response[9]==32768 && response[4]==0x178 && response[6]==16);cases++;
 struct hsc_slice bad=s;bad.bytes+=4096;assert(hsc_resource_response(request,11,&bad,response));cases++;
 for(unsigned host=0;host<4;host++) {
  request[4]=0x78|(host<<8);assert(!hsc_gmu_only_plan(request,11,32768,&s) && s.offset==32768);cases++;
 }
 request[4]=0x178;
 for(unsigned bit=0;bit<32;bit++)if(bit!=8 && bit!=9){request[4]^=1u<<bit;assert(hsc_gmu_only_plan(request,11,0,&s));request[4]^=1u<<bit;cases++;}
 request[9]=HSC_POOL_BYTES;assert(!hsc_gmu_only_plan(request,11,0,&s) && s.next==HSC_POOL_BYTES && hsc_gmu_only_plan(request,11,4096,&s));cases++;
 request[4]=0x339;request[5]=request[7]=15;request[9]=4096;
 assert(!hsc_resource_plan(request,11,0,&s) && !hsc_resource_response(request,11,&s,response) &&
  response[2]==HSC_POOL_IOVA && response[8]==HSC_POOL_IOVA && response[9]==4096);cases++;
 for(unsigned cls=0;cls<HSC_CLASSES;cls++) {
  request[4]=0x379|(cls<<1);request[5]=1;request[7]=26;request[9]=32768;
  assert(!hsc_resource_plan(request,11,cls*HSC_CLASS_BYTES,&s) && !hsc_resource_response(request,11,&s,response));
  assert(response[4]==request[4] && response[2]==HSC_POOL_IOVA+cls*HSC_CLASS_BYTES && response[8]==response[2] && response[9]==32768);cases++;
 }
 for(unsigned host=0;host<4;host++)for(unsigned cls=0;cls<HSC_CLASSES;cls++) {
  request[4]=0x79|(cls<<1)|(host<<8);request[5]=request[7]=3;request[9]=24;
  assert(!hsc_resource_plan(request,11,cls*HSC_CLASS_BYTES,&s) && s.bytes==4096 && !hsc_resource_response(request,11,&s,response));
  assert(response[4]==request[4] && response[9]==24 && response[6]==3);cases++;
 }
 // Actual r87 nonsecure context request: independent 4MiB arena, both addresses
 // real, packed alignment and logical size retained. Never permit secure flags.
 request[4]=0x37f;request[5]=request[7]=4;request[9]=0x37d000;request[10]=0;
 assert(hsc_resource_plan(request,11,rw,&s) && !hsc_large_plan(request,11,0,&s));
 assert(s.bytes==0x37d000 && s.next==0x37d000 && !hsc_resource_response(request,11,&s,response));
 assert(response[2]==HSC_LARGE_IOVA && response[8]==HSC_LARGE_IOVA && response[9]==0x37d000 && response[6]==4);cases++;
 for(unsigned bit=0;bit<32;bit++) {
  request[4]^=1u<<bit;assert((!hsc_large_plan(request,11,0,&s))==(bit==6 || bit==8 || bit==9));request[4]^=1u<<bit;cases++;
 }
 for(unsigned cursor=0;cursor<=HSC_LARGE_BYTES;cursor+=4096) {
  int status=hsc_large_plan(request,11,cursor,&s);assert((status!=0)==(cursor>HSC_LARGE_BYTES-0x37d000));
  if(!status)assert(s.offset==cursor && s.next==cursor+0x37d000);cases++;
 }
 request[10]=20|(20<<8);assert(!hsc_large_plan(request,11,4096,&s) && s.offset==0x100000 && s.bytes==0x400000?0:1);
 // 4MiB-rounded backing plus a 1MiB offset cannot fit: must reject.
 assert(hsc_large_plan(request,11,4096,&s));request[10]=0;cases++;
 request[9]=HSC_LARGE_BYTES;assert(!hsc_large_plan(request,11,0,&s) && s.next==HSC_LARGE_BYTES && hsc_large_plan(request,11,4096,&s));cases++;
 request[9]=HSC_LARGE_BYTES+1;assert(hsc_large_plan(request,11,0,&s));cases++;
 request[9]=0x37d000;request[4]=0x1007;request[5]=5;assert(hsc_large_plan(request,11,0,&s) && hsc_resource_response(request,11,&s,response));cases++;
 // Captured ordinary GPU-only counter and all exact permission/host classes.
 request[4]=0x147;request[5]=request[7]=7;request[9]=4096;request[10]=0;
 assert(!hsc_gpu_only_plan(request,11,rw,&s) && !hsc_resource_response(request,11,&s,response));
 assert(response[2]==HSC_GPU_ONLY_IOVA+rw && response[8]==0 && response[4]==0x147 && response[6]==7);cases++;
 for(unsigned host=0;host<4;host++)for(unsigned cls=0;cls<4;cls++) {
  request[4]=1|(cls<<1)|(host<<8);assert(!hsc_gpu_only_plan(request,11,cls*HSC_CLASS_BYTES,&s) && !hsc_resource_response(request,11,&s,response));
  assert(response[2]==HSC_GPU_ONLY_IOVA+cls*HSC_CLASS_BYTES && !response[8]);cases++;
 }
 request[4]=0x147;
 for(unsigned bit=0;bit<32;bit++){
  request[4]^=1u<<bit;unsigned cls=hsc_gpu_only_class(request[4]);
  assert((!hsc_gpu_only_plan(request,11,cls<4?cls*HSC_CLASS_BYTES:0,&s))==(bit==1 || bit==2 || bit==6 || bit==8 || bit==9));request[4]^=1u<<bit;cases++;
 }
 for(unsigned cls=0;cls<4;cls++)for(unsigned cursor=cls*HSC_CLASS_BYTES;cursor<=(cls+1)*HSC_CLASS_BYTES;cursor+=4096) {
  request[4]=0x141|(cls<<1);int status=hsc_gpu_only_plan(request,11,cursor,&s);
  assert(!!status==(cursor==(cls+1)*HSC_CLASS_BYTES));if(!status)assert(s.offset==cursor && s.next==cursor+4096);cases++;
 }
 request[4]=0x147;request[5]=5;assert(hsc_gpu_only_plan(request,11,rw,&s));cases++;
 printf("PASS: %u shared arena wire/size/alignment/bounds cases; four exact GFX permission classes, secure/MMIO/memstore/fence excluded, logical size preserved, page-disjoint monotonic slices\n",cases);
}
