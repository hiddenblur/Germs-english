"""Relink the Psy-Q library modules found in the EXE with PSYLINK.EXE and compare with the retail bytes.

Usage: python -I tools/lib_relink.py [--module NAME] [-v]      (needs tools/vendor/psyq44, decomp/objects.txt)

For each line of decomp/objects.txt the module's object is cut out of its Lib44 .LIB, linked with
`psylink /c /p /o <org>` so that its .text lands at the address the EXE has it at, and the linked code is
compared with SLPS_021.07. Calls into other modules (jal) and %hi/%lo of text symbols are resolved by the
real linker, with the other modules' addresses given as equates (/e). References into data (.data, .sdata,
.bss of this or another module) are not placed yet; those words are skipped and counted separately.
"""
import argparse
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import psyqlib

ROOT = Path(__file__).resolve().parent.parent
LIBDIR = ROOT / "tools" / "vendor" / "psyq44" / "LIB"
PSYLINK = ROOT / "psyq" / "bin" / "PSYLINK.EXE"
EXE = ROOT / "extracted" / "files" / "SLPS_021.07"
EXE_BASE = 0x80170000 - 0x800
# SsUtReverbOff and SpuInit have the same 8 instructions, so the text search cannot tell which of the two
# places (0x801C1AF0, 0x801CF370) is which. The retail calls decide: CC_121 and DE_1 (SsUtReverbOff) jump to
# 0x801C1AF0, SSINIT_C (SpuInit) jumps to 0x801CF370.
OVERRIDES = {"SsUtReverbOff": 0x801C1AF0, "SpuInit": 0x801CF370}
PLACEHOLDER = 0x80170000       # any address a jal can reach, for symbols whose words are skipped


def load_objects():
    """[(addr, size, lib, module)] from decomp/objects.txt."""
    out = []
    for line in (ROOT / "decomp" / "objects.txt").read_text().splitlines():
        if line and not line.startswith("#"):
            a, s, lib, mod, *_ = line.split()
            out.append((int(a, 16), int(s, 16), lib, mod))
    return out


def read_modules(objects):
    """{(lib, module): (object bytes, parsed)} for the modules in `objects`."""
    wanted = {(lib, mod) for _, _, lib, mod in objects}
    mods = {}
    for lib in sorted({lib for lib, _ in wanted}):
        for name, d, q in psyqlib.modules(LIBDIR / lib):
            if (lib, name) in wanted:
                o = psyqlib.parse_obj(d, q)
                mods[(lib, name)] = (d[q:o["end"]], o)
    return mods


def symbol_table(objects, mods):
    """Text symbols of every located module -> RAM address."""
    table = {}
    for addr, _, lib, mod in objects:
        o = mods[(lib, mod)][1]
        tid = text_id(o)
        for name, (sec, off) in o["xdefs"].items():
            if sec == tid:
                table.setdefault(name, addr + off)
    table.update(OVERRIDES)
    # functions found by libmatch.py inside modules we could not place whole, and the game's main
    for line in (ROOT / "decomp" / "symbol_addrs.txt").read_text().splitlines():
        m = re.match(r"(\w+) = 0x([0-9A-Fa-f]+);", line)
        if m:
            table.setdefault(m.group(1), int(m.group(2), 16))
    return table


def text_id(o):
    return next(i for i, s in o["sections"].items() if s[0] == ".text")


def skipped_words(o, table):
    """Offsets of text words that depend on data placement or on a symbol we cannot place."""
    tid = text_id(o)
    skip = set()
    for sec, off, refs in o["patch_refs"]:
        if sec != tid:
            continue
        for r in refs:
            if isinstance(r, tuple):
                bad = r[1] != tid
            else:
                if r in o["xrefs"]:
                    bad = o["xrefs"][r] not in table
                elif r in o["sym_ids"]:
                    bad = o["xdefs"][o["sym_ids"][r]][0] != tid
                else:
                    bad = True                   # a local symbol: where it points is not recorded
            if bad:
                skip.add(off & ~3)
    return skip


def link(obj, org, equates, tmp):
    """Run PSYLINK on one object; return (binary, text start address)."""
    (tmp / "m.obj").write_bytes(obj)
    script = [f"        org     0x{org:X}", '        include "m.obj"']       # /e has a length limit; `equ` lines do not
    script += [f"{n}\tequ\t0x{a:X}" for n, a in equates.items()]
    (tmp / "m.lnk").write_text("\n".join(script) + "\n")
    r = subprocess.run([str(PSYLINK), "/c", "/p", "/m", "@m.lnk,m.bin,m.sym,m.map"], cwd=tmp, capture_output=True, text=True)
    if "0 error(s)" not in r.stdout:
        raise RuntimeError(r.stdout.strip().splitlines()[-3:])
    m = re.search(r"^\s*([0-9A-F]{8}) [0-9A-F]{8} [0-9A-F]{8} [0-9A-F]{8} \(\S+\)\s+\.TEXT", (tmp / "m.map").read_text(), re.M | re.I)
    if not m:
        raise RuntimeError(["no .text in the map", (tmp / "m.map").read_text()[:300]])
    return (tmp / "m.bin").read_bytes(), int(m.group(1), 16)


def relink(addr, size, o, obj, table, exe):
    """Returns (status, relocated words checked, words skipped)."""
    ext = {n: table.get(n, PLACEHOLDER) for n in o["xrefs"].values()}
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        org = addr
        for _ in range(2):                       # a module with .rdata puts its text after it: shift the org
            data, start = link(obj, org, ext, tmp)
            if start == addr:
                break
            org += addr - start
        code = data[start - org:start - org + size]
    skip = skipped_words(o, table)
    want = exe[addr - EXE_BASE:addr - EXE_BASE + size]
    bad = [i for i in range(0, size, 4) if i not in skip and code[i:i + 4] != want[i:i + 4]]
    tid = text_id(o)
    checked = len({off & ~3 for sec, off, _ in o["patches"] if sec == tid} - skip)
    status = "OK" if not bad and len(code) == size else f"DIFFERS at {[hex(addr + i) for i in bad[:4]]}"
    return status, checked, len(skip), code, skip


def relinked_modules():
    """Relink every located module; yield (addr, size, lib, module, status, linked code, skipped word offsets)."""
    objects = load_objects()
    mods = read_modules(objects)
    table = symbol_table(objects, mods)
    exe = EXE.read_bytes()
    for addr, size, lib, mod in objects:
        obj, o = mods[(lib, mod)]
        status, _, _, code, skip = relink(addr, size, o, obj, table, exe)
        yield addr, size, lib, mod, status, code, skip


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--module")
    ap.add_argument("-v", action="store_true")
    args = ap.parse_args()
    objects = load_objects()
    mods = read_modules(objects)
    table = symbol_table(objects, mods)
    exe = EXE.read_bytes()
    ok = fail = checked = skipped = 0
    for addr, size, lib, mod in objects:
        if args.module and mod != args.module:
            continue
        obj, o = mods[(lib, mod)]
        try:
            status, c, s, _, _ = relink(addr, size, o, obj, table, exe)
        except RuntimeError as e:
            status, c, s = f"LINK ERROR {e}", 0, 0
        ok += status == "OK"
        fail += status != "OK"
        checked += c
        skipped += s
        if status != "OK" or args.v:
            print(f"0x{addr:08X} {lib} {mod}: {status} ({c} relocated words checked, {s} skipped)")
    print(f"{ok} modules relink to the retail bytes, {fail} do not; {checked} relocated words resolved by PSYLINK "
          f"and equal to retail, {skipped} words skipped (data references)")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
