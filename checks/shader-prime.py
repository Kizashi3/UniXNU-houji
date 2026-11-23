#!/usr/bin/env python3
"""Execute the active primer's discovery and quiet wait with virtual time."""
from pathlib import Path
import json
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'graphics/metal/AdrenoMetal/PrimeShaders.h'
text = SOURCE.read_text()


def function(start, end):
    at = text.index(start)
    return text[at:text.index('\n}\n', at) + 3]


with tempfile.TemporaryDirectory(prefix='houji-prime-') as temporary:
    tmp = Path(temporary)
    first, second = tmp / 'root-a', tmp / 'root-b'
    first.mkdir()
    second.mkdir()
    a, b = first / 'a.metallib', second / 'b.metallib'
    a.write_text('host fixture')
    b.write_text('host fixture')
    listing = tmp / 'primelist'
    listing.write_text(str(a) + '\n')
    unit = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cerrno>
#include <set>
#include <string>
#include <vector>
#include <algorithm>
#include <fts.h>
#include <sys/stat.h>
#if !defined(__APPLE__)
// Match Darwin's stat field spelling in the extracted production functions.
#define st_mtimespec st_mtim
#endif
static uint64_t clockMs=0,busyUntil=0,swipeAgainAt=0,swipeAgainUntil=0;
static bool pendingOnly=false;
static uint32_t native_prime_rate=0,native_prime_compiling=0;
static unsigned walks=0;
static uint64_t nowMs(){return clockMs;}
static bool active(){return clockMs<busyUntil || (clockMs>=swipeAgainAt && clockMs<swipeAgainUntil);}
static unsigned native_bridge_metal_recent_commits(uint64_t){return active()&&!pendingOnly?16:0;}
static unsigned native_bridge_metal_pending_commits(){return active()&&pendingOnly?1:0;}
static int virtualSleep(unsigned us){clockMs+=us/1000;assert(clockMs<60000);return 0;}
static FTS *countedOpen(char *const *paths,int flags,int(*compare)(const FTSENT **,const FTSENT **)){
 ++walks;return fts_open(paths,flags,compare);
}
#define usleep virtualSleep
#define fts_open countedOpen
static std::set<std::string> embedded;
static std::set<std::string> embeddedLines(){return embedded;}
'''
    unit += 'static const char *const kRoots[]={' + ','.join(json.dumps(str(p)) for p in (first, second)) + '};\n'
    unit += function('static std::set<std::string> readLines(', '// The same list carried')
    unit += function('static void appendLine(', '')
    unit += function('static std::string libraryKey(', '')
    unit += function('static void checkpointFunction(', '')
    unit += function('static uint64_t waitForQuiet() {', '// The libraries:')
    unit += function('static void prioritize(', '// The libraries:')
    unit += function('static std::vector<std::string> libraries(', '// One library:')
    unit += function('static bool memoryPressure(', '// One library:')
    unit += '\nint main(){\nstd::string note;\n'
    unit += f'const std::string list={json.dumps(str(listing))},a={json.dumps(str(a))},b={json.dumps(str(b))};\n'
    unit += r'''
 auto found=libraries(list,note);assert(found.size()==1 && found[0]==a && walks==0);
 embedded.insert(a);found=libraries("",note);assert(found.size()==1 && walks==0);
 embedded.clear();found=libraries("",note);
 assert(found.size()==2 && found[0]==a && found[1]==b && walks==2);
 assert(waitForQuiet()==0);
 std::vector<std::string> order={"/System/Camera/a.metallib","/System/QuartzCore.framework/default.metallib","/System/RenderBox.framework/default.metallib","/Applications/b.metallib"};
 prioritize(order);assert(order[0].find("QuartzCore")!=std::string::npos && order[1].find("RenderBox")!=std::string::npos);
 assert(order[2].find("Camera")!=std::string::npos && order[3].find("Applications")!=std::string::npos);
 assert(memoryPressure("compute pipeline: OutOfMemory(Device)"));
 assert(memoryPressure("VK_ERROR_OUT_OF_HOST_MEMORY"));
 assert(!memoryPressure("NeedsInput(FunctionConstant)"));
 struct stat identity={};identity.st_size=123;identity.st_mtimespec.tv_sec=456;
 const auto key=libraryKey(a,identity,"build-a");
 assert(key!=libraryKey(b,identity,"build-a"));
 assert(key!=libraryKey(a,identity,"build-b"));
 ++identity.st_size;assert(key!=libraryKey(a,identity,"build-a"));--identity.st_size;
 ++identity.st_mtimespec.tv_nsec;assert(key!=libraryKey(a,identity,"build-a"));
 const auto functions=list+"-functions";
 checkpointFunction(functions,key+"\tkernel",false,false);
 checkpointFunction(functions,key+"\tkernel",true,true);
 assert(readLines(functions).empty()); // failed / pressure-interrupted work must retry
 checkpointFunction(functions,key+"\tkernel",true,false);
 assert(readLines(functions)==std::set<std::string>{key+"\tkernel"});
 // Long continuous animation may not force a pipeline every ten seconds.
 clockMs=0;busyUntil=20000;assert(waitForQuiet()>=22000);
 // A slow frame with few commits still blocks while a command is pending.
 clockMs=0;pendingOnly=true;assert(waitForQuiet()>=22000);
 // A second swipe cancels the first quiet interval.
 clockMs=0;pendingOnly=false;busyUntil=1000;swipeAgainAt=2000;swipeAgainUntil=3000;
 assert(waitForQuiet()>=5000);
 puts("PASS: actual shader discovery skips scans with a usable list, scans all fallback roots, and defers during animation/pending commands");
}
'''
    source = tmp / 'prime.cpp'
    source.write_text(unit)
    binary = tmp / 'prime'
    subprocess.run(['clang++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=10)
