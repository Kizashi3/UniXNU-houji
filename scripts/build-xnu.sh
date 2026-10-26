#!/usr/bin/env bash
set -euo pipefail

# Compatibility entry point. The old version was Giulia-specific and could
# silently select the wrong board. Keep one houji path for both preparation
# and the later macOS/Xcode kernel build.
exec "$(cd "$(dirname "$0")" && pwd)/prepare-houji-xnu.sh" "$@"
