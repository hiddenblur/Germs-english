"""Write ELF objects for objdiff: build/objdiff/{base,target}/<file>.o for each C file in decomp/src.

Usage: python -I tools/objdiff_objs.py     (then open the repo root in objdiff: objdiff.json)

objdiff cannot read the Psy-Q LNK objects ASPSX writes, so this converts. Both sides are plain MIPS ELF
relocatable files with one .text section and one global FUNC symbol per function:
  base   = our compiled C (gcc 2.8.1 + ASPSX), functions in source order
  target = the retail bytes of the same functions, same layout
Words the linker would patch (jal targets, %hi/%lo, $gp offsets) are zeroed in the relocated field on both
sides, so only compiler output differs, like tools/cc_check.py. Functions that have no C yet are absent.
"""
import glob
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cc_check

ROOT = cc_check.ROOT
OUT = ROOT / "build" / "objdiff"


def elf(code, funcs):
    """Minimal ELF32 LE MIPS relocatable: .text plus a symbol per (name, offset, size)."""
    strtab = b"\0"
    syms = [struct.pack("<IIIBBH", 0, 0, 0, 0, 0, 0)]
    for name, off, size in funcs:
        syms.append(struct.pack("<IIIBBH", len(strtab), off, size, 0x12, 0, 1))   # GLOBAL FUNC in section 1
        strtab += name.encode() + b"\0"
    symtab = b"".join(syms)
    names = b"\0.text\0.symtab\0.strtab\0.shstrtab\0"
    n_text, n_sym, n_str, n_shs = (names.index(x) for x in (b".text", b".symtab", b".strtab", b".shstrtab"))
    body, pos = b"", 52
    layout = []
    for blob in (code, symtab, strtab, names):
        pad = -pos % 4
        body += b"\0" * pad + blob
        layout.append((pos + pad, len(blob)))
        pos += pad + len(blob)
    pad = -pos % 4
    body += b"\0" * pad
    shoff = pos + pad
    sh = [struct.pack("<10I", *([0] * 10))]
    sh.append(struct.pack("<10I", n_text, 1, 6, 0, *layout[0], 0, 0, 4, 0))               # PROGBITS, ALLOC|EXEC
    sh.append(struct.pack("<10I", n_sym, 2, 0, 0, *layout[1], 3, 1, 4, 16))               # SYMTAB, link .strtab
    sh.append(struct.pack("<10I", n_str, 3, 0, 0, *layout[2], 0, 0, 1, 0))
    sh.append(struct.pack("<10I", n_shs, 3, 0, 0, *layout[3], 0, 0, 1, 0))
    ident = b"\x7fELF" + bytes([1, 1, 1, 0]) + b"\0" * 8
    hdr = ident + struct.pack("<HHIIIIIHHHHHH", 1, 8, 1, 0, 0, shoff, 0x1000, 52, 0, 0, 40, 5, 4)
    return hdr + body + b"".join(sh)


def convert(src, cc1="2.8.1"):
    """Return (base ELF, target ELF, [function names]) for one C file."""
    cc_check.COMPILER = cc1
    text = Path(src).read_text()
    m = re.search(r"cc-flags:[ \t]*(.+?)[ \t]*(\*/|$)", text[:400], re.M)
    obj = cc_check.compile_c(Path(src), m.group(1) if m else cc_check.DEFAULT_FLAGS)
    tid = next(i for i, s in obj["sections"].items() if s[0] == ".text")
    code = bytes(obj["sections"][tid][1])
    relocs = {off & ~3 for sec, off, _ in obj["patches"] if sec == tid}
    starts = sorted((off, name) for name, (sec, off) in obj["xdefs"].items() if sec == tid)
    table, exe = cc_check.functions_table(), cc_check.EXE.read_bytes()
    mine = theirs = b""
    funcs = []
    for i, (start, name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(code)
        if name not in table:
            continue
        base = table[name] - cc_check.EXE_BASE
        local = {r - start for r in relocs if start <= r < end}
        a = code[start:end]
        b = exe[base:base + len(a)]
        funcs.append((name, len(mine), len(a)))
        mine += cc_check.mask(a, local)
        theirs += cc_check.mask(b, local)
    return elf(mine, funcs), elf(theirs, funcs), [f[0] for f in funcs]


def main():
    for side in ("base", "target"):
        (OUT / side).mkdir(parents=True, exist_ok=True)
    for src in sorted(glob.glob(str(ROOT / "decomp" / "src" / "*.c"))):
        base, target, names = convert(src)
        stem = Path(src).stem
        (OUT / "base" / f"{stem}.o").write_bytes(base)
        (OUT / "target" / f"{stem}.o").write_bytes(target)
        print(f"{stem}.o: {len(names)} functions")


if __name__ == "__main__":
    main()
