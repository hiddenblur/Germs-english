"""Layout simulator checks against the retail narration and the renderer emulation."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import layout  # noqa: E402
from insert_script import encode  # noqa: E402

SCE = ROOT / "extracted" / "files" / "SCE.S"


class LayoutTests(unittest.TestCase):
    def test_wraps_and_breaks(self):
        rows = [r for _, r in layout.char_rows(encode("A" * 33 + "\nB"))]
        self.assertEqual(rows, [0] * 32 + [1, 2])

    def test_full_width_takes_two_columns(self):
        rows = [r for _, r in layout.char_rows("あ".encode("cp932") * 17)]
        self.assertEqual(rows, [0] * 16 + [1])

    @unittest.skipUnless(SCE.exists(), "needs the extracted disc")
    def test_retail_opening_switches_scene_after_15_rows(self):
        raw = SCE.read_bytes()[0x59008:0x59808].split(b"\0")[0]
        chars = layout.char_rows(raw)
        office = raw.index("アシスタント".encode("cp932"))   # first line shown in the office
        self.assertEqual(max(r for o, r in chars if o < office), 14)
        self.assertEqual(min(r for o, r in chars if o >= office), 15)
        layout.check_scene_split("SCE.S:59008", raw)

    def test_short_opening_is_rejected(self):
        with self.assertRaises(ValueError):
            layout.check_scene_split("SCE.S:59008", encode("Too short.\nTwo pages at most."))

    def test_committed_test_lines_pass(self):
        tr = json.loads((ROOT / "translations" / "test_lines.json").read_text(encoding="utf-8"))
        layout.check_scene_split("SCE.S:59008", encode(tr["SCE.S:59008"]))


if __name__ == "__main__":
    unittest.main()
