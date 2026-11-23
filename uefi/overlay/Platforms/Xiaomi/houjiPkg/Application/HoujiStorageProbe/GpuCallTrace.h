/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Single-writer CPU-RAM call trace for the UEFI GPU diagnostic. Records are
 * volatile across reset. A committed record proves CPU progress, not device
 * completion: recording deliberately performs no cache maintenance or DSB.
 */
#ifndef HOUJI_GPU_CALL_TRACE_H
#define HOUJI_GPU_CALL_TRACE_H

#include <stddef.h>
#include <stdint.h>

#define HCT_CAPACITY 1024u
#define HCT_FAILURE_CAPACITY 512u
#define HCT_COLUMNS 33u
#define HCT_ROWS 3u
#define HCT_CELL_WIDTH 4u
#define HCT_CELL_HEIGHT 6u
#define HCT_MAX_SCALE 8u

struct hct_record {
  uint64_t sequence;
  uint64_t counter;
  uint64_t address;
  uint64_t value;
  uint32_t step;
  uint32_t reserved;
};

struct hct_ring {
  volatile struct hct_record record[HCT_CAPACITY];
  volatile uint64_t sequence;
  volatile uint32_t enabled;
  volatile uint32_t saturated;
};

/* First-failure window is separate from the live ring: later cleanup remains
 * observable without overwriting the call boundary that made it necessary.
 * state 1 claims the first request; state 2 publishes the completed snapshot.
 * Like the ring, this is single-writer CPU RAM, never cross-reset storage.
 */
struct hct_failure {
  volatile struct hct_record record[HCT_FAILURE_CAPACITY];
  volatile uint64_t first, last;
  volatile uint32_t count, invalid, state;
};

static inline void hct_failure_reset(struct hct_failure *f) {
  if (!f) return;
  f->state=0;
  f->first=f->last=0;
  f->count=f->invalid=0;
  for (unsigned i=0;i<HCT_FAILURE_CAPACITY;i++) f->record[i].sequence=0;
}

/* May run while the single writer is enabled, at its synchronous failure
 * boundary. No recorder call is made while copying. Read only committed slots
 * from ordinary CPU RAM; a bad slot stays invalid instead of fabricating it.
 * Claim before copying so even a nested request cannot replace the first one.
 */
static inline void hct_freeze_first_failure(const struct hct_ring *r,
                                           struct hct_failure *f) {
  if (!r || !f || f->state) return;
  f->state=1;
  uint64_t last=r->sequence;
  uint64_t first=last>HCT_FAILURE_CAPACITY ? last-HCT_FAILURE_CAPACITY+1 : 1;
  f->first=last ? first : 0;
  f->last=last;
  f->count=f->invalid=0;
  if (last) for (uint64_t sequence=first;;sequence++) {
    const volatile struct hct_record *in=&r->record[(sequence-1)&(HCT_CAPACITY-1)];
    volatile struct hct_record *out=&f->record[f->count];
    out->sequence=0;
    if (in->sequence==sequence) {
      out->counter=in->counter;
      out->address=in->address;
      out->value=in->value;
      out->step=in->step;
      out->reserved=in->reserved;
      if (in->sequence==sequence) out->sequence=sequence;
    }
    if (!out->sequence) f->invalid++;
    f->count++;
    if (sequence==last) break;
  }
  f->state=2;
}

/* A complete frozen window may be inspected after the live recorder stops.
 * Invalid/torn slots are rejected with their original sequence positions.
 */
static inline int hct_failure_get(const struct hct_failure *f,unsigned index,
                                 struct hct_record *out) {
  if (!f || !out || f->state!=2 || index>=f->count ||
      index>=HCT_FAILURE_CAPACITY) return 0;
  const volatile struct hct_record *in=&f->record[index];
  uint64_t sequence=f->first+index;
  if (!sequence || in->sequence!=sequence) return 0;
  out->counter=in->counter;
  out->address=in->address;
  out->value=in->value;
  out->step=in->step;
  out->reserved=in->reserved;
  out->sequence=sequence;
  return in->sequence==sequence;
}

struct hct_screen {
  volatile uint32_t *pixels;
  size_t pixel_count;
  uint32_t width, height, stride, x, y, scale;
  uint32_t enabled, cache_valid;
  uint8_t glyph[HCT_ROWS * HCT_COLUMNS];
};

/* Called only with recording stopped; payloads of uncommitted slots are not
 * inspected. Individual volatile stores avoid a runtime memset/memcpy call.
 */
static inline void hct_reset(struct hct_ring *r) {
  if (!r) return;
  r->enabled=0;
  r->sequence=0;
  r->saturated=0;
  for (unsigned i=0;i<HCT_CAPACITY;i++) r->record[i].sequence=0;
}

static inline void hct_start(struct hct_ring *r) {
  if (!r) return;
  hct_reset(r);
  r->enabled=1;
}

static inline void hct_stop(struct hct_ring *r) {
  if (r) r->enabled=0;
}

/* Continue after a stopped report without discarding earlier call identities. */
static inline void hct_resume(struct hct_ring *r) {
  if (r && !r->saturated) r->enabled=1;
}

/* UEFI diagnostic execution is single CPU/single writer. This is not an SMP
 * logging primitive and never spins, takes a lock or calls another service.
 * sequence is the final slot store, so a stopped reader rejects a torn slot.
 */
static inline uint64_t hct_push(struct hct_ring *r,uint32_t step,
                              uint64_t address,uint64_t value,uint64_t counter) {
  if (!r || !r->enabled) return 0;
  uint64_t previous=r->sequence;
  if (previous==UINT64_MAX) {
    r->saturated=1;
    r->enabled=0;
    return 0;
  }
  uint64_t sequence=previous+1;
  volatile struct hct_record *out=&r->record[(sequence-1)&(HCT_CAPACITY-1)];
  out->sequence=0;
  out->counter=counter;
  out->address=address;
  out->value=value;
  out->step=step;
  out->reserved=0;
  out->sequence=sequence;
  r->sequence=sequence;
  return sequence;
}

static inline uint64_t hct_first(const struct hct_ring *r) {
  if (!r || !r->sequence) return 0;
  uint64_t sequence=r->sequence;
  return sequence>HCT_CAPACITY ? sequence-HCT_CAPACITY+1 : 1;
}

static inline uint64_t hct_unreported_first(const struct hct_ring *r,uint64_t reported) {
  if (!r || r->enabled || reported>=r->sequence) return 0;
  uint64_t first=hct_first(r);
  return first>reported ? first : reported+1;
}

/* A live report is refused instead of presenting a concurrently modified
 * slot as a complete diagnostic result. Caller supplies ordinary CPU RAM.
 */
static inline int hct_get(const struct hct_ring *r,uint64_t sequence,
                          struct hct_record *out) {
  if (!r || !out || r->enabled || !sequence || sequence<hct_first(r) ||
      sequence>r->sequence) return 0;
  const volatile struct hct_record *in=&r->record[(sequence-1)&(HCT_CAPACITY-1)];
  if (in->sequence!=sequence) return 0;
  out->counter=in->counter;
  out->address=in->address;
  out->value=in->value;
  out->step=in->step;
  out->reserved=in->reserved;
  out->sequence=sequence;
  return in->sequence==sequence;
}

/* A three-row strip: row 0 = sequence(low32) / step(hex32), row 1 =
 * address(hex64) / value(hex64), row 2 = blank during normal recording.
 * Fatal display uses rows 1 and 2 for PC/ESR and FAR/LR respectively.
 * No GOP/Blt call, framebuffer read, mapping,
 * display command, cache operation or barrier occurs when drawing a record.
 * White and black have the same representation in the two supported GOP
 * 32-bit RGB/BGR formats. Fit the largest scale up to 8: a 1200-pixel display
 * gets a 1056-pixel strip and 24x40-pixel glyphs. Small displays fall back.
 * Unsupported formats stay RAM-only.
 */
static inline int hct_screen_init(struct hct_screen *s,uintptr_t base,size_t bytes,
                                 uint32_t width,uint32_t height,uint32_t stride,
                                 unsigned pixel_format) {
  if (!s) return 0;
  s->enabled=0;
  s->cache_valid=0;
  s->pixels=0;
  s->pixel_count=0;
  s->width=s->height=s->stride=s->x=s->y=s->scale=0;
  if (!base || (base&3) || !bytes || (bytes&3) || base>UINTPTR_MAX-(bytes-1) ||
      pixel_format>1 || !width || !height || stride<width ||
      (size_t)height>SIZE_MAX/(size_t)stride ||
      (size_t)height*(size_t)stride>bytes/4) return 0;
  if (width<HCT_COLUMNS*HCT_CELL_WIDTH+16 ||
      height<HCT_ROWS*HCT_CELL_HEIGHT+16) return 0;
  unsigned scale=(width-16)/(HCT_COLUMNS*HCT_CELL_WIDTH);
  unsigned height_scale=(height-16)/(HCT_ROWS*HCT_CELL_HEIGHT);
  if (scale>height_scale) scale=height_scale;
  if (scale>HCT_MAX_SCALE) scale=HCT_MAX_SCALE;
  s->pixels=(volatile uint32_t *)base;
  s->pixel_count=bytes/4;
  s->width=width;s->height=height;s->stride=stride;
  s->x=s->y=8;s->scale=scale;
  s->enabled=1;
  return 1;
}

/* The font is expressed as five top-to-bottom rows, three bits per row. */
static inline uint16_t hct_glyph(unsigned digit) {
  static const uint16_t font[17]={
    0x7b6f,0x2c97,0x73e7,0x73cf,0x5bc9,0x79cf,0x79ef,0x7252,
    0x7bef,0x7bcf,0x2bed,0x6bae,0x7927,0x6b6e,0x79a7,0x79a4,0
  };
  return font[digit<=16 ? digit : 16];
}

static inline void hct_draw_glyph(struct hct_screen *s,unsigned cell,unsigned digit) {
  if (!s || !s->enabled || !s->pixels || cell>=HCT_ROWS*HCT_COLUMNS ||
      !s->scale || s->scale>HCT_MAX_SCALE || s->x>=s->width || s->y>=s->height ||
      s->stride<s->width) return;
  size_t x=(size_t)s->x+(cell%HCT_COLUMNS)*HCT_CELL_WIDTH*s->scale;
  size_t y=(size_t)s->y+(cell/HCT_COLUMNS)*HCT_CELL_HEIGHT*s->scale;
  if (x>s->width || HCT_CELL_WIDTH*s->scale>s->width-x ||
      y>s->height || HCT_CELL_HEIGHT*s->scale>s->height-y) return;
  uint16_t glyph=hct_glyph(digit);
  for (unsigned dy=0;dy<HCT_CELL_HEIGHT*s->scale;dy++) {
    unsigned row=dy/s->scale;
    for (unsigned dx=0;dx<HCT_CELL_WIDTH*s->scale;dx++) {
      unsigned col=dx/s->scale;
      uint32_t color=row<5 && col<3 &&
        (glyph&(1u<<(14-3*row-col))) ? 0x00ffffffu : 0;
      size_t offset=(y+dy)*(size_t)s->stride+x+dx;
      if (offset<s->pixel_count) s->pixels[offset]=color;
    }
  }
}

static inline void hct_screen_number(uint8_t *out,unsigned at,unsigned digits,uint64_t value) {
  if (!out || !digits || digits>16 || at>HCT_ROWS*HCT_COLUMNS ||
      digits>HCT_ROWS*HCT_COLUMNS-at) return;
  for (unsigned i=0;i<digits;i++) out[at+i]=(uint8_t)((value>>(4*(digits-1-i)))&15);
}

static inline void hct_screen_render(struct hct_screen *s,const uint8_t *digits) {
  if (!s || !s->enabled || !digits) return;
  for (unsigned i=0;i<HCT_ROWS*HCT_COLUMNS;i++) {
    if (!s->cache_valid || s->glyph[i]!=digits[i]) hct_draw_glyph(s,i,digits[i]);
    s->glyph[i]=digits[i];
  }
  s->cache_valid=1;
}

static inline void hct_screen_show(struct hct_screen *s,uint64_t sequence,uint32_t step,
                                  uint64_t address,uint64_t value) {
  if (!s || !s->enabled) return;
  uint8_t digits[HCT_ROWS*HCT_COLUMNS];
  for (unsigned i=0;i<HCT_ROWS*HCT_COLUMNS;i++) digits[i]=16;
  hct_screen_number(digits,0,8,sequence);
  hct_screen_number(digits,9,8,step);
  hct_screen_number(digits,HCT_COLUMNS,16,address);
  hct_screen_number(digits,HCT_COLUMNS+17,16,value);
  hct_screen_render(s,digits);
}

/* Exception-context best effort display: only the previously validated CPU
 * framebuffer view is used. No formatted output, service call or barrier.
 */
static inline void hct_screen_fault(struct hct_screen *s,uint64_t sequence,
                                   uint64_t pc,uint64_t esr,uint64_t far,uint64_t lr) {
  if (!s || !s->enabled) return;
  uint8_t digits[HCT_ROWS*HCT_COLUMNS];
  for (unsigned i=0;i<HCT_ROWS*HCT_COLUMNS;i++) digits[i]=16;
  hct_screen_number(digits,0,8,sequence);
  hct_screen_number(digits,9,8,0x700f);
  hct_screen_number(digits,HCT_COLUMNS,16,pc);
  hct_screen_number(digits,HCT_COLUMNS+17,16,esr);
  hct_screen_number(digits,2*HCT_COLUMNS,16,far);
  hct_screen_number(digits,2*HCT_COLUMNS+17,16,lr);
  hct_screen_render(s,digits);
}

#ifdef __cplusplus
extern "C" {
#endif
void HoujiGpuCallTraceInit(void);
void HoujiGpuCallTraceStart(void);
void HoujiGpuCallTraceStop(void);
void HoujiGpuCallTraceResume(void);
/* Suppress normal framebuffer updates until the next Init, including across
 * Start/Stop/Resume. CPU RAM recording and explicit fatal display still work. */
void HoujiGpuCallTraceRamOnly(void);
/* Pure CPU RAM state read for suppressing normal console framebuffer output.
 * A stopped recorder, including the fatal path, permits terminal output. */
unsigned HoujiGpuCallTraceConsoleSuppressed(void);
/* Copy the latest at most 512 committed CPU records once per Start/Init.
 * No services, allocation, MMIO, display, cache operation or barrier. */
void HoujiGpuCallTraceFreezeFirstFailure(void);
void HoujiGpuCallTrace(uint32_t step,uint64_t address,uint64_t value);
void HoujiGpuCallTraceFatal(uint64_t pc,uint64_t esr,uint64_t far,uint64_t lr);
void HoujiGpuCallTraceReport(void);
#ifdef __cplusplus
}
#endif

#endif
