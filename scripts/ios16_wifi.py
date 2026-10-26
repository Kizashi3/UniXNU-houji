"""WCN7850 platform declaration for iOS service bring-up, not a radio driver.

20H392's wifid job is gated by _LimitLoadToDeviceTree = [wlan, marconi-wifi].
Describe the actual Qualcomm device without copying the iPhone's Broadcom
registers or presenting a fictional IO80211 network interface.
"""
import struct


WLAN_PATH = '/device-tree/arm-io/wlan'
STAGE = b'platform-description-only\0'
PROPERTIES = {
    'device_type': b'wlan\0',
    'compatible': b'qcom,wcn7850\0qcom,cnss-kiwi\0',
    'status': b'okay\0',
    'qcom,pci-vendor-id': struct.pack('<I', 0x17cb),
    'qcom,pci-device-id': struct.pack('<I', 0x1107),
    'qcom,pcie-root-complex': struct.pack('<I', 0),
    'giulia,bringup-stage': STAGE,
}


def valid_mac(value):
    return isinstance(value, bytes) and len(value) == 6 and any(value) and not value[0] & 1


def add_wifi_platform(tree, node):
    def walk(entry):
        yield entry
        for child in entry.children:
            yield from walk(child)

    if any(n.name in ('wlan', 'marconi-wifi') for n in walk(tree)):
        raise ValueError('Refusing to replace an existing Wi-Fi device-tree node')
    chosen = next(n for n in tree.children if n.name == 'chosen')
    mac = chosen.prop('mac-address-wifi0')
    if not valid_mac(mac):
        raise ValueError('Wi-Fi bring-up requires the existing stable unicast MAC identity')
    armio = next(n for n in tree.children if n.name == 'arm-io')
    armio.children.append(node('wlan', [*PROPERTIES.items(), ('local-mac-address', mac)]))


def check_wifi_platform(nodes):
    candidates = [p for p in nodes if p.rsplit('/', 1)[-1] in ('wlan', 'marconi-wifi')]
    if not candidates:
        return None
    if candidates != [WLAN_PATH]:
        raise ValueError('Unexpected or duplicate Wi-Fi platform nodes')
    wlan = nodes[WLAN_PATH]
    for name, expected in PROPERTIES.items():
        if wlan.get(name) != expected:
            raise ValueError('Wi-Fi platform property mismatch: ' + name)
    # CNSS's 0xb0000000 range is an IPA IOVA window, not a Wi-Fi BAR.
    # No MMIO/DMA resources are published until PCIe enumeration owns them.
    allowed = {'name', 'AAPL,phandle', 'local-mac-address', *PROPERTIES}
    if set(wlan) - allowed:
        raise ValueError('Unexpected Wi-Fi resources in the platform-only profile')
    mac = nodes['/device-tree/chosen'].get('mac-address-wifi0')
    if not valid_mac(mac) or wlan.get('local-mac-address') != mac:
        raise ValueError('Wi-Fi node and MobileGestalt MAC identities differ')
    root = nodes['/device-tree']
    if root.get('physical-model') != b'OnePlus Ace 5\0' or root.get('model') != b'iPhone10,3\0':
        raise ValueError('Wi-Fi bring-up requires the Ace 5 GUI platform')
    return {
        'stage': 'platform-description-only',
        'device_tree_path': WLAN_PATH,
        'chip': 'Qualcomm WCN7850 / Kiwi',
        'pci_id': '17cb:1107',
        'mac_identity': mac.hex(':'),
        'wifid_device_tree_gate_satisfied': True,
        'pcie_transport_implemented': False,
        'firmware_loaded': False,
        'io80211_interface_implemented': False,
        'scan_supported': False,
    }


def matching_job_nodes(job, nodes):
    """Report the names declared by the stock job; runtime launch needs testing."""
    names = job.get('_LimitLoadToDeviceTree', [])
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise ValueError('Unexpected wifid device-tree gate')
    return [path for path in nodes if path.rsplit('/', 1)[-1] in names]
