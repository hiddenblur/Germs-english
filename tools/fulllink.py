"""Link the whole EXE image with PSYLINK from Lib44 modules and glue objects, and compare with retail.

Usage: python -I tools/fulllink.py [--out build/link]

The retail link is one run of PSYLINK: all `.rdata`, then all `.text`, `.data`, `.sdata`, then the bss group,
each section being the concatenation of the objects' sections in link order. Here the objects are
  - the 303 Lib44 modules of decomp/objects.txt, cut out of their libraries (real linking: calls, data
    addresses and external symbols are resolved by PSYLINK), and
  - one glue object after each module (and one in front) holding the bytes of the EXE that no located module
    owns: game code, game data, and the sizes of the game's bss. Glue is the retail bytes, so the game part
    of the image is still "asm"; it is the part to replace with compiled C.
The result is compared with SLPS_021.07 up to the start of bss. External names that no module defines get
the address the retail relocations resolve them to (datamap.symbol_values).
"""
import argparse
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import datamap
import lib_relink
import lnk

ROOT = lib_relink.ROOT
EXE_BASE = lib_relink.EXE_BASE
PSYLINK = lib_relink.PSYLINK
RDATA = (0x80170000, 0x80173054)
TEXT = (0x80173054, 0x801D7328)              # the retail symbols put the end of .text and the start of .data here
DATA = (0x801D7328, 0x801DFC58)
SDATA = (0x801DFC58, 0x801DFE50)             # gp points at the start of .sdata (__SN_GP_BASE)
BSS_START, BSS_END = 0x801DFE50, 0x801E7A10
SBSS_END = 0x801DFFE8
RANGES = {".rdata": RDATA, ".text": TEXT, ".data": DATA, ".sdata": SDATA}
LIB_SECTIONS =(".rdata", ".text", ".data", ".sdata", ".sbss", ".bss")


def section_size(o, name):
    return datamap.sections_size(o, name)


def commons_as_xrefs(obj, o):
    """The module with its common symbols (xbss records) turned into plain external references.
    The linker would allocate commons itself, in an order that depends on every object of the link;
    here they are equates at their retail addresses and their space is part of the bss glue."""
    out = bytearray(obj)
    for op, sid, sec, size, name, at, end in sorted(o["xbss"], key=lambda x: -x[5]):
        out[at:end] = b"\x0e" + struct.pack("<H", sid) + lnk.pstr(name)
    return bytes(out)


def layout(objects, mods, placed):
    """Per slot (slot i sits after module i-1; slot 0 is in front) the ranges of RAM the glue object holds,
    {section name: (start, end)}; for bss the range is just a size."""
    n = len(objects)
    slots = [dict() for _ in range(n + 1)]
    for kind in LIB_SECTIONS:
        anchors = []                              # (module index, start, end) in link order
        for i, (addr, size, lib, mod) in enumerate(objects):
            o = mods[(lib, mod)][1]
            if kind == ".text":
                anchors.append((i, addr, addr + size))
            elif kind in placed[(lib, mod)] and section_size(o, kind):
                b = placed[(lib, mod)][kind]
                anchors.append((i, b, b + section_size(o, kind)))
        if kind in RANGES:
            lo, hi = RANGES[kind]
        elif kind == ".sbss":
            lo = BSS_START
            hi = sbss_end(anchors)
        else:                                     # .bss follows the sbss
            lo = sbss_end(sbss_anchors)
            hi = BSS_END
        if kind == ".sbss":
            sbss_anchors = anchors
        pos, slot = lo, 0
        for i, start, end in anchors:
            if start > pos:
                slots[slot][kind] = (pos, start)
            elif start < pos:
                sys.exit(f"{kind}: {objects[i][3]} at 0x{start:08X} overlaps the previous one ending at 0x{pos:08X}")
            pos, slot = end, i + 1
        if pos < hi:
            slots[slot][kind] = (pos, hi)
    return slots


def sbss_end(anchors):
    """Where .sbss ends and .bss starts. The retail data of SNMAIN holds the value (__bss = 0x801DFFE8,
    __bsslen = 0x7A28); the game's own small bss objects fill the space after SNMAIN's."""
    assert max((e for _, _, e in anchors), default=BSS_START) <= SBSS_END
    return SBSS_END


def glue_object(slot, exe):
    sections = {}
    for kind, (start, end) in slot.items():
        if kind in (".sbss", ".bss"):
            sections[kind] = end - start
        else:
            sections[kind] = exe[start - EXE_BASE:end - EXE_BASE]
    return lnk.write_object(sections, align=2)      # 2 = no padding; ASPSX's 8 = 4-byte alignment (see lnk.py)


def symbol_addresses(objects, mods, placed, exe):
    """{external name: set of addresses} as the retail relocations resolve them."""
    values = {}
    for addr, size, lib, mod in objects:
        o = mods[(lib, mod)][1]
        text = lib_relink.text_id(o)
        section_at = {text: lambda off, a=addr: a - EXE_BASE + off}
        names = {i: s[0] for i, s in o["sections"].items()}
        for name, base in placed[(lib, mod)].items():
            if name in (".rdata", ".data", ".sdata"):
                sid = next(i for i, nm in names.items() if nm == name)
                section_at[sid] = lambda off, b=base: b - EXE_BASE + off
        for name, vals in datamap.symbol_values(o, addr, exe, section_at).items():
            values.setdefault(name, set()).update(vals)
    return values


def external_symbols(mods, values):
    """Names no located module defines or allocates -> their address. Common symbols are the linker's job."""
    defined = {n for k in mods.values() for n in k[1]["xdefs"]}
    out = {}
    for name, vals in values.items():
        if name not in defined:
            if len(vals) > 1:
                print(f"warning: {name} resolves to several addresses {sorted(hex(v) for v in vals)}")
            out[name] = min(vals)
    for k in mods.values():                       # nothing refers to some commons; any address will do
        for x in k[1]["xbss"]:
            out.setdefault(x[4], lib_relink.PLACEHOLDER)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "build" / "link"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    exe = lib_relink.EXE.read_bytes()
    objects = lib_relink.load_objects()
    mods = lib_relink.read_modules(objects)
    placed, problems = datamap.place(exe, objects, mods)
    for p in problems:
        print("note:", p)
    values = symbol_addresses(objects, mods, placed, exe)
    slots = layout(objects, mods, placed)
    script = ["        org     0x80170000", "text    group", "bss     group   bss"]
    # SNMAIN refers to the start of .ctors and .dtors (empty sections between .text and .data)
    order = (".rdata", ".text", ".ctors", ".dtors", ".data", ".sdata", ".sbss", ".bss")
    script += [f"        section {s},{'bss' if s in ('.sbss', '.bss') else 'text'}" for s in order]
    for i in range(len(objects) + 1):
        if slots[i]:
            (out / f"glue{i:03d}.obj").write_bytes(glue_object(slots[i], exe))
            script.append(f'        include "glue{i:03d}.obj"')
        if i < len(objects):
            lib, mod = objects[i][2], objects[i][3]
            (out / f"{i:03d}_{mod}.obj").write_bytes(commons_as_xrefs(*mods[(lib, mod)]))
            script.append(f'        include "{i:03d}_{mod}.obj"')
    script += [f"{n}\tequ\t0x{a:X}" for n, a in sorted(external_symbols(mods, values).items())]
    (out / "full.lnk").write_text("\n".join(script) + "\n")
    r = subprocess.run([str(PSYLINK), "/c", "/p", "/m", "@full.lnk,full.bin,full.sym,full.map"], cwd=out, capture_output=True, text=True)
    print("\n".join(l for l in r.stdout.splitlines() if l.strip())[-1500:])
    image = (out / "full.bin").read_bytes() if (out / "full.bin").exists() else b""
    want = exe[0x800:0x800 + BSS_START - 0x80170000]
    n = min(len(image), len(want))
    diff = [i for i in range(0, n, 4) if image[i:i + 4] != want[i:i + 4]]
    print(f"linked {len(image)} bytes, retail {len(want)}; {len(diff)} words differ"
          + (f", first at 0x{0x80170000 + diff[0]:08X}" if diff else ""))
    sys.exit(1 if diff or len(image) < len(want) else 0)


if __name__ == "__main__":
    main()
