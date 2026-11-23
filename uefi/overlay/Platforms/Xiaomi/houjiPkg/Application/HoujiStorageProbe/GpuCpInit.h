/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Fixed vendor HWSCHED first-RAW sequence only, after actual Gen7 preparation.
 * No pre-init NOP, PAS, secure-mode exit, fence or desktop acceleration claim.
 */
#ifndef HOUJI_GPU_CP_INIT_H
#define HOUJI_GPU_CP_INIT_H
#include "GpuCodeMemory.h"
#include "GpuHfiBootstrap.h"
enum {HCI_OK,HCI_ARGUMENT,HCI_GUARD,HCI_APERTURE,HCI_EXCHANGE,HCI_IO,HCI_TIMEOUT};
struct hci_result {
 unsigned code,phase,aperture_attempted,aperture_ok,raw_attempted,idle,polls,reads;
 uint32_t busy,rbbm,sqe,interrupt_status,last_address,last_value;
 unsigned value_valid;
 struct hhb_result raw;
 unsigned debug_count;
 struct {unsigned count;uint32_t words[HHB_WORDS];} debug[8];
};
struct hci_io {struct hhb_io hfi;int (*ready)(void *);int (*aperture)(void *);int (*read)(void *,uint32_t,uint32_t *);};
static inline unsigned hci_parity(uint32_t v){unsigned p=1;while(v){p^=v&1;v>>=1;}return p;}
static inline uint32_t hci_packet(unsigned opcode,unsigned count){return 0x70000000u|count|(hci_parity(count)<<15)|(opcode<<16)|(hci_parity(opcode)<<23);}
static inline uint32_t hci_cp_word(unsigned i) {
 const uint32_t p[]={hci_packet(0x17,1),1u<<27,hci_packet(0x48,7),0x94b,3,0x20000000,2,HCC_IOVA+HCC_RECORD_OFFSET,0,1u<<31};
 return i<10?p[i]:0;
}
static inline int hci_read(const struct hci_io *io,struct hci_result *r,uint32_t a,uint32_t *v) {
 r->reads++;r->last_address=a;r->value_valid=0;
 if(!io->hfi.healthy(io->hfi.cookie) || io->read(io->hfi.cookie,a,v))return 0;
 r->last_value=*v;r->value_valid=1;return 1;
}
static inline unsigned hci_exchange_words(const struct hci_io *io,struct hci_result *r,const uint32_t *payload,unsigned words) {
 if(!io || !r || !payload || (words!=2 && words!=8 && words!=10))return HHB_ARGUMENT;
 for(unsigned i=0;i<words;i++)if(payload[i]!=hci_cp_word(i+(words==8?2:0)))return HHB_ARGUMENT;
 const struct hhb_io *hfi=&io->hfi;struct hhb_record *record=&r->raw.record[0];uint32_t request[11];
 record->attempted=1;record->header=(r->raw.next_sequence++<<20)|((words+1)<<8)|131;request[0]=record->header;
 for(unsigned i=0;i<words;i++)request[i+1]=payload[i];
 if(!hfi->healthy(hfi->cookie) || hfi->send(hfi->cookie,request,words+1) || !hfi->healthy(hfi->cookie) || hfi->doorbell(hfi->cookie))return HHB_IO;
 record->sent=1;
 for(unsigned poll=0;poll<20000;poll++) {
  if(!hfi->healthy(hfi->cookie))return HHB_IO;
  for(unsigned queue=1;queue<=2;queue++) {
   unsigned count=0;int code=hfi->receive(hfi->cookie,queue,record->reply,&count);
   if(code==1)continue;if(code || count<1 || count>HHB_WORDS)return HHB_PROTOCOL;record->count=count;
   if(queue==2) {
    unsigned index=r->debug_count++;if(index<8){r->debug[index].count=count;for(unsigned i=0;i<count;i++)r->debug[index].words[i]=record->reply[i];}
    if(r->debug_count>32)return HHB_PROTOCOL;continue;
   }
   uint32_t header=record->reply[0];
   if(count<3 || ((header>>8)&255)!=count || ((header>>16)&15)!=1 || (header&255)!=131 || record->reply[1]!=record->header)return HHB_PROTOCOL;
   record->value=record->reply[2];record->ack=1;
   // Vendor async check_ack_failure reads only results[2], with UINT_MAX as
   // the failure sentinel. Other reply words are preserved, not made statuses.
   if(record->value==UINT32_MAX)return HHB_REJECTED;r->raw.completed=1;return HHB_OK;
  }
  record->polls++;if(hfi->delay(hfi->cookie,10))return HHB_IO;
 }
 return HHB_TIMEOUT;
}
static inline unsigned hci_exchange(const struct hci_io *io,struct hci_result *r,const uint32_t payload[10]) {
 return hci_exchange_words(io,r,payload,10);
}
static inline unsigned hci_run(const struct hci_io *io,struct hci_result *r,unsigned *sequence) {
 if(!r)return HCI_ARGUMENT;*r=(struct hci_result){0};
 if(!io || !sequence || *sequence<2 || *sequence>4093 || !io->ready || !io->aperture || !io->read ||
  !io->hfi.healthy || !io->hfi.send || !io->hfi.receive || !io->hfi.doorbell || !io->hfi.delay)return r->code=HCI_ARGUMENT;
#define HCI_REQUIRE(x,e) do {if(!(x))return r->code=(e);} while(0)
 r->phase=1;HCI_REQUIRE(!io->ready(io->hfi.cookie),HCI_GUARD);
 r->phase=2;r->aperture_attempted=1;HCI_REQUIRE(!io->aperture(io->hfi.cookie),HCI_APERTURE);r->aperture_ok=1;
 HCI_REQUIRE(!io->ready(io->hfi.cookie),HCI_GUARD);
 uint32_t payload[10];for(unsigned i=0;i<10;i++)payload[i]=hci_cp_word(i);
 r->phase=3;r->raw.next_sequence=*sequence;r->raw_attempted=1;
 r->raw.code=hci_exchange(io,r,payload);*sequence=r->raw.next_sequence;
 HCI_REQUIRE(!r->raw.code,HCI_EXCHANGE);
 r->phase=4;for(unsigned poll=0;poll<20000;poll++) {
  r->polls++;HCI_REQUIRE(hci_read(io,r,0x3d8ec30,&r->busy),HCI_IO);
  if(!(r->busy&(1u<<23))){r->idle=1;break;}
  HCI_REQUIRE(!io->hfi.delay(io->hfi.cookie,10),HCI_IO);
 }
 HCI_REQUIRE(r->idle,HCI_TIMEOUT);r->phase=5;
 HCI_REQUIRE(hci_read(io,r,0x3d00840,&r->rbbm) && hci_read(io,r,0x3d02020,&r->sqe) && hci_read(io,r,0x3d00804,&r->interrupt_status),HCI_IO);
 r->phase=6;return HCI_OK;
#undef HCI_REQUIRE
}
#endif
