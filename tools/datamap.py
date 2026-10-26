"""Place the sections (.rdata, .data, .sdata, .sbss, .bss) of the located Lib44 modules in the EXE.

Usage: python -I tools/datamap.py [-v]      (writes decomp/data_objects.txt)

The retail words tell where a module's sections are: every relocation in the module's code or data that
points into one of its own sections, e.g. `lui/addiu` of `.data+0x20`, was resolved by the linker to the
section's base plus the offset. So base = (value in the EXE) - offset, read from the HI16/LO16 pairs,
JMP26 and 32-bit words. Initialized sections are then checked byte for byte (patched words ignored); bss
has no bytes in the EXE and rests on the relocations alone. Sections nothing refers to fall back to a search
for their bytes after the previous module's section of the same kind (the link order is the text order).
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_relink

ROOT = lib_relink.ROOT
EXE_BASE = lib_relink.EXE_BASE
GP = 0x801DFC58
SECTIONS = (".rdata", ".text", ".data", ".sdata", ".sbss", ".bss")
SEARCH = {".rdata": (0x80170000, 0x80173054), ".data": (0x801D7330, 0x801DFE50), ".sdata": (0x801D7330, 0x801DFE50)}


def section_bytes(o, name):
    """(bytes, set of patched word offsets) of the initialized section `name`, or None."""
    sid = next((i for i, s in o["sections"].items() if s[0] == name), None)
    if sid is None or not o["sections"][sid][1] or o["sections"][sid][2] == len(o["sections"][sid][1]):
        return None                              # absent, empty, or all zero-fill (bss)
    return bytes(o["sections"][sid][1]), {off & ~3 for sec, off, _ in o["patches"] if sec == sid}


def sections_size(o, name):
    sid = next((i for i, s in o["sections"].items() if s[0] == name), None)
    return len(o["sections"][sid][1]) if sid is not None else 0


def own_section(tree):
    """(section id, constant) when the expression is `section + constant`, else None."""
    if tree[0] == "sec" and tree[1] == 0x04:
        return tree[2], 0
    if tree[0] == 0x2C:
        a, b = tree[1], tree[2]
        if a[0] == "const" and b[0] == "sec" and b[1] == 0x04:
            return b[2], a[1]
        if b[0] == "const" and a[0] == "sec" and a[1] == 0x04:
            return a[2], b[1]
    return None


def patch_values(o, addr, exe, section_at):
    """Yield (patch index, tree, value the linker wrote) for the patches of module `o` that can be read back
    from the EXE: JMP26 (74), 32-bit (16) and LO16 (84) paired with the nearest earlier HI16 (82) of the same
    expression. `section_at(sec id, offset)` is the file offset of a word, for sections whose base is known."""
    exprs = o["patch_exprs"]
    for i, (sec, off, tag, tree) in enumerate(exprs):
        if sec not in section_at:
            continue
        w = struct.unpack_from("<I", exe, section_at[sec](off & ~3))[0]
        if tag == 74:
            value = (addr & 0xF0000000) | ((w & 0x3FFFFFF) << 2)
        elif tag == 16:
            value = w
        elif tag == 100:                                     # GPREL16: signed offset from gp
            value = GP + struct.unpack("<h", struct.pack("<H", w & 0xFFFF))[0]
        elif tag == 84:
            hi = next((exprs[j] for j in range(i - 1, -1, -1) if exprs[j][2] == 82 and exprs[j][3] == tree), None)
            if hi is None or hi[0] not in section_at:
                continue
            hw = struct.unpack_from("<I", exe, section_at[hi[0]](hi[1] & ~3))[0]
            lo = struct.unpack_from("<h", struct.pack("<H", w & 0xFFFF))[0]
            value = ((hw & 0xFFFF) << 16) + lo
        else:
            continue
        yield i, tree, value & 0xFFFFFFFF


def derive(o, addr, exe, text_id, section_at):
    """{section id: set of base addresses} implied by the retail words of module `o` (text at `addr`)."""
    bases = {}
    for i, tree, value in patch_values(o, addr, exe, section_at):
        own = own_section(tree)
        if own is not None:
            bases.setdefault(own[0], set()).add((value - own[1]) & 0xFFFFFFFF)
    return bases


def symbol_values(o, addr, exe, section_at):
    """{external name: set of addresses} implied by the retail words (`sym` or `constant + sym` expressions)."""
    out = {}
    for i, tree, value in patch_values(o, addr, exe, section_at):
        if tree[0] == "sym":
            sid, const = tree[1], 0
        elif tree[0] == 0x2C and "const" in (tree[1][0], tree[2][0]) and "sym" in (tree[1][0], tree[2][0]):
            c, s = (tree[1], tree[2]) if tree[1][0] == "const" else (tree[2], tree[1])
            sid, const = s[1], c[1]
        else:
            continue
        name = o["xrefs"].get(sid) or next((x[4] for x in o["xbss"] if x[1] == sid), None)
        if name:
            out.setdefault(name, set()).add((value - const) & 0xFFFFFFFF)
    return out


def find(exe, data, masked, lo, hi, after):
    """RAM addresses in [max(lo, after), hi) where `data` matches with the patched words ignored."""
    runs, start = [], 0
    for off in sorted(masked):
        runs.append((start, off))
        start = off + 4
    runs.append((start, len(data)))
    s, e = max(runs, key=lambda r: r[1] - r[0])
    pat = data[s:e]
    if len(pat) < 4:
        return []
    hits, p = [], exe.find(pat, max(lo, after) - EXE_BASE + s)
    while 0 <= p < hi - EXE_BASE:
        a = p - s
        if a + len(data) <= hi - EXE_BASE and all(exe[a + i] == data[i] for i in range(len(data)) if i & ~3 not in masked):
            hits.append(a + EXE_BASE)
        p = exe.find(pat, p + 1)
    return hits


def matches(exe, base, data, masked):
    a = base - EXE_BASE
    return all(exe[a + i] == data[i] for i in range(len(data)) if i & ~3 not in masked)


def place(exe, objects, mods):
    """{(lib, module): {section name: base address}} and a list of problems."""
    placed, problems = {}, []
    after = {name: lo for name, (lo, _) in SEARCH.items()}
    for addr, size, lib, mod in objects:
        o = mods[(lib, mod)][1]
        text = lib_relink.text_id(o)
        names = {i: s[0] for i, s in o["sections"].items()}
        found = derive(o, addr, exe, text, {text: lambda off, a=addr: a - EXE_BASE + off})
        # data patches (32-bit pointers inside .data/.rdata) refer to sections too, but need those sections' bases first
        got = {}
        for sid, cands in found.items():
            if len(cands) > 1:
                problems.append(f"{lib} {mod}: {names[sid]} has several bases {sorted(hex(c) for c in cands)}")
            got[names[sid]] = min(cands)
        for name in (".rdata", ".data", ".sdata"):
            sec = section_bytes(o, name)
            if not sec:
                continue
            data, masked = sec
            if name in got:
                if not matches(exe, got[name], data, masked):
                    problems.append(f"{lib} {mod}: {name} at 0x{got[name]:08X} does not match the EXE bytes")
            else:
                lo, hi = SEARCH[name]
                hits = find(exe, data, masked, lo, hi, after[name])
                if hits:
                    got[name] = hits[0]
                    if len(hits) > 1:
                        problems.append(f"{lib} {mod}: {name} searched, {len(hits)} candidates, took 0x{hits[0]:08X}")
                else:
                    problems.append(f"{lib} {mod}: {name} not found")
            if name in got:
                after[name] = got[name] + len(data)
        placed[(lib, mod)] = got
    return placed, problems


def main():
    objects = lib_relink.load_objects()
    mods = lib_relink.read_modules(objects)
    exe = lib_relink.EXE.read_bytes()
    placed, problems = place(exe, objects, mods)
    count = {}
    for got in placed.values():
        for name in got:
            count[name] = count.get(name, 0) + 1
    print("sections placed:", count)
    for p in problems:
        print(" ", p)
    if "-v" in sys.argv:
        for (lib, mod), got in placed.items():
            print(lib, mod, {k: hex(v) for k, v in got.items()})


if __name__ == "__main__":
    main()
