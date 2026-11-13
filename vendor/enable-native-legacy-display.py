"""Overlay the upstream NativeMobileDisplay driver and its audit/build scripts.

Runs before the kernel build. The prelink candidate, the ABI audit and the
libNativeLegacyDisplay late archive are produced after the first build, when
out/houji/kernel/kernel.macho exists (see the workflow's relink step).
"""
import os
import pathlib
import shutil

DEVICE = pathlib.Path(os.environ["DEVICE_DIR"])
TREE = DEVICE.parent / "unixnu" / "out" / "houji" / "tree"

drivers = TREE / "drivers" / "NativeMobileDisplay"
drivers.mkdir(parents=True, exist_ok=True)
for name in ("NativeLegacyDisplay.cpp", "NativeGOPPresenter.cpp", "NativeMobileDisplay.cpp",
             "NativeGOPWire.h", "NativeLegacyRequest.h", "OriginalMobileFramebufferABI.h", "LICENSE"):
    shutil.copyfile(DEVICE / "vendor" / "drivers" / "NativeMobileDisplay" / name, drivers / name)

scripts = TREE / "scripts"
shutil.copyfile(DEVICE / "vendor" / "scripts-audit-mobile-graphics-legacy.py",
                scripts / "audit-mobile-graphics-legacy.py")
shutil.copyfile(DEVICE / "vendor" / "build-native-legacy-display.py",
                scripts / "build-native-legacy-display.py")

print("NativeMobileDisplay overlaid:", sorted(p.name for p in drivers.iterdir()))
print("display scripts overlaid")
