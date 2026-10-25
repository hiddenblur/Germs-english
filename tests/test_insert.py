"""Round-trip tests for the SCE.S rebuild and the inserter.

Needs the extracted disc and script dump (python -I tools/extract_disc.py ...,
python -I tools/dump_script.py extracted). Run: python -m unittest discover tests
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRACTED = ROOT / "extracted"
sys.path.insert(0, str(ROOT / "tools"))
import sce  # noqa: E402
import windows  # noqa: E402
from insert_script import prepare  # noqa: E402


def load(name, base=EXTRACTED / "files"):
    return (base / name).read_bytes()


def prepared(entry, v):
    """Bytes the inserter writes for a translation value (same rules as load_translations)."""
    if isinstance(v, dict):
        return prepare(entry, v["text"], v.get("width", "half") != "full")
    return prepare(entry, v)


def words(n):
    """Wrappable English text about n characters long."""
    return ("word " * (n // 5 + 1))[:n].strip()


def command_args(scenes):
    return [list(cmd.args) for *_, cmd in sce.iter_commands(scenes)]


@unittest.skipUnless((EXTRACTED / "script" / "SCE.S.json").exists(), "needs extracted disc + dump")
class InsertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sce, cls.exe = load("SCE.S"), load("SLPS_021.07")
        cls.scenes = sce.parse(cls.sce, cls.exe)
        cls.dump = json.loads((EXTRACTED / "script" / "SCE.S.json").read_text(encoding="utf-8"))
        cls.by_id = {e["id"]: e for e in cls.dump}
        cls.dialogue = [e for e in cls.dump if e["cmd"] and windows.classify(e) == "dialogue"]

    def run_insert(self, translations, check=True):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "tr.json").write_text(json.dumps(translations), encoding="utf-8")
        res = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "insert_script.py"),
                              str(EXTRACTED), str(tmp / "out"), str(tmp / "tr.json")],
                             check=check, capture_output=True, text=True)
        if not check:
            return res
        return load("SCE.S", tmp / "out"), load("SLPS_021.07", tmp / "out")

    def check_output(self, translations, new_sce, new_exe):
        scenes = sce.parse(new_sce, new_exe)          # output must parse cleanly
        out_sce, table = sce.build(scenes)
        self.assertEqual(out_sce, new_sce)            # and round-trip itself
        self.assertEqual(table, sce.read_scene_table(new_exe))
        want = command_args(self.scenes)
        by_offset = {e["offset"]: e["id"] for e in self.dump if e["cmd"]}
        k = 0
        for *_, cmd in sce.iter_commands(self.scenes):
            for i, off in enumerate(cmd.arg_offsets):
                sid = by_offset.get(off)
                if sid in translations:
                    want[k][i] = prepared(self.by_id[sid], translations[sid])
            k += 1
        self.assertEqual(command_args(scenes), want)
        # sound chunks are untouched
        raw = lambda ss: [c for s in ss for c in s.chunks if isinstance(c, bytes)]
        self.assertEqual(raw(scenes), raw(self.scenes))
        return scenes

    def test_parse_build_identical(self):
        out, table = sce.build(sce.parse(self.sce, self.exe))
        self.assertEqual(out, self.sce)
        self.assertEqual(table, sce.read_scene_table(self.exe))

    def test_no_translation_identical(self):
        new_sce, new_exe = self.run_insert({})
        self.assertEqual(new_sce, self.sce)
        self.assertEqual(new_exe, self.exe)

    def assert_layout_kept(self, new_sce, new_exe):
        self.assertEqual(len(new_sce), len(self.sce))
        self.assertEqual(sce.read_scene_table(new_exe), sce.read_scene_table(self.exe))

    def test_shrink_keeps_layout(self):
        tr = {e["id"]: "Hi{8}!{1}" for e in self.dialogue if e["length"] > 12}
        tr.update({e["id"]: "Go" for e in self.dump if windows.marker_column(e)})   # label-style choices
        new_sce, new_exe = self.run_insert(tr)
        self.check_output(tr, new_sce, new_exe)
        self.assert_layout_kept(new_sce, new_exe)

    def test_choice_labels_get_marker_at_retail_column(self):
        e = next(e for e in self.dump if windows.marker_column(e) == 28)
        raw = prepared(e, "Desk work")
        self.assertTrue(raw.endswith("3○".encode("cp932")))
        self.assertEqual(windows.layout.line_widths(raw[:-3])[0], 28)

    def test_dialogue_is_word_wrapped(self):
        raw = prepared(self.dialogue[0], words(100))
        widths = windows.layout.line_widths(raw)
        self.assertGreater(len(widths), 3)
        self.assertTrue(all(w <= windows.WRAP_WIDTH for w in widths))

    def test_growth_within_aset_padding_keeps_layout(self):
        # pick a dialogue string in an ASET with spare padding and grow it by less than that
        for c in (c for s in self.scenes for c in s.chunks if isinstance(c, sce.Area)):
            for _, aset in c.subs:
                if not isinstance(aset, sce.Aset):
                    continue
                recs, tail = aset.to_bytes()
                spare = tail - sce.MIN_ASET_TAIL
                offs = {o for r in aset.records for cmd in r.commands for o in cmd.arg_offsets}
                cands = [e for e in self.dialogue if e["offset"] in offs]
                if spare >= 64 and cands:
                    e = cands[0]
                    tr = {e["id"]: words(e["length"] + 40)}            # about 40 bytes longer
                    new_sce, new_exe = self.run_insert(tr)
                    self.check_output(tr, new_sce, new_exe)
                    self.assert_layout_kept(new_sce, new_exe)
                    return
        self.skipTest("no ASET with spare padding")

    def test_growth_past_padding_is_rejected(self):
        first_scene = [e for e in self.dialogue if e["offset"] < sce.read_scene_table(self.exe)[1]]
        tr = {e["id"]: words(e["length"] * 2) for e in first_scene}
        res = self.run_insert(tr, check=False)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("scene 0 area 0", res.stdout)
        self.assertIn("bytes over its free space", res.stdout)

    def test_choice_wider_than_window_is_rejected(self):
        e = next(e for e in self.dump if windows.marker_column(e))
        res = self.run_insert({e["id"]: "A label far too long for the choice window"}, check=False)
        self.assertNotEqual(res.returncode, 0)

    def test_container_growth_moves_later_scenes(self):
        # the inserter refuses growth (the disc layout is fixed), but sce.build supports it
        scenes = sce.parse(self.sce, self.exe)
        for si, area, rec, cmd in sce.iter_commands(scenes):
            if si == 0 and cmd.opcode == 5:
                cmd.args[0] = b"x" * 400
        new_sce, table = sce.build(scenes)
        new_exe = sce.patch_exe(self.exe, table)
        self.assertEqual(sce.build(sce.parse(new_sce, new_exe))[0], new_sce)
        old_t, new_t = sce.read_scene_table(self.exe), sce.read_scene_table(new_exe)
        grown = new_t[1] - old_t[1]
        self.assertGreater(grown, 0)
        self.assertEqual(grown % sce.SECTOR, 0)
        self.assertEqual([b - a for a, b in zip(old_t[1:], new_t[1:])], [grown] * 23)
        self.assertEqual(new_sce[new_t[1]:], self.sce[old_t[1]:])   # later scenes byte-identical

    def test_in_place_overflow_is_rejected(self):
        loose = next(e for e in self.dump if e["cmd"] is None)
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_insert({loose["id"]: "X" * loose["capacity"]})


if __name__ == "__main__":
    unittest.main()
