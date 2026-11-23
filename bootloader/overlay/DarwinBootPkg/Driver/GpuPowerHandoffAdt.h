/* SPDX-License-Identifier: MIT
 * Bounded scalar transport only; caller owns loader/XNU integration.
 * ADT: LE u32 property/child counts; property name[32], LE size, padded data.
 * No pointer or configuration-table object is stored in the tree. The caller
 * must qualify the source record with hph_decode BEFORE hpa_bind, and must
 * exclusively own immutable inputs until this bounded synchronous copy ends.
 */
#ifndef HOUJI_GPU_POWER_HANDOFF_ADT_H
#define HOUJI_GPU_POWER_HANDOFF_ADT_H
#include <stddef.h>
#include <stdint.h>

#define HPA_PROPERTY "houji,gpu-power-handoff"
enum {HPA_RECORD_BYTES=1376,HPA_MAX_DEPTH=64,HPA_MAX_PROPERTIES=256,HPA_MAX_ADT_BYTES=1048576};
enum {HPA_OK,HPA_ARGUMENT,HPA_BOUNDS,HPA_NAME,HPA_FLAGS,HPA_TREE,
 HPA_DUPLICATE,HPA_SLOT,HPA_NONZERO,HPA_ALIAS};
struct hpa_slot {size_t offset,bytes;};
struct hpa_parse {
 const unsigned char *data;size_t bytes,offset,chosen,properties,slot;
};
static inline uint32_t hpa_u32(const unsigned char *p) {
 return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);
}
static inline int hpa_equal(const unsigned char *p,size_t bytes,const char *s) {
 size_t i=0;for(;i<bytes && s[i];++i)if(p[i]!=(unsigned char)s[i])return 0;
 return i+1==bytes && !s[i] && !p[i];
}
/* Property names are terminated within 32 bytes and use canonical zero tail.
 * Node names contain exactly one trailing NUL, printable ASCII, no path slash.
 * No string function may scan beyond its declared wire field. */
static inline int hpa_name(const unsigned char *p,size_t bytes,int property) {
 size_t n=0;for(;n<bytes && p[n];++n)
  if(p[n]<0x21 || p[n]>0x7e || p[n]=='/')return 0;
 if(!n || n==bytes)return 0;
 if(!property)return n+1==bytes;
 for(;n<bytes;++n)if(p[n])return 0;
 return 1;
}
static inline int hpa_field(const unsigned char *p,const char *s) {
 size_t n=0;while(n<32 && p[n])++n;return hpa_equal(p,n+1,s);
}
static inline int hpa_node(struct hpa_parse *p,unsigned depth) {
 if(depth>HPA_MAX_DEPTH || p->offset>p->bytes || p->bytes-p->offset<8)return HPA_BOUNDS;
 uint32_t count=hpa_u32(p->data+p->offset),children=hpa_u32(p->data+p->offset+4);
 p->offset+=8;
 if(count>HPA_MAX_PROPERTIES || count>(p->bytes-p->offset)/36)return HPA_BOUNDS;
 const unsigned char *name=NULL;size_t name_bytes=0,first=p->offset,slot=SIZE_MAX;
 for(uint32_t i=0;i<count;++i) {
  if(p->offset>p->bytes || p->bytes-p->offset<36)return HPA_BOUNDS;
  const unsigned char *key=p->data+p->offset;
  if(!hpa_name(key,32,1))return HPA_NAME;
  /* Duplicate attributes have ambiguous consumers even when unrelated to this
   * transport. Rescan at most 256 already-bounded headers, never recurse here. */
  size_t prior=first;
  for(uint32_t j=0;j<i;++j) {
   unsigned same=1;for(unsigned k=0;k<32;++k)if(p->data[prior+k]!=key[k]){same=0;break;}
   if(same)return HPA_DUPLICATE;
   prior+=36+((hpa_u32(p->data+prior+32)+3u)&~(size_t)3u);
  }
  uint32_t length=hpa_u32(key+32);p->offset+=36;
  if(length&UINT32_C(0x80000000))return HPA_FLAGS;
  if(length>p->bytes-p->offset)return HPA_BOUNDS;
  size_t padded=((size_t)length+3u)&~(size_t)3u;
  if(padded>p->bytes-p->offset)return HPA_BOUNDS;
  for(size_t k=length;k<padded;++k)if(p->data[p->offset+k])return HPA_TREE;
  if(hpa_field(key,"name")) {
   if(name || length>256 || !hpa_name(p->data+p->offset,length,0))return HPA_NAME;
   name=p->data+p->offset;name_bytes=length;
  }
  if(hpa_field(key,HPA_PROPERTY)) {
   if(++p->properties!=1 || slot!=SIZE_MAX)return HPA_DUPLICATE;
   if(length!=HPA_RECORD_BYTES)return HPA_SLOT;
   for(size_t k=0;k<length;++k)if(p->data[p->offset+k])return HPA_NONZERO;
   slot=p->offset;
  }
  p->offset+=padded;
 }
 if(!name)return HPA_NAME;
 if(!depth && !hpa_equal(name,name_bytes,"device-tree"))return HPA_TREE;
 int chosen=hpa_equal(name,name_bytes,"chosen");
 if(chosen && (depth!=1 || ++p->chosen!=1))return HPA_DUPLICATE;
 if(slot!=SIZE_MAX) {
  if(!chosen || depth!=1)return HPA_SLOT;
  p->slot=slot;
 }
 if(children>(p->bytes-p->offset)/8)return HPA_BOUNDS;
 for(uint32_t i=0;i<children;++i) {
  int status=hpa_node(p,depth+1);if(status)return status;
 }
 return HPA_OK;
}
static inline int hpa_span(uintptr_t base,size_t bytes) {return bytes<=UINTPTR_MAX-base;}
static inline int hpa_overlap(uintptr_t a,size_t an,uintptr_t b,size_t bn) {
 return a<b+bn && b<a+an;
}
/* Validate the WHOLE tree, exactly one root /chosen and exactly one global
 * target property. The fixed zero slot must already exist; no resize, add or
 * length/flag patch is performed. On failure both ADT and output stay intact. */
static inline int hpa_find(const void *adt,size_t bytes,struct hpa_slot *out) {
 if(!adt || !out || !bytes || bytes>HPA_MAX_ADT_BYTES || !hpa_span((uintptr_t)adt,bytes) ||
  !hpa_span((uintptr_t)out,sizeof(*out)))return HPA_ARGUMENT;
 if(hpa_overlap((uintptr_t)adt,bytes,(uintptr_t)out,sizeof(*out)))return HPA_ALIAS;
 struct hpa_parse p={(const unsigned char *)adt,bytes,0,0,0,SIZE_MAX};
 int status=hpa_node(&p,0);if(status)return status;
 if(p.offset!=bytes)return HPA_TREE;
 if(p.chosen!=1 || p.properties!=1 || p.slot==SIZE_MAX)return HPA_SLOT;
 out->offset=p.slot;out->bytes=HPA_RECORD_BYTES;return HPA_OK;
}
/* Source qualification belongs to hph_decode, not this transport helper.
 * record must be an independent 1376-byte scalar copy, never a UEFI pointer
 * property. No write occurs until every bounds/alias/tree/zero check passes.
 * Binding a qualified (nonzero) record consumes the zero slot, so a second
 * bind refuses. This helper intentionally does not accept/reject record CRCs. */
static inline int hpa_bind(void *adt,size_t bytes,const void *record,size_t record_bytes,struct hpa_slot *out) {
 if(!adt || !record || record_bytes!=HPA_RECORD_BYTES || !hpa_span((uintptr_t)record,record_bytes) ||
  (out && !hpa_span((uintptr_t)out,sizeof(*out))))return HPA_ARGUMENT;
 if(!hpa_span((uintptr_t)adt,bytes))return HPA_ARGUMENT;
 if(hpa_overlap((uintptr_t)adt,bytes,(uintptr_t)record,record_bytes) ||
  (out && (hpa_overlap((uintptr_t)adt,bytes,(uintptr_t)out,sizeof(*out)) ||
           hpa_overlap((uintptr_t)record,record_bytes,(uintptr_t)out,sizeof(*out)))))return HPA_ALIAS;
 struct hpa_slot found;int status=hpa_find(adt,bytes,&found);if(status)return status;
 unsigned char *d=(unsigned char *)adt+found.offset;const unsigned char *s=(const unsigned char *)record;
 for(size_t i=0;i<HPA_RECORD_BYTES;++i)d[i]=s[i];
 if(out)*out=found;return HPA_OK;
}
#endif
