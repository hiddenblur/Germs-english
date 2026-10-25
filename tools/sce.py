"""Parse and rebuild SCE.S, the scenario archive.

Layout (all little-endian, all confirmed by exact tiling of the retail file):

SCE.S       24 scenes, one after another. Their byte offsets live in the EXE
            (SCENE_TABLE, u32[24]).
scene       DIR sector (0x800): u32[6] entries (offset from scene start, size, a, b, c, d),
            ended by a zero entry. Entries are contiguous from +0x800. They are
            followed by zero or more unlisted AREA chunks up to the next scene.
chunk       MIDI/VABH sound data (kept raw) or an AREA.
AREA        header sector: "AREA", u32 0x7F8, trigger table (kept raw);
            then sub-chunks "TAG" u32 size, payload[size], until the next AREA or
            scene end: ASET (event records), ENMY, ACTR (kept raw).
ASET        event records chained by size, then zero padding (at least one zero
            u32 ends the chain). The padding is how much the records can grow before
            the AREA needs another sector.
record      u32 size (includes itself), 0x38 bytes of header (event id first), u32 count,
            count commands.
command     u32 size (bytes after this field), u16 opcode, u16 flag, u32 param,
            u32 argc, argc NUL-terminated strings zero-padded to 4 bytes.

Rebuilding changes sizes only where data changed. An ASET that outgrows its padding
grows its AREA by whole sectors, which moves later chunks (DIR entries rewritten)
and later scenes (new scene table returned for the EXE).
"""
import struct
from dataclasses import dataclass, field

SECTOR = 0x800
EXE_SCENE_TABLE = 0x67F80      # file offset in SLPS_021.07 (RAM 0x801D7780)
SCENE_COUNT = 24
MIN_ASET_TAIL = 16             # smallest zero tail seen in retail; keeps the chain terminator


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def align(n, a):
    return (n + a - 1) // a * a


@dataclass
class Command:
    opcode: int
    flag: int
    param: int
    args: list                  # list of bytes
    arg_offsets: list = field(default_factory=list)   # original file offsets (parse only)

    def to_bytes(self):
        body = b"".join(a + b"\0" for a in self.args)
        body += b"\0" * (align(len(body), 4) - len(body))
        return struct.pack("<IHHII", 12 + len(body), self.opcode, self.flag,
                           self.param, len(self.args)) + body


@dataclass
class Record:
    header: bytes               # bytes 4..0x3C (event id first)
    commands: list

    def to_bytes(self):
        cmds = b"".join(c.to_bytes() for c in self.commands)
        return struct.pack("<I", 0x40 + len(cmds)) + self.header + \
            struct.pack("<I", len(self.commands)) + cmds


@dataclass
class Aset:
    records: list
    size: int                   # original payload size, padding included

    def to_bytes(self):
        recs = b"".join(r.to_bytes() for r in self.records)
        return recs, self.size - len(recs)


@dataclass
class Area:
    header: bytes               # whole first sector
    subs: list                  # (tag, payload bytes | Aset)

    def to_bytes(self):
        out = bytearray(self.header)
        for tag, payload in self.subs:
            if isinstance(payload, Aset):
                recs, tail = payload.to_bytes()
                if tail < MIN_ASET_TAIL:
                    # grow by whole sectors so the AREA stays sector-aligned
                    tail += align(MIN_ASET_TAIL - tail, SECTOR)
                data = recs + b"\0" * tail
            else:
                data = payload
            out += tag + struct.pack("<I", len(data)) + data
        assert len(out) % SECTOR == 0, "AREA must stay sector-aligned"
        return bytes(out)


@dataclass
class Scene:
    dir_sector: bytes
    entries: list               # [a, b, c, d] extra fields per listed chunk
    chunks: list                # bytes (raw) | Area; listed first, then unlisted
    listed: int                 # how many chunks have DIR entries

    def to_bytes(self):
        blobs = [c.to_bytes() if isinstance(c, Area) else c for c in self.chunks]
        d = bytearray(self.dir_sector)
        pos = SECTOR
        for i in range(self.listed):
            struct.pack_into("<6I", d, i * 24, pos, len(blobs[i]), *self.entries[i])
            pos += len(blobs[i])
        return bytes(d) + b"".join(blobs)


def parse_command(b, p):
    size, opcode, flag, param, argc = struct.unpack_from("<IHHII", b, p)
    end, q = p + 4 + size, p + 16
    args, offs = [], []
    for _ in range(argc):
        z = b.index(b"\0", q, end)
        args.append(bytes(b[q:z]))
        offs.append(q)
        q = z + 1
    if end - q > 3 or any(b[q:end]):
        raise ValueError(f"command at 0x{p:X}: unexpected padding")
    return Command(opcode, flag, param, args, offs), end


def parse_aset(b, p, size):
    q, end, records = p, p + size, []
    while q < end and u32(b, q):
        rsize = u32(b, q)
        count = u32(b, q + 0x3C)
        c, cmds = q + 0x40, []
        for _ in range(count):
            cmd, c = parse_command(b, c)
            cmds.append(cmd)
        if c != q + rsize:
            raise ValueError(f"record at 0x{q:X}: commands end at 0x{c:X}, size says 0x{q + rsize:X}")
        records.append(Record(bytes(b[q + 4:q + 0x3C]), cmds))
        q += rsize
    if any(b[q:end]):
        raise ValueError(f"ASET at 0x{p:X}: non-zero data after last record")
    return Aset(records, size)


def parse_area(b, p, limit):
    if b[p:p + 4] != b"AREA":
        raise ValueError(f"no AREA at 0x{p:X}")
    subs, q = [], p + SECTOR
    while q < limit and b[q:q + 4] != b"AREA":
        tag, size = bytes(b[q:q + 4]), u32(b, q + 4)
        if not tag.isalpha():
            raise ValueError(f"bad sub-chunk tag at 0x{q:X}")
        payload = parse_aset(b, q + 8, size) if tag == b"ASET" else bytes(b[q + 8:q + 8 + size])
        subs.append((tag, payload))
        q += 8 + size
    return Area(bytes(b[p:p + SECTOR]), subs), q


def parse_scene(b, start, end):
    entries, chunks = [], []
    for i in range(0, SECTOR, 24):
        off, size, *extra = struct.unpack_from("<6I", b, start + i)
        if not off and not size:
            break
        entries.append(extra)
        p = start + off
        if b[p:p + 4] == b"AREA":
            area, q = parse_area(b, p, p + size)
            if q != p + size:
                raise ValueError(f"AREA at 0x{p:X} doesn't fill its DIR entry")
            chunks.append(area)
        else:
            chunks.append(bytes(b[p:p + size]))
    listed = len(chunks)
    p = start + max([SECTOR] + list(_entry_ends(b, start, listed)))
    while p < end:
        area, p = parse_area(b, p, end)
        chunks.append(area)
    if p != end:
        raise ValueError(f"scene at 0x{start:X} overruns its end")
    return Scene(bytes(b[start:start + SECTOR]), entries, chunks, listed)


def _entry_ends(b, start, n):
    for i in range(n):
        off, size = struct.unpack_from("<2I", b, start + i * 24)
        yield off + size


def read_scene_table(exe):
    return list(struct.unpack_from(f"<{SCENE_COUNT}I", exe, EXE_SCENE_TABLE))


def parse(sce, exe):
    table = read_scene_table(exe)
    bounds = table + [len(sce)]
    return [parse_scene(sce, s, e) for s, e in zip(bounds, bounds[1:])]


def build(scenes):
    """Return (SCE.S bytes, scene offset table)."""
    out, table = bytearray(), []
    for s in scenes:
        table.append(len(out))
        out += s.to_bytes()
    return bytes(out), table


def patch_exe(exe, table):
    exe = bytearray(exe)
    struct.pack_into(f"<{SCENE_COUNT}I", exe, EXE_SCENE_TABLE, *table)
    return bytes(exe)


def iter_commands(scenes):
    """Yield (scene index, area, record, command) for every script command."""
    for si, s in enumerate(scenes):
        for c in s.chunks:
            if isinstance(c, Area):
                for tag, payload in c.subs:
                    if isinstance(payload, Aset):
                        for r in payload.records:
                            for cmd in r.commands:
                                yield si, c, r, cmd
