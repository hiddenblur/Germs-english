"""tools/make_patch.py: the xdelta3 patch turns the original disc into the patched disc, and only that disc."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import make_patch

try:
    make_patch.find_xdelta()
    HAVE_XDELTA = True
except SystemExit:
    HAVE_XDELTA = False
ORIGINAL = ROOT / "Germs - Nerawareta Machi (Japan).bin"
PATCHED = ROOT / "build" / "disc" / "Germs - English.bin"


@unittest.skipUnless(HAVE_XDELTA, "needs xdelta3")
class PatchSynthetic(unittest.TestCase):
    def test_roundtrip_and_wrong_source_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = bytes((i * 7) & 0xFF for i in range(200000))
            dst = bytearray(src)
            dst[1000:1010] = b"ENGLISH!!!"
            dst[150000:150004] = b"\0\1\2\3"
            (tmp / "a.bin").write_bytes(src)
            (tmp / "b.bin").write_bytes(dst)
            self.assertEqual(make_patch.main([str(tmp / "a.bin"), str(tmp / "b.bin"), str(tmp / "out"), "--name", "t"]), 0)
            self.assertTrue((tmp / "out" / "t.xdelta").exists())
            self.assertIn("CRC32", (tmp / "out" / "t.checksums.txt").read_text())
            self.assertEqual(make_patch.verify(tmp / "a.bin", tmp / "b.bin", tmp / "out" / "t.xdelta"), [])

    def test_wrong_target_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "a.bin").write_bytes(bytes(5000))
            (tmp / "b.bin").write_bytes(bytes(4000) + b"x" * 1000)
            (tmp / "c.bin").write_bytes(b"y" * 5000)
            make_patch.encode(tmp / "a.bin", tmp / "b.bin", tmp / "p.xdelta")
            self.assertTrue(make_patch.verify(tmp / "a.bin", tmp / "c.bin", tmp / "p.xdelta"))


@unittest.skipUnless(HAVE_XDELTA and ORIGINAL.exists() and PATCHED.exists(), "needs xdelta3, the original disc and build/disc/Germs - English.bin")
class PatchRealDisc(unittest.TestCase):
    def test_patch_reproduces_built_disc_and_is_small(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(make_patch.main([str(ORIGINAL), str(PATCHED), tmp]), 0)
            patch = Path(tmp) / "Germs_EN.xdelta"
            # only the translated files differ, so the patch must be a small fraction of the disc
            self.assertLess(patch.stat().st_size, ORIGINAL.stat().st_size // 4)


if __name__ == "__main__":
    unittest.main()
