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


LOAD_IMAGE, STORE_IMAGE, KROM = 0x801B05A8, 0x801B0694, 0x801B1370


def glyph_routine(p, *, ptr, col, row_y, window, composite, half_space, advance):
    """Half-width aware replacement for a renderer's unrolled glyph block.

    Columns count 8 px half-cells: a full-width SJIS character advances 2, a byte in
    0xA1-0xFE advances 1 and draws ASCII (byte - 0x80) from the BIOS 8x15 font at
    0xBFC7F8DE (15 bytes per glyph, MSB = left pixel); 0xA0 is a half-width space.
    On exit s0 = width in bytes (= columns advanced = bytes consumed).

    p          label prefix (labels must be unique per patch)
    ptr        register holding the character pointer on entry
    col        asm leaving the column in $t1 (may end in a load: a nop follows)
    row_y      asm leaving the y offset from the page origin in $t1
    window     register holding the window object (+0x1C -> page origin x, y)
    composite  read the existing pixels first (StoreImage) and draw over them,
               instead of drawing onto a cleared cell
    half_space asm for 0xA0, ending in a jump
    advance    asm run after the upload, ending in a jump
    Uses t0-t9, a0-a3, v0, s0, s1 (the retail block used s0/s1 as scratch too).
    """
    keep = "lw    $t5, 0($t2)" if composite else "addiu $t5, $zero, 0"
    read_back = f"""
    addiu $a0, $sp, 0x10
    jal   {STORE_IMAGE:#x}          # StoreImage: start from the pixels underneath
    addiu $a1, $sp, 0x18""" if composite else ""
    return f"""
    lbu   $t0, 0({ptr})
    nop
    sltiu $t1, $t0, 0xA0
    bne   $t1, $zero, {p}full
    sltiu $t1, $t0, 0xA1
    beq   $t1, $zero, {p}half
    nop
{half_space}
{p}half:
    addiu $t0, $t0, -0xA1
    sll   $t1, $t0, 4
    subu  $t1, $t1, $t0             # (c - 0xA1) * 15
    lui   $s1, 0xBFC8
    addiu $s1, $s1, -0x722          # 0xBFC7F8DE
    addu  $s1, $s1, $t1
    beq   $zero, $zero, {p}rect
    addiu $s0, $zero, 1             # 1 byte per glyph row
{p}full:
    lbu   $t1, 1({ptr})
    sll   $a0, $t0, 8
    jal   {KROM:#x}                 # Kanji ROM lookup -> 15 rows of 2 bytes
    or    $a0, $a0, $t1
    or    $s1, $v0, $zero
    addiu $s0, $zero, 2             # 2 bytes per glyph row
{p}rect:
    lw    $t0, 0x1C({window})       # text page origin in VRAM
    {col}
    nop
    lhu   $t2, 0($t0)
    sll   $t1, $t1, 1
    addu  $t2, $t2, $t1
    sh    $t2, 0x10($sp)            # x = origin + col * 2 (VRAM halfwords)
    {row_y}
    nop
    lhu   $t2, 2($t0)
    nop
    addu  $t2, $t2, $t1
    sh    $t2, 0x12($sp)            # y = origin + row offset
    sll   $t1, $s0, 1
    sh    $t1, 0x14($sp)            # w = 2 or 4 halfwords (h = 16, set by the caller)
{read_back}
    lhu   $t7, 0x21C($gp)           # colour
    addiu $t2, $sp, 0x18            # 4bpp buffer
    addiu $t3, $zero, 16            # rows
{p}row_loop:
    or    $t4, $s0, $zero
{p}byte_loop:
    {keep}
    addiu $t8, $zero, 1
    beq   $t3, $t8, {p}store        # 16th row: no glyph data
    nop
    lbu   $t6, 0($s1)
    addiu $s1, $s1, 1
    addiu $t8, $zero, 0x80
    or    $t9, $t7, $zero
    addiu $a2, $zero, 0xF           # nibble mask
{p}bit_loop:
    and   $a1, $t6, $t8
    beq   $a1, $zero, {p}skip
    srl   $t8, $t8, 1
    nor   $a3, $a2, $zero
    and   $t5, $t5, $a3
    or    $t5, $t5, $t9
{p}skip:
    sll   $a2, $a2, 4
    bne   $t8, $zero, {p}bit_loop
    sll   $t9, $t9, 4
{p}store:
    sw    $t5, 0($t2)
    addiu $t4, $t4, -1
    bne   $t4, $zero, {p}byte_loop
    addiu $t2, $t2, 4
    addiu $t3, $t3, -1
    bne   $t3, $zero, {p}row_loop
    nop
    addiu $a0, $sp, 0x10
    jal   {LOAD_IMAGE:#x}           # LoadImage(rect, buffer)
    addiu $a1, $sp, 0x18
{advance}
"""


# Narration typewriter 0x80182860: one glyph per call, state in gp globals
# (+0x218 col, +0x21A row, +0x220 index). Entry at 0x801829DC with v1 = char pointer.
NARRATION_DRAW = glyph_routine(
    "n_", ptr="$v1", window="$s2", composite=False,
    col="lh    $t1, 0x218($gp)",
    row_y="lh    $t1, 0x21A($gp)\n    nop\n    sll   $t1, $t1, 4",
    half_space="""
    lhu   $t2, 0x218($gp)           # 0xA0: half space, like the game's 0x20 path
    lhu   $t3, 0x220($gp)
    addiu $t2, $t2, 1
    addiu $t3, $t3, 1
    sh    $t2, 0x218($gp)
    sh    $t3, 0x220($gp)
    j     0x801828AC
    lui   $v0, 0x801E""",
    advance="""
    lhu   $t0, 0x218($gp)           # the code at 0x80182BEC adds col+1, index+2:
    lhu   $t1, 0x220($gp)           # pre-adjust so the totals are +s0 for both
    addu  $t0, $t0, $s0
    addu  $t1, $t1, $s0
    addiu $t0, $t0, -1
    addiu $t1, $t1, -2
    sh    $t0, 0x218($gp)
    j     0x80182BEC
    sh    $t1, 0x220($gp)""")

# Typewriter speed. English has about twice the glyphs of the Japanese, so one glyph per
# frame was too slow. Callers of 0x80182860 go through this wrapper instead. It draws up to
# TYPEWRITER_SPEED glyphs per call, or finishes the page while Circle is held. It stops as
# soon as the typewriter returns non-zero (page full, string done). Circle comes from the raw
# pad buffer the BIOS fills at 0x80007570: byte 0 = 0 when a pad answered, byte 3 bit 5 = Circle
# (active low). The wrapper lives in the free tail of the narration block.
#
# Timed narration: the opening runs alongside a timer that brings in the office. If the
# text finishes early, the office never loads (the same hang as a too-short translation).
# Such strings keep the retail pace: the inserter writes the marker FE FF right after their
# terminator (layout.TIMED), and the retail Japanese ones are recognised by length.
TYPEWRITER = 0x80182860
TYPEWRITER_SPEED = 3
NARRATION_BLOCK = 0x801829DC
TYPEWRITER_CALLERS = [0x80183588, 0x80183C18, 0x80183E40, 0x801842C0, 0x801843EC]
TIMED_MARKER = (0xFE, 0xFF)
RETAIL_TIMED_LENGTHS = (567, 495)        # SCE.S:59008 opening, SCE.S:59808 ending
WRAPPER = f"""
    addiu $sp, $sp, -32
    sw    $ra, 28($sp)
    sw    $s0, 24($sp)
    sw    $s1, 20($sp)
    sw    $s2, 16($sp)
    or    $s1, $a0, $zero
    or    $s2, $a1, $zero
    addiu $s0, $zero, 1             # timed narration: retail pace, no skipping
    lh    $t3, 0x21E($gp)           # string length
    addiu $t7, $zero, {RETAIL_TIMED_LENGTHS[0]}
    beq   $t3, $t7, w_loop
    addiu $t7, $zero, {RETAIL_TIMED_LENGTHS[1]}
    beq   $t3, $t7, w_loop
    addu  $t4, $s1, $t3
    lbu   $t5, 1($t4)               # bytes after the terminator
    lbu   $t6, 2($t4)
    addiu $t7, $zero, {TIMED_MARKER[0]}
    bne   $t5, $t7, w_fast
    addiu $t7, $zero, {TIMED_MARKER[1]}
    beq   $t6, $t7, w_loop
    nop
w_fast:
    addiu $s0, $zero, {TYPEWRITER_SPEED}
    lui   $t0, 0x8000
    lbu   $t1, 0x7573($t0)          # buttons byte 2 (active low)
    lbu   $t2, 0x7570($t0)          # pad status: 0 = answered
    nop
    andi  $t1, $t1, 0x20            # Circle (0 = held)
    or    $t1, $t1, $t2             # held only if a pad answered too
    bne   $t1, $zero, w_loop
    nop
    addiu $s0, $zero, 200           # held: finish the page now
w_loop:
    or    $a0, $s1, $zero
    jal   {TYPEWRITER:#x}
    or    $a1, $s2, $zero
    addiu $s0, $s0, -1
    bne   $v0, $zero, w_done        # page full or string done: stop for this frame
    nop
    bne   $s0, $zero, w_loop
    nop
w_done:
    lw    $ra, 28($sp)
    lw    $s0, 24($sp)
    lw    $s1, 20($sp)
    lw    $s2, 16($sp)
    jr    $ra
    addiu $sp, $sp, 32
"""


def narration_block():
    """The glyph routine, then the typewriter wrapper right after it."""
    return NARRATION_DRAW + WRAPPER


TYPEWRITER_WRAPPER = NARRATION_BLOCK + len(asm(NARRATION_DRAW, NARRATION_BLOCK))


# Whole-string renderer 0x80182518 (menus/choices): draws the string at once into a
# cleared window. s2 col, s4 row, s3 index, fp string, s6 window, row limit at
# 0x98(sp). Entry at 0x80182604 with a1 = char pointer; loop test at 0x80182824.
MENU_DRAW = glyph_routine(
    "m_", ptr="$a1", window="$s6", composite=False,
    col="or    $t1, $s2, $zero",
    row_y="sll   $t1, $s4, 4",
    half_space="""
    addiu $s2, $s2, 1               # 0xA0: half space
    j     0x80182824
    addiu $s3, $s3, 1""",
    advance="""
    addu  $s2, $s2, $s0
    slti  $v0, $s2, 0x20            # wrap after 32 half-cells
    bne   $v0, $zero, m_next
    addu  $s3, $s3, $s0
    or    $s2, $zero, $zero
    addiu $s4, $s4, 1
m_next:
    j     0x80182824
    nop""")

# Centred panel renderer 0x80182D34 (4-line info panel): composites onto the
# background. s2 col, s5 line, s7 line y (table at 0x801D76A4), s3 index, s6 window.
# Entry at 0x80182E24 with a1 = char pointer; the code at 0x80183020 adds col+1 (and
# wraps lines >= 3 at col 15, patched to 30), then 0x80183060 adds index+2.
PANEL_DRAW = glyph_routine(
    "p_", ptr="$a1", window="$s6", composite=True,
    col="or    $t1, $s2, $zero",
    row_y="or    $t1, $s7, $zero",
    half_space="""
    addiu $s2, $s2, 1               # 0xA0: half space
    j     0x80183064
    addiu $s3, $s3, 1""",
    advance="""
    addu  $s2, $s2, $s0             # pre-adjust: totals become col+s0, index+s0
    addiu $s2, $s2, -1
    addu  $s3, $s3, $s0
    j     0x80183020
    addiu $s3, $s3, -2""")

# (start, end, expected retail first instruction, new code)
PATCHES = [
    # narration typewriter
    (0x801828E8, 0x801828EC, "slti $v0, $v0, 0x10", "slti $v0, $v0, 0x20"),
    (0x801829A8, 0x801829AC, "addiu $v0, $v0, 1", "addiu $v0, $v0, 2"),
    (NARRATION_BLOCK, 0x80182BEC, "addiu $s0, $sp, 0x18", narration_block()),
    (0x80182C40, 0x80182C44, "slti $v0, $v0, 0x10", "slti $v0, $v0, 0x20"),
    (0x80182CD0, 0x80182CD4, "slti $v0, $v0, 0x10", "slti $v0, $v0, 0x20"),
    # whole-string menu renderer
    (0x801825E8, 0x801825EC, "addiu $s2, $s2, 1", "addiu $s2, $s2, 2"),      # 0x20 = full cell
    (0x80182604, 0x80182808, "addiu $s0, $sp, 0x18", MENU_DRAW),
    # centred panel renderer
    (0x80182DC0, 0x80182DC4, "sra $s2, $v0, 2", "sra $s2, $v0, 1"),          # centre in half-cells
    (0x80182DC4, 0x80182DC8, "addiu $v0, $v0, 3", "addiu $v0, $v0, 1"),
    (0x80182DCC, 0x80182DD0, "sra $s2, $v0, 2", "sra $s2, $v0, 1"),
    (0x80182DD0, 0x80182DD4, "addiu $s2, $zero, 1", "addiu $s2, $zero, 2"),  # lines 2+: indent
    (0x80182E20, 0x80182E24, "addiu $s2, $s2, 1", "addiu $s2, $s2, 2"),      # 0x20 = full cell
    (0x80182E24, 0x80183020, "addiu $s0, $sp, 0x18", PANEL_DRAW),
    (0x80183034, 0x80183038, "slti $v0, $s2, 0xf", "slti $v0, $s2, 0x1e"),
    (0x80183040, 0x80183044, "addiu $s2, $zero, 1", "addiu $s2, $zero, 2"),
    (0x80183044, 0x80183048, "addu $v0, $s5, $s2", "addiu $v0, $s5, 1"),    # next line (retail reused s2 = 1)
] + [(a, a + 4, f"jal {TYPEWRITER:#x}", f"jal {TYPEWRITER_WRAPPER:#x}") for a in TYPEWRITER_CALLERS]


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
