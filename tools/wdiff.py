"""Word-by-word difference between one compiled function and the retail EXE (relocations masked).

Usage: python -I tools/wdiff.py <function> [decomp/src/file.c]

Compiles the file with gcc 2.8.1 -O2 (the matching compiler) and prints only the words that differ, as
`index  ours | retail`, with the status (True = identical, regs = same code with other registers). The index is the
word number in the function, so a moved instruction shows up as a run of differences. The function must be in
decomp/functions.txt (park/unpark moves it). Relocated words (calls, %hi/%lo) always show: ours has 0 there.
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capstone
import cc_check


def main():
    name = sys.argv[1]
    path = Path(sys.argv[2] if len(sys.argv) > 2 else "decomp/src/batch13.c").resolve()
    cc_check.COMPILER = "2.8.1"
    md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN)
    for n, _addr, _words, ok, mine, theirs in cc_check.compare(path, "-O2"):
        if n != name:
            continue
        print(ok, len(mine) // 4, len(theirs) // 4)
        for i in range(0, min(len(mine), len(theirs)), 4):
            m = struct.unpack_from("<I", mine, i)[0]
            t = struct.unpack_from("<I", theirs, i)[0]
            if m != t:
                dm = next(md.disasm(mine[i:i + 4], 0))
                dt = next(md.disasm(theirs[i:i + 4], 0))
                print(f"{i // 4:3d} {dm.mnemonic} {dm.op_str:24s} | {dt.mnemonic} {dt.op_str}")
        return
    sys.exit(f"{name}: not found in {path} (is it in decomp/functions.txt?)")


if __name__ == "__main__":
    main()
