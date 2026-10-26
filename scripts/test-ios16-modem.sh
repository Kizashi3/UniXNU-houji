#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x .cache/modem-verify-env/bin/python ]; then
  exec .cache/modem-verify-env/bin/python scripts/verify-ios16-modem.py "$@"
fi
exec python3 scripts/verify-ios16-modem.py "$@"
