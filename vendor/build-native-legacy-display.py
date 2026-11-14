"""Build the 20H392 Legacy backend: 338-slot header, original bindings, driver,
and the late archive the kernel force-loads. No sheng kit is required.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/native-legacy-display'
OUT.mkdir(parents=True, exist_ok=True)
AUDIT = ROOT / 'build/display-analysis/mobile-graphics-legacy-abi.json'
DRIVER = ROOT / 'drivers/NativeMobileDisplay/NativeHoujiLegacyDisplay.cpp'
NAME_SLOT = {'free': 14, 'init': 21, 'setProperties': 44, 'probe': 85, 'start': 86,
             'stop': 87, 'getWorkLoop': 111, 'newUserClient': 141, 'setPowerState': 155,
             'getDisplayDimensions': 246, 'startHardware': 274, 'kickSwapQueue': 276,
             'completeCurrentSwap': 281, 'validateSwap': 282, 'prepareSwap': 283,
             'getRefreshAttributes': 287}
SPECIAL = {
    '__ZTV25IOMobileFramebufferLegacy': ('vtable', -16),
    '__ZN25IOMobileFramebufferLegacyC2EPK11OSMetaClass': ('ctor', 0),
    '__ZN25IOMobileFramebufferLegacyD2Ev': ('dtor', 0),
    '__ZN25IOMobileFramebufferLegacy10gMetaClassE': ('metaclass', 0),
}


def run(cmd, **kw):
    return subprocess.check_output([str(x) for x in cmd], timeout=180, **kw)


def require(value, why):
    if not value:
        raise SystemExit(why)


audit = json.loads(AUDIT.read_text())
require(audit['virtual_entries'] == 338 and audit['legacy_instance_bytes'] == 0x1660,
        'audit is not the 338-slot 20H392 profile')
methods = {m['slot']: int(m['address'], 16) for m in audit['methods']}
pure = audit['abstract_slots']
vptr = int(audit['legacy_vptr'], 16)
lifecycle = audit['lifecycle']

# ---- 338-slot ABI header -------------------------------------------------
named = {246: 'virtual void getDisplayDimensions(uint32_t *, uint32_t *);',
         274: 'virtual bool startHardware();',
         276: 'virtual void kickSwapQueue();',
         281: 'virtual void completeCurrentSwap();',
         282: 'virtual bool validateSwap(const void *);',
         283: 'virtual bool prepareSwap(const void *);',
         287: 'virtual bool getRefreshAttributes(uint64_t *, bool);'}
header = '''#pragma once
#include <IOKit/IOService.h>
class IOMobileFramebufferLegacy : public IOService {
    OSDeclareAbstractStructors(IOMobileFramebufferLegacy)
    unsigned char originalPrivate[0x1660 - sizeof(IOService)];
public:
    void free() override;
    bool init(OSDictionary *properties = nullptr) override;
    IOReturn setProperties(OSObject *) override;
    IOService *probe(IOService *, SInt32 *) override;
    bool start(IOService *) override;
    void stop(IOService *) override;
    IOWorkLoop *getWorkLoop() const override;
    IOReturn newUserClient(task_t, void *, UInt32, IOUserClient **) override;
    IOReturn setPowerState(unsigned long, IOService *) override;
'''
for slot in range(168, 338):
    if slot in named:
        header += '    ' + named[slot] + '\n'
    elif slot in pure:
        header += '    virtual void opaque%d() = 0;\n' % slot
    else:
        header += '    virtual void opaque%d();\n' % slot
header += '};\nstatic_assert(sizeof(IOMobileFramebufferLegacy) == 0x1660, "20H392 extent");\n'
(OUT / 'OriginalHoujiLegacyABI.h').write_text(header)

# ---- compile the driver against the real source-kernel recipe ------------
record = json.loads((ROOT / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/'
                     'IOPlatformExpert.cpo.json').read_text().strip().rstrip(','))


def recipe(source, destination, extra):
    cmd = []
    args = record['arguments']
    i = 0
    while i < len(args):
        v = args[i]
        if v == record['file']:
            cmd.append(str(source))
        elif v == '-o':
            cmd += ['-o', str(destination)]
            i += 1
        elif v == '-Xclang' and args[i + 1].startswith('-W'):
            i += 1
        elif not v.startswith('-W'):
            cmd.append(v)
        i += 1
    cmd += ['-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
            '-Wno-c99-designator', '-Wno-reorder-init-list',
            '-Wno-deprecated-enum-enum-conversion', '-Wno-unnecessary-virtual-specifier',
            '-Wno-deprecated-declarations', '-I', str(ROOT / '.cache/xnu-work/osfmk'),
            '-I', str(OUT)] + extra
    return cmd


driver_obj = OUT / 'NativeHoujiLegacyDisplay.o'
result = subprocess.run(recipe(DRIVER, driver_obj, []), cwd=record['directory'],
                        capture_output=True, text=True)
(OUT / 'driver-compile.log').write_text(result.stdout + result.stderr)
require(result.returncode == 0, (result.stdout + result.stderr)[-4000:])

# ---- map every undefined original symbol to its original address ---------
def nm_undefined(obj):
    for tool in (['llvm-nm', '-u'], ['xcrun', 'llvm-nm', '-u'], ['nm', '-u']):
        r = subprocess.run([str(x) for x in tool + [str(obj)]], capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout
    raise SystemExit('no nm tool could read the driver object')


def method_name(sym):
    token = '25IOMobileFramebufferLegacy'
    at = sym.find(token)
    if at < 0:
        return None
    i = at + len(token)
    if i < len(sym) and sym[i].isdigit():
        n = 0
        while i < len(sym) and sym[i].isdigit():
            n = n * 10 + int(sym[i])
            i += 1
        return sym[i:i + n]
    return None


undefined = sorted({ln.split()[-1] for ln in nm_undefined(driver_obj).splitlines()
                    if 'IOMobileFramebufferLegacy' in ln})

bindings = {}
unmapped = []
for sym in undefined:
    dem = method_name(sym)
    if sym in SPECIAL:
        kind, delta = SPECIAL[sym]
        base = {'vtable': vptr, 'ctor': int(lifecycle['protected_constructor'], 16),
                'dtor': int(lifecycle['protected_destructor'], 16),
                'metaclass': int(lifecycle['metaclass'], 16)}[kind]
        bindings[sym] = base + delta
        continue
    m = re.search(r'opaque(\d+)', sym)
    if m:
        bindings[sym] = methods[int(m.group(1))]
        continue
    slot = NAME_SLOT.get(dem) if dem else None
    if slot is None:
        unmapped.append((sym, dem))
    else:
        bindings[sym] = methods[slot]
require(not unmapped, 'unmapped original symbols: ' + repr(unmapped[:6]))

asm = OUT / 'original-bindings.S'
asm.write_text(''.join('.globl %s\n.set %s, %#x\n' % (n, n, a) for n, a in sorted(bindings.items())))
bindings_obj = OUT / 'original-bindings.o'
result = subprocess.run(['xcrun', 'clang', '-target', 'arm64-apple-ios16.0', '-c',
                         str(asm), '-o', str(bindings_obj)], capture_output=True, text=True)
require(result.returncode == 0, result.stderr[-2000:])

archive = OUT / 'libNativeLegacyDisplay.late.a'
archive.unlink(missing_ok=True)
run(['xcrun', 'ar', 'rcs', archive, driver_obj, bindings_obj])


def sha(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


sources = [DRIVER, OUT / 'OriginalHoujiLegacyABI.h', asm, AUDIT]
(OUT / 'build-report.json').write_text(json.dumps({
    'archive_sha256': sha(archive),
    'source_sha256': {str(Path(p).resolve().relative_to(ROOT)): sha(p) for p in sources},
    'bound_symbols': len(bindings), 'virtual_entries': 338,
    'runtime_instantiation': False}, indent=2) + '\n')
print('HOUJI-LEGACY build: 338-slot archive with %d original bindings; probe gated off' % len(bindings))
