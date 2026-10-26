"""Read Psy-Q .LIB archives (LIB/LNK object format) and pull out each module's code.

Only the pieces needed to match library code against a game EXE are parsed:
module names, section switches, code bytes and patch (relocation) offsets.
Usage: python -I tools/psyqlib.py list psyq/lib/LIBAPI.LIB
"""
import struct
import sys


def pstr(d, p):
    n = d[p]
    return d[p + 1:p + 1 + n].decode('latin1'), p + 1 + n


def expr(d, p):
    """Skip a patch expression; return (end, referenced symbol ids)."""
    t = d[p]
    p += 1
    if t == 0x00:                       # constant
        return p + 4, []
    if t == 0x02:                       # symbol
        return p + 2, [struct.unpack_from('<H', d, p)[0]]
    if t in (0x04, 0x0C, 0x16):         # section base / start / end
        return p + 2, [('sec', struct.unpack_from('<H', d, p)[0])]
    if t == 0x14:                       # bank
        return p + 2, []
    if t in (0x1E, 0x20, 0x22, 0x24, 0x26, 0x28, 0x2A, 0x2C, 0x2E, 0x30, 0x32, 0x34, 0x36, 0x38, 0x3A, 0x3C):
        p, a = expr(d, p)               # binary ops
        p, b = expr(d, p)
        return p, a + b
    raise ValueError('expr tag 0x%02X at %d' % (t, p - 1))


def parse_obj(d, p):
    """Parse one LNK object starting at its 'LNK\x02' magic. Returns dict."""
    assert d[p:p + 3] == b'LNK'
    p += 4
    sections = {}                       # id -> [name, bytearray]
    cur = None
    chunk = 0
    patches = []                        # (section id, offset, tag)
    patch_refs = []                     # (section id, offset, symbol ids / ('sec', id) the patch refers to)
    xrefs = {}                          # symbol id -> external name
    sym_ids = {}                        # symbol id -> xdef name
    funcs = []                          # (section, offset, name)
    xdefs = {}
    while True:
        op = d[p]
        p += 1
        if op == 0:
            break
        elif op == 2:                   # code/data bytes
            n = struct.unpack_from('<H', d, p)[0]
            chunk = len(sections[cur][1])   # patch offsets are relative to the start of this chunk
            sections[cur][1] += d[p + 2:p + 2 + n]
            p += 2 + n
        elif op == 8:                   # run of zeroes? (bss reserve)
            n = struct.unpack_from('<I', d, p)[0]
            sections[cur][1] += b'\0' * n
            sections[cur][2] += n
            p += 4
        elif op == 4:                   # repeated byte fill
            n = struct.unpack_from('<H', d, p)[0]
            sections[cur][1] += bytes([0]) * 0 + b'\0' * n
            p += 2
            sections[cur][2] += n
        elif op == 6:
            cur = struct.unpack_from('<H', d, p)[0]
            p += 2
        elif op == 10:                  # patch
            tag = d[p]
            off = struct.unpack_from('<H', d, p + 1)[0]
            q, refs = expr(d, p + 3)
            patches.append((cur, chunk + off, tag))
            patch_refs.append((cur, chunk + off, refs))
            p = q
        elif op == 12:                  # xdef
            sid, sec, off = struct.unpack_from('<HHI', d, p)
            name, p = pstr(d, p + 8)
            xdefs[name] = (sec, off)
            sym_ids[sid] = name
        elif op == 14:                  # xref
            sid = struct.unpack_from('<H', d, p)[0]
            xrefs[sid], p = pstr(d, p + 2)
        elif op == 16:                  # section def
            sid, grp = struct.unpack_from('<HH', d, p)
            name, p = pstr(d, p + 5)
            sections[sid] = [name, bytearray(), 0]
        elif op == 18:                  # local symbol
            p += 6
            _, p = pstr(d, p)
        elif op == 20:                  # group
            p += 3
            _, p = pstr(d, p)
        elif op == 22:                  # set mx info
            p += 3
        elif op == 24:
            p += 3
        elif op in (26, 48):            # xbss
            p += 8
            _, p = pstr(d, p)
        elif op == 28:                  # source file (ASPSX output): id, name
            p += 2
            _, p = pstr(d, p)
        elif op == 30:
            p += 3
        elif op == 32:
            p += 1
        elif op == 34:
            p += 2
        elif op == 36:
            p += 6
        elif op == 38:
            p += 8
        elif op == 44:                  # file
            p += 2
            _, p = pstr(d, p)
        elif op == 46:                  # cpu type
            p += 1
        elif op == 60:                  # precedes an XBSS in ASPSX output (u16, meaning unknown)
            p += 2
        elif op == 74:                  # function
            sec, off = struct.unpack_from('<HI', d, p)
            name, q = pstr(d, p + 28)
            funcs.append((sec, off, name))
            p = q
        elif op == 76:                  # end function
            p += 10
        elif op == 78:                  # def
            p += 16
            _, p = pstr(d, p - 0)
        elif op == 80:                  # def2
            nd = struct.unpack_from('<H', d, p + 16)[0]
            p += 18 + 4 * nd
            _, p = pstr(d, p)
            _, p = pstr(d, p)
        else:
            raise ValueError('opcode %d at %d' % (op, p - 1))
    return dict(sections=sections, patches=patches, funcs=funcs, xdefs=xdefs, end=p,
                patch_refs=patch_refs, xrefs=xrefs, sym_ids=sym_ids)


def modules(path):
    """Yield (name, data, object_offset) for each module in the archive."""
    d = open(path, 'rb').read()
    assert d[:4] == b'LIB', 'not a LIB'
    p = 4
    while p + 20 < len(d):
        name = d[p:p + 8].decode('latin1').strip()
        off, size = struct.unpack_from('<II', d, p + 12)
        if not size:
            break
        yield name, d, p + off
        p += size


if __name__ == '__main__':
    cmd, path = sys.argv[1], sys.argv[2]
    for name, d, q in modules(path):
        o = parse_obj(d, q)
        print(name, {s[0]: len(s[1]) for s in o['sections'].values() if len(s[1])})
