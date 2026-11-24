"""Adapt the pinned upstream Vulkan probe to run standalone on Houji."""

import sys
from pathlib import Path


source, output = map(Path, sys.argv[1:])
code = source.read_text()


def replace(before, after=""):
    global code
    if code.count(before) != 1:
        raise ValueError(f"Unexpected upstream probe content near {before[:80]!r}")
    code = code.replace(before, after)


for line in (
    "#include <sys/sysctl.h>",
    "#include <sys/wait.h>",
    "#include <spawn.h>",
    '#define MTLTEST "/usr/libexec/mtltest"',
    "extern char **environ;",
    "static int con = -1;",
):
    replace(line + "\n")
for header in ("tri_vert_spv.h", "tri_frag_spv.h"):
    replace(next(line for line in code.splitlines() if f'"{header}"' in line) + "\n")
replace('#define DRIVER "/usr/lib/libvulkan_freedreno.dylib"\n', "")
replace("write(con, buf,", "write(STDOUT_FILENO, buf,")
replace("main(void)", "main(int argc, char **argv)")
start = code.index('\tcon = open("/dev/console"')
end = code.index("\t/* ---- part 1:")
replace(code[start:end], '''	if (argc != 2 || argv[1][0] != '/') {
		say("Usage: vktest /absolute/path/to/libvulkan_freedreno.dylib");
		return 2;
	}
	const char *driver = argv[1];
	setenv("TU_DARWIN_SERVICE", "IOAcceleratorES", 1);
	setenv("TU_DARWIN_OPEN_TYPE", "0x4147", 1);
	setenv("TU_DEBUG", "sysmem,nocb", 1);
	say("VKTEST: start (IOAcceleratorES)");

''')
replace("dlopen(DRIVER,", "dlopen(driver,")
replace("DRIVER, dlerror()", "driver, dlerror()")
start = code.index("\t/* ---- part 5:")
end = code.index("done:\n", start)
replace(code[start:end], "")
start = code.index("\t/* The Metal test,")
end = code.index("\treturn failures != 0;", start)
replace(code[start:end], "")
for part in (2, 3):
    wait = f'"part {part}: vkWaitForFences", vkWaitForFences(dev, 1, &fence, VK_TRUE, 2000000000ull)'
    start = code.index(wait)
    end = code.index("\n\t}", start)
    replace(code[start:end + 3], code[start:end + 3] + " else {\n\t\tgoto done;\n\t}")
output.write_text(code)
