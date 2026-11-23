#!/usr/bin/env python3
"""Strict, read-only FDT inspection for captured houji board descriptions."""
from dataclasses import dataclass, field
import struct

MAGIC = b"\xd0\x0d\xfe\xed"


@dataclass
class Node:
    name: str
    properties: dict[str, bytes] = field(default_factory=dict)
    children: list["Node"] = field(default_factory=list)

    def walk(self, parent=""):
        path = parent.rstrip("/") + "/" + self.name
        yield path, self
        for child in self.children:
            yield from child.walk(path)


def cells(data):
    if len(data) % 4:
        raise ValueError("FDT cell value is not a multiple of four bytes")
    return list(struct.unpack(">" + "I" * (len(data) // 4), data))


def strings(data):
    if not data.endswith(b"\0"):
        raise ValueError("FDT string value is not terminated")
    return data[:-1].decode("utf-8").split("\0")


def parse(data):
    if len(data) < 40 or data[:4] != MAGIC:
        raise ValueError("Not a complete FDT header")
    _, total, tree_off, str_off, _, version, compat, _, str_size, tree_size = struct.unpack_from(">10I", data)
    if total > len(data) or total < 40 or version < 17 or compat > 17:
        raise ValueError("Unsupported or truncated FDT")
    if any(off < 40 or off + size > total for off, size in [(tree_off, tree_size), (str_off, str_size)]):
        raise ValueError("FDT section outside declared image")
    names = data[str_off:str_off + str_size]
    pos, end, stack, root = tree_off, tree_off + tree_size, [], None
    while pos + 4 <= end:
        token = struct.unpack_from(">I", data, pos)[0]
        pos += 4
        if token == 1:
            stop = data.find(b"\0", pos, end)
            if stop < 0:
                raise ValueError("Unterminated node name")
            node = Node(data[pos:stop].decode("ascii"))
            if stack:
                stack[-1].children.append(node)
            elif root is None:
                root = node
            else:
                raise ValueError("Multiple root nodes")
            stack.append(node)
            pos = (stop + 4) & ~3
        elif token == 2:
            if not stack:
                raise ValueError("Unbalanced FDT end node")
            stack.pop()
        elif token == 3:
            if not stack or pos + 8 > end:
                raise ValueError("Property without node or header")
            size, name_off = struct.unpack_from(">II", data, pos)
            pos += 8
            stop = names.find(b"\0", name_off)
            if name_off >= len(names) or stop < 0 or pos + size > end:
                raise ValueError("Property name or data outside section")
            name = names[name_off:stop].decode("ascii")
            if name in stack[-1].properties:
                raise ValueError("Duplicate FDT property: " + name)
            stack[-1].properties[name] = data[pos:pos + size]
            pos = (pos + size + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            if stack or root is None:
                raise ValueError("Unbalanced or empty FDT")
            return root, total
        else:
            raise ValueError("Unknown FDT token: " + hex(token))
    raise ValueError("Missing FDT end token")


def embedded(data):
    """Find independently validated FDTs in an OEM container, retaining offsets."""
    pos = 0
    while True:
        pos = data.find(MAGIC, pos)
        if pos < 0:
            return
        try:
            root, size = parse(data[pos:])
        except (ValueError, UnicodeError, struct.error):
            pos += 4
            continue
        yield pos, size, root
        pos += size
