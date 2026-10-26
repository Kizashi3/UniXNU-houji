"""Fetch one small JSON member from an Actions ZIP using authenticated range reads.

The GitHub token is sent only to api.github.com. Signed redirect URLs and
credentials are never logged or saved. HTTPS_PROXY is honored.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

class MetadataError(Exception):
    pass

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',default='tycykp/UniXNU-OnePlus-Ace5')
    p.add_argument('--artifact',type=int,required=True)
    p.add_argument('--member',required=True)
    p.add_argument('--upstream',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',a.repo) or a.artifact<=0:
        p.error('Invalid repository or artifact')
    if a.output.exists():raise MetadataError('Output already exists')
    token=subprocess.check_output(['gh','auth','token'],text=True).strip()
    request=urllib.request.Request(
        f'https://api.github.com/repos/{a.repo}/actions/artifacts/{a.artifact}/zip',
        headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json'})
    opener=urllib.request.build_opener(NoRedirect())
    try:
        opener.open(request,timeout=60)
        raise MetadataError('Expected an artifact redirect')
    except urllib.error.HTTPError as error:
        if error.code!=302:raise MetadataError('Artifact API returned HTTP '+str(error.code)) from None
        location=error.headers['Location']
    del token,request
    parsed=urllib.parse.urlsplit(location)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username:
        raise MetadataError('Unexpected artifact location')
    sys.path.insert(0,str(a.upstream.resolve()/'scripts'))
    from unixnu.ipsw import RangeFile
    with RangeFile(location,block=128*1024) as remote,zipfile.ZipFile(remote) as archive:
        info=archive.getinfo(a.member)
        if not info.filename.endswith('.json') or info.file_size>32*1024*1024:
            raise MetadataError('Requested member is not bounded JSON metadata')
        data=archive.read(info)
    json.loads(data)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('xb') as output:output.write(data)
    print(f'Downloaded and CRC-verified JSON metadata: {len(data)} bytes')

if __name__=='__main__':
    try:main()
    except Exception as error:
        # Do not print exceptions that can embed a private signed download URL.
        detail=str(error) if isinstance(error,MetadataError) else type(error).__name__
        print('Artifact metadata fetch failed: '+detail,file=sys.stderr)
        sys.exit(1)
