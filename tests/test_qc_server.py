"""tools/qc_server.py: saving one sheet cell, and the live string check."""
import csv
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import qc_server  # noqa: E402


def write_sheet(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows([["id", "window", "limit", "ja", "en", "note"], *rows])


class SaveCellTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.path = self.dir / "t.csv"
        write_sheet(self.path, [["A:1", "dialogue", "x", "あ\nい", "one\ntwo", ""],
                                ["A:2", "dialogue", "x", "う", "", "note"]])

    def test_roundtrip_is_byte_identical(self):
        before = self.path.read_bytes()
        qc_server.save_cell(self.path, "A:1", "one\ntwo", "one\ntwo")
        self.assertEqual(self.path.read_bytes(), before)

    def test_writes_only_the_en_cell(self):
        qc_server.save_cell(self.path, "A:2", "new\ntext", "")
        rows = list(csv.reader(open(self.path, encoding="utf-8-sig", newline="")))
        self.assertEqual(rows[2], ["A:2", "dialogue", "x", "う", "new\ntext", "note"])
        self.assertEqual(rows[1][4], "one\ntwo")

    def test_stale_base_is_refused(self):
        with self.assertRaises(qc_server.Conflict):
            qc_server.save_cell(self.path, "A:1", "x", "something else")
        self.assertEqual(list(csv.reader(open(self.path, encoding="utf-8-sig", newline="")))[1][4], "one\ntwo")

    def test_unknown_id(self):
        with self.assertRaises(KeyError):
            qc_server.save_cell(self.path, "A:9", "x", "")

    def test_crlf_in_base_is_equivalent(self):
        qc_server.save_cell(self.path, "A:1", "x", "one\r\ntwo")


@unittest.skipUnless((ROOT / "extracted" / "script" / "SCE.S.json").exists() and (ROOT / "sheets" / "sce_00.csv").exists(),
                     "needs extracted disc + exported sheets")
class LiveCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.review = qc_server.Review()
        cls.sid = next(i for i, m in cls.review.meta.items() if m[3] == "profile")

    def test_fits(self):
        out = self.review.check_one(self.sid, "Short")
        self.assertIsNone(out["problem"])
        self.assertEqual(out["flags"], [])

    def test_too_wide_is_long(self):
        out = self.review.check_one(self.sid, "w" * 80)
        self.assertIn("half-cells", out["problem"])
        self.assertEqual(out["flags"][0][0], "LONG")

    def test_empty_keeps_japanese(self):
        out = self.review.check_one(self.sid, "")
        self.assertTrue(out["en_empty"])

    def test_unknown_id(self):
        self.assertIn("error", self.review.check_one("NOPE:1", "x"))


if __name__ == "__main__":
    unittest.main()
