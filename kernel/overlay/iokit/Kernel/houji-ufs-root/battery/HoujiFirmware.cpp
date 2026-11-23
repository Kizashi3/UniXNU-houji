// SPDX-License-Identifier: BSD-2-Clause-Patent
// The pinned UniXNU-sheng FAT/split-MDT path, with a bounded houji-only UFS
// backend, explicit allocation checks and no VFS/alternate-slot fallback.
#include <IOKit/IOLib.h>
#include <libkern/libkern.h>
#include <sys/errno.h>
#include "HoujiFirmware.h"
#include "FatVolume.h"
#include "QcomMdt.h"

namespace {
struct Volume {
    FatVolume fat;
    uint64_t bytes, cached;
    uint8_t block[4096];
};
struct Image {
    QcomMdtSplit split;
    FatFile pieces[QCOM_MDT_MAX_SEGMENTS];
};
// Only the ADSP worker calls these functions, from first open until close.
Volume *gVolume;
int partitionRead(void *context,uint64_t offset,void *to,size_t length) {
    Volume *v=static_cast<Volume *>(context);uint8_t *out=static_cast<uint8_t *>(to);
    if(offset>v->bytes || length>v->bytes-offset || (!to && length))return EINVAL;
    while(length) {
        uint64_t lba=offset/4096;size_t within=offset%4096;
        if(!within && length>=4096) {
            uint32_t blocks=length/4096>32?32:static_cast<uint32_t>(length/4096);
            if(!houji_modem_read(lba,blocks,out))return EIO;
            size_t n=blocks*4096;out+=n;offset+=n;length-=n;
        } else {
            if(v->cached!=lba) {
                v->cached=UINT64_MAX;
                if(!houji_modem_read(lba,1,v->block))return EIO;
                v->cached=lba;
            }
            size_t n=4096-within;if(n>length)n=length;
            memcpy(out,v->block+within,n);out+=n;offset+=n;length-=n;
        }
    }
    return 0;
}
int mountVolume() {
    if(gVolume)return 0;
    uint64_t blocks=0;
    if(!houji_modem_partition(&blocks))return ENXIO;
    if(!blocks || blocks>UINT64_MAX/4096)return EINVAL;
    Volume *v=static_cast<Volume *>(IOMalloc(sizeof(Volume)));
    if(!v)return ENOMEM;
    bzero(v,sizeof(*v));v->bytes=blocks*4096;v->cached=UINT64_MAX;
    int rc=fat_mount(&v->fat,v->bytes,partitionRead,v);
    if(rc){IOFree(v,sizeof(*v));return EFTYPE;}
    gVolume=v;return 0;
}
int pieceRead(void *context,unsigned index,uint64_t offset,void *to,size_t length) {
    Image *m=static_cast<Image *>(context);
    if(index>=m->split.count)return EINVAL;
    return fat_read(&gVolume->fat,&m->pieces[index],offset,to,length);
}
}

extern "C" int houji_fw_open(const char *name,void **handle,uint64_t *size) {
    if(!name || !handle || !size || (strcmp(name,"adsp") && strcmp(name,"adsp_dtb")))return EINVAL;
    *handle=nullptr;*size=0;
    int rc=mountVolume();if(rc)return rc;
    Image *m=static_cast<Image *>(IOMalloc(sizeof(Image)));
    if(!m)return ENOMEM;
    bzero(m,sizeof(*m));char path[48];FatFile headers={};
    snprintf(path,sizeof(path),"image/%s.b00",name);
    rc=fat_open(&gVolume->fat,path,&headers);
    if(rc)rc=rc==FatNotFound?ENOENT:EIO;
    if(!rc && (headers.size<52 || headers.size>65536))rc=EFTYPE;
    uint8_t *bytes=nullptr;
    if(!rc) {bytes=static_cast<uint8_t *>(IOMalloc(headers.size));if(!bytes)rc=ENOMEM;}
    if(!rc && fat_read(&gVolume->fat,&headers,0,bytes,headers.size))rc=EIO;
    if(!rc && qcom_mdt_split(&m->split,bytes,headers.size))rc=EFTYPE;
    if(bytes)IOFree(bytes,headers.size);
    for(unsigned i=0;!rc && i<m->split.count;i++) {
        if(!m->split.piece[i].size)continue;
        snprintf(path,sizeof(path),"image/%s.b%02u",name,i);
        if(fat_open(&gVolume->fat,path,&m->pieces[i]))rc=ENOENT;
        else if(m->pieces[i].size!=m->split.piece[i].size)rc=EFTYPE;
    }
    if(rc){IOFree(m,sizeof(*m));return rc;}
    *handle=m;*size=m->split.size;return 0;
}
extern "C" int houji_fw_read(void *handle,uint64_t offset,void *to,size_t length) {
    if(!handle || (!to && length) || !gVolume)return EINVAL;
    Image *m=static_cast<Image *>(handle);
    return qcom_mdt_split_read(&m->split,pieceRead,m,offset,to,length)?EIO:0;
}
extern "C" void houji_fw_close(void *handle) {
    if(handle)IOFree(handle,sizeof(Image));
}
