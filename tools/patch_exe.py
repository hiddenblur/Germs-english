"""Apply code patches to the main EXE (SLPS_021.07).

Usage: python tools/patch_exe.py <in_exe> <out_exe>

Each patch replaces a known range of retail code. Before writing, it checks that
the range still holds the expected retail instructions, so patches can't be applied
twice or to the wrong build. Assembled with keystone (pip install keystone-engine),
with .set noreorder: delay slots and load-delay slots are filled by hand.
"""
import struct
import sys
from pathlib import Path

from keystone import KS_ARCH_MIPS, KS_MODE_LITTLE_ENDIAN, KS_MODE_MIPS32, Ks

LOAD = 0x80170000
HEADER = 0x800
ks = Ks(KS_ARCH_MIPS, KS_MODE_MIPS32 | KS_MODE_LITTLE_ENDIAN)


def asm(src, addr):
    enc, _ = ks.asm(".set noreorder\n" + src, addr)
    return bytes(enc)


# Half-width text, narration renderer (typewriter, 0x80182860).
# Columns count 8 px half-cells: a full-width SJIS character advances 2, a byte in
# 0xA1-0xFE advances 1 and draws ASCII (byte - 0x80) from the BIOS 8x15 font at
# 0xBFC7F8DE (15 bytes per glyph, MSB = left pixel). 0xA0 is a half-width space.
NARRATION_DRAW = """
    lbu   $t0, 0($v1)
    nop
    sltiu $t1, $t0, 0xA0
    bne   $t1, $zero, full
    sltiu $t1, $t0, 0xA1
    beq   $t1, $zero, half
    nop
    lhu   $t2, 0x218($gp)           # 0xA0: half space, like the game's 0x20 path
    lhu   $t3, 0x220($gp)
    addiu $t2, $t2, 1
    addiu $t3, $t3, 1
    sh    $t2, 0x218($gp)
    sh    $t3, 0x220($gp)
    j     0x801828AC
    lui   $v0, 0x801E
half:
    addiu $t0, $t0, -0xA1
    sll   $t1, $t0, 4
    subu  $t1, $t1, $t0             # (c - 0xA1) * 15
    lui   $s1, 0xBFC8
    addiu $s1, $s1, -0x722          # 0xBFC7F8DE
    addu  $s1, $s1, $t1
    beq   $zero, $zero, draw
    addiu $s0, $zero, 1             # 1 byte per glyph row
full:
    lbu   $t1, 1($v1)
    sll   $a0, $t0, 8
    jal   0x801B1370                # Kanji ROM lookup -> 15 rows of 2 bytes
    or    $a0, $a0, $t1
    or    $s1, $v0, $zero
    addiu $s0, $zero, 2             # 2 bytes per glyph row
draw:
    lhu   $t7, 0x21C($gp)           # colour
    addiu $t2, $sp, 0x18            # 4bpp buffer
    addiu $t3, $zero, 16            # rows
row_loop:
    or    $t4, $s0, $zero
byte_loop:
    addiu $t5, $zero, 0
    addiu $t8, $zero, 1
    beq   $t3, $t8, store           # 16th row is blank
    nop
    lbu   $t6, 0($s1)
    addiu $s1, $s1, 1
    addiu $t8, $zero, 0x80
    or    $t9, $t7, $zero
bit_loop:
    and   $a1, $t6, $t8
    beq   $a1, $zero, skip
    srl   $t8, $t8, 1
    or    $t5, $t5, $t9
skip:
    bne   $t8, $zero, bit_loop
    sll   $t9, $t9, 4
store:
    sw    $t5, 0($t2)
    addiu $t4, $t4, -1
    bne   $t4, $zero, byte_loop
    addiu $t2, $t2, 4
    addiu $t3, $t3, -1
    bne   $t3, $zero, row_loop
    nop
    lw    $t0, 0x1C($s2)            # text page origin in VRAM
    lh    $t1, 0x218($gp)
    lhu   $t2, 0($t0)
    sll   $t1, $t1, 1
    addu  $t2, $t2, $t1
    sh    $t2, 0x10($sp)            # x = origin + col * 2 (VRAM halfwords)
    lh    $t1, 0x21A($gp)
    lhu   $t2, 2($t0)
    sll   $t1, $t1, 4
    addu  $t2, $t2, $t1
    sh    $t2, 0x12($sp)            # y = origin + row * 16
    sll   $t1, $s0, 1
    sh    $t1, 0x14($sp)            # w = 2 or 4 halfwords
    addiu $a0, $sp, 0x10
    jal   0x801B05A8                # LoadImage(rect, buffer)
    addiu $a1, $sp, 0x18
    lhu   $t0, 0x218($gp)           # the code at 0x80182BEC adds col+1, index+2:
    lhu   $t1, 0x220($gp)           # pre-adjust so the totals are +s0 for both
    addu  $t0, $t0, $s0
    addu  $t1, $t1, $s0
    addiu $t0, $t0, -1
    addiu $t1, $t1, -2
    sh    $t0, 0x218($gp)
    j     0x80182BEC
    sh    $t1, 0x220($gp)
"""

# (start, end, expected retail first instruction, new code)
PATCHES = [
    (0x801828E8, 0x801828EC, "slti $v0, $v0, 0x10", "slti $v0, $v0, 0x20"),
    (0x801829A8, 0x801829AC, "addiu $v0, $v0, 1", "addiu $v0, $v0, 2"),
    (0x801829DC, 0x80182BEC, "addiu $s0, $sp, 0x18", NARRATION_DRAW),
    (0x80182C40, 0x80182C44, "slti $v0, $v0, 0x10", "slti $v0, $v0, 0x20"),
    (0x80182CD0, 0x80182CD4, "slti $v0, $v0, 0x10", "slti $v0, $v0, 0x20"),
]


def apply(exe):
    exe = bytearray(exe)
    if struct.unpack_from("<I", exe, 0x18)[0] != LOAD:
        raise SystemExit("unexpected EXE load address")
    for start, end, expect, src in PATCHES:
        off = start - LOAD + HEADER
        if exe[off:off + 4] != asm(expect, start):
            raise SystemExit(f"0x{start:08X}: retail code not found (already patched?)")
        code = asm(src, start)
        if len(code) > end - start:
            raise SystemExit(f"0x{start:08X}: patch is {len(code)} bytes, room for {end - start}")
        # fill any leftover room with nops so nothing stale stays reachable
        exe[off:off + (end - start)] = code.ljust(end - start, b"\0")
        print(f"0x{start:08X}: {len(code) // 4}/{(end - start) // 4} instructions")
    return bytes(exe)


def main():
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    dst.write_bytes(apply(src.read_bytes()))


if __name__ == "__main__":
    main()
