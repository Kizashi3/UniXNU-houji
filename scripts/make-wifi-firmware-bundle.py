"""Package already extracted original ROM assets with hashes and source priority."""
import argparse
import json
from pathlib import Path
import shutil
from ios16_wifi_firmware import inspect_asset, load_bundle

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--stock-cache',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
a=p.parse_args()
cache=a.stock_cache.resolve()
hashes=json.loads((cache/'input-hashes.json').read_text())
expected={'NON-HLOS.bin','vendor.img','odm.img'}
if not expected<={r['name'] for r in hashes if r['package_checksum_match']}:
    raise ValueError('Missing verified source image checksums')
if a.out.exists():raise ValueError('Refusing to replace firmware bundle')
# Same priority as captured Android bootargs (per-device persist is not copied).
sources=(('NON-HLOS.bin','/image/kiwi',cache/'firmware/kiwi'),
         ('odm.img','/etc/wifi/kiwi',cache/'odm-wifi/kiwi'))
selected={};overrides=[]
for image,base,folder in sources:
    for file in sorted(folder.iterdir()):
        if not file.is_file() or file.is_symlink():continue
        if file.name in ('regdb_version',):continue
        name='kiwi/'+file.name
        asset=inspect_asset(file.read_bytes(),name)
        asset['source']={'image':image,'path':base+'/'+file.name}
        if name in selected:overrides.append({'path':name,'replaced':selected[name][1],'selected':asset})
        selected[name]=(file,asset)
config=cache/'vendor-wifi-config/kiwi_v2/WCNSS_qcom_cfg.ini'
asset=inspect_asset(config.read_bytes(),'config/kiwi_v2/WCNSS_qcom_cfg.ini')
asset['source']={'image':'vendor.img','path':'/etc/wifi/kiwi_v2/WCNSS_qcom_cfg.ini'}
selected[asset['path']]=(config,asset)
a.out.mkdir(parents=True)
for name,(file,_) in selected.items():
    target=a.out/name;target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(file,target)
catalog={'schema':1,'model':'OnePlus Ace 5 / PKG110','project':23851,'region':'CN',
    'rom_version':'16.0.3.500(CN01)','pci_id':'17cb:1107','source_images':hashes,
    'files':[value[1] for _,value in sorted(selected.items())],
    'priority_overrides':overrides,
    'per_device_persist_included':False,'silicon_version_observed':False,
    'qmi_board_id_observed':False,'firmware_uploaded':False,'rf_scan_supported':False,
    'selection_sources':[
      {'url':'https://github.com/OnePlusOSS/android_kernel_modules_and_devicetree_oneplus_sm8650/blob/453d8875f815bf9dfad9035982861226a4823a6c/vendor/qcom/opensource/wlan/platform/cnss2/pci.c','git_blob':'4cb2d7247e517127d7b8c002a6c90647cd4e7d98'},
      {'url':'https://github.com/OnePlusOSS/android_kernel_modules_and_devicetree_oneplus_sm8650/blob/453d8875f815bf9dfad9035982861226a4823a6c/vendor/qcom/opensource/wlan/platform/cnss2/qmi.c','git_blob':'20ef953ae5c717a6b89242bb6855f48d7763cd40'}]}
(a.out/'manifest.json').write_text(json.dumps(catalog,indent=2)+'\n')
load_bundle(a.out)
print(f'Verified {len(selected)} original firmware/config assets; no firmware has been uploaded')
