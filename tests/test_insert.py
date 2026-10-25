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
from insert_script import encode  # noqa: E402


def load(name, base=EXTRACTED / "files"):
    return (base / name).read_bytes()


def encode_value(v):
    """Encode a translation value the way insert_script.load_translations reads it."""
    if isinstance(v, dict):
        return encode(v["text"], v.get("width", "half") != "full")
    return encode(v)


def command_args(scenes):
    return [list(cmd.args) for *_, cmd in sce.iter_commands(scenes)]


@unittest.skipUnless((EXTRACTED / "script" / "SCE.S.json").exists(), "needs extracted disc + dump")
class InsertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sce, cls.exe = load("SCE.S"), load("SLPS_021.07")
        cls.scenes = sce.parse(cls.sce, cls.exe)
        cls.dump = json.loads((EXTRACTED / "script" / "SCE.S.json").read_text(encoding="utf-8"))

    def run_insert(self, translations):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "tr.json").write_text(json.dumps(translations), encoding="utf-8")
        subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "insert_script.py"),
                        str(EXTRACTED), str(tmp / "out"), str(tmp / "tr.json")],
                       check=True, capture_output=True)
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
                    want[k][i] = encode_value(translations[sid])
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
        tr = {e["id"]: "Hi{8}!{1}" for e in self.dump if e["cmd"] and e["length"] > 12}
        new_sce, new_exe = self.run_insert(tr)
        self.check_output(tr, new_sce, new_exe)
        self.assert_layout_kept(new_sce, new_exe)

    def test_growth_within_aset_padding_keeps_layout(self):
        # pick a string in an ASET with spare padding and grow it by less than the spare
        for c in (c for s in self.scenes for c in s.chunks if isinstance(c, sce.Area)):
            for _, aset in c.subs:
                if not isinstance(aset, sce.Aset):
                    continue
                recs, tail = aset.to_bytes()
                spare = tail - sce.MIN_ASET_TAIL
                offs = {o for r in aset.records for cmd in r.commands for o in cmd.arg_offsets}
                cands = [e for e in self.dump if e["cmd"] and e["offset"] in offs]
                if spare >= 64 and cands:
                    e = cands[0]
                    tr = {e["id"]: "W" * ((e["length"] + 40) // 2)}   # about 40 bytes longer
                    new_sce, new_exe = self.run_insert(tr)
                    self.check_output(tr, new_sce, new_exe)
                    self.assert_layout_kept(new_sce, new_exe)
                    return
        self.skipTest("no ASET with spare padding")

    def test_growth_past_padding_adds_sector_in_place(self):
        cmds = [e for e in self.dump if e["cmd"]][:40]
        tr = {e["id"]: "A slightly longer line{8} here{1}" for e in cmds}
        new_sce, new_exe = self.run_insert(tr)
        self.check_output(tr, new_sce, new_exe)
        self.assertEqual((len(new_sce) - len(self.sce)) % sce.SECTOR, 0)
        self.assertGreater(len(new_sce), len(self.sce))

    def test_large_growth_moves_later_scenes(self):
        first_scene = [e for e in self.dump if e["cmd"] and e["offset"] < sce.read_scene_table(self.exe)[1]]
        long_line = "This line is far longer than the original Japanese text " * 3
        tr = {e["id"]: {"text": long_line, "width": "full"} for e in first_scene}
        new_sce, new_exe = self.run_insert(tr)
        self.check_output(tr, new_sce, new_exe)
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
