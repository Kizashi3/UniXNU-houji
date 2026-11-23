// SPDX-License-Identifier: BSD-2-Clause-Patent
// SM8650 battery transport survey. The upstream sheng ADSP implementation uses
// these SMEM/SMP2P formats; addresses are from houji's captured and vendor FDT.
// No DSP boot, SMEM allocation, mailbox acknowledgment, power vote or battery
// publication occurs here. A valid old SMP2P item is not proof of a live DSP.
#include <IOKit/IODeviceMemory.h>
#include <IOKit/IOMemoryDescriptor.h>
#include "battery/HoujiSmemSurvey.h"
#include "battery/QcomSmp2p.h"
extern "C" void houji_ufs_checkpoint(const char *stage,unsigned stopId);

// Each phase is published once; a concurrent log snapshot never observes a
// string being rewritten. Only this startup thread advances the phase count.
static char gHoujiBatterySurvey[3][768];
static unsigned gHoujiBatterySurveyBytes[3],gHoujiBatterySurveyPhases;

static void houjiBatterySurveyNote(const char *phase,const HoujiSmemReader &reader,
    bool mapped,int partition,int global,uint32_t present,const uint32_t sizes[5],int p2p,int slave) {
  unsigned index=__atomic_load_n(&gHoujiBatterySurveyPhases,__ATOMIC_RELAXED);
  if(index>=3)return;
  char *text=gHoujiBatterySurvey[index];const unsigned capacity=sizeof(gHoujiBatterySurvey[index]);
  int n=snprintf(text,capacity,
    "HOUJI BATTERY SURVEY: mode=read-only phase=%s smem-map=%u reads=%u last-offset=%x error=%d "
    "partition=%d global=%d items=%x sizes=%u,%u,%u,%u,%u smp2p=%d slave=%d; "
    "no live battery reading, DSP start or power-policy write\n",
    phase,(unsigned)mapped,reader.reads,reader.last_offset,reader.error,partition,global,present,
    sizes[0],sizes[1],sizes[2],sizes[3],sizes[4],p2p,slave);
  gHoujiBatterySurveyBytes[index]=n<=0?0:(unsigned)n<capacity?(unsigned)n:capacity-1;
  __atomic_store_n(&gHoujiBatterySurveyPhases,index+1,__ATOMIC_RELEASE);
  IOLog("%s",text);
}
static int houjiBatteryRead32(void *context,uint32_t offset,uint32_t *value) {
  const volatile uint32_t *base=static_cast<volatile uint32_t *>(context);
  *value=base[offset/4];return 1;
}

static void houjiBatterySurvey(void) {
  unsigned enabled=0;
  if (!PE_parse_boot_argn("houji_battery_probe", &enabled, sizeof(enabled)) || enabled<1 || enabled>4)
    return;
  IODeviceMemory *memory=IODeviceMemory::withRange(0x81d00000ULL,0x200000);
  IOMemoryMap *map=memory ? memory->map(kIOMapAnywhere|kIOMapInhibitCache) : nullptr;
  if(memory)memory->release();
  int partition=HoujiSmemNoTable,global=HoujiSmemNoTable,p2p=-1,slave=-1;
  uint32_t present=0,sizes[5]={};
  HoujiSmemReader reader={houjiBatteryRead32,map?reinterpret_cast<void *>(map->getVirtualAddress()):nullptr,
                         0x200000,0,8192,0,0};
  if(map){
    // Only table entries, partition/item headers and the requested SMP2P item
    // are read. An address range being mapped does not make every word in it
    // readable. Recheck bounds before and after walking firmware-owned lists.
    houjiBatterySurveyNote("before-table",reader,true,partition,global,present,sizes,p2p,slave);
    houji_ufs_checkpoint("battery SMEM before sparse metadata reads",0);
    HoujiSmemPart part={},common={};
    partition=houji_smem_partition_ro(&reader,0,2,&part);
    global=houji_smem_partition_ro(&reader,0xfffe,0xfffe,&common);
    houjiBatterySurveyNote("before-items",reader,true,partition,global,present,sizes,p2p,slave);
    houji_ufs_checkpoint("battery SMEM partition metadata read; before selected items",0);
    if(partition==HoujiSmemOk){
      const uint16_t ids[]={443,429,478,479,480};
      for(unsigned i=0;i<5;i++){
        uint32_t at=0,size=0;
        if(houji_smem_item_ro(&reader,&part,ids[i],&at,&size)!=HoujiSmemOk)continue;
        sizes[i]=size; present|=1U<<i;
        if(i==0 && size>=QCOM_SMP2P_ITEM_BYTES && !(at&3)){
          uint32_t words[QCOM_SMP2P_ITEM_BYTES/4]={};bool complete=true;
          for(unsigned w=0;w<QCOM_SMP2P_ITEM_BYTES/4;w++) {
            if(!houji_smem_read(&reader,at+w*4,&words[w])){complete=false;break;}
          }
          if(!complete || houji_smem_same_header(&reader,&part)!=HoujiSmemOk)continue;
          QcomSmp2p view={};view.in=words;
          p2p=qcom_smp2p_check_in(view.in,0,2);
          if(!p2p){
            int index=qcom_smp2p_find_in(&view,"slave-kernel");
            if(index>=0)slave=(int)qcom_smp2p_in_value(&view,index);
          }
        }
      }
    }
  }
  houjiBatterySurveyNote("complete",reader,map!=nullptr,partition,global,present,sizes,p2p,slave);
  if(map)map->release();
  houji_ufs_checkpoint("battery SMEM read-only sparse survey finished",0);
}

static unsigned houjiBatterySurveySnapshot(char *out,unsigned capacity){
  if(!out||!capacity)return 0;
  unsigned count=__atomic_load_n(&gHoujiBatterySurveyPhases,__ATOMIC_ACQUIRE);
  if(!count){out[0]=0;return 0;}
  unsigned bytes=gHoujiBatterySurveyBytes[count-1];
  if(bytes>=capacity)bytes=capacity-1;
  memcpy(out,gHoujiBatterySurvey[count-1],bytes);out[bytes]=0;return bytes;
}
