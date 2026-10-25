"""Run the narration renderer (0x80182860) on an emulated R3000 and check its uploads.

The real EXE code runs under unicorn. The BIOS font is a synthetic pattern, and
calls into the window lookup, the Kanji ROM lookup and LoadImage are stubbed, so
every glyph upload (VRAM rect + 4bpp pixels) can be checked exactly.
Needs: pip install unicorn keystone-engine. Run: python -m unittest discover tests
"""
import struct
import sys
import unittest
from pathlib import Path

from unicorn import UC_ARCH_MIPS, UC_HOOK_CODE, UC_MODE_32, UC_MODE_LITTLE_ENDIAN, Uc
from unicorn import mips_const as R

ROOT = Path(__file__).resolve().parent.parent
EXE_PATH = ROOT / "extracted" / "files" / "SLPS_021.07"
sys.path.insert(0, str(ROOT / "tools"))

LOAD, GP = 0x80170000, 0x801DFC58
RENDER = 0x80182860
WINDOW, ORIGIN, STRING, KANJI = 0x80100000, 0x80100100, 0x80100200, 0x80100400
SENTINEL = 0x80000100
ORIGIN_X, ORIGIN_Y, COLOUR = 0x200, 0x100, 7
HALF_FONT = 0xBFC7F8DE


def P(addr):
    """unicorn translates kseg0/kseg1 itself: memory is mapped and accessed physically."""
    return addr & 0x1FFFFFFF


def font_byte(code, row):
    """Synthetic 8x15 BIOS font: a distinct byte for every glyph row."""
    return (code * 7 + row * 13 + 1) & 0xFF


def kanji_bytes(sjis):
    return bytes((sjis * 3 + i * 5) & 0xFF for i in range(30))


def expand(rows, width_bytes):
    """Expected 4bpp buffer for 15 glyph rows (+1 blank row)."""
    out = bytearray()
    for r in range(16):
        for k in range(width_bytes):
            b = rows[r * width_bytes + k] if r < 15 else 0
            word = 0
            for i in range(8):
                if b & (0x80 >> i):
                    word |= COLOUR << (4 * i)
            out += struct.pack("<I", word)
    return bytes(out)


class Machine:
    def __init__(self, exe):
        self.uc = uc = Uc(UC_ARCH_MIPS, UC_MODE_32 | UC_MODE_LITTLE_ENDIAN)
        uc.mem_map(P(0x80000000), 0x200000)
        uc.mem_map(P(0xBFC00000), 0x80000)
        uc.mem_write(P(LOAD), exe[0x800:])
        rom = bytearray(0x80000)
        for c in range(0x21, 0x80):
            for r in range(15):
                rom[HALF_FONT - 0xBFC00000 + (c - 0x21) * 15 + r] = font_byte(c, r)
        uc.mem_write(P(0xBFC00000), bytes(rom))
        uc.mem_write(P(WINDOW + 0x1C), struct.pack("<I", ORIGIN))
        uc.mem_write(P(ORIGIN), struct.pack("<HH", ORIGIN_X, ORIGIN_Y))
        self.uploads, self.kanji = [], []
        stubs = {0x801A44B8: self.window, 0x801B1370: self.krom, 0x801B05A8: self.load_image,
                 0x80184160: self.ret0, 0x801A4A68: self.ret0}
        uc.hook_add(UC_HOOK_CODE, lambda uc, addr, size, _: self.hook(addr, stubs))

    def hook(self, addr, stubs):
        if addr == SENTINEL:
            self.uc.emu_stop()
        elif addr in stubs:
            stubs[addr]()
            self.uc.reg_write(R.UC_MIPS_REG_PC, self.uc.reg_read(R.UC_MIPS_REG_RA))

    def ret0(self):
        self.uc.reg_write(R.UC_MIPS_REG_V0, 0)

    def window(self):
        self.uc.reg_write(R.UC_MIPS_REG_V0, WINDOW)

    def krom(self):
        code = self.uc.reg_read(R.UC_MIPS_REG_A0) & 0xFFFF
        self.kanji.append(code)
        self.uc.mem_write(P(KANJI), kanji_bytes(code))
        self.uc.reg_write(R.UC_MIPS_REG_V0, KANJI)

    def load_image(self):
        rect = self.uc.reg_read(R.UC_MIPS_REG_A0)
        buf = self.uc.reg_read(R.UC_MIPS_REG_A1)
        x, y, w, h = struct.unpack("<4h", self.uc.mem_read(P(rect), 8))
        self.uploads.append((x, y, w, h, bytes(self.uc.mem_read(P(buf), w * h * 2))))

    def g(self, off, fmt="<h"):
        return struct.unpack(fmt, self.uc.mem_read(P(GP + off), 2))[0]

    def render(self, text):
        """Call the renderer like the game's per-frame typewriter until the string ends."""
        uc = self.uc
        uc.mem_write(P(STRING), text + b"\0")
        for off, v in ((0x218, 0), (0x21A, 0), (0x21C, COLOUR), (0x21E, len(text)), (0x220, 0)):
            uc.mem_write(P(GP + off), struct.pack("<h", v))
        for _ in range(len(text) + 2):
            if self.g(0x220) >= len(text):
                break
            uc.reg_write(R.UC_MIPS_REG_GP, GP)
            uc.reg_write(R.UC_MIPS_REG_SP, 0x801FF000)
            uc.reg_write(R.UC_MIPS_REG_RA, SENTINEL)
            uc.reg_write(R.UC_MIPS_REG_A0, STRING)
            uc.reg_write(R.UC_MIPS_REG_A1, 0)
            uc.emu_start(RENDER, SENTINEL, count=200000)
        return self.uploads


@unittest.skipUnless(EXE_PATH.exists(), "needs the extracted disc")
class NarrationRenderer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import patch_exe
        cls.retail = EXE_PATH.read_bytes()
        cls.patched = patch_exe.apply(cls.retail)

    def test_harness_reproduces_retail(self):
        m = Machine(self.retail)
        ups = m.render("あい".encode("cp932"))
        self.assertEqual([(x, y, w, h) for x, y, w, h, _ in ups],
                         [(ORIGIN_X, ORIGIN_Y, 4, 16), (ORIGIN_X + 4, ORIGIN_Y, 4, 16)])
        self.assertEqual(ups[0][4], expand(kanji_bytes(0x82A0), 2))

    def test_mixed_half_and_full_width(self):
        m = Machine(self.patched)
        text = bytes([0xC8, 0xE9, 0xA0]) + "あ".encode("cp932") + bytes([0xA1])   # "Hi", half space, あ, "!"
        ups = m.render(text)
        self.assertEqual([(x, y, w, h) for x, y, w, h, _ in ups], [
            (ORIGIN_X + 0, ORIGIN_Y, 2, 16),     # H at col 0
            (ORIGIN_X + 2, ORIGIN_Y, 2, 16),     # i at col 1
            (ORIGIN_X + 6, ORIGIN_Y, 4, 16),     # あ at col 3 (after the half space)
            (ORIGIN_X + 10, ORIGIN_Y, 2, 16),    # ! at col 5
        ])
        half = lambda c: expand([font_byte(c, r) for r in range(15)], 1)
        self.assertEqual(ups[0][4], half(ord("H")))
        self.assertEqual(ups[1][4], half(ord("i")))
        self.assertEqual(ups[2][4], expand(kanji_bytes(0x82A0), 2))
        self.assertEqual(ups[3][4], half(ord("!")))
        self.assertEqual((m.g(0x218), m.g(0x220)), (6, len(text)))

    def test_full_width_keeps_retail_spacing(self):
        m = Machine(self.patched)
        ups = m.render("あ い".encode("cp932"))     # full-width chars around the game's full-cell space
        self.assertEqual([x for x, *_ in ups], [ORIGIN_X, ORIGIN_X + 8])

    def test_wraps_at_32_half_cells(self):
        m = Machine(self.patched)
        ups = m.render(bytes([0xC1]) * 33)       # 33 x "A"
        self.assertEqual((ups[31][0], ups[31][1]), (ORIGIN_X + 62, ORIGIN_Y))
        self.assertEqual((ups[32][0], ups[32][1]), (ORIGIN_X, ORIGIN_Y + 16))


if __name__ == "__main__":
    unittest.main()
