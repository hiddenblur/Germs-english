"""Disassemble part of the main executable, and find jal callers of an address.

Usage: python tools/disasm.py <exe> <ram_addr_hex> <count>
       python tools/disasm.py <exe> --callers <ram_addr_hex>
"""
import struct
import sys

import capstone

exe = open(sys.argv[1], "rb").read()
LOAD = struct.unpack_from("<I", exe, 0x18)[0]
text = exe[0x800:]
md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 | capstone.CS_MODE_LITTLE_ENDIAN)

if sys.argv[2] == "--callers":
    target = int(sys.argv[3], 16)
    want = 0x0C000000 | ((target >> 2) & 0x03FFFFFF)
    for off in range(0, len(text) - 3, 4):
        if struct.unpack_from("<I", text, off)[0] == want:
            print(f"{LOAD + off:08X}")
else:
    addr, count = int(sys.argv[2], 16), int(sys.argv[3])
    off = addr - LOAD
    for i in range(count):
        a, word = addr + i * 4, text[off + i * 4:off + i * 4 + 4]
        if len(word) < 4:
            break
        ins = next(md.disasm(word, a), None)   # one word at a time: data must not stop the dump
        if ins:
            print(f"{a:08X}  {ins.mnemonic:8} {ins.op_str}")
        else:
            print(f"{a:08X}  .word    0x{int.from_bytes(word, 'little'):08x}")
