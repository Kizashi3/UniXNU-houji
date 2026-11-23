#!/usr/bin/env python3
"""Compile the actual frontend asynchronous wrappers against a gated compiler."""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / 'graphics/metal/AdrenoMetal'
text = (FRONTEND / 'NativeBridgeMetalFrontend.mm').read_text()
methods = [match[0] for match in re.finditer(r'^- \(void\)new(?:Function|RenderPipelineState|ComputePipelineState)[\s\S]+?^}', text, re.M)
           if 'completionHandler:' in match[0]]
assert len(methods) == 7, 'Every supported async creation overload must be checked'
source = (ROOT / 'checks/metal-async.mm').read_text()
source = source.replace('/* ACTUAL_METHODS */', '\n'.join(methods))
source = source.replace('/* ACTUAL_DECLARATIONS */', '\n'.join(m.split('{', 1)[0] + ';' for m in methods))
with tempfile.TemporaryDirectory(prefix='houji-metal-async-') as directory:
    temporary = Path(directory)
    unit, binary = temporary / 'check.mm', temporary / 'check'
    unit.write_text(source)
    subprocess.run(['xcrun', 'clang++', '-std=c++17', '-fobjc-arc', '-fblocks',
                    '-Wall', '-Wextra', '-Werror', '-Wno-deprecated-declarations',
                    '-fsanitize=address,undefined', '-I', str(FRONTEND),
                    '-framework', 'Foundation', '-framework', 'Metal', str(unit), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=20)
