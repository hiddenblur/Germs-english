"""Print one retail function with branch labels and call targets, for writing C by hand.

Usage: python -I tools/fdis.py 0x8018C750 [words]    (default: up to the first `jr $ra` + delay slot
that no earlier forward branch jumps past)
"""
import struct
import sys
from pathlib import Path

import capstone

EXE = Path(__file__).resolve().parent.parent / "extracted" / "files" / "SLPS_021.07"
BASE = 0x80170000 - 0x800


def function_words(d, start, limit=400):
    words, far = [], start
    for i in range(limit):
        a = start + 4 * i
        w = struct.unpack_from("<I", d, a - BASE)[0]
        words.append(w)
        op = w >> 26
        if op in (4, 5, 6, 7, 1):                     # branches
            off = struct.unpack("<h", struct.pack("<H", w & 0xFFFF))[0]
            far = max(far, a + 4 + 4 * off)
        if w == 0x03E00008 and a + 8 > far:
            words.append(struct.unpack_from("<I", d, a + 4 - BASE)[0])
            break
    return words


def main():
    start = int(sys.argv[1], 16)
    d = EXE.read_bytes()
    words = function_words(d, start) if len(sys.argv) < 3 else [struct.unpack_from("<I", d, start + 4 * i - BASE)[0] for i in range(int(sys.argv[2]))]
    md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN)
    md.detail = True
    ins = list(md.disasm(b"".join(struct.pack("<I", w) for w in words), start))
    targets = set()
    for i in ins:
        if i.mnemonic in ("beq", "bne", "blez", "bgtz", "bltz", "bgez", "beqz", "bnez", "b"):
            targets.add(int(i.op_str.split(",")[-1].strip(), 16))
    print(f"{start:08X} {len(ins)} words")
    for i in ins:
        if i.address in targets:
            print(f"L{i.address:08X}:")
        op = i.op_str
        if i.mnemonic in ("beq", "bne", "blez", "bgtz", "bltz", "bgez", "beqz", "bnez", "b"):
            t = int(op.split(",")[-1].strip(), 16)
            op = ", ".join(op.split(",")[:-1] + [f"L{t:08X}"]).lstrip(", ")
        print(f"  {i.address:08X}  {i.mnemonic:8} {op}")


if __name__ == "__main__":
    main()
