import argparse
import hashlib
import json
from pathlib import Path
import struct

FAMILY = 'com.apple.iokit.IOMobileGraphicsFamily'
FAMILY_SHA = '03e4c4d80e4f9c78d4ad03366cd3f1d5894d054ae53cdf06b1a43c81a2eab1cd'
VTABLE = 0xfffffff005def8e0


def inspect(kernel, plan):
    blob = Path(kernel).read_bytes()
    meta = json.loads(Path(plan).read_text())
    digest = hashlib.sha256(blob).hexdigest()
    if digest != meta['candidate_sha256']:
        raise ValueError('Kernel does not match prelink plan')
    segments = []
    at = 32
    for _ in range(struct.unpack_from('<I', blob, 16)[0]):
        cmd, size = struct.unpack_from('<II', blob, at)
        if cmd == 0x19:
            segments.append(struct.unpack_from('<4Q', blob, at + 24))
        at += size

    def read(va, size):
        for vm, vs, fo, fs in segments:
            if vm <= va and va + size <= vm + fs:
                return blob[fo + va - vm:fo + va - vm + size]
        raise ValueError('Unbacked address ' + hex(va))

    symtab = None
    at = 32
    for _ in range(struct.unpack_from('<I', blob, 16)[0]):
        cmd, size = struct.unpack_from('<II', blob, at)
        if cmd == 2:
            symtab = struct.unpack_from('<4I', blob, at + 8)
        at += size
    symoff, count, stroff, strsize = symtab
    names = {}
    strings = blob[stroff:stroff + strsize]
    for i in range(count):
        strx, kind, _, _, address = struct.unpack_from('<IBBHQ', blob, symoff + i * 16)
        if kind & 0xe0 or not kind & 1 or not kind & 0x0e:
            continue
        end = strings.index(0, strx)
        names[strings[strx:end].decode()] = address

    text = next(e for e in meta['extents'] if e['module'] == FAMILY
                and e['segment'] == '__TEXT_EXEC')
    text_sha = hashlib.sha256(read(text['va'], text['size'])).hexdigest()
    if text_sha != FAMILY_SHA or text_sha != meta['original_executable_sha256'][FAMILY]:
        raise ValueError('Unqualified original family executable')
    original_slots = struct.unpack('<338Q', read(VTABLE, 338 * 8))
    pure = [i for i, address in enumerate(original_slots)
            if address == names['___cxa_pure_virtual']]
    if not all(original_slots) or read(VTABLE + 338 * 8, 24) != bytes(24):
        raise ValueError('Unqualified Legacy vtable extent')
    if pure != [211, 212, 242, 243, 292, 293, 321, 322, 329]:
        raise ValueError('Unqualified Legacy abstract backend leaves')
    evidence = []

    def check(va, words, purpose):
        expected = struct.pack('<' + 'I' * len(words), *words)
        if read(va, len(expected)) != expected:
            raise ValueError(purpose + ': instruction mismatch at ' + hex(va))
        evidence.append({'address': hex(va), 'bytes': expected.hex(), 'purpose': purpose})

    def slot(index, address):
        actual = struct.unpack('<Q', read(VTABLE + index * 8, 8))[0]
        if actual != address:
            raise ValueError('Slot mismatch: ' + str(index))

    def branch(va):
        word = struct.unpack('<I', read(va, 4))[0]
        if word & 0xfc000000 != 0x94000000:
            raise ValueError('Expected direct call at ' + hex(va))
        delta = word & 0x3ffffff
        if delta & (1 << 25):
            delta -= 1 << 26
        return va + delta * 4

    def stub(va, name):
        a, b, c = struct.unpack('<3I', read(va, 12))
        if a & 0x9f00001f != 0x90000010 or b & 0xffc003ff != 0xf9400210 or c != 0xd61f0200:
            raise ValueError('Expected import stub at ' + hex(va))
        imm = (((a >> 5) & 0x7ffff) << 2) | ((a >> 29) & 3)
        if imm & (1 << 20):
            imm -= 1 << 21
        ptr = (va & ~4095) + (imm << 12) + (((b >> 10) & 4095) * 8)
        if struct.unpack('<Q', read(ptr, 8))[0] != names[name]:
            raise ValueError('Wrong imported symbol: ' + name)

    check(0xfffffff004c0bb48, [0xd000f1c0, 0x91150000], 'Original Legacy metaclass global address')
    check(0xfffffff004c0bbc8, [0x90008f28, 0x91234108, 0x91004108],
          'Protected Legacy constructor selects actual original vtable')
    check(0xfffffff004c0bbec, [0x97ffd720], 'Legacy protected constructor calls original Service constructor')
    check(0xfffffff004c0189c, [0x97ffff76], 'Service constructor calls original Framebuffer constructor')
    check(0xfffffff004c0bc20, [0x97ffd726], 'Legacy protected destructor calls original Service destructor')
    check(0xfffffff004c0bbf4, [0xf94007e8, 0xf9000008], 'Legacy constructor installs original vptr')
    check(0xfffffff004c24788, [0xb9545900], 'Original width getter reads field 5208')
    check(0xfffffff004c247a0, [0xb9545d00], 'Original height getter reads field 5212')
    check(0xfffffff004c247dc, [0xb9545908], 'Dimension pair getter reads same width')
    check(0xfffffff004c24804, [0xb9545d08], 'Dimension pair getter reads same height')
    check(0xfffffff004c0d5d8, [0xf9444908, 0xd63f0100, 0x370000e0],
          'Original startHardware dispatch slot 274 returns bool')
    slot(244, 0xfffffff004c2477c)
    slot(245, 0xfffffff004c24794)
    slot(246, 0xfffffff004c247ac)
    slot(274, 0xfffffff004c17e44)
    check(0xfffffff004c0bca4, [0x5282cc03], 'Original metaclass registers instance size 0x1660')
    stub(branch(0xfffffff004c0bca8), '__ZN11OSMetaClassC2EPKcPKS_j')
    if read(0xfffffff003f6564a, len(b'IOMobileFramebufferLegacy\0')) != b'IOMobileFramebufferLegacy\0':
        raise ValueError('Original Legacy metaclass identity mismatch')
    stub(branch(0xfffffff004c0c4e8), '__ZN13IOCommandGate11commandGateEP8OSObjectPFiS1_PvS2_S2_S2_E')
    stub(branch(0xfffffff004c0c538), '__ZN10IOWorkLoop8workLoopEv')
    check(0xfffffff004c0c4f0, [0xf909d900], 'Original initializer stores command gate at 5040')
    check(0xfffffff004c0c540, [0xf909dd00], 'Original initializer stores workloop at 5048')
    check(0xfffffff004c0c58c, [0xf949dd00, 0xf949d901, 0xf9400008,
          0xf9405108, 0xd63f0100], 'Original workloop receives the command gate through addEventSource')
    check(0xfffffff004c122bc, [0xd10043ff, 0xf90007e0, 0xf94007e8,
          0xf949dd00, 0x910043ff, 0xd65f03c0], 'Original getWorkLoop returns field 5048')
    for vtable_name, index, method in [
        ('__ZTV13IOCommandGate', 29, '__ZN13IOCommandGate9runActionEPFiP8OSObjectPvS2_S2_S2_ES2_S2_S2_S2_'),
        ('__ZTV10IOWorkLoop', 20, '__ZN10IOWorkLoop14addEventSourceEP13IOEventSource')]:
        target = struct.unpack('<Q', read(names[vtable_name] + 16 + index * 8, 8))[0]
        if target != names[method]:
            raise ValueError('Unqualified native method ' + method)
    check(0xfffffff004c13a38, [0xf949d908], 'Submission enters original command gate')
    check(0xfffffff004c13a94, [0xf9407508], 'Submission uses native gate runAction slot 29')
    check(0xfffffff004c1afa0, [0xf949d908], 'Notification registration enters same command gate')
    check(0xfffffff004c1b004, [0xf9407508], 'Notification registration uses native gate runAction slot 29')
    slot(111, 0xfffffff004c122bc)

    check(0xfffffff004c194fc, [0xf9400fe8, 0x91222108, 0xb94017e9,
          0xf8697901, 0xf9400fe8, 0x911fe108, 0xb94017e9, 0x8b090d02],
          'Surface resolver reads layer input at 2184 and writes resolved layer pointer at 2040')
    check(0xfffffff004c1952c, [0x97fffe0e], 'Layer resolver calls original surface acquire helper')
    check(0xfffffff004c166d4, [0x71001108], 'Submission resolves four layers')
    check(0xfffffff004c166e4, [0xf85303a8, 0x911fe109, 0xb89183aa,
          0xd2800008, 0xf82a7928], 'Resolved layer array starts cleared before original acquisition')
    check(0xfffffff004c1674c, [0xf9452d08, 0xd63f0100], 'Original layer resolution dispatch uses slot 331')
    check(0xfffffff004c165b4, [0xf9446908, 0xd63f0100], 'Request validation dispatch uses slot 282')
    check(0xfffffff004c16628, [0xf9446d08, 0xd63f0100], 'Pre-submit backend dispatch uses slot 283')
    slot(282, 0xfffffff004c1ad10)
    slot(283, 0xfffffff004c1ad2c)
    slot(331, 0xfffffff004c19480)

    check(0xfffffff004c0d45c, [0xd282620a, 0xf909893f, 0xaa0903e8,
          0x8b0a0108, 0xf9098d28], 'Pending queue initialized empty with tail pointing to head')
    check(0xfffffff004c0d47c, [0xd282640a, 0xf909913f, 0xaa0903e8,
          0x8b0a0108, 0xf9099528], 'Submission queue initialized with independent tail')
    check(0xfffffff004c0d4c0, [0xd282660a], 'Notification array base 4912')
    check(0xfffffff004c0d4a8, [0x71001908], 'Six notification queue heads')
    check(0xfffffff004c1b0d4, [0xd282660a, 0xaa0903e8, 0x8b0a0108,
          0xb94017eb, 0x8b0b1108], 'Registration selects notification queue with type times 16')
    check(0xfffffff004c1b1ec, [0x78, 0x78, 0x78, 0x3c, 0x5c, 0x10, 0x78],
          'Notification type 5 dispatches to registration branch at 0xfffffff004c1b168')
    check(0xfffffff004c1b170, [0xf944b908, 0x52800009, 0x12000121,
          0xd63f0100], 'Type 5 registration calls refresh slot 302 with false')
    check(0xfffffff004c1b188, [0xf9445108, 0xd63f0100],
          'Type 5 registration kicks backend slot 276')
    check(0xfffffff004c1b948, [0xf949c108], 'Vsync sender reads notification head at 4992')
    check(0xfffffff004c1b974, [0x910023e2, 0x528000c3, 0x52800024,
          0x97ff8a36], 'Six-word notification with drop-allowed option')
    check(0xfffffff004c13b04, [0xf904b51f, 0xf9499528, 0xf85e83aa,
          0xf904b948], 'Submission links use request next 2408 and previous-link 2416')
    check(0xfffffff004c0fecc, [0xf9498928, 0xf9098528],
          'Pending head transferred into current at 4872')
    check(0xfffffff004c10004, [0xf85e03a9, 0xf9498528, 0xf944b908,
          0xf9098d28], 'Last-element removal restores pending tail')
    check(0xfffffff004c10018, [0xf85e03a9, 0xf9498528, 0xf944b508,
          0xf9498529, 0xf944b929, 0xf9000128], 'Removal repairs next previous-link and head')
    check(0xfffffff004c1acf4, [0xf94007e0, 0x52800028, 0x12000101,
          0x97ffd50b], 'Normal completion calls body with true')
    check(0xfffffff004c10240, [0xf9450508, 0xd2800003, 0xaa0303e2,
          0x52800004, 0xd63f0100], 'Completion requests optional reports through slot 321')
    check(0xfffffff004c1075c, [0xf9498500, 0xf9400008, 0xf9401508,
          0xd63f0100, 0xf94013e8, 0xf909851f], 'Completion releases current request then clears it')
    check(0xfffffff004c236ac, [0xf9447d08], 'Refresh publisher calls slot 287')
    check(0xfffffff004c234c0, [0xd2888888, 0xf2a08888], 'Refresh minimum 32.32 interval')
    slot(208, 0xfffffff004c1af70)
    slot(276, 0xfffffff004c192b8)
    slot(330, 0xfffffff004c0fbe8)
    slot(281, 0xfffffff004c1ace4)
    slot(287, 0xfffffff004c234b4)
    surface_name = 'com.apple.iokit.IOSurface'
    surface = next(e for e in meta['extents'] if e['module'] == surface_name
                   and e['segment'] == '__TEXT_EXEC')
    surface_sha = hashlib.sha256(read(surface['va'], surface['size'])).hexdigest()
    if surface_sha != meta['original_executable_sha256'][surface_name]:
        raise ValueError('Modified IOSurface executable')
    getters = {}
    for name, address, field, wide in [
        ('descriptor', 0xfffffff004a4e724, 56, True),
        ('width', 0xfffffff004a4e7f4, 144, False),
        ('height', 0xfffffff004a4e7fc, 148, False),
        ('stride', 0xfffffff004a4e80c, 152, False),
        ('offset', 0xfffffff004a4e804, 160, False),
        ('format', 0xfffffff004a4e7e4, 164, False),
        ('allocation', 0xfffffff004a4e834, 172, False),
        ('planes', 0xfffffff004a4e82c, 176, False),
        ('memory_region', 0xfffffff004a4e844, 48, True),
        ('region_offset', 0xfffffff004a4e83c, 168, False)]:
        word = (0xf9400000 if wide else 0xb9400000) | ((field // (8 if wide else 4)) << 10)
        check(address, [word, 0xd65f03c0], 'Original IOSurface getter: ' + name)
        getters[name] = {'address': hex(address), 'field': field, 'bits': 64 if wide else 32}
    for key, address in [('IOSurfaceWidth', 0xfffffff003ed0a3c),
                         ('IOSurfaceHeight', 0xfffffff003ed0a4b),
                         ('IOSurfaceBytesPerRow', 0xfffffff003ed09f8),
                         ('IOSurfacePixelFormat', 0xfffffff003ed0a98),
                         ('IOSurfaceAllocSize', 0xfffffff003ed0aad),
                         ('IOSurfacePlaneInfo', 0xfffffff003ed0ad6)]:
        if read(address, len(key) + 1) != key.encode() + b'\0':
            raise ValueError('Unqualified surface property key ' + key)
    check(0xfffffff004a4ac10, [0xd0ffa421, 0x9128f021], 'Width key loaded by parser')
    check(0xfffffff004a4ac40, [0xb9009260], 'Parsed width stored at 144')
    check(0xfffffff004a4ac58, [0xd0ffa421, 0x91292c21], 'Height key loaded by parser')
    check(0xfffffff004a4ac88, [0xb9009660], 'Parsed height stored at 148')
    check(0xfffffff004a4af30, [0xd0ffa421, 0x9127e021], 'Stride key loaded by parser')
    check(0xfffffff004a4af64, [0xb9009a60], 'Parsed stride stored at 152')
    check(0xfffffff004a4a9b0, [0xd0ffa421, 0x912a6021], 'Pixel format key loaded by parser')
    check(0xfffffff004a4a9d8, [0xb900a660], 'Parsed pixel format stored at 164')
    check(0xfffffff004a4b2d0, [0x912ab421], 'Allocation-size property key loaded by parser')
    check(0xfffffff004a4b3b4, [0xb900ae60], 'Parsed allocation stored at 172')
    check(0xfffffff004a47898, [0x912b5821], 'Plane-info array property key loaded by parser')
    check(0xfffffff004a478cc, [0xb900b260], 'Parsed plane count stored at 176')
    stub(branch(0xfffffff004a4c0e8), '__ZN24IOBufferMemoryDescriptor17inTaskWithOptionsEP4taskjmm')
    check(0xfffffff004a4e578, [0x9100e000], 'Descriptor setter selects surface field 56')
    check(0xfffffff004a4e5cc, [0xf9400013, 0xf9000001], 'Descriptor setter replaces held object')
    check(0xfffffff004c11e30, [0x94005553], 'Original framebuffer obtains descriptor through getter')
    check(0xfffffff004c11e38, [0xf9407508, 0x52800021, 0xd63f0100],
          'Original framebuffer maps returned memory descriptor')
    return {'kernel_sha256': digest, 'original_family_text_sha256': text_sha,
            'legacy_vtable': hex(VTABLE), 'virtual_entries': 338,
            'legacy_instance_bytes': 0x1660, 'abstract_slots': pure,
            'legacy_vptr': hex(VTABLE),
            'methods': [{'slot': i, 'address': hex(a)} for i, a in enumerate(original_slots)],
            'externals': {
                'vsync_notify': hex(0xfffffff004c1b838),
                'set_refresh_properties': hex(0xfffffff004c23610),
                'descriptor': getters['descriptor']['address'],
                'width': getters['width']['address'],
                'height': getters['height']['address'],
                'stride': getters['stride']['address'],
                'allocation': getters['allocation']['address'],
                'format': getters['format']['address'],
                'planes': getters['planes']['address'],
            },
            'lifecycle': {'protected_constructor': hex(0xfffffff004c0bbbc),
                          'protected_destructor': hex(0xfffffff004c0bc08),
                          'metaclass': hex(0xfffffff006a45540),
                          'width_field': 5208, 'height_field': 5212,
                          'dimension_pair_slot': 246, 'start_hardware_slot': 274,
                          'runtime_class_registered': False},
            'serialization': {'command_gate': 5040, 'workloop': 5048,
                              'get_workloop_slot': 111, 'gate_run_action_slot': 29,
                              'submit_action': hex(0xfffffff004c13abc),
                              'register_action': hex(0xfffffff004c1b01c),
                              'required_context': 'original workloop gate held; reentrancy possible'},
            'offsets': {'current_swap': 4872, 'pending_head': 4880,
                        'pending_tail': 4888, 'submission_head': 4896,
                        'submission_tail': 4904, 'request_next': 2408,
                        'request_previous_link': 2416, 'notification_heads': 4912,
                        'notification_stride': 16, 'notification_types': 6,
                        'vsync_type': 5, 'vsync_head': 4992,
                        'request_layer_inputs': 2184, 'request_resolved_surfaces': 2040,
                        'request_layer_stride': 8, 'request_layer_count': 4},
            'request_resolution': {'validate_slot': 282, 'pre_submit_slot': 283,
                                   'resolve_layer_slot': 331,
                                   'acquire_helper': hex(0xfffffff004c18d64),
                                   'surface_lifetime_runtime_qualified': False},
            'slots': {'register_notification': 208, 'kick_swap_queue': 276,
                      'complete_current_swap': 281, 'get_refresh_attributes': 287,
                      'completion_reports_callsite': 321, 'generic_queue_processor': 330},
            'functions': {'vsync_sender': hex(0xfffffff004c1b838),
                          'vsync_wrapper': hex(0xfffffff004c1082c),
                          'completion_body': hex(0xfffffff004c1012c),
                          'refresh_publisher': hex(0xfffffff004c23610)},
            'iosurface': {'original_text_sha256': surface_sha, 'getters': getters,
                          'cpp_symbol_spellings_qualified': False,
                          'descriptor_region_distinction_qualified': True},
            'evidence': evidence, 'static_qualified': True,
            'runtime_qualified': False, 'backend_enabled': False}


def test_queue():
    for count in range(5):
        queue = list(range(count))
        links = {i: {'next': i + 1 if i + 1 < count else None,
                     'previous': ('head', 4880) if i == 0 else ('next', i - 1)}
                 for i in queue}
        head = queue[0] if queue else None
        tail = ('next', count - 1) if count else ('head', 4880)
        retired = []
        while head is not None:
            current = head
            assert links[current]['previous'] == ('head', 4880)
            following = links[current]['next']
            if following is None:
                assert tail == ('next', current)
                head = None
                tail = ('head', 4880)
            else:
                head = following
                links[following]['previous'] = ('head', 4880)
            retired.append(current)
        assert retired == queue and tail == ('head', 4880)


if __name__ == '__main__':
    _root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument('kernel', nargs='?',
                        default=str(_root / 'build/native-prelink/native-owner-mobile-graphics-candidate.macho'))
    parser.add_argument('plan', nargs='?',
                        default=str(_root / 'build/native-prelink/native-owner-mobile-graphics-candidate.json'))
    parser.add_argument('output', nargs='?',
                        default=str(_root / 'build/display-analysis/mobile-graphics-legacy-abi.json'))
    args = parser.parse_args()
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    test_queue()
    result = inspect(args.kernel, args.plan)
    Path(args.output).write_text(json.dumps(result, indent=2) + '\n')
    print('PASS: 20H392 queue/vsync instruction checks and 0..4-element queue model')
    print('Static qualification only; original runtime/backend remains disabled')
