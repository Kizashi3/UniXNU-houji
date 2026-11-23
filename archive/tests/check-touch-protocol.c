// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../native/touch/HoujiTouchReport.h"
#include "../native/touch/HoujiTouchWire.h"
#include "../native/touch/HoujiTouchGpio.h"
#include "../native/touch/HoujiTouchDescriptor.h"
static unsigned reads,writes,waits,phase,edges,selected;
static int bad_padding,large_header,discard_error;
static unsigned discarded;
static int mock_read(uint8_t *p,unsigned n) {
  reads++;
  if(n==4) {const uint8_t h[]={0xa5,1,2,0};memcpy(p,h,4);if(large_header){p[1]=0xc0;p[2]=0;p[3]=6;}return 0;}
  assert(n==9);memset(p,0x5a,n);p[0]=0xa5;p[1]=3;p[2]=0x22;p[3]=0x33;
  if(bad_padding)p[8]=0;return 0;
}
static int mock_write(const uint8_t *p,unsigned n) {
  writes++;assert(n==4 && p[0]==5 && p[1]==1 && p[2]==0 && p[3]==0x11);return 0;
}
static void mock_wait(unsigned ms) {assert(ms==10);waits++;}
static int mock_discard(unsigned n) {assert(n==1536);discarded++;return discard_error;}
static void gpio_set(unsigned pin,unsigned v) {
  assert(pin>=1 && pin<=3 && v<2);
  if(pin==3)selected=!v;
  if(pin==2) {if(v) {assert(selected);edges++;}phase=v;}
}
static unsigned gpio_sample(void) {assert(selected && phase);return 1;}
static void gpio_pause(void) {}
int main(void) {
  struct gt_state state={0},before;struct gt_frame frame={0},saved;
  const uint8_t two[]={2,0,1,0,0,0,0,9,2,0xaf,4,0x6d,10};
  assert(gt_decode(0x11,two,sizeof(two),1199,2669,1,&state,&frame)==0);
  assert(state.active==0x201 && frame.count==2 && state.x[9]==1199 && state.y[9]==2669);
  const uint8_t one[]={1,9,1,100,0,200,0};
  assert(gt_decode(0x11,one,sizeof(one),1199,2669,1,&state,&frame)==0);
  assert(frame.count==2 && frame.events[0].id==0 && !frame.events[0].down);
  assert(frame.events[1].id==9 && frame.events[1].down && frame.events[1].x==100);
  before=state;saved=frame;
  uint8_t bad[sizeof(two)];memcpy(bad,two,sizeof(bad));bad[7]=0;
  assert(gt_decode(0x11,bad,sizeof(bad),1199,2669,1,&state,&frame)!=0);
  assert(!memcmp(&before,&state,sizeof(state)) && !memcmp(&saved,&frame,sizeof(frame)));
  for(unsigned n=0;n<sizeof(one);n++)assert(gt_decode(0x11,one,n,1199,2669,1,&state,&frame)!=0);
  assert(gt_decode(0xc0,one,sizeof(one),1199,2669,1,&state,&frame)!=0);
  assert(gt_decode(0x11,one,sizeof(one),1199,2669,0,&state,&frame)!=0);
  const uint8_t none[]={0};assert(!gt_decode(0x11,none,1,1199,2669,1,&state,&frame));
  assert(!state.active && frame.count==1 && !frame.events[0].down);
  assert(gt_config_matches(gt_report_config,sizeof(gt_report_config)));
  uint8_t config[512]={0};memcpy(config,gt_report_config,sizeof(gt_report_config));
  assert(gt_config_matches(config,sizeof(config)));config[511]=1;assert(!gt_config_matches(config,sizeof(config)));
  struct gw_bus bus={mock_read,mock_write,mock_wait,512,NULL};struct gw_message msg={0};
  assert(!gw_read(&bus,&msg) && msg.code==1 && msg.size==2 && msg.data[0]==0x22);
  bad_padding=1;assert(gw_read(&bus,&msg)==6);bad_padding=0;
  uint8_t report=0x11;assert(!gw_command(&bus,5,&report,1,&msg) && writes==1 && waits==1);
  assert(gw_command(&bus,5,NULL,1,&msg)==7);
  bus.max_write=3;assert(gw_command(&bus,5,&report,1,&msg)==7);
  large_header=1;assert(gw_read(&bus,&msg)==3);
  bus.discard_report=mock_discard;assert(!gw_read(&bus,&msg) && msg.code==0xc0 && msg.size==0 && discarded==1);
  discard_error=1;assert(gw_read(&bus,&msg)==3);large_header=0;
  struct gg_bus pins={gpio_set,gpio_sample,gpio_pause};uint8_t rx[2]={0};
  assert(!gg_transfer(&pins,NULL,rx,2) && edges==16 && !selected && !phase && rx[0]==255 && rx[1]==255);
  assert(gg_transfer(&pins,NULL,rx,8200)==1);
  assert(!gg_pin_owned(1u<<11) && gg_pin_owned((1u<<11)|(1u<<12)) && gg_pin_owned(1));
  struct hd_layout layout;assert(!hd_layout_parse(gt_report_config,sizeof(gt_report_config),&layout));
  memset(&state,0,sizeof(state));assert(!hd_decode(gt_report_config,sizeof(gt_report_config),two,sizeof(two),1199,2669,&state,&frame));
  assert(state.active==0x201 && state.x[9]==1199 && state.y[9]==2669);
  const uint8_t bitcfg[]={0x18,4,4,1,6,4,7,4,8,12,9,12,3,0};
  const uint8_t bitdata[]={1,0x10,0x34,0x62,0x45};
  assert(!hd_decode(bitcfg,sizeof(bitcfg),bitdata,sizeof(bitdata),1199,2669,&state,&frame));
  assert(state.active==1 && state.x[0]==0x234 && state.y[0]==0x456);
  before=state;saved=frame;
  for(unsigned k=0;k<sizeof(bitdata);k++) {
    assert(hd_decode(bitcfg,sizeof(bitcfg),bitdata,k,1199,2669,&state,&frame));
    assert(!memcmp(&before,&state,sizeof(state)) && !memcmp(&saved,&frame,sizeof(frame)));
  }
  assert(!hd_decode(bitcfg,sizeof(bitcfg),none,sizeof(none),1199,2669,&state,&frame) && !state.active);
  for(unsigned k=0;k<sizeof(bitcfg);k++)assert(hd_layout_parse(bitcfg,k,&layout));
  const uint8_t nested[]={1,1,7,8,8,16,9,16,3,3,0};
  assert(hd_layout_parse(nested,sizeof(nested),&layout));
  puts("PASS: two-contact bounds/releases, unchanged invalid frames, exact configuration, TouchCom framing and SPI mode-0 edges");
}
