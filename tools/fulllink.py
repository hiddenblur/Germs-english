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
import cc_check
import cobjs
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


def slot_objects(i, slot, exe, funcs):
    """The objects of slot `i` in link order: glue objects, with the C function objects in the places of
    their code. Returns [(file name, bytes)]. The first piece carries the slot's data and bss glue."""
    text = slot.get(".text")
    inside = sorted((f for f in funcs if text and text[0] <= f["addr"] < text[1]), key=lambda f: f["addr"])
    rest = {k: v for k, v in slot.items() if k != ".text"}
    out, pos, n = [], text[0] if text else 0, 0

    def glue(part):
        nonlocal n, rest
        pieces = dict(rest, **part)
        rest = {}
        if pieces:
            out.append((f"glue{i:03d}_{n}.obj", glue_object(pieces, exe)))
            n += 1

    for f in inside:
        if f["addr"] < pos:
            sys.exit(f"{f['name']} (0x{f['addr']:08X}) overlaps the previous function, which ends at 0x{pos:08X}")
        if f["addr"] + f["size"] > text[1]:
            sys.exit(f"{f['name']} runs past the end of the code gap at 0x{text[1]:08X}")
        glue({".text": (pos, f["addr"])} if f["addr"] > pos else {})
        out.append((f"c_{f['name']}.obj", f["obj"]))
        pos = f["addr"] + f["size"]
    glue({".text": (pos, text[1])} if text and pos < text[1] else {})
    return out


def external_symbols(mods, values, extra_defined=()):
    """Names no located module defines or allocates -> their address. Common symbols are the linker's job."""
    defined = {n for k in mods.values() for n in k[1]["xdefs"]} | set(extra_defined)
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
    ap.add_argument("--no-c", action="store_true", help="leave the game code as retail bytes (libraries only)")
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
    funcs = []
    if not args.no_c:
        funcs, cvalues = cobjs.build()
        table = cc_check.functions_table()
        for f in funcs:                           # names the C refers to that are neither libraries nor C functions
            for r in f["refs"]:
                a = cobjs.address_of(r, cvalues, table)
                if a is not None:
                    values.setdefault(r, set()).add(a)
    slots = layout(objects, mods, placed)
    script = ["        org     0x80170000", "text    group", "bss     group   bss"]
    # SNMAIN refers to the start of .ctors and .dtors (empty sections between .text and .data)
    order = (".rdata", ".text", ".ctors", ".dtors", ".data", ".sdata", ".sbss", ".bss")
    script += [f"        section {s},{'bss' if s in ('.sbss', '.bss') else 'text'}" for s in order]
    for i in range(len(objects) + 1):
        for name, blob in slot_objects(i, slots[i], exe, funcs):
            (out / name).write_bytes(blob)
            script.append(f'        include "{name}"')
        if i < len(objects):
            lib, mod = objects[i][2], objects[i][3]
            (out / f"{i:03d}_{mod}.obj").write_bytes(commons_as_xrefs(*mods[(lib, mod)]))
            script.append(f'        include "{i:03d}_{mod}.obj"')
    script += [f"{n}\tequ\t0x{a:X}" for n, a in sorted(external_symbols(mods, values, [f["name"] for f in funcs]).items())]
    (out / "full.lnk").write_text("\n".join(script) + "\n")
    r = subprocess.run([str(PSYLINK), "/c", "/p", "/m", "@full.lnk,full.bin,full.sym,full.map"], cwd=out, capture_output=True, text=True)
    print("\n".join(l for l in r.stdout.splitlines() if l.strip())[-1500:])
    image = (out / "full.bin").read_bytes() if (out / "full.bin").exists() else b""
    want = exe[0x800:0x800 + BSS_START - 0x80170000]
    n = min(len(image), len(want))
    diff = [i for i in range(0, n, 4) if image[i:i + 4] != want[i:i + 4]]
    print(f"linked {len(image)} bytes, retail {len(want)}; {len(diff)} words differ"
          + (f", first at 0x{0x80170000 + diff[0]:08X}" if diff else ""))
    where = {}
    for i in diff:
        a = 0x80170000 + i
        name = next((f["name"] for f in funcs if f["addr"] <= a < f["addr"] + f["size"]), f"outside C (0x{a:08X})")
        where[name] = where.get(name, 0) + 1
    for name, count in where.items():
        print(f"  {name}: {count} words differ")
    c_words = sum(f["size"] for f in funcs) // 4
    print(f"{len(funcs)} C functions ({c_words} code words) are linked from our compiled objects")
    sys.exit(1 if diff or len(image) < len(want) else 0)


if __name__ == "__main__":
    main()
