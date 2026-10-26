"""Create required directories in a new iOS root without skipping migration.

Only for freshly assembled images. No Setup, account, activation, migration
completion, or system-binary changes are made here.
"""
import os
from pathlib import Path
import plistlib

VERSION = '/System/Library/CoreServices/SystemVersion.plist'
MIGRATION = '/private/var/mobile/Library/Preferences/com.apple.migration.plist'
DIRECTORIES = (
    ('/private/var/containers', 0), ('/private/var/containers/Bundle', 33),
    ('/private/var/containers/Data', 0), ('/private/var/containers/Data/System', 0),
    ('/private/var/containers/Shared', 0),
    ('/private/var/containers/Shared/SystemGroup', 0),
    ('/private/var/containers/Temp', 0),
)


class MountedRoot:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)

    def path(self, name):
        path = self.root / name.lstrip('/')
        if not path.resolve().is_relative_to(self.root):
            raise ValueError('Path escapes the new root')
        if any(p.is_symlink() for p in (path, *path.parents) if p != self.root):
            raise ValueError('Symlink in root layout path')
        return path

    def exists(self, name):
        return self.path(name).exists()

    def read(self, name):
        return self.path(name).read_bytes()

    def directory(self, name, uid):
        path = self.path(name)
        if path.exists():
            if not path.is_dir():
                raise ValueError(f'Expected directory: {name}')
            return
        path.mkdir()
        os.chown(path, uid, uid)
        os.chmod(path, 0o755)

    def write(self, name, data, uid=0, mode=0o644):
        path = self.path(name)
        path.write_bytes(data)
        os.chown(path, uid, uid)
        os.chmod(path, mode)

    def move(self, source, destination):
        if self.exists(destination): raise ValueError('Move destination exists')
        self.path(source).rename(self.path(destination))


class GuestRoot:
    def __init__(self, guest):
        self.guest = guest

    def exists(self, name):
        return self.guest.exists(name)

    def read(self, name):
        return self.guest.read_file(name)

    def directory(self, name, uid):
        if self.exists(name):
            if not self.guest.is_dir(name, followsymlinks=False):
                raise ValueError(f'Expected directory: {name}')
            return
        self.guest.mkdir(name)
        self.guest.chown(uid, uid, name)
        self.guest.chmod(0o755, name)

    def write(self, name, data, uid=0, mode=0o644):
        if self.guest.is_symlink(name): raise ValueError('Symlink write target')
        self.guest.write(name, data)
        self.guest.chown(uid, uid, name)
        self.guest.chmod(mode, name)

    def move(self, source, destination):
        if self.exists(destination): raise ValueError('Move destination exists')
        self.guest.mv(source, destination)


def prepare_layout(root, build):
    if plistlib.loads(root.read(VERSION))['ProductBuildVersion'] != build:
        raise ValueError('System build does not match the verified source')
    if root.exists(MIGRATION) or root.exists('/private/var/datamigrator/migrate'):
        raise ValueError('Expected a fresh image with no migration history')
    for name, uid in DIRECTORIES:
        root.directory(name, uid)
    if root.exists(MIGRATION):
        raise ValueError('Migration completion override must remain absent')
    return {'build': build, 'migration_completion_seeded': False,
            'normal_migration_enabled': True,
            'container_directories': [name for name, _ in DIRECTORIES],
            'scope': 'container directories only; normal first-boot migration',
            'hardware_verified': False}
