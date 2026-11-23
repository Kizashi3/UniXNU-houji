#!/usr/bin/env python3
"""Run the real CoreBrightness parser against scalar and parameter dictionaries."""
from pathlib import Path
import json
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
text = (root / 'kernel/overlay/iokit/Kernel/arm/HoujiBacklight.inc').read_text()
at = text.index('    static OSNumber *numberValue(')
methods = text[at:text.index('    bool start(', at)]
unit = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <map>
#include <string>
struct OSObject {virtual ~OSObject()=default;};
struct OSNumber : OSObject {
 uint64_t value;explicit OSNumber(uint64_t v):value(v){}
 uint64_t unsigned64BitValue(){return value;}
 uint32_t unsigned32BitValue(){return (uint32_t)value;}
};
struct OSDictionary : OSObject {
 std::map<std::string,OSObject *> entries;
 unsigned getCount(){return entries.size();}
 OSObject *getObject(const char *key){auto i=entries.find(key);return i==entries.end()?nullptr:i->second;}
};
#define OSDynamicCast(type,object) dynamic_cast<type *>(object)
namespace HoujiBacklightTrace {
enum Field {RequestFields,BrightnessKind,FadeKind,RawBrightnessLo,RawBrightnessHi,RawFadeLo,RawFadeHi,Count};
static unsigned data[Count];static void set(Field field,unsigned value){data[field]=value;}
}
'''
unit += '#include ' + json.dumps(str(root / 'kernel/overlay/iokit/Kernel/arm/HoujiBacklightProtocol.h')) + '\n'
unit += 'struct Parser {\n' + methods + '};\n'
unit += r'''
int main() {
 unsigned level=77;uint64_t duration=88;
 OSNumber half(32768),fade(16384),metadata(123),maximum(65536),tooHigh(65537);
 OSDictionary d;d.entries={{"brightness",&half},{"FadePeriod",&fade}};
 assert(Parser::values(&d,&level,&duration) && level==32768 && duration==250000);
 // Extra CoreBrightness metadata must not reject the brightness request.
 d.entries["DisplayBrightness"]=&metadata;
 assert(Parser::values(&d,&level,&duration) && level==32768);
 // The parameter dictionary form uses its numeric value; no other key acts.
 OSDictionary wrapped;wrapped.entries={{"value",&maximum},{"min",&metadata}};
 d.entries["brightness"]=&wrapped;
 assert(Parser::values(&d,&level,&duration) && level==65536);
 assert(HoujiBacklightTrace::data[HoujiBacklightTrace::BrightnessKind]==2);
 d.entries.erase("FadePeriod");assert(Parser::values(&d,&level,&duration) && duration==0);
 d.entries["brightness"]=&tooHigh;level=19;duration=29;
 assert(!Parser::values(&d,&level,&duration) && level==19 && duration==29);
 d.entries["brightness"]=&half;OSObject bad;d.entries["FadePeriod"]=&bad;
 assert(!Parser::values(&d,&level,&duration));
 OSNumber hugeFade(11*65536);d.entries["FadePeriod"]=&hugeFade;
 assert(!Parser::values(&d,&level,&duration));
 d.entries.erase("brightness");assert(!Parser::values(&d,&level,&duration));
 assert(!Parser::values(nullptr,&level,&duration));
 puts("PASS: actual brightness parser accepts scalar/value dictionaries with inert metadata; rejects malformed/out-of-range controls; no panel");
}
'''
with tempfile.TemporaryDirectory(prefix='houji-backlight-') as temporary:
    source = Path(temporary) / 'properties.cpp'
    binary = Path(temporary) / 'properties'
    source.write_text(unit)
    subprocess.run(['clang++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=10)
