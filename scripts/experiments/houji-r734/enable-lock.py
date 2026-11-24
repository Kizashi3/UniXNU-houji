from hashlib import sha256
from pathlib import Path
import plistlib
import sys

source, output = map(Path, sys.argv[1:])
data = source.read_bytes()
assert sha256(data).hexdigest() == "400464b5cc422a027634f7c744a8ce29e9e56bb244cad47082f4e0a5e3514425"
marker = b"<key>SBDontLockEver</key><true/>"
assert data.count(marker) == 1
middle = data.index(marker)
start = data.rindex(b"<?xml", 0, middle)
end = data.index(b"\0", middle)
original = data[start:end]
assert len(original) == 503
expected = plistlib.loads(original)
revised = original.replace(b"?>\n<!DOCTYPE", b"?><!DOCTYPE", 1)
revised = revised.replace(b".dtd\">\n<plist", b".dtd\"><plist", 1)
for key in ("SBDontLockEver", "SBDontDimOrLockOnAC"):
    prefix = f"<key>{key}</key>".encode()
    assert expected[key] is True and revised.count(prefix + b"<true/>") == 1
    revised = revised.replace(prefix + b"<true/>", prefix + b"<false/>", 1)
    expected[key] = False
assert len(revised) == len(original)
assert plistlib.loads(revised) == expected
result = data[:start] + revised + data[end:]
with output.open("xb") as file:
    file.write(result)
print(sha256(result).hexdigest(), output)
