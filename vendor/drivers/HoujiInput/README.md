# HoujiInput - touch and buttons for houji, on the r591 line

Base commit 04db0a97 (kernel run 591). Branch input-houji-r591, worktree
/home/yun/mrk-input, build script build-houji-input.sh, images houji-in-*.img,
round tags in<nn><letter>. Deliberately named apart from the parallel line that
uses NativeHidInput / SweetHID / iokit/Kernel/arm/hid, so the two agents cannot
overwrite each other's files or share a boot-arg spelling.

Subclasses Apple's prelinked IOHID classes using the verbatim tag headers under
../hid-abi; no Apple .cpp is vendored, no class is shadowed by name.
