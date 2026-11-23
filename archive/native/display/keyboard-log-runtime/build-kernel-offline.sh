#!/bin/bash
set -euo pipefail
native_work=${HOUJI_PORT_ROOT}/.cache/ios16-reference/dxb-ios
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
export PATH="$DEVELOPER_DIR/Toolchains/XcodeDefault.xctoolchain/usr/bin:$DEVELOPER_DIR/usr/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export KERNEL_BUILD_DATE='Mon Aug 14 05:06:07 UTC 2023'
export KERNEL_BUILD_OBJROOT=1b191cb
native_memory=$(sysctl -n hw.memsize)
native_physical=$(sysctl -n hw.physicalcpu)
native_logical=$(sysctl -n hw.logicalcpu)
cd "$native_work/xnu"
make install -j8 VERBOSE=YES SDKROOT=macosx TARGET_CONFIGS='DEVELOPMENT ARM64 SWEET' CONCISE=0 LOGCOLORS=y BUILD_WERROR=0 BUILD_LTO=0 SRCROOT="$native_work/xnu" OBJROOT="$native_work/build/xnu.obj" SYMROOT="$native_work/build/xnu.sym" DSTROOT="$native_work/fakeroot" FAKEROOT_DIR="$native_work/fakeroot" KDKROOT=${HOUJI_PORT_ROOT}/.cache/ios16-reference/kdk/unpacked/KDK.pkg/Payload TIGHTBEAMC=tightbeamc-not-supported RC_DARWIN_KERNEL_VERSION=22.6.0 MEMORY_SIZE="$native_memory" SYSCTL_HW_PHYSICALCPU="$native_physical" SYSCTL_HW_LOGICALCPU="$native_logical" KERNEL_BUILDS_IN_PARALLEL=1 CTFCONVERT="$native_work/fakeroot/usr/local/bin/ctfconvert" CTFMERGE="$native_work/fakeroot/usr/local/bin/ctfmerge" CTFDUMP="$native_work/fakeroot/usr/local/bin/ctfdump" IIG=${HOUJI_PORT_ROOT}/scripts/iig-darwin22.py > ${HOUJI_PORT_ROOT}/native/display/keyboard-log-runtime/offline-kernel-build.log 2>&1
