#!/usr/bin/env python3
"""Stage original iOS16 wallpaper layers as PNG, using UniXNU's overlay approach.

Reference: UniXNU/UniXNU 40d21cc6 scripts/make-wallpaper-overlay.py.
This generalizes the iPad-only source to this owner's iPhone20H392 resources.
Nothing is installed and no Apple asset is replaced with generated artwork.
"""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import struct
import subprocess
from urllib.parse import quote, unquote
import xml.etree.ElementTree as ET


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('source',type=Path);a.add_argument('output',type=Path)
    args=a.parse_args();source=args.source.resolve();out=args.output.resolve()
    assert not out.exists() and source.is_dir()
    default=plistlib.loads((source/'Library/Wallpaper/DefaultWallpapers~iphone.plist').read_bytes())
    assert default['default']['wallpaperIdentifier']==7400
    wallpaper=source/'Library/Wallpaper'
    originals=[p for p in wallpaper.rglob('*') if p.is_file() and p.suffix.lower() in ('.heic','.heif')]
    assert originals and len(originals)<=256
    out.mkdir(parents=True);new=[];changed=[]
    for p in originals:
        rel=p.relative_to(source).with_suffix('.png');dest=out/rel
        assert not (source/rel).exists();dest.parent.mkdir(parents=True,exist_ok=True)
        subprocess.run(['sips','-s','format','png',str(p),'--out',str(dest)],check=True,capture_output=True)
        data=dest.read_bytes();assert data[:8]==b'\x89PNG\r\n\x1a\n'
        width,height=struct.unpack_from('>II',data,16);assert 1<=width<=16384 and 1<=height<=16384
        new.append(dict(path='/'+str(rel),sha256=sha(dest),bytes=len(data),width=width,height=height,
                        source='/'+str(p.relative_to(source)),source_sha256=sha(p),uid=0,gid=0,mode=0o644))
    # Every animation has its own local asset names. Preserve all non-image
    # animation and color data, only changing references to converted assets.
    by_animation={}
    for p in originals:
        animation=next((x for x in p.parents if x.suffix=='.ca'),None)
        if animation:by_animation.setdefault(animation,[]).append(p)
    for animation,images in by_animation.items():
        for p in animation.rglob('*'):
            if not p.is_file() or p.suffix not in ('.caml','.xml'):continue
            text=p.read_text();modified=text
            for image in images:
                modified=modified.replace(image.name,image.with_suffix('.png').name)
                modified=modified.replace(quote(image.name),quote(image.with_suffix('.png').name))
            if modified==text:continue
            rel=p.relative_to(source);dest=out/rel;dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_text(modified)
            changed.append(dict(path='/'+str(rel),before_sha256=sha(p),sha256=sha(dest),bytes=dest.stat().st_size))
    assert changed
    references=set()
    for row in changed:
        f=out/row['path'].lstrip('/')
        for node in ET.fromstring(f.read_bytes()).iter():
            src=node.attrib.get('src','')
            assert not src.lower().endswith(('.heic','.heif')),src
            if src.endswith('.png'):
                target=f.parent/unquote(src)
                assert target.is_file(),(f,src)
                references.add(str(target))
    assert references=={str(out/x['path'].lstrip('/')) for x in new}
    result=dict(source_root=str(source),source_os='iOS16.7.16 20H392',original_default=default['default'],
        reference='https://github.com/UniXNU/UniXNU/blob/40d21cc65171c3a24faa130a2a8e899f85790485/scripts/make-wallpaper-overlay.py',
        images=new,modified_existing=changed,original_HEIC_files_preserved=True,
        phone_accessed=False,hardware_visual_result='not tested',
        scope='lossless PNG copies of original HEIC layers and animation-reference updates; no animation suppression or alternate wallpaper')
    (out/'manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(images=len(new),animations=len(by_animation),modified_files=len(changed),
        PNG_bytes=sum(x['bytes'] for x in new),output=str(out),hardware_tested=False),indent=2))


if __name__=='__main__':main()
