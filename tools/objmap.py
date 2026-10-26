"""Locate whole Psy-Q library modules (.text) in the game EXE and write decomp/objects.txt.

Usage: python -I tools/objmap.py [tools/vendor/psyq44/LIB/*.LIB]     (default: every Lib44 library)

A module counts as found when its whole .text, with relocated words masked, equals the EXE bytes at one
address (the longest unmasked run is searched first, as in libmatch.py). Modules that match at several
places (short stubs) are listed as ambiguous and left out of the map. Output, sorted by address:
    <ram start> <size> <lib> <module>
Only addresses and names are written, no game code, so the file is committed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import libmatch
import psyqlib

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "extracted" / "files" / "SLPS_021.07"
LIBDIR = ROOT / "tools" / "vendor" / "psyq44" / "LIB"
MIN_WORDS = 4
# Same code, different data: the retail relocations decide (tools/datamap.py). OBJT2 would need a .data
# section at 0x801E2DB0, inside bss, so the game has OBJT3, which refers to that symbol externally.
PREFER = {"OBJT3"}


def module_texts(lib):
    """Yield (module, text bytes, masked offsets, xdef names in .text) per module."""
    for name, d, q in psyqlib.modules(lib):
        try:
            o = psyqlib.parse_obj(d, q)
        except ValueError:
            continue
        tid = next((i for i, s in o["sections"].items() if s[0] == ".text"), None)
        if tid is None:
            continue
        code = bytes(o["sections"][tid][1])
        if len(code) // 4 < MIN_WORDS:
            continue
        masked = {off & ~3 for sec, off, _ in o["patches"] if sec == tid}
        yield name, code, masked


def locate(libs, exe):
    found, ambiguous = [], []
    for lib in libs:
        for mod, code, masked in module_texts(lib):
            hits = libmatch.match(exe, code, masked)
            if len(hits) == 1:
                found.append((libmatch.EXE_BASE + hits[0], len(code), Path(lib).name, mod))
            elif hits:
                ambiguous.append((Path(lib).name, mod, len(hits)))
    return sorted(found), ambiguous


def main():
    libs = sys.argv[1:] or sorted(str(p) for p in LIBDIR.glob("*.LIB"))
    found, ambiguous = locate(libs, EXE.read_bytes())
    # Identical code in two modules (LIBC/LIBC2 QSORT, LIBGS GS_132/LIBHMD VWUNIT, ...) or a stub that sits
    # inside a bigger module cannot be told apart by text: keep the first/biggest, list the others as `also`.
    found.sort(key=lambda f: (f[0], -f[1], f[3] not in PREFER, f[2] != "LIBC2.LIB"))
    kept = []
    for a, s, lib, mod in found:
        if kept and a < kept[-1][0] + kept[-1][1]:
            kept[-1][4].append(f"{lib}:{mod}")
        else:
            kept.append((a, s, lib, mod, []))
    lines = ["# RAM address, size in bytes, library, module [also: identical or contained modules]: Lib44 modules whose",
             "# .text is in SLPS_021.07 (tools/objmap.py)"]
    lines += [f"0x{a:08X} 0x{s:X} {lib} {mod}" + (f" also:{','.join(alt)}" if alt else "") for a, s, lib, mod, alt in kept]
    (ROOT / "decomp" / "objects.txt").write_text("\n".join(lines) + "\n")
    covered = sum(s for _, s, _, _, _ in kept)
    print(f"{len(kept)} modules located ({covered} bytes), {len(ambiguous)} ambiguous, {len(found) - len(kept)} aliases folded")


if __name__ == "__main__":
    main()
