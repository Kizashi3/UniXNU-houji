"""Build the 20H392 Legacy backend: 338-slot header, original bindings, driver,
and the late archive the kernel force-loads. No sheng kit is required.
"""
import json
import os
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
         287: 'virtual bool getRefreshAttributes(uint64_t *, bool);',
         321: 'virtual IOReturn collectCompletionReports(uint32_t, void *, uint32_t *, uint32_t) = 0;'}
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
        try:
            r = subprocess.run([str(x) for x in tool + [str(obj)]],
                               capture_output=True, text=True)
        except OSError:
            continue
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
bindings['_houji_legacy_vsync_notify'] = int(audit['externals']['vsync_notify'], 16)
for getter in ('descriptor', 'width', 'height', 'stride', 'offset', 'allocation', 'format', 'planes'):
    bindings['_houji_legacy_surface_' + getter] = int(audit['iosurface']['getters'][getter]['address'], 16)

asm = OUT / 'original-bindings.S'
asm.write_text(''.join('.globl %s\n.set %s, %#x\n' % (n, n, a) for n, a in sorted(bindings.items())))
bindings_obj = OUT / 'original-bindings.o'
result = subprocess.run(['xcrun', 'clang', '-target', 'arm64-apple-ios16.0', '-c',
                         str(asm), '-o', str(bindings_obj)], capture_output=True, text=True)
require(result.returncode == 0, result.stderr[-2000:])

llvm = Path(run(['brew', '--prefix', 'llvm'], text=True).strip()) / 'bin'
initializer = '__GLOBAL__sub_I_NativeHoujiLegacyDisplay.cpp'
late_obj = OUT / 'NativeHoujiLegacyDisplay.late.o'
run([llvm / 'llvm-objcopy', '--remove-section=__DATA,__mod_init_func',
     '--remove-section=__DATA,__mod_term_func', '--globalize-symbol=' + initializer,
     driver_obj, late_obj])
print(run(['python3', ROOT / 'scripts/validate-houji-late-object.py', driver_obj, late_obj],
          text=True), end='')
symbols = run([llvm / 'llvm-nm', str(late_obj)], text=True)
require(any(line.split()[-1] == initializer and line.split()[-2].isupper()
            for line in symbols.splitlines() if len(line.split()) >= 2),
        'Deferred initializer is not global')
sections = run([llvm / 'llvm-objdump', '--section-headers', str(late_obj)], text=True)
require('__mod_init_func' not in sections and '__mod_term_func' not in sections,
        'Late object still has automatic initializer/finalizer sections')
late_asm = OUT / 'late-registration.S'
late_asm.write_text('.text\n.globl _houji_legacy_initialize_class\n'
                    '.p2align 2\n_houji_legacy_initialize_class:\n'
                    'b ' + initializer + '\n')
late_registration = OUT / 'late-registration.o'
run(['xcrun', 'clang', '-target', 'arm64-apple-ios16.0', '-c',
     late_asm, '-o', late_registration])
archive = OUT / 'libNativeLegacyDisplay.late.a'
archive.unlink(missing_ok=True)
run(['xcrun', 'ar', 'rcs', archive, late_obj, bindings_obj, late_registration])


def sha(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


for test in ('houji-legacy-queue-test', 'houji-legacy-pixels-test', 'houji-legacy-request-test'):
    test_source = DRIVER.parent / (test + '.cpp')
    test_binary = OUT / test
    run(['xcrun', 'clang++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
         '-fsanitize=address,undefined', test_source, '-o', test_binary])
    run([test_binary])
    print('PASS: ' + test)
sources = [DRIVER, OUT / 'OriginalHoujiLegacyABI.h', asm, late_asm, AUDIT,
           ROOT / 'scripts/validate-houji-late-object.py',
           DRIVER.parent / 'HoujiLegacyQueue.h', DRIVER.parent / 'HoujiLegacyPixels.h',
           DRIVER.parent / 'houji-legacy-queue-test.cpp',
           DRIVER.parent / 'houji-legacy-pixels-test.cpp',
           DRIVER.parent / 'HoujiLegacyRequest.h',
           DRIVER.parent / 'houji-legacy-request-test.cpp']
(OUT / 'build-report.json').write_text(json.dumps({
    'archive_sha256': sha(archive),
    'source_sha256': {os.path.relpath(str(p), str(ROOT)): sha(p) for p in sources},
    'bound_symbols': len(bindings), 'virtual_entries': 338,
    'automatic_class_registration': False,
    'runtime_instantiation': 'boot-arg-gated',
    'runtime_publish_boot_arg': 'houji-legacy-publish=1'}, indent=2) + '\n')
print('HOUJI-LEGACY build: 338-slot archive with %d original bindings; automatic registration removed; runtime activation gated' % len(bindings))
