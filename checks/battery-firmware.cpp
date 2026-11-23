// Synthetic GPT/FAT/ELF fixtures exercise the actual native firmware reader.
// No vendor firmware or device identifiers are included.
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <cerrno>
#include "../kernel/overlay/iokit/Kernel/houji-ufs-root/battery/HoujiFirmware.h"
#include "../kernel/overlay/iokit/Kernel/houji-ufs-root/battery/HoujiFirmwareGpt.h"
#include "../kernel/overlay/iokit/Kernel/houji-ufs-root/battery/QcomMdt.h"
static uint8_t disk[8192*512];
static int failAllocation=-1,allocations,live,failRead;
void *IOMalloc(size_t n) {
    if(allocations++==failAllocation)return nullptr;
    void *p=malloc(n);if(p)live++;return p;
}
void IOFree(void *p,size_t) {if(p){assert(live>0);live--;free(p);}}
extern "C" int houji_modem_partition(uint64_t *blocks) {*blocks=sizeof(disk)/4096;return 1;}
extern "C" int houji_modem_read(uint64_t lba,uint32_t blocks,void *to) {
    assert(to && blocks && blocks<=32 && lba<sizeof(disk)/4096 && blocks<=sizeof(disk)/4096-lba);
    if(failRead)return 0;
    memcpy(to,disk+lba*4096,blocks*4096);return 1;
}
static void p16(uint8_t *p,uint16_t v){p[0]=v;p[1]=v>>8;}
static void p32(uint8_t *p,uint32_t v){p16(p,v);p16(p+2,v>>16);}
static void p64(uint8_t *p,uint64_t v){p32(p,v);p32(p+4,v>>32);}
static uint8_t *cluster(unsigned c){return disk+(34+c-2)*512;}
static void entry(uint8_t *p,const char *name,unsigned c,unsigned bytes,bool dir=false) {
    memcpy(p,name,11);p[11]=dir?0x10:0x20;p16(p+26,c);p32(p+28,bytes);
    p16(disk+512+c*2,0xffff);
}
static void fixture() {
    p16(disk+11,512);disk[13]=1;p16(disk+14,1);disk[16]=1;
    p16(disk+17,16);p16(disk+19,8192);p16(disk+22,32);disk[510]=0x55;disk[511]=0xaa;
    entry(disk+33*512,"IMAGE      ",2,0,true);
    entry(cluster(2),"ADSP    B00",3,148);
    entry(cluster(2)+32,"ADSP    B01",4,32);
    entry(cluster(2)+64,"ADSP    B02",100,64);
    uint8_t *h=cluster(3);memcpy(h,"\x7f" "ELF",4);h[4]=1;h[5]=1;h[6]=1;
    p16(h+16,2);p16(h+18,164);p32(h+28,52);p16(h+40,52);p16(h+42,32);p16(h+44,3);
    struct {uint32_t type,off,address,bytes,memory,flags;} segments[]={
        {0,0,0,148,0,7u<<24},{0,512,0,32,32,2u<<24},
        {1,4096,0x100000,64,128,5|QCOM_MDT_RELOCATABLE}};
    for(unsigned i=0;i<3;i++) {
        uint8_t *p=h+52+i*32;auto s=segments[i];
        p32(p,s.type);p32(p+4,s.off);p32(p+8,s.address);p32(p+12,s.address);
        p32(p+16,s.bytes);p32(p+20,s.memory);p32(p+24,s.flags);p32(p+28,4096);
    }
    memset(cluster(4),0xab,32);for(unsigned i=0;i<64;i++)cluster(100)[i]=(uint8_t)i;
}
static void crc(uint8_t *h,uint8_t *e) {
    p32(h+88,houji_fw_crc32(e,128*4,0));p32(h+16,houji_fw_crc32(h,92,1));
}
static void gptTests() {
    uint8_t h[4096]={},e[512]={};HoujiFirmwarePartition p={};
    memcpy(h,"EFI PART",8);p32(h+8,0x10000);p32(h+12,92);p64(h+24,1);p64(h+32,20000);
    p64(h+40,4);p64(h+48,19998);p64(h+72,2);p32(h+80,4);p32(h+84,128);
    e[0]=1;p64(e+32,128);p64(e+40,1151);const char *name="modem_a";
    for(unsigned i=0;i<7;i++)e[56+2*i]=name[i];crc(h,e);
    assert(houji_fw_gpt_bytes(h,sizeof(h))==512);
    assert(houji_fw_gpt_partition(h,e,sizeof(e),&p) && p.first==128 && p.blocks==1024);
    e[9]^=1;assert(!houji_fw_gpt_partition(h,e,sizeof(e),&p));e[9]^=1;
    assert(!houji_fw_gpt_partition(h,e,sizeof(e)-1,&p));
    memcpy(e+128,e,128);crc(h,e);assert(!houji_fw_gpt_partition(h,e,sizeof(e),&p));
    e[128+56]='x';crc(h,e);assert(!houji_fw_gpt_partition(h,e,sizeof(e),&p)); // same extent, different name
    memset(e+128,0,128);p64(e+40,20000);crc(h,e);assert(!houji_fw_gpt_partition(h,e,sizeof(e),&p));
    p64(e+40,1151);p64(h+72,0xffffffffffffffffULL);crc(h,e);assert(!houji_fw_gpt_bytes(h,sizeof(h)));
}
static int readImage(void *handle,uint64_t at,void *to,size_t n){return houji_fw_read(handle,at,to,n);}
int main(int argc,char **argv) {
    gptTests();fixture();const char *mode=argc>1?argv[1]:"ok";
    if(!strncmp(mode,"alloc",5))failAllocation=atoi(mode+5);
    if(!strcmp(mode,"read-fail"))failRead=1;
    if(!strcmp(mode,"bad-fat"))disk[510]=0;
    if(!strcmp(mode,"bad-elf"))cluster(3)[0]=0;
    if(!strcmp(mode,"short-piece"))p32(cluster(2)+64+28,63);
    void *file=nullptr;uint64_t size=0;
    assert(houji_fw_open("../adsp",&file,&size)==EINVAL);
    int rc=houji_fw_open("adsp",&file,&size);
    if(strcmp(mode,"ok")) {
        assert(rc!=0 && file==nullptr);
        assert(live==(allocations>1 && strcmp(mode,"read-fail") && strcmp(mode,"bad-fat")?1:0));
    } else {
        assert(rc==0 && file && size==4160);
        uint8_t bytes[4160];assert(!houji_fw_read(file,0,bytes,sizeof(bytes)));
        assert(!memcmp(bytes,cluster(3),148));for(unsigned i=148;i<512;i++)assert(bytes[i]==0);
        for(unsigned i=512;i<544;i++)assert(bytes[i]==0xab);
        for(unsigned i=4096;i<4160;i++)assert(bytes[i]==i-4096);
        assert(houji_fw_read(file,4160,bytes,1)!=0);
        assert(houji_fw_read(file,UINT64_MAX,bytes,64)!=0);
        QcomMdtImage mdt={};assert(!qcom_mdt_parse(&mdt,size,readImage,file));
        uint64_t offset=99;assert(!qcom_mdt_place(&mdt,2,0x9df00000,0x4680000,&offset) && offset==0);
        assert(qcom_mdt_place(&mdt,2,0x9df00000,127,&offset)!=0);
        houji_fw_close(file);assert(live==1);
        assert(houji_fw_open("adsp_dtb",&file,&size)==ENOENT && file==nullptr);
    }
    printf("PASS firmware reader: %s\n",mode);
}
