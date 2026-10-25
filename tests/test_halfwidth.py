"""Run the text renderers on an emulated R3000 and check what they draw.

The real EXE code runs under unicorn. The BIOS 8x15 font is a synthetic pattern, the
window lookup / Kanji ROM lookup / LoadImage / StoreImage calls are stubbed, and a
small VRAM model records every halfword written. Each renderer is checked two ways:
  - Japanese text: the patched renderer must leave VRAM exactly as retail does.
  - half-width text: positions, widths and pixels match the BIOS font.
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
NARRATION, MENU, PANEL = 0x80182860, 0x80182518, 0x80182D34
WINDOW, ORIGIN, STRING, KANJI = 0x80100000, 0x80100100, 0x80100200, 0x80100400
SENTINEL = 0x80000100
ORIGIN_X, ORIGIN_Y, COLOUR = 0x200, 0x100, 7
HALF_FONT = 0xBFC7F8DE
PANEL_LINE_Y = 0x801D76A4      # retail table of panel line y offsets


def P(addr):
    """unicorn translates kseg0/kseg1 itself: memory is mapped and accessed physically."""
    return addr & 0x1FFFFFFF


def font_byte(code, row):
    """Synthetic 8x15 BIOS font: a distinct byte for every glyph row."""
    return (code * 7 + row * 13 + 1) & 0xFF


def kanji_bytes(sjis):
    return bytes((sjis * 3 + i * 5) & 0xFF for i in range(30))


def background(x, y):
    return (x * 0x1F + y * 0x0B5) & 0xFFFF


def expand(rows, width_bytes):
    """Expected 4bpp buffer for 15 glyph rows (+1 blank row) drawn on a cleared cell."""
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


def half_rows(c):
    return [font_byte(c, r) for r in range(15)]


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
        uc.mem_write(P(ORIGIN), struct.pack("<HHHH", ORIGIN_X, ORIGIN_Y, 0x40, 0x40))
        self.uploads, self.vram = [], {}
        stubs = {0x801A44B8: self.window, 0x801B1370: self.krom, 0x801B05A8: self.load_image,
                 0x801B0694: self.store_image, 0x80184160: self.ret0, 0x801A4A68: self.ret0}
        uc.hook_add(UC_HOOK_CODE, lambda uc, addr, size, _: self.hook(addr, stubs))

    def hook(self, addr, stubs):
        if addr == SENTINEL:
            self.uc.emu_stop()
        elif addr in stubs:
            stubs[addr]()
            self.uc.reg_write(R.UC_MIPS_REG_PC, self.uc.reg_read(R.UC_MIPS_REG_RA))

    def reg(self, r):
        return self.uc.reg_read(r)

    def ret0(self):
        self.uc.reg_write(R.UC_MIPS_REG_V0, 0)

    def window(self):
        self.uc.reg_write(R.UC_MIPS_REG_V0, WINDOW)

    def krom(self):
        self.uc.mem_write(P(KANJI), kanji_bytes(self.reg(R.UC_MIPS_REG_A0) & 0xFFFF))
        self.uc.reg_write(R.UC_MIPS_REG_V0, KANJI)

    def rect(self):
        return struct.unpack("<4h", self.uc.mem_read(P(self.reg(R.UC_MIPS_REG_A0)), 8))

    def load_image(self):
        x, y, w, h = self.rect()
        data = bytes(self.uc.mem_read(P(self.reg(R.UC_MIPS_REG_A1)), w * h * 2))
        self.uploads.append((x, y, w, h, data))
        for j in range(h):
            for i in range(w):
                self.vram[(x + i, y + j)] = struct.unpack_from("<H", data, (j * w + i) * 2)[0]

    def store_image(self):
        x, y, w, h = self.rect()
        data = b"".join(struct.pack("<H", self.vram.get((x + i, y + j), background(x + i, y + j)))
                        for j in range(h) for i in range(w))
        self.uc.mem_write(P(self.reg(R.UC_MIPS_REG_A1)), data)

    def g(self, off):
        return struct.unpack("<h", self.uc.mem_read(P(GP + off), 2))[0]

    def call(self, func, a1):
        uc = self.uc
        uc.reg_write(R.UC_MIPS_REG_GP, GP)
        uc.reg_write(R.UC_MIPS_REG_SP, 0x801FF000)
        uc.reg_write(R.UC_MIPS_REG_RA, SENTINEL)
        uc.reg_write(R.UC_MIPS_REG_A0, STRING)
        uc.reg_write(R.UC_MIPS_REG_A1, a1)
        uc.emu_start(func, SENTINEL, count=2000000)

    def set_text(self, text):
        self.uc.mem_write(P(STRING), text + b"\0")
        self.uc.mem_write(P(GP + 0x21C), struct.pack("<h", COLOUR))

    def narrate(self, text):
        """Call the typewriter like the game does, once per frame, until the string ends."""
        self.set_text(text)
        for off, v in ((0x218, 0), (0x21A, 0), (0x21E, len(text)), (0x220, 0)):
            self.uc.mem_write(P(GP + off), struct.pack("<h", v))
        for _ in range(len(text) + 2):
            if self.g(0x220) >= len(text):
                break
            self.call(NARRATION, 0)
        return self.uploads

    def start_typewriter(self, text):
        self.set_text(text)
        for off, v in ((0x218, 0), (0x21A, 0), (0x21E, len(text)), (0x220, 0)):
            self.uc.mem_write(P(GP + off), struct.pack("<h", v))

    def menu(self, text, rows=3):
        self.set_text(text)
        self.call(MENU, rows)
        return self.uploads

    def panel(self, text, line):
        self.set_text(text)
        self.call(PANEL, line)
        return self.uploads


def rects(ups):
    return [(x, y, w, h) for x, y, w, h, _ in ups]


@unittest.skipUnless(EXE_PATH.exists(), "needs the extracted disc")
class RendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import patch_exe
        cls.retail = EXE_PATH.read_bytes()
        cls.patched = patch_exe.apply(cls.retail)
        table = cls.retail[PANEL_LINE_Y - LOAD + 0x800:][:32]
        cls.line_y = struct.unpack("<8i", table)

    def assert_same_as_retail(self, run, text):
        old, new = Machine(self.retail), Machine(self.patched)
        run(old, text)
        run(new, text)
        self.assertEqual(new.vram, old.vram)
        self.assertEqual(rects(new.uploads), rects(old.uploads))


class NarrationRenderer(RendererTests):
    def test_harness_reproduces_retail(self):
        ups = Machine(self.retail).narrate("あい".encode("cp932"))
        self.assertEqual(rects(ups), [(ORIGIN_X, ORIGIN_Y, 4, 16), (ORIGIN_X + 4, ORIGIN_Y, 4, 16)])
        self.assertEqual(ups[0][4], expand(kanji_bytes(0x82A0), 2))

    def test_japanese_matches_retail(self):
        self.assert_same_as_retail(Machine.narrate, "8あいう1 え,おか".encode("cp932"))

    def test_mixed_half_and_full_width(self):
        m = Machine(self.patched)
        text = bytes([0xC8, 0xE9, 0xA0]) + "あ".encode("cp932") + bytes([0xA1])   # "Hi", half space, あ, "!"
        ups = m.narrate(text)
        self.assertEqual(rects(ups), [
            (ORIGIN_X + 0, ORIGIN_Y, 2, 16),     # H at col 0
            (ORIGIN_X + 2, ORIGIN_Y, 2, 16),     # i at col 1
            (ORIGIN_X + 6, ORIGIN_Y, 4, 16),     # あ at col 3 (after the half space)
            (ORIGIN_X + 10, ORIGIN_Y, 2, 16),    # ! at col 5
        ])
        self.assertEqual(ups[0][4], expand(half_rows(ord("H")), 1))
        self.assertEqual(ups[1][4], expand(half_rows(ord("i")), 1))
        self.assertEqual(ups[2][4], expand(kanji_bytes(0x82A0), 2))
        self.assertEqual(ups[3][4], expand(half_rows(ord("!")), 1))
        self.assertEqual((m.g(0x218), m.g(0x220)), (6, len(text)))

    def test_wraps_at_32_half_cells(self):
        ups = Machine(self.patched).narrate(bytes([0xC1]) * 33)       # 33 x "A"
        self.assertEqual(ups[31][:2], (ORIGIN_X + 62, ORIGIN_Y))
        self.assertEqual(ups[32][:2], (ORIGIN_X, ORIGIN_Y + 16))


class TypewriterSpeed(RendererTests):
    def wrapper(self):
        import patch_exe
        return patch_exe.TYPEWRITER_WRAPPER

    def test_draws_several_glyphs_per_frame(self):
        import patch_exe
        m = Machine(self.patched)
        m.start_typewriter(bytes([0xC1]) * 10)
        m.call(self.wrapper(), 0)
        self.assertEqual(len(m.uploads), patch_exe.TYPEWRITER_SPEED)
        self.assertEqual(m.g(0x220), patch_exe.TYPEWRITER_SPEED)

    def test_stops_at_end_of_string(self):
        m = Machine(self.patched)
        m.start_typewriter(bytes([0xC1]) * 2)
        m.call(self.wrapper(), 0)
        self.assertEqual(len(m.uploads), 2)

    def test_marked_narration_keeps_retail_pace(self):
        m = Machine(self.patched)
        text = bytes([0xC1]) * 10
        m.start_typewriter(text)
        m.uc.mem_write(P(STRING + len(text) + 1), bytes([0xFE, 0xFF]))
        m.call(self.wrapper(), 0)
        self.assertEqual(len(m.uploads), 1)

    def test_retail_narration_length_keeps_retail_pace(self):
        m = Machine(self.patched)
        m.start_typewriter(bytes([0xC1]) * 567)            # length of the retail opening
        m.call(self.wrapper(), 0)
        self.assertEqual(len(m.uploads), 1)

    def test_callers_use_the_wrapper(self):
        import patch_exe
        for a in patch_exe.TYPEWRITER_CALLERS:
            off = a - LOAD + 0x800
            self.assertEqual(self.patched[off:off + 4], patch_exe.asm(f"jal {self.wrapper():#x}", a))


class MenuRenderer(RendererTests):
    def test_japanese_matches_retail(self):
        text = " 机にむかう        3○, ソファーにすわる     3○, 部屋をでる".encode("cp932")
        self.assert_same_as_retail(Machine.menu, text)

    def test_japanese_wrap_matches_retail(self):
        self.assert_same_as_retail(Machine.menu, ("あ" * 20).encode("cp932"))

    def test_half_width_menu_line(self):
        # " Desk" + half spaces, then the game's 3○ marker, aligned on a half-cell grid
        text = bytes([0xA0]) + bytes(c + 0x80 for c in b"Desk") + bytes([0xA0]) * 3 + b"3" + "○".encode("cp932")
        ups = Machine(self.patched).menu(text)
        self.assertEqual(rects(ups), [(ORIGIN_X + 2 * c, ORIGIN_Y, 2, 16) for c in (1, 2, 3, 4)]
                         + [(ORIGIN_X + 2 * 8, ORIGIN_Y, 4, 16)])
        self.assertEqual(ups[0][4], expand(half_rows(ord("D")), 1))

    def test_half_width_wraps_and_respects_row_limit(self):
        ups = Machine(self.patched).menu(bytes([0xC1]) * 40, rows=1)   # 40 x "A", one row allowed
        self.assertEqual(len(ups), 32)
        self.assertEqual(ups[-1][:2], (ORIGIN_X + 62, ORIGIN_Y))


class PanelRenderer(RendererTests):
    def test_japanese_matches_retail(self):
        # lines 0-1 are centred; retail rounds to whole cells, so use lengths where the
        # half-cell centre lands on a whole cell (see test_centring_differs_from_retail)
        for line, text in enumerate(["名前", "アルバイト記者見習い", "事務所 で働いている。",
                                     "彼の母親は香港の出身らしい。特技はすばやく移動する事。"]):
            with self.subTest(line=line):
                self.assert_same_as_retail(lambda m, t: m.panel(t, line), text.encode("cp932"))

    def test_centring_differs_from_retail_by_half_a_cell(self):
        # intended: an odd number of spare cells is centred exactly, not rounded down
        text = "アルバイト（記者見習）".encode("cp932")                    # 11 cells, 5 spare
        old, new = Machine(self.retail), Machine(self.patched)
        old.panel(text, 1)
        new.panel(text, 1)
        self.assertEqual([x + 2 for x, *_ in old.uploads], [x for x, *_ in new.uploads])

    def test_half_width_is_centred_on_half_cells(self):
        text = bytes(c + 0x80 for c in b"Hello")                        # 5 half-cells
        ups = Machine(self.patched).panel(text, 0)
        start = (32 - 5) >> 1
        self.assertEqual(rects(ups), [(ORIGIN_X + 2 * (start + i), ORIGIN_Y + self.line_y[0], 2, 16)
                                      for i in range(5)])

    def test_profile_description_breaks_between_words(self):
        from insert_script import profile_text
        text = "Works at my office. His mother is said to be from Hong Kong. Good at moving fast."
        raw = profile_text(text)
        ups = Machine(self.patched).panel(raw, 3)
        rows = {}
        for x, y, w, h, _ in ups:
            rows.setdefault(y, []).append(x)
        ys = sorted(rows)
        self.assertGreater(len(ys), 1)
        self.assertEqual(ys, [ORIGIN_Y + self.line_y[i] for i in range(3, 3 + len(ys))])
        import windows
        words_rows = windows.wrap(text, width=windows.PROFILE_ROW,
                                  measure=lambda t: len(t)).split("\n")
        for y, row in zip(ys, words_rows):
            xs = sorted(rows[y])
            self.assertEqual(xs[0], ORIGIN_X + 4)                      # every row starts at col 2
            glyphs = sum(1 for c in row if c != " ")
            self.assertEqual(len([x for x in xs if x < ORIGIN_X + 2 * 28]), glyphs)   # blank pad glyph sits at col 28

    def test_half_width_composites_onto_background(self):
        ups = Machine(self.patched).panel(bytes([0xC1]), 1)              # "A"
        x, y, w, h, data = ups[0]
        for r in range(16):
            word = struct.unpack_from("<I", data, r * 4)[0]
            bg = background(x, y + r) | background(x + 1, y + r) << 16
            glyph = font_byte(ord("A"), r) if r < 15 else 0
            for i in range(8):
                want = COLOUR if glyph & (0x80 >> i) else (bg >> (4 * i)) & 0xF
                self.assertEqual((word >> (4 * i)) & 0xF, want, f"row {r} pixel {i}")


if __name__ == "__main__":
    unittest.main()
