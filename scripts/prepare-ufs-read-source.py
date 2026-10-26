"""Extract the pinned NativeUfs read transport, without storage-class bindings."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--upstream',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
a=p.parse_args()
revision=subprocess.check_output(['git','-C',str(a.upstream),'rev-parse','HEAD'],text=True).strip()
if revision!='af785c1777161a62931425c2faaa536ce0bebd5b':raise SystemExit('Unexpected NativeUfs revision')
s=(a.upstream/'NativeUfs.cpp').read_text()
def section(start,end):
    if s.count(start)!=1 or s.count(end)!=1:raise SystemExit('Upstream section changed')
    return s[s.index(start):s.index(end)]
prefix=s[:s.index('extern "C" {\n// Optional passive observer')]
prefix=('// SPDX-License-Identifier: BSD-2-Clause-Patent\n'
        '// Generated pinned NativeUfs read transport for giulia-ufs-probe=2.\n'
        '// No IOBlockStorageDevice bindings or persistent write helpers.\n'+prefix[prefix.index('#include'):])
prefix=prefix.replace('#include <IOKit/storage/IOBlockStorageDevice.h>\n','')
prefix=prefix.replace('#include "SmmuTakeover.h"','#include "GiuliaSmmuTakeover.h"')
access=section('static uint32_t read32','static bool contains')
mapping=section('static uintptr_t mapPhys','void NativeUfs::inspect (void)')
smmu=section('static void smmuBypassStream','void NativeUfs::adoptAndRead')
smmu=smmu.replace('uint64_t dma, uint64_t bytes)','uint64_t dma, uint64_t bytes, uintptr_t host)')
smmu=smmu.replace('  uintptr_t smmu = mapPhys',
    '  if ((read32(host, 0x60) & 1) || read32(host, 0x58) || read32(host, 0x78))\n'
    '    panic("GIULIA UFS: queue not quiescent before SMMU takeover");\n  uintptr_t smmu = mapPhys')
smmu=smmu.replace('UfsSmmuPlan plan = planUfsSmmu', 'GiuliaSmmuPlan selection = planGiuliaSmmu')
smmu=smmu.replace('  gRootDiagnostic.smmuId1 =', '  const UfsSmmuPlan &plan = selection.target;\n  gRootDiagnostic.smmuId1 =',1)
smmu=smmu.replace('configureUfsSmmu (plan, stream,','configureGiuliaSmmu (selection, stream, true,')
core=section('namespace {\n#include "RootTransportLayout.h"','namespace {\nstatic uint32_t be32w')
core=core.replace('gHost.phys, kDmaBytes);','gHost.phys, kDmaBytes, gHost.hc);')
tail='''
namespace {
#include "RootLayout.h"
}
static void rootDiagnosticFailure(const char *why) {
  char text[2048];
  formatUfsRootDiagnostics(text, sizeof(text), gRootDiagnostic, why);
  panic("GIULIA UFS READ FAILED\\n%s", text);
}
extern "C" void giulia_ufs_read_root(void) {
  gRootDiagnosticEnabled = true;
  const char *why = "unknown";
  if (!hostBringUp(&why)) rootDiagnosticFailure(why);
  RootLayout layout;
  if (!findRootLayout(&layout, &why)) rootDiagnosticFailure(why);
  gRootDiagnostic.manifest = layout.manifestStatus;
  if (layout.manifestStatus || layout.windows != 2 ||
      layout.userdataFirst != 3920350 || layout.userdataLast != 61321210)
    rootDiagnosticFailure("unexpected PKG110 GPT or SHNGROOT manifest");
  uint32_t signatures[2] = {};
  for (unsigned i=0; i<2; ++i) {
    uint64_t absolute = layout.userdataFirst * 4096 + layout.window[i].offset;
    if (hostRead4k(0, absolute / 4096, 1, gScratch) != kIOReturnSuccess)
      rootDiagnosticFailure("system window header read");
    bool os = !strcmp(layout.window[i].name, "OS");
    bool system = !strcmp(layout.window[i].name, "SystemOS");
    signatures[i] = le32(gScratch + (os ? 512 : 32));
    if ((!os && !system) || (os && memcmp(gScratch+512,"EFI PART",8)) ||
        (system && memcmp(gScratch+32,"NXSB",4)))
      rootDiagnosticFailure("system window signature mismatch");
  }
  panic("GIULIA UFS READ OK\\nGPT CRC and SHNGROOT hash valid\\n"
        "userdata=%llx-%llx windows=%u\\n%s sig=%08x bytes=%llx\\n%s sig=%08x bytes=%llx\\n"
        "DMA=%llx bank route=%x\\nRoot media not yet published or mounted",
        layout.userdataFirst, layout.userdataLast, layout.windows,
        layout.window[0].name, signatures[0], layout.window[0].size,
        layout.window[1].name, signatures[1], layout.window[1].size,
        gHost.phys, gRootDiagnostic.s2cr);
}
'''
a.out.mkdir(parents=True,exist_ok=True)
(a.out/'GiuliaUfsRead.cpp').write_text(prefix+access+mapping+smmu+core+tail)
hashes={}
for name in ('LICENSE','GccUfs.h','RootDiagnostics.h','TransferPoll.h','SmmuTakeover.h',
             'RootTransportLayout.h','RootQueue.h','RootCommands.h','RootLayout.h'):
    data=(a.upstream/name).read_bytes();hashes[name]=hashlib.sha256(data).hexdigest()
    if name=='RootCommands.h':
        data=data.decode().split('// ---- Persistent store and log windows ')[0].encode()
    (a.out/name).write_bytes(data)
(a.out/'upstream.json').write_text(json.dumps({'revision':revision,
    'source_sha256':hashlib.sha256((a.upstream/'NativeUfs.cpp').read_bytes()).hexdigest(),
    'headers_sha256':hashes,'scope':'read transport only; no IOBlockStorageDevice or persistent write helpers'},indent=2)+'\n')
