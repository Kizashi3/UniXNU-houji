"""Cache public Apple header manifests using gh's scoped API authentication.

The upstream restorer still checks every downloaded file against its Git blob
hash. Authentication is used only by gh against github.com, never raw URLs.
"""
import json
from pathlib import Path
import subprocess
import sys
import tomllib

source = Path(sys.argv[1]).resolve()
feed = tomllib.loads((source / 'feeds.toml').read_text())
xnu = next(entry for entry in feed['source'] if entry['name'] == 'xnu')
cache = source / 'out/giulia/tree/.cache/sources'
cache.mkdir(parents=True, exist_ok=True)
for prefix, relative, tag in [
    ('xnu-driverkit', 'iokit/DriverKit', xnu['driverkit_tag']),
    ('xnu-driverkit-crypto', 'iokit/DriverKit/crypto', xnu['driverkit_tag']),
    ('xnu-trustcache', 'EXTERNAL_HEADERS/TrustCache', xnu['trustcache_tag']),
]:
    destination = cache / f'{prefix}-{tag.removeprefix("xnu-")}.json'
    data = subprocess.check_output(['gh', 'api', '--hostname', 'github.com',
        f'repos/apple-oss-distributions/xnu/contents/{relative}?ref={tag}'])
    entries = json.loads(data)
    if not isinstance(entries, list) or not entries:
        raise SystemExit(f'Invalid manifest for {relative}')
    destination.write_bytes(data)
    print(f'Cached {relative} manifest at {tag}')
