import hashlib
import json
import pathlib
import sys

p = pathlib.Path(sys.argv[1])
out = pathlib.Path(sys.argv[2])
run = sys.argv[3] if len(sys.argv) > 3 else ""
d = json.loads(out.read_text()) if out.exists() else {}
d.update({
    "bytes": p.stat().st_size,
    "sha256": hashlib.file_digest(p.open("rb"), "sha256").hexdigest(),
    "run": run,
})
out.write_text(json.dumps(d, indent=1) + "\n")
print(d)
