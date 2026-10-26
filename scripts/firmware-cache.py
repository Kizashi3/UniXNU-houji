"""Stable firmware cache keys and validation, independent of board/driver edits."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tomllib

ROOT=Path(__file__).resolve().parents[1]

def cache_key(board,group):
    identity={'ipsw':board['ipsw']}
    if group=='kernel':
        identity['kernelcache_sha256']=board['kernel']['prelink']['kernelcache_sha256']
    encoded=json.dumps(identity,sort_keys=True,separators=(',',':')).encode()
    return f'apple-fw-v1-{group}-{board["ipsw"]["build"]}-{hashlib.sha256(encoded).hexdigest()[:20]}'

def valid_kernel(board,cache):
    path=cache/board['ipsw']['build']/'kernelcache.decompressed'
    if not path.is_file(): return False
    with path.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()==board['kernel']['prelink']['kernelcache_sha256']

def emit(name,value):
    print(f'{name}={value}')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as f: f.write(f'{name}={value}\n')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--board',type=Path,default=ROOT/'board.toml')
    sub=p.add_subparsers(dest='command',required=True)
    key=sub.add_parser('key'); key.add_argument('--group',choices=['os','kernel'],required=True)
    validate=sub.add_parser('validate-kernel'); validate.add_argument('--cache',type=Path,required=True)
    args=p.parse_args()
    board=tomllib.loads(args.board.read_text())
    if args.command=='key': emit('key',cache_key(board,args.group))
    else: emit('valid','true' if valid_kernel(board,args.cache) else 'false')

if __name__=='__main__': main()
