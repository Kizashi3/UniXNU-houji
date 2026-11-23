// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <assert.h>
#include <stdio.h>
#include <vector>
#include <utility>
#include "../kernel/overlay/iokit/Kernel/arm/HoujiThermalPolicy.h"
#include "../kernel/overlay/iokit/Kernel/arm/HoujiBacklightProtocol.h"
struct Dsi {
    uint32_t regs[256]={};std::vector<std::pair<unsigned,uint32_t>> writes;
    static uint32_t read(void *p,unsigned r){assert(r<sizeof(Dsi::regs));return ((Dsi*)p)->regs[r/4];}
    static void write(void *p,unsigned r,uint32_t v){
        auto &d=*(Dsi*)p;d.writes.emplace_back(r,v);
        // Independent model of the controller's documented W1C/enable layout.
        constexpr uint32_t status=(1u<<0)|(1u<<8)|(1u<<10)|(1u<<12)|(1u<<14)|
            (1u<<16)|(1u<<20)|(1u<<24)|(1u<<26)|(1u<<28)|(1u<<30);
        if(r==0x110)d.regs[r/4]=(d.regs[r/4]&status&~v)|(v&~status);
        else if(r==0x1d4){d.regs[r/4]=0;if(v&1)d.regs[0x6c/4]=0;}
        else d.regs[r/4]=v;
    }
    HoujiDsiCommand driver(){regs[1]=5;regs[0x3c/4]=0x84000000;regs[0x390/4]=6;regs[0x4c/4]=128;return {{this,read,write},false,false,0,0,0,0,0};}
};
int main(){
    int t=0;assert(!houjiTsensDecode(950,&t));
    assert(houjiTsensDecode((1<<21)|950,&t) && t==950);
    assert(houjiTsensDecode((1<<21)|0xf9c,&t) && t==-100);
    assert(!houjiTsensDecode((1<<21)|1800,&t));
    assert(!houjiTsensDecode((1<<21)|0x800,&t));
    // A conversion briefly drops VALID. Accept only a later VALID word;
    // permanent loss still expires, and a hot sample still reaches policy.
    uint64_t clock=0;unsigned reads=0;HoujiTsensSample sample={};
    auto now=[&](){return clock;};auto pause=[&](){++clock;};
    assert(houjiTsensRead([&](){return ++reads<3?950u:(1u<<21)|960u;},now,pause,20000,&t,&sample));
    assert(t==960 && sample.reads==3 && clock==2 && !sample.timeout);
    clock=0;t=123;
    assert(!houjiTsensRead([](){return 400u;},now,pause,20000,&t,&sample));
    assert(sample.timeout && clock==20000 && t==123);
    clock=0;
    assert(!houjiTsensRead([](){return (1u<<21)|1800u;},now,pause,20000,&t,&sample));
    assert(!sample.timeout && sample.reads==1 && clock==0 && t==123);
    HoujiThermalPolicy p={};
    assert(houjiThermalChoose(&p,12,true,420,950)==12);
    for(unsigned expected=11;expected;--expected)assert(houjiThermalChoose(&p,12,true,960,950)==expected);
    for(unsigned i=0;i<50;++i)assert(houjiThermalChoose(&p,12,true,910,950)==1);
    for(unsigned i=0;i<9;++i)assert(houjiThermalChoose(&p,12,true,890,950)==1);
    assert(houjiThermalChoose(&p,12,true,890,950)==2);
    assert(houjiThermalChoose(&p,12,false,0,950)==1);
    p={};assert(houjiThermalChoose(&p,12,true,1100,950)==1);
    p={};assert(houjiThermalChoose(&p,12,false,0,950)==1);
    assert(houjiThermalChoose(&p,12,true,400,950)==1); // no full-speed jump after missing sensors
    for(unsigned i=0;i<200;++i)houjiThermalChoose(&p,12,true,400,950);
    assert(p.cap==12);
    unsigned previous=0;
    for(unsigned i=0;i<=65536;++i){unsigned level=houjiBacklightLevel(i);assert(level>=previous && level<=2866);previous=level;}
    assert(houjiBacklightLevel(0)==0 && houjiBacklightLevel(65536)==2866);
    assert(houjiBacklightFade(60000,1000,0,1000)==60000);
    assert(houjiBacklightFade(60000,1000,500,1000)==30500);
    assert(houjiBacklightFade(60000,1000,1000,1000)==1000);
    assert(houjiBacklightFade(0,65536,50,0)==65536);
    Dsi d;auto c=d.driver();
    assert(!c.brightness(4096,0) && d.writes.empty());
    d.regs[2]=2;assert(!c.brightness(100,0) && d.writes.empty());d.regs[2]=0;
    assert(c.brightness(0xb32,100));assert(!c.brightness(25,101));
    std::vector<uint32_t> fifo;for(auto w:d.writes)if(w.first==0x17c)fifo.push_back(w.second);
    assert((fifo==std::vector<uint32_t>{0xc0390003,0xff320b51}));
    assert(c.poll(200)==0);d.regs[0x110/4]=1;assert(c.poll(201)==1);
    assert(d.regs[0x3c/4]==0x84000000 && d.regs[0x390/4]==6 && d.regs[0x4c/4]==128 && d.regs[0x15c/4]==0);
    assert(c.brightness(0,500));size_t count=d.writes.size();
    assert(c.poll(50499)==0 && c.poll(50500)==-1 && c.failed);
    assert(d.writes.size()==count && !c.brightness(100,50600)); // timeout: no unsafe FIFO reuse
    Dsi e;auto bad=e.driver();assert(bad.brightness(25,0));e.regs[0x110/4]=1<<24;
    assert(bad.poll(1)==-1);
    Dsi f;auto readback=f.driver();uint32_t word=0xa0060052;
    f.regs[0x1d4/4]=4u<<16;f.regs[0x6c/4]=0x220b3200;
    assert(readback.readBrightness(0));fifo.clear();
    for(auto w:f.writes)if(w.first==0x17c)fifo.push_back(w.second);
    assert((fifo==std::vector<uint32_t>{word,0}) && f.regs[0x4c/4]==4);
    assert(f.regs[0x1d4/4]==0 && f.regs[0x6c/4]==0);
    auto clear=f.writes.begin(),trigger=f.writes.begin();
    for(auto it=f.writes.begin();it!=f.writes.end();++it){if(it->first==0x1d4 && it->second==1)clear=it;if(it->first==0x90)trigger=it;}
    assert(clear<trigger);
    unsigned level=123;
    assert(!houjiBacklightReadback(0,0x220b3200,&level) && level==123);
    assert(!houjiBacklightReadback(3u<<16,0x220b3200,&level));
    assert(houjiBacklightReadback(4u<<16,0x220b3200,&level) && level==2866);
    assert(houjiBacklightReadback(8u<<16,0x22001900,&level) && level==25);
    assert(!houjiBacklightReadback(4u<<16,0x02111100,&level));
    assert(!houjiBacklightReadback(4u<<16,0x22100000,&level));
    Dsi g;auto irq=g.driver();
    const uint32_t unrelated=(1u<<8)|(1u<<10)|(1u<<12)|(1u<<14)|(1u<<16)|(1u<<20)|(1u<<26)|(1u<<28)|(1u<<30);
    const uint32_t enables=(1u<<1)|(1u<<9)|(1u<<11)|(1u<<13)|(1u<<15)|(1u<<17)|(1u<<21)|(1u<<25)|(1u<<29)|(1u<<31);
    g.regs[0x110/4]=unrelated|enables|1;
    assert(irq.brightness(25,0) && g.regs[0x110/4]==(unrelated|enables));
    g.regs[0x110/4]|=1;assert(irq.poll(1)==1 && g.regs[0x110/4]==(unrelated|enables));
    Dsi h;auto fault=h.driver();h.regs[0x110/4]=1u<<24;
    assert(!fault.readBrightness(0) && h.writes.empty());
    puts("PASS: TSENS decode/loss/hysteresis; brightness/DSI FIFO, fresh readback, W1C ownership, busy/timeout/restore");
}
