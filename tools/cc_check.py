"""Compile C with the Psy-Q toolchain and compare the code with the game EXE, byte for byte.

Pipeline (all Win32 tools in psyq/bin): CPPPSX -> CC1PSX -> ASPSX -> a Psy-Q LNK object, whose
.text bytes are read with psyqlib.py. Words the linker would rewrite (calls, %hi/%lo of globals)
are masked, the same way libmatch.py does, so only the compiler's output is compared.

Usage: python -I tools/cc_check.py decomp/src/foo.c [--flags "-O2 -G8"] [--show]
Each function in the C file is looked up in decomp/functions.txt ("name 0xADDRESS words").
"""
import argparse
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import psyqlib

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "psyq" / "bin"
EXE = ROOT / "extracted" / "files" / "SLPS_021.07"
EXE_BASE = 0x80170000 - 0x800


def run(tool, *args, stdout=None):
    r = subprocess.run([str(BIN / tool), *map(str, args)], capture_output=True, cwd=BIN)
    if r.returncode:
        raise SystemExit(f"{tool} failed:\n{(r.stdout + r.stderr).decode('latin1')}")
    return r


def compile_c(src, flags="-O2"):
    """Return (sections, patches, xdefs) of the object built from `src`."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "in.i").write_bytes(run("CPPPSX.EXE", src).stdout)
        run("CC1PSX.EXE", "-quiet", *flags.split(), tmp / "in.i", "-o", tmp / "out.s")
        run("ASPSX.EXE", "-q", tmp / "out.s", "-o", tmp / "out.obj")
        data = (tmp / "out.obj").read_bytes()
    assert data[:3] == b"LNK", "unexpected object format"
    return psyqlib.parse_obj(data, 0)


def functions_table():
    table = {}
    for line in (ROOT / "decomp" / "functions.txt").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            name, addr, *_ = line.split()
            table[name] = int(addr, 16)
    return table


def mask(code, offsets):
    out = bytearray(code)
    for off in offsets:
        w = struct.unpack_from("<I", code, off)[0]
        keep = 0xFC000000 if (w >> 26) in (2, 3) else 0xFFFF0000
        struct.pack_into("<I", out, off, w & keep)
    return bytes(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--flags", default="-O2")
    ap.add_argument("--show", action="store_true", help="print both instruction streams")
    args = ap.parse_args()
    obj = compile_c(Path(args.source).resolve(), args.flags)
    text_id = next(i for i, s in obj["sections"].items() if s[0] == ".text")
    code = bytes(obj["sections"][text_id][1])
    masked = {off & ~3 for sec, off, _ in obj["patches"] if sec == text_id}
    starts = sorted((off, name) for name, (sec, off) in obj["xdefs"].items() if sec == text_id)
    exe, table, bad = EXE.read_bytes(), functions_table(), 0
    for i, (start, name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(code)
        mine = code[start:end]
        if name not in table:
            print(f"{name}: not in decomp/functions.txt")
            continue
        addr = table[name]
        theirs = exe[addr - EXE_BASE:addr - EXE_BASE + len(mine)]
        local = {m - start for m in masked if start <= m < end}
        ok = mask(mine, local) == mask(theirs, local)
        bad += not ok
        print(f"{name} @ 0x{addr:08X}: {len(mine) // 4} words, {'MATCH' if ok else 'DIFFERS'}")
        if args.show or not ok:
            import capstone
            md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN)
            a = [f"{x.mnemonic} {x.op_str}" for x in md.disasm(mine, 0)]
            b = [f"{x.mnemonic} {x.op_str}" for x in md.disasm(theirs, 0)]
            for j in range(max(len(a), len(b))):
                x, y = (a[j] if j < len(a) else ""), (b[j] if j < len(b) else "")
                print(f"  {'  ' if x == y else '!!'} {x:32} {y}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
