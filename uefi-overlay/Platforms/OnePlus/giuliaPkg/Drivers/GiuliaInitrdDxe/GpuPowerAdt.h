/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Bounded validation of a serialized ADT. No allocation, address mutation or
 * firmware services; returns only the fixed report payload's byte offset.
 * UEFI UINT8/UINT32/UINTN types are supplied by the including translation unit.
 */
#ifndef GIULIA_GPU_POWER_ADT_H
#define GIULIA_GPU_POWER_ADT_H
#define GPA_ADT_MAX_BYTES (16u*1024u*1024u)
#define GPA_ADT_MAX_NODES 256u
#define GPA_ADT_MAX_PROPERTIES 256u
#define GPA_ADT_MAX_WORK 2097152u
enum { GPA_ADT_INVALID=-1, GPA_ADT_ABSENT=0, GPA_ADT_PRESENT=1 };
struct gpa_adt_node { UINTN name, length; unsigned parent; };
struct gpa_adt_scan {
  const UINT8 *data;
  const char *report_key;
  UINTN bytes, at, report, report_bytes;
  unsigned nodes, chosen, matches, work, board;
  struct gpa_adt_node node[GPA_ADT_MAX_NODES];
};
static UINT32 gpa_adt_u32(const UINT8 *p)
{
  return (UINT32)p[0]|((UINT32)p[1]<<8)|((UINT32)p[2]<<16)|((UINT32)p[3]<<24);
}
static int gpa_adt_equal(const UINT8 *a,const UINT8 *b,UINTN bytes)
{
  UINTN i;for(i=0;i<bytes;++i)if(a[i]!=b[i])return 0;return 1;
}
static int gpa_adt_key(const UINT8 *key,const char *name)
{
  unsigned i;for(i=0;i<32;++i) {
    if(key[i]!=(UINT8)name[i])return 0;
    if(!key[i])return 1;
  }
  return 0;
}
static int gpa_adt_name_valid(const UINT8 *name,UINTN bytes)
{
  UINTN i;if(!bytes || bytes>128 || name[bytes-1])return 0;
  for(i=0;i+1<bytes;++i)if(name[i]<32 || name[i]>126 || name[i]=='/')return 0;
  return bytes>1;
}
static int gpa_adt_node_read(struct gpa_adt_scan *s,unsigned depth,unsigned parent)
{
  UINT32 properties,children,length;
  UINTN properties_at,property,prior,name=0,name_bytes=0,candidate=0;
  unsigned i,j,id,has_candidate=0;
  if(depth>64 || s->nodes==GPA_ADT_MAX_NODES || s->at>s->bytes || s->bytes-s->at<8)return 0;
  id=s->nodes++;properties=gpa_adt_u32(s->data+s->at);children=gpa_adt_u32(s->data+s->at+4);s->at+=8;
  if(properties>GPA_ADT_MAX_PROPERTIES || properties>(s->bytes-s->at)/36 || children>GPA_ADT_MAX_NODES-s->nodes)return 0;
  properties_at=s->at;
  for(i=0;i<properties;++i) {
    if(s->at>s->bytes || s->bytes-s->at<36 || ++s->work>GPA_ADT_MAX_WORK)return 0;
    property=s->at;
    for(j=0;j<32 && s->data[property+j];++j) {}
    if(!j || j==32)return 0;
    /* Compare semantic keys, including a terminating NUL. Different trailing
     * key padding cannot hide duplicate properties. Previous lengths were
     * checked when their payloads were consumed. */
    prior=properties_at;
    while(prior<property) {
      UINTN previous_length;
      if(++s->work>GPA_ADT_MAX_WORK)return 0;
      if(gpa_adt_equal(s->data+prior,s->data+property,(UINTN)j+1))return 0;
      previous_length=gpa_adt_u32(s->data+prior+32);
      prior+=36+((previous_length+3)&~(UINTN)3);
    }
    length=gpa_adt_u32(s->data+property+32);s->at+=36;
    if(length>s->bytes-s->at)return 0;
    if(gpa_adt_key(s->data+property,"name")) {name=s->at;name_bytes=length;}
    if(!depth && gpa_adt_key(s->data+property,"physical-model"))
      s->board=length==14 && gpa_adt_equal(s->data+s->at,(const UINT8 *)"OnePlus Ace 5",14);
    if(gpa_adt_key(s->data+property,s->report_key)) {
      if(has_candidate || length!=s->report_bytes)return 0;
      candidate=s->at;has_candidate=1;
    }
    s->at+=length;s->at=(s->at+3)&~(UINTN)3;if(s->at>s->bytes)return 0;
  }
  if(!name || !gpa_adt_name_valid(s->data+name,name_bytes))return 0;
  if(!depth && (name_bytes!=12 || !gpa_adt_equal(s->data+name,(const UINT8 *)"device-tree",12)))return 0;
  for(i=0;i<id;++i) {
    if(++s->work>GPA_ADT_MAX_WORK)return 0;
    if(s->node[i].parent==parent && s->node[i].length==name_bytes &&
       gpa_adt_equal(s->data+s->node[i].name,s->data+name,name_bytes))return 0;
  }
  s->node[id].name=name;s->node[id].length=name_bytes;s->node[id].parent=parent;
  if(depth==1 && name_bytes==7 && gpa_adt_equal(s->data+name,(const UINT8 *)"chosen",7)) {
    if(++s->chosen!=1)return 0;
    if(has_candidate){s->report=candidate;++s->matches;}
  } else if(has_candidate)return 0;
  for(i=0;i<children;++i)if(!gpa_adt_node_read(s,depth+1,id))return 0;
  return 1;
}
static int gpa_adt_find_named(const void *data,UINTN bytes,UINTN report_bytes,
    const char *report_key,UINTN *offset)
{
  struct gpa_adt_scan scan;
  unsigned key_bytes;
  if(!offset)return GPA_ADT_INVALID;
  *offset=0;
  if(!data || !bytes || bytes>GPA_ADT_MAX_BYTES || !report_bytes || report_bytes>256 || !report_key)return GPA_ADT_INVALID;
  for(key_bytes=0;key_bytes<32 && report_key[key_bytes];++key_bytes) {}
  if(!key_bytes || key_bytes==32)return GPA_ADT_INVALID;
  scan.data=(const UINT8 *)data;scan.bytes=bytes;scan.at=scan.report=0;scan.report_bytes=report_bytes;
  scan.report_key=report_key;
  scan.nodes=scan.chosen=scan.matches=scan.work=scan.board=0;
  if(!gpa_adt_node_read(&scan,0,GPA_ADT_MAX_NODES) || scan.at!=bytes || scan.chosen!=1 || scan.matches>1)return GPA_ADT_INVALID;
  if(!scan.matches)return GPA_ADT_ABSENT;
  if(!scan.board)return GPA_ADT_INVALID;
  *offset=scan.report;return GPA_ADT_PRESENT;
}
static inline int gpa_adt_find(const void *data,UINTN bytes,UINTN report_bytes,UINTN *offset)
{return gpa_adt_find_named(data,bytes,report_bytes,"giulia-gpu-power",offset);}
#endif
