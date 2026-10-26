"""Download pinned Apple OS components locally, with bounded range-cache RAM.

Does not mount or flash images. Uses the upstream extractor and SHA256 pins.
"""
import argparse
import json
from pathlib import Path
import sys
import hashlib
import tomllib

p = argparse.ArgumentParser()
p.add_argument('--unixnu',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
p.add_argument('--components',nargs='+',default=['OS','Cryptex1,SystemOS','StaticTrustCache','Cryptex1,SystemTrustCache'])
args = p.parse_args()
root = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(args.unixnu.resolve()/'scripts'))
from unixnu import ipsw
from unixnu.cli import parser
from unixnu.config import Context

class BoundedRangeFile(ipsw.RangeFile):
    def __init__(self,url):
        super().__init__(url,block=1<<20)
        self.fetched=0

    def _block(self,index):
        missed=index not in self.cache
        data = super()._block(index)
        if missed:
            self.fetched+=len(data)
            if self.fetched//(32<<20)!=(self.fetched-len(data))//(32<<20):
                print(f'Fetched {self.fetched//(1<<20)} MiB from Apple CDN',flush=True)
        self.cache.pop(index,None)
        self.cache[index] = data
        while len(self.cache) > 8:
            self.cache.pop(next(iter(self.cache)))
        return data

ipsw.RangeFile = BoundedRangeFile
ctx = Context(parser().parse_args(['ipsw','info','-D',str(root),'--out',str(args.out.resolve())]))
config=tomllib.loads((root/'board.toml').read_text())['ipsw']
cache=args.out.resolve()/'ipsw'/config['build']
cached={}
# Verify bytes on a cache hit, rather than trusting a cached JSON claim.
for record_path in cache.glob('*.json'):
    try:
        record=json.loads(record_path.read_text())
        component=record.get('component')
        if component not in args.components: continue
        name=Path(record['member']).name
        pin=config.get('sha256',{}).get(name)
        path=cache/name
        if pin and path.is_file():
            with path.open('rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
            if digest==pin and path.stat().st_size==record['size']:
                cached[component]=record
            else:
                # Force the upstream extractor to recheck/re-download corrupt data.
                record_path.unlink()
    except (ValueError,KeyError):
        record_path.unlink(missing_ok=True)
    except OSError:
        continue
source=None
records = []
for component in args.components:
    if component in cached:
        records.append(cached[component])
        print(f'Using cached and SHA256-verified: {component}',flush=True)
        continue
    if source is None: source=ipsw.Ipsw(ctx)
    path = source.extract(component)
    records.append(json.loads(path.with_suffix(path.suffix+'.json').read_text()))
    print(f'Completed and hash-checked: {component}',flush=True)
args.out.mkdir(parents=True,exist_ok=True)
(args.out/'system-inputs.json').write_text(json.dumps(records,indent=2)+'\n')
