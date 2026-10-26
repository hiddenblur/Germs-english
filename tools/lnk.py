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


def write_object(sections, align=2, symbols=None):
    """`align` is the section header's alignment byte. Measured with PSYLINK 2.82: 2 = 1 byte (no padding),
    4 = 2 bytes, 8 = 4 bytes (what ASPSX writes); 1 and 16 make it align to 256, so avoid them."""
    out = bytearray(b"LNK\x02\x2e\x07")                     # magic, version 2, CPU 7 (R3000)
    ids = {name: 0xF001 + i for i, name in enumerate(SECTIONS)}
    for name in SECTIONS:
        out += b"\x10" + struct.pack("<HH", ids[name], 0) + bytes([align]) + pstr(name)
    for n, (name, (sec, off)) in enumerate((symbols or {}).items(), 1):
        out += b"\x0c" + struct.pack("<HHI", n, ids[sec], off) + pstr(name)
    for name in SECTIONS:
        body = sections.get(name)
        if not body:
            continue
        out += b"\x06" + struct.pack("<H", ids[name])
        if isinstance(body, int):
            out += b"\x08" + struct.pack("<I", body)
        else:
            for i in range(0, len(body), CHUNK):
                piece = body[i:i + CHUNK]
                out += b"\x02" + struct.pack("<H", len(piece)) + piece
    return bytes(out + b"\x00")
