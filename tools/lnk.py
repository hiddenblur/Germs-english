"""Write Psy-Q LNK object files (the format ASPSX writes and PSYLINK reads), for objects made of raw bytes.

An object is {section name: bytes (initialized) or int (zero-filled, bss)}; no relocations, no symbols
unless `symbols` is given as {name: (section name, offset)}. See psyqlib.py for the reader.
"""
import struct

SECTIONS = (".rdata", ".text", ".data", ".sdata", ".sbss", ".bss")      # ids 0xF001..0xF006, as ASPSX numbers them
CHUNK = 0x4000


def pstr(s):
    b = s.encode("latin1")
    return bytes([len(b)]) + b


def expression(tree, ids, xref_ids):
    """Serialize a patch expression: ('const', v), ('sym', name), ('sec', tag, section name), (op tag, a, b)."""
    if tree[0] == "const":
        return b"\x00" + struct.pack("<i", tree[1])
    if tree[0] == "sym":
        return b"\x02" + struct.pack("<H", xref_ids[tree[1]])
    if tree[0] == "sec":
        return bytes([tree[1]]) + struct.pack("<H", ids[tree[2]])
    return bytes([tree[0]]) + expression(tree[1], ids, xref_ids) + expression(tree[2], ids, xref_ids)


def write_object(sections, align=2, symbols=None, xrefs=(), patches=()):
    """`align` is the section header's alignment byte. Measured with PSYLINK 2.82: 2 = 1 byte (no padding),
    4 = 2 bytes, 8 = 4 bytes (what ASPSX writes); 1 and 16 make it align to 256, so avoid them.
    `symbols` = {name: (section, offset)} exported, `xrefs` = names imported, `patches` = [(offset in .text,
    patch tag, expression tree)] for the .text, which must then fit in one chunk (the offsets are chunk-relative)."""
    out = bytearray(b"LNK\x02\x2e\x07")                     # magic, version 2, CPU 7 (R3000)
    ids = {name: 0xF001 + i for i, name in enumerate(SECTIONS)}
    for name in SECTIONS:
        out += b"\x10" + struct.pack("<HH", ids[name], 0) + bytes([align]) + pstr(name)
    for n, (name, (sec, off)) in enumerate((symbols or {}).items(), 1):
        out += b"\x0c" + struct.pack("<HHI", n, ids[sec], off) + pstr(name)
    xref_ids = {}
    for name in xrefs:
        xref_ids[name] = 0x100 + len(xref_ids)
        out += b"\x0e" + struct.pack("<H", xref_ids[name]) + pstr(name)
    for name in SECTIONS:
        body = sections.get(name)
        if not body:
            continue
        out += b"\x06" + struct.pack("<H", ids[name])
        if isinstance(body, int):
            out += b"\x08" + struct.pack("<I", body)
        else:
            assert not patches or name != ".text" or len(body) <= CHUNK
            for i in range(0, len(body), CHUNK):
                piece = body[i:i + CHUNK]
                out += b"\x02" + struct.pack("<H", len(piece)) + piece
            if name == ".text":
                for off, tag, tree in patches:
                    out += b"\x0a" + bytes([tag]) + struct.pack("<H", off) + expression(tree, ids, xref_ids)
    return bytes(out + b"\x00")
