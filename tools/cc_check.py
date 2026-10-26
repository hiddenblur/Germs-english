"""Compile C with the Psy-Q toolchain and compare the code with the game EXE, byte for byte.

Pipeline (all Win32 tools in psyq/bin): CPPPSX -> CC1PSX -> ASPSX -> a Psy-Q LNK object, whose
.text bytes are read with psyqlib.py. Words the linker would rewrite (calls, %hi/%lo of globals)
are masked, the same way libmatch.py does, so only the compiler's output is compared.

Usage: python -I tools/cc_check.py decomp/src/foo.c [--flags "-O2 -fno-schedule-insns2"] [--show]
A `/* cc-flags: ... */` comment in the first lines of the C file sets its flags (objects of the
retail build were compiled with different ones). Each function in the C file is looked up in decomp/functions.txt ("name 0xADDRESS words").
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
BIN = ROOT / "psyq" / "bin"
EXE = ROOT / "extracted" / "files" / "SLPS_021.07"
EXE_BASE = 0x80170000 - 0x800


def run(tool, *args, stdout=None):
    r = subprocess.run([str(BIN / tool), *map(str, args)], capture_output=True, cwd=BIN)
    if r.returncode:
        raise SystemExit(f"{tool} failed:\n{(r.stdout + r.stderr).decode('latin1')}")
    return r


DEFAULT_FLAGS = "-O2 -fno-schedule-insns2"     # what the retail code was built with (docs/decomp-setup.md)


def compile_c(src, flags=DEFAULT_FLAGS):
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


FLAG_SETS = ["-O2", "-O2 -fno-schedule-insns2", "-O2 -fno-schedule-insns -fno-schedule-insns2", "-O1"]


def no_regs(code):
    """Words with the register fields cleared, to tell register-allocation differences from real ones."""
    out = bytearray(code)
    for off in range(0, len(code) - 3, 4):
        w = struct.unpack_from("<I", code, off)[0]
        op = w >> 26
        if op == 0:                                  # R-type: keep opcode, shamt, funct
            w &= 0xFC00_07FF
        elif op in (2, 3):                           # j/jal
            pass
        else:                                        # I-type (and REGIMM): keep opcode and immediate
            w &= 0xFC00_FFFF
            if op == 1:                              # REGIMM: the rt field is the condition
                w = struct.unpack_from("<I", code, off)[0] & 0xFC1F_FFFF
        struct.pack_into("<I", out, off, w)
    return bytes(out)


def compare(source, flags):
    """Compile `source` and compare each function with the EXE: [(name, addr, words, ok, mine, theirs)]."""
    obj = compile_c(source, flags)
    text_id = next(i for i, s in obj["sections"].items() if s[0] == ".text")
    code = bytes(obj["sections"][text_id][1])
    masked = {off & ~3 for sec, off, _ in obj["patches"] if sec == text_id}
    starts = sorted((off, name) for name, (sec, off) in obj["xdefs"].items() if sec == text_id)
    exe, table, out = EXE.read_bytes(), functions_table(), []
    for i, (start, name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(code)
        mine = code[start:end]
        if name not in table:
            out.append((name, None, len(mine) // 4, None, mine, b""))
            continue
        addr = table[name]
        theirs = exe[addr - EXE_BASE:addr - EXE_BASE + len(mine)]
        local = {m - start for m in masked if start <= m < end}
        ok = mask(mine, local) == mask(theirs, local)
        if not ok and no_regs(mask(mine, local)) == no_regs(mask(theirs, local)):
            ok = "regs"                              # same code, different register choice
        out.append((name, addr, len(mine) // 4, ok, mine, theirs))
    return out


def show(mine, theirs):
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN)
    a = [f"{x.mnemonic} {x.op_str}" for x in md.disasm(mine, 0)]
    b = [f"{x.mnemonic} {x.op_str}" for x in md.disasm(theirs, 0)]
    for j in range(max(len(a), len(b))):
        x, y = (a[j] if j < len(a) else ""), (b[j] if j < len(b) else "")
        print(f"  {'  ' if x == y else '!!'} {x:32} {y}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--flags", default=None, help="default: the `cc-flags:` comment in the file, else DEFAULT_FLAGS")
    ap.add_argument("--show", action="store_true", help="print both instruction streams")
    ap.add_argument("--which-flags", action="store_true", help="try several flag sets and list which match")
    args = ap.parse_args()
    source = Path(args.source).resolve()
    if args.which_flags:
        found = {}
        for flags in FLAG_SETS:
            for name, addr, words, ok, _, _ in compare(source, flags):
                found.setdefault((name, addr), []).append((flags, ok))
        for (name, addr), res in found.items():
            good = [f for f, ok in res if ok is True]
            near = [f for f, ok in res if ok == "regs"]
            print(f"{name} @ 0x{addr:08X}: " + (" | ".join(good) if good else
                  ("registers-only with " + " | ".join(near) if near else "no flag set matches")))
        return
    flags = args.flags
    if flags is None:
        m = re.search(r"cc-flags:[ 	]*(.+?)[ 	]*(\*/|$)", source.read_text()[:400], re.M)
        flags = m.group(1) if m else DEFAULT_FLAGS
    print(f"# {source.name}: cc1psx {flags}")
    bad = 0
    for name, addr, words, ok, mine, theirs in compare(source, flags):
        if addr is None:
            print(f"{name}: not in decomp/functions.txt")
            continue
        bad += ok is not True
        print(f"{name} @ 0x{addr:08X}: {words} words, {'MATCH' if ok is True else 'REGS-ONLY' if ok == 'regs' else 'DIFFERS'}")
        if args.show or ok is not True:
            show(mine, theirs)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
