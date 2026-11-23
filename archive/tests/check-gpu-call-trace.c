/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Actual RAM ring and framebuffer renderer. Guard regions, per-pixel bounds,
 * supported modes, glyph visibility, replay and overwrite/restart semantics.
 */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../native/gpu/uefi/GpuCallTrace.h"

static unsigned cases;

static void ring_tests(void) {
  struct hct_ring *r=calloc(1,sizeof(*r));
  struct hct_record out;
  assert(r);
  assert(!hct_push(NULL,1,2,3,4));
  assert(!hct_first(NULL));
  assert(!hct_get(NULL,1,&out));
  hct_reset(NULL);hct_start(NULL);hct_stop(NULL);hct_resume(NULL);
  assert(!hct_unreported_first(NULL,0));
  assert(!hct_push(r,1,2,3,4) && !hct_first(r));
  assert(!hct_get(r,0,&out));cases++;
  hct_start(r);
  for (unsigned i=1;i<=HCT_CAPACITY+137;i++) {
    assert(hct_push(r,1000+i,UINT64_C(0x1234567800000000)+i,
      UINT64_C(0xfedcba9800000000)+i,UINT64_C(0x8000000000000000)+i)==i);
    assert(!hct_get(r,i,&out));
    cases++;
  }
  hct_stop(r);
  assert(hct_first(r)==138);
  assert(hct_unreported_first(r,0)==138 && hct_unreported_first(r,137)==138);
  assert(hct_unreported_first(r,138)==139 && hct_unreported_first(r,1000)==1001);
  assert(!hct_unreported_first(r,HCT_CAPACITY+137));
  assert(!hct_unreported_first(r,UINT64_MAX));cases++;
  assert(!hct_get(r,137,&out) && !hct_get(r,HCT_CAPACITY+138,&out));cases++;
  for (unsigned i=138;i<=HCT_CAPACITY+137;i++) {
    assert(hct_get(r,i,&out));
    assert(out.sequence==i && out.step==1000+i && !out.reserved &&
      out.address==UINT64_C(0x1234567800000000)+i &&
      out.value==UINT64_C(0xfedcba9800000000)+i &&
      out.counter==UINT64_C(0x8000000000000000)+i);
    cases++;
  }
  r->record[137].sequence=0;
  assert(!hct_get(r,138,&out));cases++;
  hct_start(r);
  assert(!hct_first(r) && r->enabled && !r->saturated);
  assert(hct_push(r,0xffffffff,UINT64_MAX,UINT64_MAX,UINT64_MAX)==1);
  hct_stop(r);assert(hct_get(r,1,&out));
  assert(out.step==UINT32_MAX && out.address==UINT64_MAX && out.value==UINT64_MAX);
  assert(!hct_get(r,1,NULL));cases++;
  hct_resume(r);
  assert(r->sequence==1 && r->enabled && !hct_unreported_first(r,0));
  assert(hct_push(r,4000,0x3d02020,1,500)==2);
  hct_stop(r);
  assert(hct_unreported_first(r,0)==1 && hct_unreported_first(r,1)==2);
  assert(hct_get(r,1,&out) && out.step==UINT32_MAX);
  assert(hct_get(r,2,&out) && out.step==4000 && out.value==1);cases++;
  hct_start(r);r->sequence=UINT64_MAX;
  assert(!hct_push(r,1,2,3,4) && r->saturated && !r->enabled);
  assert(hct_first(r)==UINT64_MAX-HCT_CAPACITY+1);cases++;
  hct_resume(r);assert(!r->enabled && !hct_unreported_first(r,UINT64_MAX));cases++;
  free(r);
}

static void failure_tests(void) {
  struct hct_ring *r=calloc(1,sizeof(*r));
  struct guarded_failure {
    uint64_t before[8];
    struct hct_failure failure;
    uint64_t after[8];
  } *g=malloc(sizeof(*g));
  assert(r && g);
  memset(g,0xa5,sizeof(*g));
  struct hct_failure *f=&g->failure;
  struct hct_record out;
  hct_failure_reset(NULL);
  hct_freeze_first_failure(NULL,f);
  hct_freeze_first_failure(r,NULL);
  assert(!hct_failure_get(NULL,0,&out));cases++;
  static const unsigned lengths[]={0,1,511,512,513,1024,1537};
  for (unsigned n=0;n<sizeof(lengths)/sizeof(lengths[0]);n++) {
    unsigned length=lengths[n];
    hct_start(r);hct_failure_reset(f);
    assert(!hct_failure_get(f,0,&out));
    for (unsigned i=1;i<=length;i++)
      assert(hct_push(r,0x6000+i,0x3d02020+i,0x9000+i,0x100000+i)==i);
    /* The production failure path freezes while recording remains enabled. */
    hct_freeze_first_failure(r,f);
    assert(r->enabled && f->state==2 && f->last==length && !f->invalid);
    unsigned count=length>HCT_FAILURE_CAPACITY ? HCT_FAILURE_CAPACITY : length;
    assert(f->count==count && f->first==(count?length-count+1:0));
    assert(!hct_failure_get(f,count,&out) && !hct_failure_get(f,0,NULL));
    /* Exceed both rings after the failure. A repeated freeze must preserve
     * the original window rather than the diagnostically unhelpful cleanup. */
    for (unsigned i=0;i<2*HCT_CAPACITY;i++)
      assert(hct_push(r,0xdead,UINT64_MAX,UINT64_MAX,UINT64_MAX));
    hct_freeze_first_failure(r,f);hct_stop(r);hct_resume(r);
    assert(f->count==count && f->last==length && r->enabled);
    for (unsigned i=0;i<count;i++) {
      uint64_t sequence=length-count+1+i;
      assert(hct_failure_get(f,i,&out));
      assert(out.sequence==sequence && out.step==0x6000+sequence &&
        out.address==0x3d02020+sequence && out.value==0x9000+sequence &&
        out.counter==0x100000+sequence && !out.reserved);
      cases++;
    }
    for (unsigned i=0;i<8;i++)
      assert(g->before[i]==UINT64_C(0xa5a5a5a5a5a5a5a5) &&
             g->after[i]==UINT64_C(0xa5a5a5a5a5a5a5a5));
    cases++;
  }
  /* A claimed but incomplete window is neither overwritten nor reportable. */
  hct_failure_reset(f);f->state=1;
  hct_freeze_first_failure(r,f);
  assert(f->state==1 && !hct_failure_get(f,0,&out));cases++;
  /* A torn source slot is an explicit hole; adjacent records retain their
   * exact sequence identities and no stale payload is presented as valid. */
  hct_start(r);hct_failure_reset(f);
  for (unsigned i=1;i<=HCT_FAILURE_CAPACITY+3;i++) hct_push(r,i,i+1,i+2,i+3);
  r->record[8].sequence=0;
  hct_freeze_first_failure(r,f);
  assert(f->first==4 && f->invalid==1 && !hct_failure_get(f,5,&out));
  assert(hct_failure_get(f,4,&out) && out.sequence==8);
  assert(hct_failure_get(f,6,&out) && out.sequence==10);cases++;
  /* The terminal sequence cannot wrap the copy loop or output identities. */
  hct_failure_reset(f);hct_reset(r);r->sequence=UINT64_MAX;
  for (unsigned i=0;i<HCT_FAILURE_CAPACITY;i++) {
    uint64_t sequence=UINT64_MAX-HCT_FAILURE_CAPACITY+1+i;
    volatile struct hct_record *slot=&r->record[(sequence-1)&(HCT_CAPACITY-1)];
    slot->counter=sequence;slot->address=sequence;slot->value=sequence;
    slot->step=i;slot->reserved=0;slot->sequence=sequence;
  }
  hct_freeze_first_failure(r,f);
  assert(f->count==HCT_FAILURE_CAPACITY && f->last==UINT64_MAX && !f->invalid);
  for (unsigned i=0;i<HCT_FAILURE_CAPACITY;i++) {
    assert(hct_failure_get(f,i,&out));
    assert(out.sequence==UINT64_MAX-HCT_FAILURE_CAPACITY+1+i && out.step==i);
    cases++;
  }
  hct_failure_reset(f);
  assert(!f->state && !f->count && !f->first && !f->last && !f->invalid);
  for (unsigned i=0;i<HCT_FAILURE_CAPACITY;i++) assert(!f->record[i].sequence);
  cases++;
  free(g);free(r);
}

static int expected_on(unsigned cell,unsigned x,unsigned y,const struct hct_screen *s) {
  unsigned col=x/s->scale,row=y/s->scale;
  return row<5 && col<3 &&
    (hct_glyph(s->glyph[cell])&(1u<<(14-3*row-col)))!=0;
}

static void framebuffer_mode(unsigned format,unsigned width,unsigned height,unsigned stride,
                             unsigned expected_scale) {
  enum {GUARD=64};
  size_t count=(size_t)stride*height;
  uint32_t *allocation=malloc((count+GUARD*2)*sizeof(*allocation));
  assert(allocation);
  for (size_t i=0;i<count+GUARD*2;i++) allocation[i]=0xdecafbad;
  uint32_t *fb=allocation+GUARD;
  struct hct_screen screen;
  assert(hct_screen_init(&screen,(uintptr_t)fb,count*4,width,height,stride,format));
  assert(screen.scale==expected_scale);
  if (width==1200 && height>=160) {
    assert(screen.scale==8 && HCT_COLUMNS*HCT_CELL_WIDTH*screen.scale==1056 &&
      3*screen.scale==24 && 5*screen.scale==40);
  }
  hct_screen_show(&screen,0x12345678,0xa1b2c3d4,UINT64_C(0x0123456789abcdef),
    UINT64_C(0xfedcba9876543210));
  assert(screen.enabled && screen.cache_valid);
  for (size_t y=0;y<height;y++) for (size_t x=0;x<stride;x++) {
    int inside=x>=screen.x && x<screen.x+HCT_COLUMNS*HCT_CELL_WIDTH*screen.scale &&
      y>=screen.y && y<screen.y+HCT_ROWS*HCT_CELL_HEIGHT*screen.scale;
    if (!inside) assert(fb[y*stride+x]==0xdecafbad);
    else {
      unsigned lx=(unsigned)x-screen.x,ly=(unsigned)y-screen.y;
      unsigned cell=ly/(HCT_CELL_HEIGHT*screen.scale)*HCT_COLUMNS+
        lx/(HCT_CELL_WIDTH*screen.scale);
      int on=expected_on(cell,lx%(HCT_CELL_WIDTH*screen.scale),
        ly%(HCT_CELL_HEIGHT*screen.scale),&screen);
      assert(fb[y*stride+x]==(on?0x00ffffffu:0));
    }
  }
  for (unsigned i=0;i<GUARD;i++) {
    assert(allocation[i]==0xdecafbad && allocation[GUARD+count+i]==0xdecafbad);
  }
  /* Replaying an identical display is a no-write operation, including blank
   * cells. Tamper a visible pixel and prove cache avoids touching it again.
   */
  size_t first=(size_t)screen.y*screen.stride+screen.x;
  fb[first]=0xabcdef01;
  hct_screen_show(&screen,0x12345678,0xa1b2c3d4,UINT64_C(0x0123456789abcdef),
    UINT64_C(0xfedcba9876543210));
  assert(fb[first]==0xabcdef01);
  /* Changing the high nibble of sequence repaints its glyph. */
  hct_screen_show(&screen,0x22345678,0xa1b2c3d4,UINT64_C(0x0123456789abcdef),
    UINT64_C(0xfedcba9876543210));
  assert(fb[first]!=0xabcdef01);
  for (unsigned i=0;i<GUARD;i++) {
    assert(allocation[i]==0xdecafbad && allocation[GUARD+count+i]==0xdecafbad);
  }
  /* Fatal context has explicit field positions and expands to the reserved
   * third row. Verify both glyph contents and every physical strip pixel.
   */
  hct_screen_fault(&screen,0x89abcdef,UINT64_C(0x0123456789abcdef),
    UINT64_C(0xfedcba9876543210),UINT64_C(0x0badc0ffee008000),
    UINT64_C(0xffff0000deadbeef));
  static const uint8_t expected_sequence[]={8,9,10,11,12,13,14,15};
  static const uint8_t expected_step[]={0,0,0,0,7,0,0,15};
  static const uint8_t expected_far[]={0,11,10,13,12,0,15,15,14,14,0,0,8,0,0,0};
  static const uint8_t expected_lr[]={15,15,15,15,0,0,0,0,13,14,10,13,11,14,14,15};
  assert(!memcmp(screen.glyph,expected_sequence,sizeof expected_sequence));
  assert(!memcmp(screen.glyph+9,expected_step,sizeof expected_step));
  assert(!memcmp(screen.glyph+2*HCT_COLUMNS,expected_far,sizeof expected_far));
  assert(!memcmp(screen.glyph+2*HCT_COLUMNS+17,expected_lr,sizeof expected_lr));
  for (unsigned i=0;i<16;i++) {
    assert(screen.glyph[HCT_COLUMNS+i]==i);
    assert(screen.glyph[HCT_COLUMNS+17+i]==15-i);
  }
  assert(screen.glyph[8]==16);
  assert(screen.glyph[HCT_COLUMNS+16]==16 && screen.glyph[2*HCT_COLUMNS+16]==16);
  for (unsigned i=17;i<HCT_COLUMNS;i++) assert(screen.glyph[i]==16);
  for (unsigned y=0;y<HCT_ROWS*HCT_CELL_HEIGHT*screen.scale;y++)
    for (unsigned x=0;x<HCT_COLUMNS*HCT_CELL_WIDTH*screen.scale;x++) {
      unsigned cell=y/(HCT_CELL_HEIGHT*screen.scale)*HCT_COLUMNS+
        x/(HCT_CELL_WIDTH*screen.scale);
      int on=expected_on(cell,x%(HCT_CELL_WIDTH*screen.scale),
        y%(HCT_CELL_HEIGHT*screen.scale),&screen);
      assert(fb[((size_t)screen.y+y)*stride+screen.x+x]==(on?0x00ffffffu:0));
    }
  /* A subsequent ordinary record must clear the full fatal third row. */
  hct_screen_show(&screen,1,0x3000,0x3d02020,1);
  for (unsigned i=2*HCT_COLUMNS;i<HCT_ROWS*HCT_COLUMNS;i++) assert(screen.glyph[i]==16);
  for (unsigned y=2*HCT_CELL_HEIGHT*screen.scale;y<HCT_ROWS*HCT_CELL_HEIGHT*screen.scale;y++)
    for (unsigned x=0;x<HCT_COLUMNS*HCT_CELL_WIDTH*screen.scale;x++)
      assert(fb[((size_t)screen.y+y)*stride+screen.x+x]==0);
  for (unsigned i=0;i<GUARD;i++)
    assert(allocation[i]==0xdecafbad && allocation[GUARD+count+i]==0xdecafbad);
  cases++;free(allocation);
}

static void invalid_framebuffer_tests(void) {
  uint32_t fb[400*40];
  for (size_t i=0;i<sizeof(fb)/sizeof(*fb);i++) fb[i]=0xbad0cafe;
  struct hct_screen s;
  assert(!hct_screen_init(NULL,1,1,1,1,1,0));cases++;
#define DENY(base,bytes,w,h,stride,fmt) do { \
  assert(!hct_screen_init(&s,(uintptr_t)(base),(size_t)(bytes),(w),(h),(stride),(fmt))); \
  assert(!s.enabled && !s.pixels);hct_screen_show(&s,1,2,3,4);cases++; \
} while(0)
  DENY(0,sizeof fb,400,40,400,0);
  DENY((uintptr_t)fb+1,sizeof fb-4,400,39,400,0);
  DENY(fb,0,400,40,400,0);
  DENY(fb,sizeof fb-1,400,40,400,0);
  DENY(fb,sizeof fb,400,40,400,2);
  DENY(fb,sizeof fb,400,40,400,3);
  DENY(fb,sizeof fb,400,40,400,UINT32_MAX);
  DENY(fb,sizeof fb,0,40,400,0);
  DENY(fb,sizeof fb,400,0,400,0);
  DENY(fb,sizeof fb,400,40,399,0);
  DENY(fb,sizeof fb-4,400,40,400,0);
  DENY(fb,sizeof fb,147,40,400,0);
  DENY(fb,sizeof fb,400,27,400,0);
  DENY(fb,sizeof fb,400,33,400,0);
  DENY(UINTPTR_MAX-3,8,1,1,1,0);
  DENY(fb,SIZE_MAX&~(size_t)3,UINT32_MAX,UINT32_MAX,UINT32_MAX,0);
#undef DENY
  for (size_t i=0;i<sizeof(fb)/sizeof(*fb);i++) assert(fb[i]==0xbad0cafe);
  /* Rendering must refuse a corrupted scale even when the original display
   * metadata was valid. A scale above eight must not touch the framebuffer.
   */
  assert(hct_screen_init(&s,(uintptr_t)fb,sizeof fb,400,40,400,0));
  s.scale=9;hct_draw_glyph(&s,0,1);
  s.scale=0;hct_draw_glyph(&s,0,1);
  for (size_t i=0;i<sizeof(fb)/sizeof(*fb);i++) assert(fb[i]==0xbad0cafe);
  cases++;
  uint8_t target[HCT_ROWS*HCT_COLUMNS];
  memset(target,16,sizeof target);
  hct_screen_number(NULL,0,1,0);
  hct_screen_number(target,0,0,1);
  hct_screen_number(target,0,17,1);
  hct_screen_number(target,HCT_ROWS*HCT_COLUMNS+1,1,1);
  hct_screen_number(target,HCT_ROWS*HCT_COLUMNS,1,1);
  for (unsigned i=0;i<sizeof target;i++) assert(target[i]==16);
  hct_screen_show(NULL,1,2,3,4);
  hct_screen_fault(NULL,1,2,3,4,5);
  hct_screen_render(&s,NULL);
  hct_draw_glyph(NULL,0,1);cases++;
  /* Every accepted glyph has visible foreground and a blank cell margin. */
  for (unsigned digit=0;digit<16;digit++) {
    assert(hct_glyph(digit) && !(hct_glyph(digit)&0x8000));cases++;
  }
  assert(!hct_glyph(16) && !hct_glyph(100));cases++;
}

int main(void) {
  ring_tests();failure_tests();invalid_framebuffer_tests();
  framebuffer_mode(0,400,52,400,2);
  framebuffer_mode(1,400,52,419,2);
  framebuffer_mode(0,148,34,151,1);
  framebuffer_mode(1,1200,2670,1216,8);
  framebuffer_mode(0,1071,160,1088,7);
  framebuffer_mode(1,1072,160,1088,8);
  framebuffer_mode(0,1200,159,1216,7);
  framebuffer_mode(1,1200,160,1216,8);
  framebuffer_mode(0,1200,34,1216,1);
  framebuffer_mode(1,1500,160,1536,8);
  printf("GPU CPU-RAM call trace: %u cases PASS; no firmware or device execution\n",cases);
  return 0;
}
