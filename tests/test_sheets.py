"""Free-space budgets as reported by tools/sheets.py."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRACTED = ROOT / "extracted"
sys.path.insert(0, str(ROOT / "tools"))
import insert_script  # noqa: E402
import sheets  # noqa: E402
import windows  # noqa: E402


@unittest.skipUnless((EXTRACTED / "script" / "SCE.S.json").exists(), "needs extracted disc + dump")
class FreeSpaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.retail = sheets.area_budgets(*sheets.load_game())
        cls.areas = sheets.area_of(cls.retail)
        cls.dump = json.loads((EXTRACTED / "script" / "SCE.S.json").read_text(encoding="utf-8"))

    def test_retail_budgets(self):
        self.assertEqual(len(self.retail), 84)
        self.assertEqual(self.retail[(0, 0)][0], 0)        # the office: nothing to spare
        self.assertEqual(self.retail[(0, 1)][0], 1644)
        self.assertTrue(all(free >= 0 for free, _ in self.retail.values()))

    def test_free_space_follows_translations(self):
        # grow one dialogue line in a roomy area; its free space must drop by exactly the growth
        key = (0, 1)
        e = next(e for e in self.dump if e["cmd"] and self.areas.get(e["offset"]) == key)
        text = "word " * 20
        bufs, problems = insert_script.apply(EXTRACTED, {e["id"]: (text, True)})
        self.assertEqual(problems, [])
        now = sheets.area_budgets(bytes(bufs["SCE.S"]), bytes(bufs["SLPS_021.07"]))
        # a command pads all of its args together, so growth is measured on the whole block
        rest = sum(len(a.encode("cp932")) + 1 for a in e["cmd"]["args"][1:])
        old_len = insert_script.sce.align(e["length"] + 1 + rest, 4)
        new_len = insert_script.sce.align(len(insert_script.prepare(e, text)) + 1 + rest, 4)
        self.assertEqual(self.retail[key][0] - now[key][0], new_len - old_len)
        self.assertEqual({k: v[0] for k, v in now.items() if k != key},
                         {k: v[0] for k, v in self.retail.items() if k != key})

    def test_limit_column_shows_area_space(self):
        office = next(e for e in self.dump if e["cmd"] and windows.marker_column(e)
                      and self.areas.get(e["offset"]) == (0, 0))
        self.assertIn("area 0: 0 bytes free (tight)", sheets.limit_text(office, self.retail, self.areas))


if __name__ == "__main__":
    unittest.main()
