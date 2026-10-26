/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Read the current entry-HOB FDT. Never invoke a hypercall, bind an IRQ or
 * use saved/captured capability defaults. The protocol freezes one report
 * in this DXE image's RAM; DarwinBoot can only copy it into a pristine ADT.
 */
#if defined(GG_GUNYAH_FDT_STANDALONE)
#include <stdint.h>
#include <stddef.h>
#include <libfdt.h>
typedef uint8_t UINT8;
typedef uint32_t UINT32;
typedef uint64_t UINT64;
typedef int32_t INT32;
typedef size_t UINTN;
typedef void VOID;
typedef char CHAR8;
#define CONST const
#define FdtCheckHeader fdt_check_header
#define FdtNextNode fdt_next_node
#define FdtParentOffset fdt_parent_offset
#define FdtGetProp fdt_getprop
#define FdtFirstPropertyOffset fdt_first_property_offset
#define FdtNextPropertyOffset fdt_next_property_offset
#define FdtGetPropertyByOffset fdt_get_property_by_offset
#define FdtGetString fdt_get_string
#else
#include <Uefi.h>
#include <Library/BaseMemoryLib.h>
#include <Library/DebugLib.h>
#include <Library/FdtLib.h>
#include <Library/UefiBootServicesTableLib.h>
#endif
#define GGR_FIRMWARE_TYPES 1
#include "GpuGunyahReport.h"

static UINT32 ggr_be32(const VOID *data)
{
    const UINT8 *p=(const UINT8 *)data;
    return (UINT32)p[0]<<24|(UINT32)p[1]<<16|(UINT32)p[2]<<8|p[3];
}
static UINT64 ggr_be64(const VOID *data)
{return (UINT64)ggr_be32(data)<<32|ggr_be32((const UINT8 *)data+4);}
static int ggr_same(const CHAR8 *a,const CHAR8 *b)
{
    for(unsigned i=0;i<256;i++) {if(a[i]!=b[i])return 0;if(!a[i])return 1;}
    return 0;
}
static int ggr_extent(UINT32 start,UINT32 bytes,UINT32 total)
{return start>=40 && start<=total && bytes<=total-start;}
static int ggr_overlap(UINT32 a,UINT32 na,UINT32 b,UINT32 nb)
{return a<b+nb && b<a+na;}
static UINT32 ggr_le32(const UINT8 *p)
{return (UINT32)p[0]|(UINT32)p[1]<<8|(UINT32)p[2]<<16|(UINT32)p[3]<<24;}
static UINT64 ggr_le64(const UINT8 *p)
{return (UINT64)ggr_le32(p)|(UINT64)ggr_le32(p+4)<<32;}
int ggr_fdt_memory_covered(const void *map,GGR_U32 map_bytes,GGR_U32 stride,
    GGR_U64 address,GGR_U32 bytes)
{
    struct {UINT64 start,end;} extents[128];unsigned count=0;
    if(!map || stride<40 || (stride&7) || !map_bytes || map_bytes%stride ||
       map_bytes/stride>4096 || !bytes || bytes>(UINT64)-1-address ||
       (UINTN)map>(UINTN)-1-map_bytes)return 0;
    UINT64 limit=address+bytes;
    for(UINT32 at=0;at<map_bytes;at+=stride) {
        const UINT8 *p=(const UINT8 *)map+at;
        UINT32 type=ggr_le32(p);UINT64 start=ggr_le64(p+8),pages=ggr_le64(p+24),attr=ggr_le64(p+32);
        if((start&4095) || !pages || pages>((UINT64)-1-start)/4096)return 0;
        UINT64 end=start+pages*4096;
        if(start>=limit || end<=address)continue;
        /* Reserved RAM is included: this platform describes its Kernel/DTB
         * reservations using that type. MMIO, unusable, PAL and unaccepted
         * memory are excluded. Read-only and execute-protected RAM is fine. */
        if((type>7 && type!=9 && type!=10) || (attr&0x2000ULL) || count==128)return 0;
        for(unsigned i=0;i<count;i++)if(start<extents[i].end && extents[i].start<end)return 0;
        extents[count].start=start;extents[count++].end=end;
    }
    UINT64 cursor=address;
    for(unsigned step=0;step<count && cursor<limit;step++) {
        unsigned found=0;
        for(unsigned i=0;i<count;i++)if(extents[i].start<=cursor && cursor<extents[i].end) {
            cursor=extents[i].end;found=1;break;
        }
        if(!found)return 0;
    }
    return cursor>=limit;
}

/* FdtCheckHeader alone does not validate the complete structure or reservation
 * map. Bound and validate every token before using the public FdtLib APIs.
 * Only the actual boot profile's v17 representation is supported. */
static int ggr_layout(const VOID *data,UINT32 bytes)
{
    const UINT8 *p=(const UINT8 *)data;
    if(bytes<72 || bytes>GGR_MAX_FDT_BYTES || ggr_be32(p)!=0xd00dfeed ||
       ggr_be32(p+4)!=bytes || ggr_be32(p+20)!=17 ||
       ggr_be32(p+24)>17 || ggr_be32(p+24)<16)return 0;
    UINT32 st=ggr_be32(p+8),ss=ggr_be32(p+36),str=ggr_be32(p+12),ns=ggr_be32(p+32);
    UINT32 reserve=ggr_be32(p+16),end=reserve;
    if((st&3) || (reserve&7) || !ggr_extent(st,ss,bytes) ||
       !ggr_extent(str,ns,bytes) || ggr_overlap(st,ss,str,ns) || !ggr_extent(reserve,16,bytes))return 0;
    for(unsigned i=0;;i++) {
        if(i==4096 || !ggr_extent(end,16,bytes))return 0;
        UINT64 address=ggr_be64(p+end),size=ggr_be64(p+end+8);end+=16;
        if(!address && !size)break;
        if(size>(UINT64)-1-address)return 0;
    }
    if(ggr_overlap(reserve,end-reserve,st,ss) || ggr_overlap(reserve,end-reserve,str,ns))return 0;
    UINT32 at=st,limit=st+ss;unsigned depth=0,nodes=0,closed=0,child_seen[64]={0};
    while(at<limit) {
        if(limit-at<4)return 0;
        UINT32 tag=ggr_be32(p+at);at+=4;
        if(tag==1) {
            if(closed || ++depth>64 || ++nodes>8192)return 0;
            if(depth>1)child_seen[depth-2]=1;
            child_seen[depth-1]=0;
            UINT32 name=at;
            while(at<limit && p[at]) {
                if(at-name>=255 || p[at]<33 || p[at]>126 || p[at]=='/')return 0;
                ++at;
            }
            if(at==limit || (nodes==1 && at!=name))return 0;
            at=(at+4)&~3u;if(at>limit)return 0;
        } else if(tag==2) {
            if(!depth)return 0;
            if(!--depth)closed=1;
        } else if(tag==3) {
            if(!depth || child_seen[depth-1] || limit-at<8)return 0;
            UINT32 length=ggr_be32(p+at),name=ggr_be32(p+at+4);at+=8;
            if(length>limit-at || name>=ns)return 0;
            UINT32 n=0;
            while(name+n<ns && p[str+name+n]) {
                if(++n>255 || p[str+name+n-1]<33 || p[str+name+n-1]>126)return 0;
            }
            if(!n || name+n==ns)return 0;
            at+=(length+3)&~3u;if(at>limit)return 0;
        } else if(tag==9)return closed && !depth && at==limit;
        else if(tag!=4)return 0;
    }
    return 0;
}

static int ggr_unique(const VOID *fdt,INT32 node,unsigned *work)
{
    /* This board's __symbols__ node contains 1465 entries. Keep the full
     * uniqueness check bounded while accommodating that real boot tree. */
    const CHAR8 *names[2048];unsigned count=0;
    INT32 offset=FdtFirstPropertyOffset(fdt,node);
    while(offset>=0) {
        INT32 bytes=0,n=0;
        const VOID *property=FdtGetPropertyByOffset(fdt,offset,&bytes);
        if(!property || bytes<0 || count==2048)return 0;
        const CHAR8 *name=FdtGetString(fdt,(INT32)ggr_be32((const UINT8 *)property+8),&n);
        if(!name || n<=0 || n>255)return 0;
        for(unsigned i=0;i<count;i++) {
            if(++*work>2097152 || ggr_same(name,names[i]))return 0;
        }
        names[count++]=name;
        offset=FdtNextPropertyOffset(fdt,offset);
    }
    return offset==-FDT_ERR_NOTFOUND;
}
/* Fully validate each list, including its final terminator. Duplicate matches
 * are ambiguous; an early matching string cannot hide a malformed tail. */
static int ggr_compatible(const VOID *fdt,INT32 node,const CHAR8 *wanted)
{
    INT32 bytes=0;const UINT8 *p=FdtGetProp(fdt,node,"compatible",&bytes);
    if(!p)return bytes==-FDT_ERR_NOTFOUND?0:-1;
    if(bytes<=0 || bytes>4096)return -1;
    unsigned found=0;INT32 at=0;
    while(at<bytes) {
        INT32 start=at;
        while(at<bytes && p[at]) {if(at-start>=255 || p[at]<32 || p[at]>126)return -1;++at;}
        if(at==bytes || at==start)return -1;
        if(ggr_same((const CHAR8 *)p+start,wanted) && ++found>1)return -1;
        ++at;
    }
    return (int)found;
}
static int ggr_enabled(const VOID *fdt,INT32 node)
{
    for(unsigned depth=0;node>=0;depth++) {
        if(depth==64)return 0;
        INT32 bytes=0;const UINT8 *p=FdtGetProp(fdt,node,"status",&bytes);
        if(p) {
            if(!((bytes==5 && ggr_same((const CHAR8 *)p,"okay")) ||
                 (bytes==3 && ggr_same((const CHAR8 *)p,"ok"))))return 0;
        } else if(bytes!=-FDT_ERR_NOTFOUND)return 0;
        node=FdtParentOffset(fdt,node);
    }
    return node==-FDT_ERR_NOTFOUND;
}
static int ggr_parent(const VOID *fdt,INT32 node,UINT32 *parent)
{
    for(unsigned depth=0;node>=0;depth++) {
        if(depth==64)return 0;
        INT32 bytes=0;const UINT8 *p=FdtGetProp(fdt,node,"interrupt-map",&bytes);
        if(p || bytes!=-FDT_ERR_NOTFOUND)return 0;
        p=FdtGetProp(fdt,node,"interrupt-parent",&bytes);
        if(p) {
            if(bytes!=4 || !ggr_be32(p) || ggr_be32(p)==0xffffffffu)return 0;
            *parent=ggr_be32(p);return 1;
        }
        if(bytes!=-FDT_ERR_NOTFOUND)return 0;
        node=FdtParentOffset(fdt,node);
    }
    return 0;
}

int ggr_fdt_capture(const void *fdt,GGR_U32 bytes,GGR_U64 epoch,struct ggr_report *out)
{
    if(!fdt || !out || !epoch || ((UINTN)fdt&7) || (UINTN)out%__alignof__(*out) ||
       (UINTN)fdt>(UINTN)-1-bytes || (UINTN)out>(UINTN)-1-sizeof(*out) ||
       ((UINTN)fdt<(UINTN)out+sizeof(*out) && (UINTN)out<(UINTN)fdt+bytes))return GGR_ERR_ARGUMENT;
    if(!ggr_layout(fdt,bytes) || FdtCheckHeader(fdt))return GGR_ERR_FDT;
    struct ggr_report r;ggr_report_init(&r);
    r.source=GGR_SOURCE_BOOT_FDT;r.epoch=epoch;r.fdt_bytes=bytes;r.fdt_crc32=ggr_crc32(fdt,bytes);
    INT32 node=-1,rm=-1,gic=-1;unsigned work=0,nodes=0;
    while((node=FdtNextNode(fdt,node,NULL))>=0) {
        if(++nodes>8192 || !ggr_unique(fdt,node,&work))return GGR_ERR_FDT;
        int compatible=ggr_compatible(fdt,node,"gunyah-resource-manager");
        if(compatible<0)return GGR_ERR_FDT;
        if(compatible){if(rm>=0)return GGR_ERR_RESOURCE;rm=node;}
    }
    if(node!=-FDT_ERR_NOTFOUND || rm<0 || !ggr_enabled(fdt,rm) ||
       !ggr_parent(fdt,rm,&r.interrupt_parent))return GGR_ERR_RESOURCE;
    /* The actual RM parent is /hypervisor, not /soc: the captured board's
     * lines 35189-35193 specify the Gunyah 2/0 capability bus. The canonical
     * rsc_mgr driver explicitly reads two u64 reg entries as capabilities. */
    INT32 parent=FdtParentOffset(fdt,rm),cells=0;
    const UINT8 *cell=parent>=0?FdtGetProp(fdt,parent,"#address-cells",&cells):NULL;
    if(!cell || cells!=4 || ggr_be32(cell)!=2)return GGR_ERR_RESOURCE;
    cell=FdtGetProp(fdt,parent,"#size-cells",&cells);
    if(!cell || cells!=4 || ggr_be32(cell)!=0 ||
       ggr_compatible(fdt,parent,"qcom,gunyah-hypervisor")!=1)return GGR_ERR_RESOURCE;
    node=-1;unsigned matches=0;
    while((node=FdtNextNode(fdt,node,NULL))>=0) {
        INT32 a=0,b=0;const UINT8 *p=FdtGetProp(fdt,node,"phandle",&a);
        const UINT8 *q=FdtGetProp(fdt,node,"linux,phandle",&b);
        if((p && (a!=4 || !ggr_be32(p) || ggr_be32(p)==0xffffffffu)) ||
           (q && (b!=4 || !ggr_be32(q) || ggr_be32(q)==0xffffffffu)) ||
           (!p && a!=-FDT_ERR_NOTFOUND) || (!q && b!=-FDT_ERR_NOTFOUND) ||
           (p && q && ggr_be32(p)!=ggr_be32(q)))return GGR_ERR_FDT;
        if((p && ggr_be32(p)==r.interrupt_parent) || (q && ggr_be32(q)==r.interrupt_parent)) {
            if(++matches!=1)return GGR_ERR_RESOURCE;
            gic=node;
        }
    }
    if(node!=-FDT_ERR_NOTFOUND || gic<0 || ggr_compatible(fdt,gic,"arm,gic-v3")!=1 ||
       !ggr_enabled(fdt,gic))return GGR_ERR_RESOURCE;
    INT32 n=0;const UINT8 *p=FdtGetProp(fdt,gic,"#interrupt-cells",&n);
    if(!p || n!=4 || ggr_be32(p)!=3)return GGR_ERR_RESOURCE;
    p=FdtGetProp(fdt,gic,"interrupt-controller",&n);
    if(!p || n)return GGR_ERR_RESOURCE;
    p=FdtGetProp(fdt,rm,"interrupts-extended",&n);
    if(p || n!=-FDT_ERR_NOTFOUND)return GGR_ERR_RESOURCE;
    p=FdtGetProp(fdt,rm,"reg",&n);
    if(!p || n!=16)return GGR_ERR_RESOURCE;
    r.tx_cap=ggr_be64(p);r.rx_cap=ggr_be64(p+8);
    p=FdtGetProp(fdt,rm,"interrupts",&n);
    if(!p || n!=24)return GGR_ERR_RESOURCE;
    for(unsigned i=0;i<3;i++){r.tx_irq[i]=ggr_be32(p+i*4);r.rx_irq[i]=ggr_be32(p+12+i*4);}
    r.rm_node=(UINT32)rm;r.gic_node=(UINT32)gic;r.interrupt_cells=3;
    if(ggr_crc32(fdt,bytes)!=r.fdt_crc32)return GGR_ERR_FDT;
    ggr_report_seal(&r);if(!ggr_report_valid(&r))return GGR_ERR_RESOURCE;
    *out=r;return GGR_OK;
}

#if !defined(GG_GUNYAH_FDT_STANDALONE)
static struct ggr_report mGunyahReport;
static unsigned mGunyahAttempted;
static int GunyahNextCount(void *unused,GGR_U64 *out)
{
    UINT64 count=0;(void)unused;
    EFI_STATUS status=gBS->GetNextMonotonicCount(&count);
    if(EFI_ERROR(status))return 0;
    *out=count;return 1;
}
static EFI_STATUS EFIAPI GunyahCapture(struct ggr_report *out,UINTN bytes)
{
    if(!out || bytes!=sizeof(*out) || !ggr_report_requested(out))return EFI_INVALID_PARAMETER;
    if(!ggr_report_valid(&mGunyahReport))return EFI_NOT_READY;
    CopyMem(out,&mGunyahReport,sizeof(*out));return EFI_SUCCESS;
}
VOID GiuliaGpuGunyahInstall(CONST VOID *Fdt)
{
    typedef struct {UINT64 Version;EFI_STATUS(EFIAPI *Capture)(struct ggr_report *,UINTN);} GUNYAH_PROTOCOL;
    static GUNYAH_PROTOCOL protocol={GGR_PROTOCOL_VERSION,GunyahCapture};
    EFI_GUID guid=GGR_PROTOCOL_GUID;EFI_HANDLE handle=NULL;UINT64 epoch=0;
    if(mGunyahAttempted)return;
    mGunyahAttempted=1;
    if(!Fdt || ((UINTN)Fdt&7))return;
    UINTN map_bytes=0,key=0,stride=0,capacity;UINT32 version=0;
    EFI_MEMORY_DESCRIPTOR *map=NULL;
    EFI_STATUS status=gBS->GetMemoryMap(&map_bytes,NULL,&key,&stride,&version);
    if(status!=EFI_BUFFER_TOO_SMALL || !map_bytes || map_bytes>1024*1024)return;
    capacity=map_bytes+8*sizeof(EFI_MEMORY_DESCRIPTOR);
    status=gBS->AllocatePool(EfiBootServicesData,capacity,(VOID **)&map);
    if(EFI_ERROR(status) || !map)return;
    map_bytes=capacity;
    status=gBS->GetMemoryMap(&map_bytes,map,&key,&stride,&version);
    struct ggr_report report;
    unsigned captured=0;
    if(!EFI_ERROR(status) && map_bytes<=capacity && map_bytes<=1024*1024 &&
       stride<=1024*1024 && version==EFI_MEMORY_DESCRIPTOR_VERSION &&
       ggr_fdt_memory_covered(map,(UINT32)map_bytes,(UINT32)stride,(UINT64)(UINTN)Fdt,40)) {
        UINT32 bytes=ggr_be32((const UINT8 *)Fdt+4);
        if(bytes>=72 && bytes<=GGR_MAX_FDT_BYTES &&
           ggr_fdt_memory_covered(map,(UINT32)map_bytes,(UINT32)stride,(UINT64)(UINTN)Fdt,bytes)) {
            if(ggr_boot_epoch(GunyahNextCount,NULL,&epoch) &&
               ggr_fdt_capture(Fdt,bytes,epoch,&report)==GGR_OK)captured=1;
        }
    }
    gBS->FreePool(map);
    if(!captured)return;
    mGunyahReport=report;
    status=gBS->InstallMultipleProtocolInterfaces(&handle,&guid,&protocol,NULL);
    DEBUG((DEBUG_ERROR,"GIULIA GUNYAH: current boot FDT report=%r; no HVC or IRQ lease installed\n",status));
}
#endif
