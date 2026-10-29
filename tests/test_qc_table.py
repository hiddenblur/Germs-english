"""Auto-flags of tools/qc_table.py."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import qc_table  # noqa: E402


def codes(ja, en, problem=None, label_only=False):
    return [c for c, _ in qc_table.text_flags(ja, en, problem, label_only)]


class FlagTests(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(codes("{7}薬{1}を飲んだ %s", "{7}Drank{1} it %s"), [])

    def test_japanese_left(self):
        self.assertIn("JA-LEFT", codes("あ", "Hello あ"))

    def test_placeholders(self):
        self.assertIn("PLACEHOLDER", codes("%s %d", "%d %s"))
        self.assertIn("PLACEHOLDER", codes("{7}a{1}", "a"))

    def test_label_only_marker_is_not_a_colour_mismatch(self):
        self.assertEqual(codes(" 話す{3}○", "Talk", label_only=True), [])

    def test_spaces(self):
        self.assertEqual(codes("a", "  indent ok"), [])
        self.assertIn("DOUBLE-SPACE", codes("a", "two  spaces"))
        self.assertIn("TRAILING-SPACE", codes("a", "line \nnext"))

    def test_problem_kinds(self):
        self.assertIn("LONG", codes("a", "b", "dialogue line is 40 half-cells wide, limit 32"))
        self.assertIn("CHECK", codes("a", "b", "unknown id"))

    def test_status(self):
        self.assertEqual(qc_table.status_of("a", ""), "untranslated")
        self.assertEqual(qc_table.status_of("a", "a"), "identical")


if __name__ == "__main__":
    unittest.main()
