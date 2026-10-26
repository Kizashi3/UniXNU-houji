"""Read-only audit of the delivered HFSX image, ADT, kernel and serial capture."""
import argparse
import hashlib
import json
import plistlib
import re
from pathlib import Path

from ios16_platform import read_nodes
from ios16_wifi import check_wifi_platform, matching_job_nodes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root-image', type=Path, required=True)
    parser.add_argument('--adt', type=Path, required=True)
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--serial-log', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Use a new audit directory')

    import pytsk3
    fs = pytsk3.FS_Info(pytsk3.Img_Info(str(args.root_image)))

    def read(path):
        f = fs.open(path)
        if f.info.meta.size > 16 * 1024**2:
            raise ValueError('Unexpected audit input size: ' + path)
        return f.read_random(0, f.info.meta.size)

    launchd = read('/System/Library/xpc/launchd.plist')
    jobs = plistlib.loads(launchd)['LaunchDaemons']
    selected = {k: v for k, v in jobs.items() if 'wifi' in k.lower()}
    job = jobs['/System/Library/LaunchDaemons/com.apple.wifid.plist']
    adt = args.adt.read_bytes()
    nodes = read_nodes(adt)
    kernel = args.kernel.read_bytes()
    # Snapshot a shared capture first. Hash and analyze exactly the same bytes.
    log = args.serial_log.read_bytes()
    events = [m.group().decode('ascii', 'replace') for m in re.finditer(
        rb'^(?:EXEC|EXIT|EXIT_REASON|SMP) [^\r\n]*\b(?:wifid|wifiFirmwareLoader)\b[^\r\n]*', log, re.M)]
    binaries = {}
    for path in ('/usr/sbin/wifid', '/usr/libexec/wifiFirmwareLoader'):
        data = read(path)
        binaries[path] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    matches = matching_job_nodes(job, nodes)
    result = {
        'root_image': str(args.root_image.resolve()),
        'root_image_is_offline_build_not_live_readback': True,
        'system_version': plistlib.loads(read('/System/Library/CoreServices/SystemVersion.plist')),
        'adt_sha256': hashlib.sha256(adt).hexdigest(),
        'kernel_sha256': hashlib.sha256(kernel).hexdigest(),
        'launchd_cache_sha256': hashlib.sha256(launchd).hexdigest(),
        'serial_source': str(args.serial_log.resolve()),
        'serial_snapshot_sha256': hashlib.sha256(log).hexdigest(),
        'serial_snapshot_bytes': len(log),
        'wifid_disabled': job.get('Disabled'),
        'wifid_run_at_load': job.get('RunAtLoad'),
        'wifid_required_device_tree_names': job.get('_LimitLoadToDeviceTree'),
        'wifid_matching_device_tree_paths': matches,
        'wifid_events_seen': events,
        'kernel_string_presence': {s: s.encode() in kernel for s in (
            'IO80211Interface', 'IO80211Controller', 'IONetworkController',
            'AppleBCMWLANCore', 'WCN7850', 'ath12k', 'cnss')},
        'kernel_string_presence_is_not_runtime_driver_enumeration': True,
        'binaries': binaries,
        'wifi_platform': check_wifi_platform(nodes),
        'finding': 'wifid device-tree prerequisite present; runtime and driver validation required' if matches
                   else 'wifid device-tree prerequisite missing from supplied ADT',
        'scan_fixed': False,
        'audit_reboots_device': False,
        'audit_flashes_device': False,
    }
    args.out.mkdir(parents=True)
    (args.out/'serial-snapshot.log').write_bytes(log)
    (args.out/'wifi-launch-jobs.json').write_text(json.dumps(selected, indent=2)+'\n')
    (args.out/'audit.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({
        'report': str((args.out/'audit.json').resolve()),
        'finding': result['finding'],
        'wifid_event_count': len(events),
        'wifid_exec_seen': any(e.startswith('EXEC ') and 'name=wifid' in e for e in events),
        'scan_fixed': False,
    }, indent=2))


if __name__ == '__main__':
    main()
