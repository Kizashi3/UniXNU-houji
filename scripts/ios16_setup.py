"""Opt-in Setup UI preferences for a freshly assembled iOS 16 userdata image.

The caller must use a new root built from the verified firmware base. This
controls the first-boot assistant; it does not provision activation records.
"""
import hashlib
import plistlib
import struct

from ios16_root_layout import VERSION

# Experimental development-board identity from ios-sweet/tools/mkadt.py.
# In the original 20H392 mobileactivationd, DeviceType.init compares these
# MobileGestalt values with 0,0,1,1 and sets its native should_hactivate flag.
# These are ADT inputs, separate from userdata preferences and activation data.
DEVELOPMENT_SETUP_CHOSEN = {
    'certificate-production-status': 0,
    'effective-production-status-ap': 0,
    'certificate-security-mode': 1,
    'effective-security-mode-sep': 1,
}


def development_setup_properties(*, gui=False):
    if not gui:
        raise ValueError('Development Setup identity requires the GUI profile')
    return {key: struct.pack('<I', value)
            for key, value in DEVELOPMENT_SETUP_CHOSEN.items()}


PREFERENCES = '/private/var/mobile/Library/Preferences'
OVERRIDES = {
    'com.apple.purplebuddy': {
        'SetupDone': True, 'SetupFinishedAllSteps': True,
        'SetupVersion': 11, 'daemonizeNeedsToRun': False,
    },
    'com.apple.purplebuddy.notbackedup': {
        name: False for name in (
            'ShouldRunDiagnosticsMiniBuddy', 'ShouldRunHSA2MiniBuddy',
            'ShouldRunKeychainSyncMiniBuddy', 'ShouldRunMesaMiniBuddy',
            'ShouldRunPaymentMiniBuddy', 'ShouldRunStandardMiniBuddy',
            'SilentICDPUpgrade',
        )
    },
    'com.apple.managedconfiguration.notbackedup': {
        'LockdownActivationIndicatesCloudConfigurationAvailable': False,
    },
    'com.apple.springboard': {'MCForceShowCloudConfigurationUI': False},
}


def prepare_setup(root, enabled=False):
    if not enabled:
        return {'skip_setup': False}
    version = plistlib.loads(root.read(VERSION))
    if (version.get('ProductBuildVersion') != '20H392'
            or version.get('ProductVersion') != '16.7.16'):
        raise ValueError('Setup skip requires the verified 16.7.16/20H392 fresh root')
    if root.exists('/private/var/datamigrator/migrate'):
        raise ValueError('Active migration; refusing to seed Setup preferences')

    # Parse every source before writing so a malformed preference cannot leave
    # a partially configured image. Preserve unrelated and startup-compat keys.
    pending = []
    for domain, values in OVERRIDES.items():
        path = f'{PREFERENCES}/{domain}.plist'
        original = root.read(path) if root.exists(path) else None
        merged = plistlib.loads(original) if original is not None else {}
        if not isinstance(merged, dict):
            raise ValueError(f'Expected a preference dictionary: {path}')
        merged.update(values)
        encoded = plistlib.dumps(merged, fmt=plistlib.FMT_BINARY)
        pending.append((path, original, encoded))

    for path in ('/private/var/mobile/Library', PREFERENCES):
        root.directory(path, 501)
    changes = []
    for path, original, encoded in pending:
        root.write(path, encoded, uid=501, mode=0o600)
        if root.read(path) != encoded:
            raise ValueError(f'Setup preference readback mismatch: {path}')
        changes.append({
            'path': path,
            'before_sha256': hashlib.sha256(original).hexdigest() if original is not None else None,
            'after_sha256': hashlib.sha256(encoded).hexdigest(),
        })
    return {
        'skip_setup': True, 'setup_completion_seeded': True,
        'activation_state_seeded': False,
        'setup_skip': {'preference_changes': changes, 'hardware_verified': False},
    }
