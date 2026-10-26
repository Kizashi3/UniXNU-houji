"""Run upstream production root parser/read/publication tests on Linux or macOS."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--upstream',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--root-image',type=Path,required=True)
p.add_argument('--openssl-prefix',type=Path,required=True)
p.add_argument('--gpt',type=Path,help='Read-only captured first six 4K blocks of LUN0')
a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=True)
copy=a.output/'NativeUfs'
shutil.copytree(a.upstream/'drivers/NativeUfs',copy,dirs_exist_ok=True)
# uint64_t is unsigned long on Linux; Apple's typedef is unsigned long long.
# Change only the fixture's initializer spelling, never the production parser.
test=copy/'tests/RootWindowRead.cpp'
text=test.read_text()
if text.count('{0ULL,UINT64_MAX}') != 1:
    raise SystemExit('Unexpected upstream fixture')
test.write_text(text.replace('{0ULL,UINT64_MAX}','{uint64_t(0),UINT64_MAX}'))
subprocess.run([sys.executable,str(copy/'tests/check_root_path_host.py'),
                '--output',str(a.output/'results'),
                '--root-image',str(a.root_image.resolve()),
                '--openssl-prefix',str(a.openssl_prefix)],check=True)
if a.gpt:
    # Use the exact captured GPT, not the generic harness's sheng geometry.
    harness=a.output/'CapturedRoot.cpp'
    harness.write_text('''#define main upstream_fixture_main
#include "NativeUfs/tests/RootLayout.cpp"
#undef main
int main(int argc, char **argv) {
  assert(argc == 3); fixture();
  std::ifstream gpt(argv[1], std::ios::binary);
  gpt.seekg(4096); gpt.read(reinterpret_cast<char *>(header), sizeof(header));
  assert(gpt.gcount() == sizeof(header));
  assert(le64(header+72) == 2);
  gpt.read(reinterpret_cast<char *>(entries), sizeof(entries));
  assert(gpt.gcount() == sizeof(entries));
  std::ifstream image(argv[2], std::ios::binary);
  image.read(reinterpret_cast<char *>(manifest), sizeof(manifest));
  assert(image.gcount() == sizeof(manifest));
  userdata=3920350;
  RootLayout layout; const char *why=nullptr;
  assert(findRootLayout(&layout, &why));
  assert(layout.userdataFirst == 3920350 && layout.userdataLast == 61321210);
  assert(layout.manifestStatus == 0 && layout.windows == 2);
  assert(layout.imageBytes == 9382658048ULL);
  puts("PASS: captured PKG110 GPT CRCs and actual system manifest; no synthetic GPT or device I/O");
}
''')
    binary=a.output/'CapturedRoot'
    subprocess.run(['clang++','-std=c++17','-fsanitize=address,undefined',
                    '-I',str(a.openssl_prefix/'include'),str(harness),
                    '-L',str(a.openssl_prefix/'lib'),'-lcrypto','-o',str(binary)],check=True)
    result=subprocess.run([str(binary),str(a.gpt.resolve()),str(a.root_image.resolve())],
                          check=True,capture_output=True,text=True)
    (a.output/'results/CapturedRoot.log').write_text(result.stdout)
    print(result.stdout,end='')
