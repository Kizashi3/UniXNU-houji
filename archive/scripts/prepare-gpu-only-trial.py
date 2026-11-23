#!/usr/bin/env python3
"""Prepare the next houji UEFI-only GPU run; preserve the unexecuted XNU asset.

Requires the previous captured native log, exact root rescue identity, all boot
and GPT backups, stable misc reserved bytes and the unchanged initial XNU marker.
Only removes the already-archived UniXNU.log and creates a fresh FAT backup.
The separate boot tool backs up/arms the no-wipe recovery request.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

P=Path('${HOUJI_PORT_ROOT}')
N=Path('${HOUJI_ARTIFACTS}/native-port')
U=Path('${HOUJI_UEFI_ROOT}/Platforms/Xiaomi/houjiPkg/Application/HoujiStorageProbe')
C=N/'native-ios-candidate'
ADB='${USER_HOME}/Library/Android/sdk/platform-tools/adb'
SERIAL='DEVICE_SERIAL'


def verify_previous_evidence(cap, result, prev, allow_foundation_failure, reader):
    """A missing pre-logfs snapshot is evidence of failure, never a passing log."""
    captured=json.loads((cap/'capture.json').read_text())
    files={item.get('file'):item for item in captured.get('files',[])}
    xnu=(cap/'XnuLog.bin').read_bytes()
    assert files.get('XnuLog.bin',{}).get('stable') is True
    assert files['XnuLog.bin']['sha256']==hashlib.sha256(xnu).hexdigest()
    native_path=cap/'UniXNU.log'
    if not allow_foundation_failure:
        native=native_path.read_bytes()
        integrity=reader.verify_native_snapshot(native)
        assert integrity['valid'] and f'HOUJI LOGFS r{prev}:'.encode() in native
        assert files.get('UniXNU.log',{}).get('stable') is True
        assert files['UniXNU.log']['sha256']==hashlib.sha256(native).hexdigest()
        return captured,native,integrity
    required={
        'run':f'r{prev}', 'phase':'OEM-foundation-before-logfs-and-GPU',
        'manual_recovery':True, 'native_snapshot_present':False,
        'boot_partitions_unchanged':True, 'all_12_gpt_ranges_unchanged':True,
        'misc_reserved_unchanged':True, 'GPU_CP_execution_proven':False,
        'GPU_writeback_proven':False,
    }
    assert all(result.get(key)==value for key,value in required.items())
    assert not native_path.exists() and captured.get('native_log_file_present') is False
    assert files.get('UniXNU.log',{}).get('status')=='missing'
    photo=cap.parent/result['photo']
    assert photo.resolve().is_relative_to(cap.resolve()) and photo.is_file()
    return captured,None,{'valid':False,'reason':'confirmed OEM foundation failure before native logfs; no GPU result'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=int,required=True)
    parser.add_argument('--adb-port',type=int,choices=(5037,5038,5047),required=True)
    parser.add_argument('--previous-foundation-failure',action='store_true',
                        help='Require archived photo, explicit failed-foundation result and confirmed missing native log; never counts as GPU success')
    a=parser.parse_args();v=a.run;prev=v-1
    if v<79:parser.error('This workflow follows the qualified r78 UEFI-only batch')
    old=f'r{prev}';new=f'r{v}'
    base=[ADB,'-P',str(a.adb_port),'-s',SERIAL]
    def root(command):
        ports=[int(base[2])]+[port for port in (5037,5038,5047) if port!=int(base[2])]
        for port in ports:
            command_base=[ADB,'-P',str(port),'-s',SERIAL]
            r=subprocess.run(command_base+['exec-out',command],capture_output=True,timeout=30)
            missing=r.returncode and any(s in r.stderr for s in (b'not found',b'device offline',b'no devices/emulators'))
            if missing:continue
            if r.returncode or r.stderr:raise RuntimeError((r.returncode,r.stderr.decode(errors='replace')))
            base[2]=str(port)
            return r.stdout
        raise RuntimeError('No existing ADB server has the verified rescue device')
    assert root('id -u; getprop ro.product.device; getprop ro.houji.native_rescue').splitlines()==[b'0',b'houji',b'1']
    spec=importlib.util.spec_from_file_location('preflight',P/'scripts/try-native-userland-boot.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    policy=json.loads((C/f'{old}-policy.json').read_text())
    assert policy==m.POLICY and policy['execution_profile']['XNU_boot'] is False
    for name,sha in m.BOOT.items():assert root('sha256sum /dev/block/by-name/'+name).split()==[sha.encode(),('/dev/block/by-name/'+name).encode()]
    for disk in json.loads((N/'partition-backup-20261024/manifest.json').read_text())['disks']:
        for suffix,skip in [('primary',0),('backup',disk['backup_start_lba'])]:
            expected=m.expected_gpt(disk,suffix)
            assert root(f'dd if={disk["device"]} bs=4096 skip={skip} count={len(expected)//4096} status=none')==expected
    misc=root('cat /dev/block/by-name/misc')
    assert len(misc)==4194304 and misc[864:]==(N/f'device-baseline/misc-before-native-ios-{old}.bin').read_bytes()[864:]
    (N/f'device-baseline/misc-after-native-ios-{old}.bin').write_bytes(misc)
    cap=N/f'evidence/logfs-recovery-{old}'
    reader_spec=importlib.util.spec_from_file_location('capture',P/'scripts/capture-logfs.py')
    reader=importlib.util.module_from_spec(reader_spec);reader_spec.loader.exec_module(reader)
    result_path=N/f'evidence/native-ios-{old}-result.json'
    result=json.loads(result_path.read_text()) if result_path.exists() else {}
    captured,native,integrity=verify_previous_evidence(cap,result,prev,a.previous_foundation_failure,reader)
    assert root('cat /dev/logfs/XnuLog.bin')==(cap/'XnuLog.bin').read_bytes()
    assert hashlib.sha256((cap/'XnuLog.bin').read_bytes()).hexdigest()==policy['log_initial_sha256']
    helper=N/'native-log-candidate/logfs-direct-read'
    assert hashlib.sha256(helper.read_bytes()).hexdigest()=='716048584c1c6e85e64335e9528704f0e80c46a893f0e3e5d723bb3bd778b6a0'
    subprocess.run(base+['push',str(helper),'/tmp/houji-logfs-read'],check=True,timeout=30)
    root('chmod 755 /tmp/houji-logfs-read')
    assert root('sha256sum /tmp/houji-logfs-read').split()[0].decode()==hashlib.sha256(helper.read_bytes()).hexdigest()
    existence=root('if [ -e /dev/logfs/UniXNU.log ]; then echo PRESENT; else echo ABSENT; fi').strip()
    if existence==b'PRESENT':
        assert native is not None, 'Unexpected native log after confirmed early failure; archive and investigate before deletion'
        assert root('cat /dev/logfs/UniXNU.log')==native
        root('set -e; mount -o remount,rw /dev/logfs; rm /dev/logfs/UniXNU.log; sync; mount -o remount,ro /dev/logfs')
    else:assert existence==b'ABSENT'  # Safe resume after prior archive/deletion.
    backup=None
    for _ in range(4):
        first=root('/tmp/houji-logfs-read');second=root('/tmp/houji-logfs-read')
        if len(first)==8388608 and first==second:backup=first;break
    if backup is None:raise RuntimeError('No stable complete 8MiB read; archived logs are preserved; do not boot')
    dest=N/f'logfs-backup-before-native-ios-{new}';dest.mkdir()
    (dest/'logfs.bin').write_bytes(backup)
    for name in ('HoujiStorageProbe.c','LogFsTest.h'):
        f=U/name;f.write_text(f.read_text().replace(old,new))
    f=P/'scripts/capture-logfs.py';s=f.read_text();needle=f'{prev})))';assert needle in s
    f.write_text(s.replace(needle,f'{prev}, {v})))'))
    for ext in ('macho','unstripped'):shutil.copy2(C/f'kernel-{old}.{ext}',C/f'kernel-{new}.{ext}')
    shutil.copy2(C/f'{old}-psci-assembly-check.txt',C/f'{new}-psci-assembly-check.txt')
    shutil.copytree(C/f'{old}-allocation',C/f'{new}-allocation')
    policy['execution_profile']['kernel_asset_reused_from']=f'{old}; same bytes and initial XNU marker; native UEFI label/image/source distinguish this run'
    (C/f'{new}-policy.json').write_text(json.dumps(policy,indent=2)+'\n')
    before=hashlib.sha256((N/f'logfs-backup-before-native-ios-{old}/logfs.bin').read_bytes()).hexdigest()
    after=hashlib.sha256(backup).hexdigest()
    stage=(N/f'storage-candidate/make-native-ios-{old}.py').read_text().replace(old,new).replace(before,after)
    (N/f'storage-candidate/make-native-ios-{new}.py').write_text(stage)
    f=P/'scripts/try-native-userland-boot.py'
    f.write_text('\n'.join('POLICY='+repr(policy) if line.startswith('POLICY=') else line.replace(old,new) for line in f.read_text().splitlines())+'\n')
    result.update(boot_partitions_unchanged=True,all_12_gpt_ranges_unchanged=True,misc_reserved_unchanged=True,
                  expected_XNU_not_booted=True,native_snapshot_integrity=integrity)
    result_path.write_text(json.dumps(result,indent=2)+'\n')
    print(f'{new}: protected state/live logs verified, fresh FAT backup complete; XNU bytes/marker preserved, no kernel build; ADB port={base[2]}')


if __name__=='__main__':main()
