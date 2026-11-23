#!/usr/bin/env python3
"""Keep the actual Rust and Objective-C++ packed constant ABIs in agreement."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1] / 'graphics/metal/AdrenoMetal'


def function(path, start):
    text = path.read_text()
    at = text.index(start)
    return text[at:text.index('\n}\n', at) + 3]


with tempfile.TemporaryDirectory(prefix='houji-constants-') as directory:
    tmp = Path(directory)
    cpp = '#include <cstdint>\n#include <cstdio>\n'
    cpp += function(ROOT / 'NativeBridgeMetalFrontend.mm', 'static uint64_t constantBytes(')
    cpp += '\nint main(){for(unsigned i=0;i<129;i++)printf("%llu\\n",(unsigned long long)constantBytes(i));}\n'
    rust = function(ROOT / 'bridge/NativeMetalObjects.rs', 'fn constant_bytes(')
    rust += '\nfn main(){for i in 0..129 {println!("{}",constant_bytes(i));}}\n'
    results = []
    for extension, unit, command in [
        ('cpp', cpp, ['clang++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined']),
        ('rs', rust, ['rustc', '--edition=2021', '-Dwarnings']),
    ]:
        source, binary = tmp / ('constants.' + extension), tmp / extension
        source.write_text(unit)
        subprocess.run([*command, str(source), '-o', str(binary)], check=True)
        results.append(list(map(int, subprocess.check_output([str(binary)], text=True).split())))
    assert results[0] == results[1], 'Frontend and bridge disagree on packed constant lengths'
    expected = [0] * 129
    for start, scalar in [(3, 4), (16, 2), (29, 4), (33, 4), (37, 2), (41, 2),
                          (45, 1), (49, 1), (53, 1), (81, 8), (85, 8), (121, 2)]:
        expected[start:start + 4] = [scalar * lanes for lanes in range(1, 5)]
    assert results[0] == expected, 'Function constant vectors must be packed, including three lanes'
    # Both halves compile independently, so the final linker cannot detect a
    # descriptor layout disagreement. Compare the actual definitions here.
    fields = ['function', 'max_threads', 'multiple_of_execution_width', 'indirect',
              'max_call_stack_depth', 'adding_binary_functions', 'mutability',
              'linked', 'linked_count', 'private_linked', 'private_linked_count']
    cpp = '#include <cstdio>\n#include <cstddef>\n#include "' + str(ROOT / 'bridge/NativeMetalObjects.h') + '"\n'
    cpp += 'int main(){printf("%zu\\n",sizeof(NmbComputePipelineDescriptor));'
    cpp += ''.join('printf("%zu\\n",offsetof(NmbComputePipelineDescriptor,' + f + '));' for f in fields) + '}\n'
    rust = '#[repr(C)] pub struct NmbFunction(u8);\n#[repr(C)]\n'
    rust += function(ROOT / 'bridge/NativeMetalObjects.rs', 'pub struct NmbComputePipelineDescriptor {')
    rust += 'fn main(){println!("{}",std::mem::size_of::<NmbComputePipelineDescriptor>());'
    rust += ''.join('println!("{}",std::mem::offset_of!(NmbComputePipelineDescriptor,' + f + '));' for f in fields) + '}\n'
    layouts = []
    for extension, unit, compiler in [('cpp', cpp, 'clang++'), ('rs', rust, 'rustc')]:
        source, binary = tmp / ('layout.' + extension), tmp / ('layout-' + extension)
        source.write_text(unit)
        subprocess.run([compiler, str(source), '-o', str(binary)], check=True)
        layouts.append(subprocess.check_output([str(binary)], text=True))
    assert layouts[0] == layouts[1], 'Compute descriptor ABI differs across C++/Rust'
print('PASS: actual frontend/bridge agree on packed constants and linked-function descriptor size/offsets')
