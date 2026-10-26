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
# TYPEWRITER_SPEED glyphs per call and stops as soon as the typewriter returns non-zero
# (page full, string done). It lives in the free tail of the narration block.
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

# Weapon name renderer 0x8018C864 (attack analysis, weapon lists): the name is the RES.R
# WEPN record's +4 field. Retail squashes each 16 px Kanji ROM glyph into an 8x15 cell
# (2 source pixels -> 1: both set 2, both clear 0xE, mixed 0xA) and draws 12 cells,
# blanking the ones past the end with 0xEE. Patched: the same, but a byte in 0xA1-0xFE is
# one cell from the BIOS 8x15 font (2 / 0xE) and 0xA0 a blank cell, so 12 half-width
# characters fit. s4 record, s2 byte index, s3 cells drawn, rect at 0x10(sp) (w 2, h 15),
# buffer at 0x18(sp). Entry at 0x8018C8E4 with v0 = strlen; exits to the epilogue.
WEAPON_CELLS = 12
WEAPON_DRAW = f"""
    or    $s1, $v0, $zero           # string length
    or    $s3, $zero, $zero         # cells drawn
wd_cell:
    slt   $v0, $s2, $s1
    beq   $v0, $zero, wd_blank
    addiu $s0, $sp, 0x18
    addu  $t0, $s4, $s2
    lbu   $a0, 4($t0)
    lbu   $t1, 5($t0)
    sltiu $t2, $a0, 0xA0
    bne   $t2, $zero, wd_full
    addiu $t2, $a0, -0xA1
    bltz  $t2, wd_blank             # 0xA0: half space
    addiu $s2, $s2, 1
    sll   $t3, $t2, 4
    subu  $t3, $t3, $t2             # (c - 0xA1) * 15
    lui   $t9, 0xBFC8
    addiu $t9, $t9, -0x722          # 0xBFC7F8DE
    addu  $t9, $t9, $t3
    beq   $zero, $zero, wd_draw
    addiu $t8, $zero, 1             # 1 byte per row, 1 bit per pixel
wd_full:
    sll   $a0, $a0, 8
    jal   {KROM:#x}
    or    $a0, $a0, $t1
    or    $t9, $v0, $zero
    addiu $s2, $s2, 2
    addiu $t8, $zero, 2             # 2 bytes per row, 2 bits per pixel
wd_draw:
    addiu $t7, $zero, 15            # rows
wd_row:
    or    $t5, $zero, $zero         # 8 pixels, 4bpp
    or    $t6, $zero, $zero         # nibble shift
    or    $t4, $t8, $zero           # bytes left in this row
wd_byte:
    lbu   $t3, 0($t9)
    addiu $t9, $t9, 1
    addiu $t2, $zero, 0x80          # bit mask, MSB = left
wd_px:
    and   $a1, $t3, $t2
    srl   $t2, $t2, 1
    addiu $a2, $zero, 1
    beq   $t8, $a2, wd_one
    sltu  $a1, $zero, $a1           # first bit
    and   $a3, $t3, $t2
    srl   $t2, $t2, 1
    sltu  $a3, $zero, $a3           # second bit
    bne   $a1, $a3, wd_nib
    addiu $a2, $zero, 0xA           # mixed: grey
wd_one:
    addiu $a2, $zero, 0xE
    beq   $a1, $zero, wd_nib
    nop
    addiu $a2, $zero, 2
wd_nib:
    sllv  $a2, $a2, $t6
    or    $t5, $t5, $a2
    bne   $t2, $zero, wd_px
    addiu $t6, $t6, 4
    addiu $t4, $t4, -1
    bne   $t4, $zero, wd_byte
    nop
    sw    $t5, 0($s0)
    addiu $t7, $t7, -1
    bne   $t7, $zero, wd_row
    addiu $s0, $s0, 4
    beq   $zero, $zero, wd_upload
    nop
wd_blank:
    addiu $a0, $sp, 0x18
    addiu $a1, $zero, 0xEE
    jal   0x801ACE00                # memset(buffer, 0xEE, 0x40)
    addiu $a2, $zero, 0x40
wd_upload:
    addiu $a0, $sp, 0x10
    jal   {LOAD_IMAGE:#x}           # LoadImage(rect, buffer)
    addiu $a1, $sp, 0x18
    lhu   $v0, 0x10($sp)
    addiu $s3, $s3, 1
    addiu $v0, $v0, 2               # next cell: 8 px
    sh    $v0, 0x10($sp)
    slti  $v0, $s3, {WEAPON_CELLS}
    bne   $v0, $zero, wd_cell
    nop
    j     0x8018CB50
    nop
"""

# Buttons in analog mode. The game reads the pad through libetc PadRead (0x801CCA40), which calls
# a BIOS routine (B0:0x16) that fills the word at 0x801E6DC0 from the pad buffer 0x80007570, but
# only for a digital pad (ID 0x41) or a neGcon (0x23). An analog pad (0x73) leaves the word at
# 0xFFFFFFFF, so no button registers at all while analog mode is on (found: Circle and every other
# button stopped working once the sticks were enabled). This wrapper runs the BIOS call and then,
# for ID 0x73, stores the two button bytes the way the BIOS does: halfword = (buf[2] << 8) | buf[3].
BIOS_PAD = 0x801CCA94           # stub that jumps to the BIOS B0 table, function 0x16
PAD_READ_CALL = 0x801CCA48      # inside PadRead
PAD_FIX_ASM = f"""
    addiu $sp, $sp, -24
    sw    $ra, 16($sp)
    jal   {BIOS_PAD:#x}
    nop
    lui   $t0, 0x8000
    ori   $t0, $t0, 0x7570          # BIOS pad buffer, port 1
    lbu   $t1, 1($t0)
    addiu $t2, $zero, 0x73
    bne   $t1, $t2, f_done          # only an analog pad needs this
    nop
    lbu   $t1, 0($t0)
    nop
    bne   $t1, $zero, f_done        # status: no pad answered
    nop
    lbu   $t3, 2($t0)
    lbu   $t4, 3($t0)
    nop
    sll   $t3, $t3, 8
    or    $t3, $t3, $t4
    lui   $t5, 0x801E
    sh    $t3, 0x6DC0($t5)
f_done:
    lw    $ra, 16($sp)
    nop
    jr    $ra
    addiu $sp, $sp, 24
"""

# Analog sticks (prototype). The game only reads the digital buttons, but an analog pad in analog
# mode (ID 0x73) also leaves the sticks in the BIOS pad buffer: 0x80007570 +4 RX, +5 RY, +6 LX,
# +7 LY (0x80 = centre). The movement function 0x80199548 (docs/controls.md) is called from
# 0x801A8880, 0x801942E4 and 0x8017DF7C; those calls go through this wrapper, which runs it and then adds the sticks on top,
# standard dual-stick layout:
#   right stick X -> yaw (+0x6E)          like the Left/Right buttons
#   right stick Y -> pitch (+0x6C)        like Up/Down, kept inside the game's range -25..65
#   left stick Y  -> forward (+0x50)      like Triangle/Cross
#   left stick X  -> strafe (+0x4E)       like L1/R1
# Digital pads (ID 0x41) and the look-offset mode (+0x46 != 0) are left alone. The code replaces
# GsSetFlatLight (0x801B1F90-0x801B2500), which nothing in the game calls.
MOVE = 0x80199548
MOVE_CALLS = [0x801A8880, 0x801942E4, 0x8017DF7C]   # city (a1 = 2), office (0), a1 = 1
STICK_BLOCK, STICK_BLOCK_END = 0x801B1F90, 0x801B2500
STICK_DEADZONE = 24             # raw stick units around the centre that are ignored
STICK_YAW_SHIFT = 5             # yaw += stick * dt >> 5 (the pad adds dt per frame)
STICK_PITCH_SHIFT = 6
PITCH_MIN, PITCH_MAX = -25, 65  # where the Up/Down buttons stop
STICK_RUN, STICK_STRAFE = 11, 6  # velocity at full deflection = n * dt (pad: walk 4, run 11, strafe 6)


def stick(axis, label):
    """Leave the centred raw stick byte `axis` of the pad buffer in $t4 (signed), skipping to
    `label` inside the dead zone."""
    return f"""
    lbu   $t4, {axis}($t0)
    nop
    addiu $t4, $t4, -0x80
    addiu $t5, $t4, {STICK_DEADZONE}
    sltiu $t5, $t5, {2 * STICK_DEADZONE + 1}
    bne   $t5, $zero, {label}
    nop"""


STICK_WRAPPER = f"""
    addiu $sp, $sp, -32
    sw    $ra, 24($sp)
    sw    $s0, 16($sp)
    jal   {MOVE:#x}
    or    $s0, $a0, $zero           # the controller state (its +0x5C is the player struct)
    lui   $t0, 0x8000
    ori   $t0, $t0, 0x7570          # BIOS pad buffer, port 1
    lbu   $t1, 1($t0)
    addiu $t2, $zero, 0x73
    bne   $t1, $t2, k_done          # not in analog mode
    nop
    lw    $t1, 0x5C($s0)            # player struct
    nop
    beq   $t1, $zero, k_done
    nop
    lhu   $t2, 0x46($t1)
    nop
    bne   $t2, $zero, k_done        # look-offset mode
    lui   $t3, 0x801E
    lw    $t3, 0x6DB4($t3)          # time step
    nop
{stick(4, "k_ry")}
    mult  $t4, $t3
    mflo  $t5
    sra   $t5, $t5, {STICK_YAW_SHIFT}
    lhu   $t6, 0x6E($t1)
    nop
    addu  $t6, $t6, $t5             # stick right = Right button: yaw up
    sh    $t6, 0x6E($t1)
    addiu $t6, $zero, 1
    sh    $t6, 0x3C($t1)            # "moving this frame": the view only updates with it set
k_ry:
{stick(5, "k_ly")}
    mult  $t4, $t3
    mflo  $t5
    sra   $t5, $t5, {STICK_PITCH_SHIFT}
    lh    $t6, 0x6C($t1)
    nop
    subu  $t6, $t6, $t5             # stick up = Up button: pitch up
    slti  $t7, $t6, {PITCH_MAX + 1}
    bne   $t7, $zero, k_pmax
    nop
    addiu $t6, $zero, {PITCH_MAX}
k_pmax:
    slti  $t7, $t6, {PITCH_MIN}
    beq   $t7, $zero, k_pmin
    nop
    addiu $t6, $zero, {PITCH_MIN}
k_pmin:
    sh    $t6, 0x6C($t1)
    addiu $t6, $zero, 1
    sh    $t6, 0x3C($t1)
k_ly:
{stick(7, "k_lx")}
    subu  $t4, $zero, $t4           # stick up = forward = positive
    mult  $t4, $t3
    mflo  $t5
    addiu $t6, $zero, {STICK_RUN}
    mult  $t5, $t6
    mflo  $t5
    sra   $t5, $t5, 7
    sh    $t5, 0x50($t1)
    addiu $t6, $zero, 1
    sh    $t6, 0x3C($t1)            # "moving this frame"
k_lx:
{stick(6, "k_done")}
    mult  $t4, $t3
    mflo  $t5
    addiu $t6, $zero, {STICK_STRAFE}
    mult  $t5, $t6
    mflo  $t5
    sra   $t5, $t5, 7
    sh    $t5, 0x4E($t1)          # stick right = R1: positive
    addiu $t6, $zero, 1
    sh    $t6, 0x3C($t1)
k_done:
    lw    $s0, 16($sp)
    lw    $ra, 24($sp)
    nop
    jr    $ra
    addiu $sp, $sp, 32
"""


# (start, end, expected retail first instruction, new code)
PAD_FIX = STICK_BLOCK + len(asm(STICK_WRAPPER, STICK_BLOCK))

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
    # weapon name renderer
    (0x8018C8E4, 0x8018CB50, "addu $s1, $v0, $zero", WEAPON_DRAW),
    # analog sticks: wrapper in the dead GsSetFlatLight, reached from the movement call site
    (STICK_BLOCK, STICK_BLOCK_END, "addiu $sp, $sp, -144", STICK_WRAPPER + PAD_FIX_ASM),
    (PAD_READ_CALL, PAD_READ_CALL + 4, f"jal {BIOS_PAD:#x}", f"jal {PAD_FIX:#x}"),
] + [(a, a + 4, f"jal {MOVE:#x}", f"jal {STICK_BLOCK:#x}") for a in MOVE_CALLS] + [
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
