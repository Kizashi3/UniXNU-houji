"""User-selected clean-root migration baseline, with the setup assistant retained.

The schema matches ios-vermeer-lab's hardware-tested 20H392 bootstrap.
Apply only while assembling a fresh image; never edit a running device's history.
"""
import hashlib
import plistlib
from ios16_root_layout import MIGRATION, VERSION
from ios16_startup_compat import LAUNCHD

BASELINE = {'LastSystemVersion':'20H392',
            'DMUserDataDisposition':{'SyntheticDidUpgrade':False,'buildVersion':'20H392'}}
LOG_ENV = {'OS_ACTIVITY_DT_MODE':'YES', 'OS_ACTIVITY_MODE':'debug',
           'CFLOG_FORCE_STDERR':'YES', 'ACTIVITY_LOG_STDERR':'YES'}
SOURCE = 'https://github.com/xyyyds0106/ios-vermeer-lab/blob/d1dcb06ff1d8fa57acc54051ae87d31c97e771db/xnu/vermeer/vermeer_migration_transaction.h'


def prepare_baseline(root, full_logging=False):
    version=plistlib.loads(root.read(VERSION))
    if version.get('ProductBuildVersion')!='20H392' or version.get('ProductVersion')!='16.7.16':
        raise ValueError('Baseline requires the verified 16.7.16/20H392 fresh root')
    if root.exists(MIGRATION) or root.exists('/private/var/datamigrator/migrate'):
        raise ValueError('Existing migration history must not be replaced')
    for name in ('/private/var/mobile/Library', '/private/var/mobile/Library/Preferences'):
        root.directory(name,501)
    data=plistlib.dumps(BASELINE,fmt=plistlib.FMT_BINARY)
    root.write(MIGRATION,data,uid=501,mode=0o600)
    if plistlib.loads(root.read(MIGRATION))!=BASELINE:raise ValueError('Baseline readback mismatch')
    result={'normal_migration_enabled':False,'migration_completion_seeded':True,
            'migration_baseline_source':SOURCE,'migration_baseline':BASELINE,
            'setup_completion_seeded':False,'activation_state_seeded':False,
            'scope':'fresh-root migration baseline; setup retained; no runtime preference mutation'}
    if full_logging:
        original=root.read(LAUNCHD); config=plistlib.loads(original)
        jobs=config['LaunchDaemons']
        for job in jobs.values():
            env=job.setdefault('EnvironmentVariables',{})
            if not isinstance(env,dict):raise ValueError('Unexpected launchd environment')
            env.update(LOG_ENV)
        encoded=plistlib.dumps(config,fmt=plistlib.FMT_BINARY,sort_keys=False)
        root.write(LAUNCHD,encoded)
        if root.read(LAUNCHD)!=encoded:raise ValueError('Logging configuration readback mismatch')
        result['full_boot_logging']={'launch_daemon_count':len(jobs),'environment':LOG_ENV,
            'launchd_before_sha256':hashlib.sha256(original).hexdigest(),
            'launchd_after_sha256':hashlib.sha256(encoded).hexdigest()}
    return result
