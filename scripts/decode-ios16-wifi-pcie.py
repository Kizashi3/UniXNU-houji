"""Decode actual PCIe handoff records from a saved serial log."""
import argparse
import hashlib
import json
from pathlib import Path
from ios16_wifi_pcie import decode_reports

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('log',type=Path)
p.add_argument('--out',type=Path,required=True)
a=p.parse_args()
data=a.log.read_bytes()
reports=decode_reports(data)
if not reports:p.error('No PCIe report captured; hardware result is unknown')
result={'source':str(a.log.resolve()),'sha256':hashlib.sha256(data).hexdigest(),'reports':reports}
with a.out.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
print(json.dumps(result,indent=2))
