#!/usr/bin/env python3
"""Execute the actual IOPlatformExpert UUID method against bounded host fixtures."""
from pathlib import Path
import hashlib,subprocess,tempfile

P=Path(__file__).resolve().parents[1]
source=P/'.cache/ios16-reference/dxb-ios/xnu/iokit/Kernel/IOPlatformExpert.cpp'
text=source.read_text();start=text.index('void\nIOPlatformExpertDevice::generatePlatformUUID( void )');end=text.index('\n/* * * *',start);function=text[start:end]
assert 'houji,platform-uuid' in function
prefix=r'''
#include <CommonCrypto/CommonDigest.h>
#include <uuid/uuid.h>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>
#include <map>
#define ARM64_BOARD_CONFIG_SWEET 1
#define SHA1_CTX CC_SHA1_CTX
#define SHA_DIGEST_LENGTH CC_SHA1_DIGEST_LENGTH
#define SHA1Init CC_SHA1_Init
#define SHA1Update CC_SHA1_Update
#define SHA1Final CC_SHA1_Final
#define OSDynamicCast(T,p) dynamic_cast<T *>(p)
struct OSObject { virtual ~OSObject()=default; };
struct OSData:OSObject {std::vector<uint8_t> bytes; OSData(std::vector<uint8_t> b):bytes(b){} unsigned getLength(){return bytes.size();} const void*getBytesNoCopy(){return bytes.data();}};
struct OSString:OSObject {std::string value; static OSString*withCString(const char*v){auto*p=new OSString;p->value=v;return p;} void release(){delete this;}};
static std::map<std::string,OSObject*> properties;
static bool chosen=true;
struct IORegistryEntry {static IORegistryEntry*fromPath(const char*,const void*){static IORegistryEntry e;return chosen?&e:nullptr;} OSObject*getProperty(const char*k){auto i=properties.find(k);return i==properties.end()?nullptr:i->second;} void release(){}};
static const void*gIODTPlane=nullptr;
static const char*kIOPlatformUUIDKey="IOPlatformUUID";
static bool gIOPlatformUUIDAndSerialDone=false;
static int fallback_logs=0;
static void IOLog(const char*,...){fallback_logs++;}
struct IOPlatformExpertDevice {std::string result;void generatePlatformUUID(); void setProperty(const char*,OSString*v){result=v->value;}};
'''
suffix=r'''
int main(){
 const std::vector<uint8_t> valid={0x10,0x20,0x30,0x40,0x50,0x60,0x5a,0x80,0x91,0x22,0x33,0x44,0x55,0x66,0x77,0x88};
 unsigned cases=0;
 auto run=[&](std::vector<uint8_t> bytes,bool expected){properties.clear();OSData data(bytes);properties["houji,platform-uuid"]=&data;gIOPlatformUUIDAndSerialDone=false;fallback_logs=0;IOPlatformExpertDevice d;d.generatePlatformUUID();assert(!d.result.empty()==expected);assert(gIOPlatformUUIDAndSerialDone==expected);assert(fallback_logs==(expected?1:0));cases++;};
 run(valid,true);
 for(unsigned len=0;len<=32;len++){if(len==16)continue;auto bytes=valid;bytes.resize(len);run(bytes,false);}
 for(unsigned version=0;version<16;version++){auto bytes=valid;bytes[6]=(bytes[6]&15)|(version<<4);run(bytes,version==5);}
 for(unsigned variant=0;variant<4;variant++){auto bytes=valid;bytes[8]=(bytes[8]&63)|(variant<<6);run(bytes,variant==2);}
 properties.clear();gIOPlatformUUIDAndSerialDone=false;IOPlatformExpertDevice absent;absent.generatePlatformUUID();assert(absent.result.empty()&&!gIOPlatformUUIDAndSerialDone);cases++;
 chosen=false;IOPlatformExpertDevice missing;missing.generatePlatformUUID();assert(missing.result.empty());chosen=true;cases++;
 OSData host(valid),ecid({1,2,3,4,5,6,7,8}),chip({9,10,11,12});properties={{"houji,platform-uuid",&host},{"unique-chip-id",&ecid},{"chip-id",&chip}};fallback_logs=0;gIOPlatformUUIDAndSerialDone=false;IOPlatformExpertDevice apple;apple.generatePlatformUUID();assert(apple.result=="__APPLE_EXPECTED__");assert(fallback_logs==0&&gIOPlatformUUIDAndSerialDone);cases++;
 printf("PASS: %u actual UUID method cases; size/version/variant guards and normal Apple precedence\n",cases);
}
'''
namespace=bytes.fromhex('a6dd4ccbb5e84af5acddb6dc6a0542b8');digest=bytearray(hashlib.sha1(namespace+bytes(range(1,13))).digest()[:16]);digest[6]=(digest[6]&15)|0x50;digest[8]=(digest[8]&63)|0x80
import uuid
suffix=suffix.replace('__APPLE_EXPECTED__',str(uuid.UUID(bytes=bytes(digest))).upper())
with tempfile.TemporaryDirectory() as directory:
 d=Path(directory);(d/'check.cpp').write_text(prefix+function+suffix)
 subprocess.run(['xcrun','clang++','-std=c++17','-Wno-deprecated-declarations',str(d/'check.cpp'),'-o',str(d/'check')],check=True)
 subprocess.run([str(d/'check')],check=True)
