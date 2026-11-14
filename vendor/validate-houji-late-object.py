import argparse
import struct
from pathlib import Path


def sections(blob):
    result = {}
    at = 32
    for _ in range(struct.unpack_from('<I', blob, 16)[0]):
        cmd, size = struct.unpack_from('<II', blob, at)
        if cmd == 0x19:
            count = struct.unpack_from('<I', blob, at + 64)[0]
            for i in range(count):
                pos = at + 72 + 80 * i
                name = blob[pos:pos + 16].split(b'\0')[0].decode()
                segment = blob[pos + 16:pos + 32].split(b'\0')[0].decode()
                length = struct.unpack_from('<Q', blob, pos + 40)[0]
                offset = struct.unpack_from('<I', blob, pos + 48)[0]
                flags = struct.unpack_from('<I', blob, pos + 64)[0]
                result[(segment, name)] = b'' if flags & 0xff == 1 else blob[offset:offset + length]
        at += size
    return result


def validate(original, late):
    before = sections(Path(original).read_bytes())
    after = sections(Path(late).read_bytes())
    if ('__DATA', '__mod_init_func') not in before:
        raise ValueError('Original object has no expected initializer section')
    for key in after:
        if key[1] in ('__mod_init_func', '__mod_term_func'):
            raise ValueError('Automatic class registration remains')
    compared = 0
    for key, content in before.items():
        if key[1] in ('__mod_init_func', '__mod_term_func'):
            continue
        if key not in after or after[key] != content:
            raise ValueError('Owned section content changed: ' + repr(key))
        compared += 1
    if set(after) - set(before):
        raise ValueError('Unexpected late-object sections')
    return compared


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('original')
    parser.add_argument('late')
    args = parser.parse_args()
    print('PASS: unchanged owned sections', validate(args.original, args.late))
