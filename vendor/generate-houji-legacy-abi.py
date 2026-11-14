import argparse
import importlib.util
import json
from pathlib import Path


def generate(audit_path, kernel, plan, output):
    spec = importlib.util.spec_from_file_location('houji_legacy_audit', audit_path)
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    qualified = audit.inspect(kernel, plan)
    audit.test_queue()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    pure = qualified['abstract_slots']
    methods = {
        246: 'virtual void getDisplayDimensions(uint32_t *, uint32_t *);',
        274: 'virtual bool startHardware();',
        276: 'virtual void kickSwapQueue();',
        281: 'virtual void completeCurrentSwap();',
        282: 'virtual bool validateSwap(const void *);',
        283: 'virtual bool prepareSwap(const void *);',
        287: 'virtual bool getRefreshAttributes(uint64_t *, bool);',
    }
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
        if slot in methods:
            header += '    ' + methods[slot] + '\n'
        elif slot in pure:
            header += '    virtual void opaque%d() = 0;\n' % slot
        else:
            header += '    virtual __attribute__((deprecated("Unqualified ABI; never call"))) void opaque%d();\n' % slot
    header += '};\nstatic_assert(sizeof(IOMobileFramebufferLegacy) == 0x1660, "Original 20H392 extent");\n'
    (output / 'OriginalHoujiLegacyABI.h').write_text(header)
    probe = '''#include "OriginalHoujiLegacyABI.h"
class HoujiLegacyABIProbe : public IOMobileFramebufferLegacy {
    OSDeclareDefaultStructors(HoujiLegacyABIProbe)
public:
'''
    for slot in pure:
        probe += '    void opaque%d() override { __builtin_trap(); }\n' % slot
    probe += '};\nOSDefineMetaClassAndStructors(HoujiLegacyABIProbe, IOMobileFramebufferLegacy)\n'
    (output / 'HoujiLegacyABIProbe.cpp').write_text(probe)
    qualified['probe_only'] = True
    qualified['runtime_registration_emitted'] = False
    (output / 'abi-audit.json').write_text(json.dumps(qualified, indent=2) + '\n')
    print('Generated 338-slot compile-only ABI probe; not a runtime backend')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('audit')
    parser.add_argument('kernel')
    parser.add_argument('plan')
    parser.add_argument('output')
    args = parser.parse_args()
    generate(args.audit, args.kernel, args.plan, args.output)
