"""TIM round trips, the image font, and drawing English into mail pages, inbox rows and screens."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "extracted" / "files" / "RES.R"
sys.path.insert(0, str(ROOT / "tools"))
import font  # noqa: E402
import images  # noqa: E402
import insert_script  # noqa: E402
import tim  # noqa: E402


class FontTests(unittest.TestCase):
    def test_covers_printable_ascii(self):
        self.assertTrue(all(chr(c) in font.GLYPHS for c in range(0x20, 0x7F)))
        self.assertTrue(all(len(g) == font.HEIGHT for g in font.GLYPHS.values()))

    def test_wrap_respects_width(self):
        lines = font.wrap("word " * 40, 100)
        self.assertTrue(all(font.text_width(l) <= 100 for l in lines))
        with self.assertRaises(ValueError):
            font.wrap("é", 100)


def glyph_boxes(t, inks):
    """Bounding boxes of the 8-connected blobs of the given colours."""
    w = t.width
    todo = {(i % w, i // w) for i, v in enumerate(t.pixels) if v in inks}
    boxes = []
    while todo:
        stack = [todo.pop()]
        xs, ys = [], []
        while stack:
            x, y = stack.pop()
            xs.append(x)
            ys.append(y)
            for q in ((x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                if q in todo:
                    todo.remove(q)
                    stack.append(q)
        boxes.append((min(xs), min(ys), max(xs), max(ys)))
    return boxes


@unittest.skipUnless(RES.exists(), "needs the extracted disc")
class ImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = RES.read_bytes()
        cls.items = images.text_images(cls.res)

    def test_every_tim_round_trips(self):
        from survey import find_tims
        for off, *_ in find_tims(self.res):
            t = tim.parse(self.res, off)
            self.assertEqual(t.to_bytes(), self.res[off:off + t.size], hex(off))

    def test_text_images_found(self):
        kinds = [k for _, k, _ in self.items]
        self.assertEqual((kinds.count("mail page"), kinds.count("inbox row")), (79, 32))

    def test_page_overflow_is_rejected(self):
        t = next(t for _, k, t in self.items if k == "mail page")
        with self.assertRaises(ValueError):
            images.render(t, "line\n" * 9)

    def test_row_keeps_frame_and_checkbox(self):
        t = next(t for _, k, t in self.items if k == "inbox row")
        px = images.render(t, "Fujita | Hello")
        inside = {(x, y) for x0, w in images.ROW_BOXES
                  for x in range(x0, x0 + w) for y in range(images.ROW_TOP, images.ROW_TOP + images.ROW_HEIGHT)}
        for y in range(16):
            for x in range(240):
                if (x, y) not in inside:
                    self.assertEqual(px[y * 240 + x], t.pixels[y * 240 + x], (x, y))

    def test_regions_change_only_their_rectangles(self):
        t = tim.parse(self.res, 0x1E301C)                   # Config screen
        region = dict(x=14, y=13, w=100, h=15, text="Config", ink=1)
        px = images.render(t, {"regions": [region]})
        for y in range(t.height):
            for x in range(t.width):
                if not (14 <= x < 114 and 13 <= y < 28):
                    self.assertEqual(px[y * t.width + x], t.pixels[y * t.width + x], (x, y))
        self.assertIn(1, px[20 * t.width + 14:20 * t.width + 114])
        with self.assertRaises(ValueError):
            images.render(t, {"regions": [dict(region, w=20)]})
        with self.assertRaises(ValueError):
            images.render(t, {"regions": [dict(region, x=250)]})

    def test_screen_translations_fit(self):
        tr = insert_script.load_translations([ROOT / "translations" / "screens.json"])
        buf, problems = bytearray(self.res), []
        images.apply(buf, tr, problems)
        self.assertEqual(problems, [])

    def test_screen_regions_cover_whole_glyphs(self):
        """A region that cuts through an original glyph leaves stray pixels next to it."""
        tr = insert_script.load_translations([ROOT / "translations" / "screens.json"])
        files = {"RES.R": self.res, "SCE.S": (ROOT / "extracted" / "files" / "SCE.S").read_bytes()}
        for sid, (spec, _) in tr.items():
            name, off = images.parse_id(sid)
            t = tim.parse(files[name], off)
            regions = spec["regions"]
            for x0, y0, x1, y1 in glyph_boxes(t, {r["ink"] for r in regions}):
                if x1 - x0 > 60 or y1 - y0 > 20:
                    continue                                # frames and bars
                touched = [r for r in regions if x0 < r["x"] + r["w"] and x1 >= r["x"]
                           and y0 < r["y"] + r["h"] and y1 >= r["y"]]
                if touched:                                 # every pixel cleared by some region
                    self.assertTrue(all(any(r["x"] <= x < r["x"] + r["w"] and r["y"] <= y < r["y"] + r["h"]
                                            for r in regions)
                                        for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)),
                                    f"{sid}: glyph {x0, y0, x1, y1} is cut by {touched[0]['text']!r}")

    def test_apply_changes_only_that_tim(self):
        sid, kind, t = next(i for i in self.items if i[1] == "mail page")
        buf, problems = bytearray(self.res), []
        images.apply(buf, {sid: ("Hello there.", True)}, problems)
        self.assertEqual(problems, [])
        self.assertEqual(len(buf), len(self.res))
        changed = [i for i in range(len(buf)) if buf[i] != self.res[i]]
        self.assertTrue(changed)
        self.assertTrue(t.offset <= changed[0] and changed[-1] < t.offset + t.size)
        new = tim.parse(bytes(buf), t.offset)
        self.assertEqual(new.clut, t.clut)
        self.assertEqual(set(new.pixels), set(t.pixels))     # same two colours


if __name__ == "__main__":
    unittest.main()
