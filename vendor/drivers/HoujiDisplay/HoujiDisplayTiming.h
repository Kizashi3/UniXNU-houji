/* SPDX-License-Identifier: MIT */
#ifndef HOUJI_DISPLAY_TIMING_H
#define HOUJI_DISPLAY_TIMING_H
#include <stdint.h>
#include <stddef.h>

// Houji pineapple-sde-common.dtsi: MDSS-relative offsets, not sheng's
// MDP-relative offsets. DSI0 uses INTF1 at physical 0x0ae36000.
namespace HoujiDisplayTiming {
constexpr uint64_t Base=0x0ae00000;
constexpr size_t Bytes=0x84000;
constexpr uint32_t Interface=0x36000,Control=0x16000;
constexpr uint32_t Pipes[]={0x5000,0x7000,0x9000,0xb000,0x25000,0x27000,0x29000,0x2b000,0x2d000,0x2f000};
constexpr uint32_t Config[]={0x04,0x6c,0xa8,0x284,0x288,0x28c,0x294,0x29c,0x2b4};
constexpr uint32_t Counts[]={0xac,0xa4,0x298,0x2b0};
struct Snapshot {
    uint32_t version[2],control[4],pipes[10][4],config[9],counts[5][4];
    uint64_t timeUs[5];
};
using Read=uint32_t (*)(void *,uint32_t);
static inline void readConfiguration(Snapshot &s,void *ctx,Read read) {
    s.version[0]=read(ctx,0);s.version[1]=read(ctx,0x1000);
    constexpr uint32_t ctl[]={0x14,0x18,0xf4,0xfc},pipe[]={0,0x14,0x24,0x30};
    for(unsigned i=0;i<4;++i)s.control[i]=read(ctx,Control+ctl[i]);
    for(unsigned i=0;i<10;++i)for(unsigned j=0;j<4;++j)s.pipes[i][j]=read(ctx,Pipes[i]+pipe[j]);
    for(unsigned i=0;i<9;++i)s.config[i]=read(ctx,Interface+Config[i]);
}
static inline bool readCounts(Snapshot &s,unsigned sample,void *ctx,Read read,uint64_t nowUs) {
    if(sample>=5)return false;
    s.timeUs[sample]=nowUs;
    for(unsigned i=0;i<4;++i)s.counts[sample][i]=read(ctx,Interface+Counts[i]);
    return true;
}
// Called from recovery logging: cached RAM only; no register or pixel reads.
static inline unsigned format(const Snapshot &s,unsigned state,char *out,unsigned capacity) {
    if(!out || !capacity)return 0;
    unsigned used=0;out[0]=0;
    auto append=[&](const char *pattern,auto... values){
        if(used>=capacity-1)return;
        int n=snprintf(out+used,capacity-used,pattern,values...);
        if(n>0 && (unsigned)n<capacity-used)used+=(unsigned)n;else out[used]=0;
    };
    append("HOUJI PANEL PROBE: state=%u; read-only DSI0 counters, no refresh or scanout writes\n",state);
    if(state!=3)return used;
    append("HOUJI PANEL CONFIG: mdss=%x mdp=%x ctl=%x/%x/%x/%x intf=%x timing=%x count-enable=%x tear=%x sync=%x height=%x init=%x threshold=%x autorefresh=%x\n",
        s.version[0],s.version[1],s.control[0],s.control[1],s.control[2],s.control[3],
        s.config[0],s.config[1],s.config[2],s.config[3],s.config[4],s.config[5],s.config[6],s.config[7],s.config[8]);
    for(unsigned i=0;i<5;++i)
        append("HOUJI PANEL COUNT: sample=%u up-us=%llu frame=%u mdp-frame=%u read-frame=%u read-line=%u write-line=%u; hardware counters, not rendered FPS\n",
            i,(unsigned long long)s.timeUs[i],s.counts[i][0],s.counts[i][1],s.counts[i][2]>>16,s.counts[i][2]&0xffff,s.counts[i][3]);
    for(unsigned i=0;i<10;++i)if(s.pipes[i][1])
        append("HOUJI PANEL PIPE: offset=%x size=%x address=%x stride=%x format=%x; inherited register state\n",
            Pipes[i],s.pipes[i][0],s.pipes[i][1],s.pipes[i][2],s.pipes[i][3]);
    return used;
}
}
#endif
