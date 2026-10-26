"""Rebuild SLPS_021.07 from the retail EXE with every function that has C in decomp/src recompiled.

Usage: python -I tools/build_exe.py [--out build/SLPS_021.07.rebuilt] [--cc1 2.8.1]

The EXE is loaded at fixed addresses, so no linker is needed for this check: each C file is compiled
(cc_check.compile_c: CPPPSX -> gcc 2.8.1 -> ASPSX), and each function's words are written over the retail
bytes at its address from decomp/functions.txt. Words the linker would patch (jal targets, %hi/%lo and
$gp offsets of globals) keep the retail bits of those fields; everything else comes from our compiler.
Reports the functions that differ from retail and how much of the code is C so far.
Exit status 0 when the rebuilt image equals the retail file.
"""
import argparse
import glob
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cc_check

ROOT = cc_check.ROOT
CODE = (0x80173054, 0x801D7330)        # game code and Psy-Q code (docs/decomp-setup.md memory map)


def merge(mine, theirs, reloc_offsets):
    """Our words, except the fields the linker fills in, which come from the retail word."""
    out = bytearray(mine)
    for off in reloc_offsets:
        a = struct.unpack_from("<I", mine, off)[0]
        b = struct.unpack_from("<I", theirs, off)[0]
        keep = 0xFC000000 if (a >> 26) in (2, 3) else 0xFFFF0000
        struct.pack_into("<I", out, off, (a & keep) | (b & ~keep & 0xFFFFFFFF))
    return bytes(out)


def build(cc1="2.8.1"):
    """Return (image bytes, results) where results is [(name, addr, words, status)]."""
    cc_check.COMPILER = cc1
    exe = cc_check.EXE.read_bytes()
    image = bytearray(exe)
    results = []
    for src in sorted(glob.glob(str(ROOT / "decomp" / "src" / "*.c"))):
        text = Path(src).read_text()
        m = re.search(r"cc-flags:[ \t]*(.+?)[ \t]*(\*/|$)", text[:400], re.M)
        flags = m.group(1) if m else cc_check.DEFAULT_FLAGS
        obj = cc_check.compile_c(Path(src), flags)
        text_id = next(i for i, s in obj["sections"].items() if s[0] == ".text")
        code = bytes(obj["sections"][text_id][1])
        relocs = sorted({off & ~3 for sec, off, _ in obj["patches"] if sec == text_id})
        starts = sorted((off, name) for name, (sec, off) in obj["xdefs"].items() if sec == text_id)
        table = cc_check.functions_table()
        for i, (start, name) in enumerate(starts):
            end = starts[i + 1][0] if i + 1 < len(starts) else len(code)
            if name not in table:
                continue
            addr = table[name]
            mine, base = code[start:end], addr - cc_check.EXE_BASE
            theirs = exe[base:base + len(mine)]
            local = [r - start for r in relocs if start <= r < end]
            image[base:base + len(mine)] = merge(mine, theirs, local)
            same = cc_check.mask(mine, local) == cc_check.mask(theirs, local)
            regs = not same and cc_check.no_regs(cc_check.mask(mine, local)) == cc_check.no_regs(cc_check.mask(theirs, local))
            results.append((name, addr, len(mine) // 4, "MATCH" if same else "REGS-ONLY" if regs else "DIFFERS"))
    return bytes(image), exe, results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "build" / "SLPS_021.07.rebuilt"))
    ap.add_argument("--cc1", default="2.8.1", choices=sorted(cc_check.COMPILERS))
    args = ap.parse_args()
    image, exe, results = build(args.cc1)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(image)
    words = sum(w for _, _, w, _ in results)
    total = (CODE[1] - CODE[0]) // 4
    for name, addr, w, st in results:
        if st != "MATCH":
            print(f"{name} @ 0x{addr:08X} ({w} words): {st}")
    diff = [i for i in range(0, len(exe), 4) if image[i:i + 4] != exe[i:i + 4]]
    print(f"{sum(st == 'MATCH' for *_, st in results)}/{len(results)} functions byte-identical; "
          f"{words}/{total} code words ({100 * words / total:.1f}%) are C, the rest is still asm")
    print(f"rebuilt image: {len(diff)} words differ from the retail EXE -> {out}")
    sys.exit(1 if diff else 0)


if __name__ == "__main__":
    main()
