"""Initialize a freshly assembled iOS root for the experimental GUI port.

This prevents a clean firmware image from being treated as an OS upgrade.
It does not implement App Store, account, FairPlay, activation or Setup services.
Callers must supply a new root, never a user's existing Data volume.
"""
import os
import plistlib
from pathlib import Path

VERSION_PATH = '/System/Library/CoreServices/SystemVersion.plist'
PREF_PATH = '/private/var/mobile/Library/Preferences/com.apple.migration.plist'
CONTAINERS = (
    ('/private/var/containers', 0),
    ('/private/var/containers/Bundle', 33),
    ('/private/var/containers/Data', 0),
    ('/private/var/containers/Data/System', 0),
    ('/private/var/containers/Shared', 0),
    ('/private/var/containers/Shared/SystemGroup', 0),
    ('/private/var/containers/Temp', 0),
)


class MountedRoot:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)

    def path(self, path):
        result = self.root / path.lstrip('/')
        if not result.resolve().is_relative_to(self.root):
            raise ValueError(f'Path escapes mounted root: {path}')
        # These paths are deliberately /private/var, not the /var symlink.
        if any(p.is_symlink() for p in (result, *result.parents) if p != self.root):
            raise ValueError(f'Symlink in seed path: {path}')
        return result

    def exists(self, path):
        return self.path(path).exists()

    def read(self, path):
        return self.path(path).read_bytes()

    def directory(self, path, uid):
        target = self.path(path)
        if target.exists():
            if not target.is_dir():
                raise ValueError(f'Expected directory: {path}')
            return
        target.mkdir()
        os.chown(target, uid, uid)
        os.chmod(target, 0o755)

    def write(self, path, data):
        target = self.path(path)
        with target.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(target, 501, 501)
        os.chmod(target, 0o600)


class GuestRoot:
    def __init__(self, guest):
        self.guest = guest

    def exists(self, path):
        return self.guest.exists(path)

    def read(self, path):
        return self.guest.read_file(path)

    def directory(self, path, uid):
        if self.exists(path):
            if not self.guest.is_dir(path, followsymlinks=False):
                raise ValueError(f'Expected directory: {path}')
            return
        self.guest.mkdir(path)
        self.guest.chown(uid, uid, path)
        self.guest.chmod(0o755, path)

    def write(self, path, data):
        if self.exists(path):
            raise ValueError(f'Refusing to replace {path}')
        self.guest.write(path, data)
        self.guest.chown(501, 501, path)
        self.guest.chmod(0o600, path)


def seed(root, expected_build):
    version = plistlib.loads(root.read(VERSION_PATH))
    if version['ProductBuildVersion'] != expected_build:
        raise ValueError('SystemVersion does not match the verified root build')
    if root.exists('/private/var/datamigrator/migrate'):
        raise ValueError('Active migration sentinel; this is not a fresh root')
    wanted = {
        'LastSystemVersion': expected_build,
        'DMUserDataDisposition': {
            'SyntheticDidUpgrade': False, 'buildVersion': expected_build,
        },
    }
    # Do not overwrite a pre-existing migration history or upgrade in progress.
    if root.exists(PREF_PATH) and plistlib.loads(root.read(PREF_PATH)) != wanted:
        raise ValueError('Existing migration history; refusing to replace it')
    for path, uid in CONTAINERS:
        root.directory(path, uid)
    for path in ('/private/var/mobile/Library',
                 '/private/var/mobile/Library/Preferences'):
        root.directory(path, 501)
    if not root.exists(PREF_PATH):
        root.write(PREF_PATH, plistlib.dumps(wanted, fmt=plistlib.FMT_BINARY))
    if plistlib.loads(root.read(PREF_PATH)) != wanted:
        raise ValueError('Migration preference readback differs')
    return {'build': expected_build, 'preference': PREF_PATH,
            'container_directories': [path for path, _ in CONTAINERS],
            'scope': 'fresh-root migration metadata and container directories',
            'account_services_fixed': False, 'hardware_verified': False}
