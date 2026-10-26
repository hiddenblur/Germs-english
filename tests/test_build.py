"""tools/build_exe.py and tools/objdiff_objs.py: the rebuilt EXE equals retail except in the known non-matching functions."""
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
HAVE = ((ROOT / "psyq" / "bin" / "ASPSX.EXE").exists() and (ROOT / "tools" / "vendor" / "oldgcc" / "bin" / "cc1-2.8.1.exe").exists()
        and (ROOT / "extracted" / "files" / "SLPS_021.07").exists())
NOT_C_YET = set()          # functions with C that do not match yet (all 86 match)


@unittest.skipUnless(HAVE, "needs psyq/, the 2.8.1 build and extracted/")
class BuildExe(unittest.TestCase):
    def test_rebuild_differs_only_in_unmatched_functions(self):
        import build_exe
        image, exe, results = build_exe.build()
        self.assertEqual(len(image), len(exe))
        bad = {n for n, _, _, st in results if st != "MATCH"}
        self.assertEqual(bad, NOT_C_YET)
        spans = [(a - build_exe.cc_check.EXE_BASE, w * 4) for n, a, w, st in results if st != "MATCH"]
        for i in range(0, len(exe), 4):
            if image[i:i + 4] != exe[i:i + 4]:
                self.assertTrue(any(s <= i < s + n for s, n in spans), hex(i))

    @unittest.skipUnless((ROOT / "tools" / "vendor" / "psyq44" / "LIB").exists() and (ROOT / "decomp" / "objects.txt").exists(),
                         "needs the unpacked Lib44 (tools/vendor/psyq44)")
    def test_library_modules_relink_to_retail(self):
        import lib_relink
        bad = [(m, st) for _, _, _, m, st, _, _ in lib_relink.relinked_modules() if st != "OK"]
        self.assertEqual(bad, [])

    @unittest.skipUnless((ROOT / "tools" / "vendor" / "psyq44" / "LIB").exists() and (ROOT / "decomp" / "objects.txt").exists(),
                         "needs the unpacked Lib44 (tools/vendor/psyq44)")
    def test_full_psylink_link_equals_retail(self):
        import subprocess
        out = ROOT / "build" / "link"
        r = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "fulllink.py"), "--out", str(out), "--no-c"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("0 words differ", r.stdout)

    @unittest.skipUnless((ROOT / "tools" / "vendor" / "psyq44" / "LIB").exists() and (ROOT / "decomp" / "objects.txt").exists(),
                         "needs the unpacked Lib44 (tools/vendor/psyq44)")
    def test_c_functions_in_the_link(self):
        """With our compiled C linked in the image equals retail, except for functions in NOT_C_YET."""
        import re
        import subprocess
        r = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "fulllink.py"), "--out", str(ROOT / "build" / "link-c")],
                           capture_output=True, text=True)
        self.assertIn("0 error(s)", r.stdout, r.stdout + r.stderr)
        differing = set(re.findall(r"^  (\w+): \d+ words differ", r.stdout, re.M))
        self.assertEqual(differing, NOT_C_YET, r.stdout)
        if not NOT_C_YET:
            self.assertIn("0 words differ", r.stdout)
        listed = [l for l in (ROOT / "decomp" / "functions.txt").read_text().splitlines() if l.strip() and not l.startswith("#")]
        self.assertIn(f"{len(listed)} C functions", r.stdout)

    def test_lnk_writer_roundtrip(self):
        import lnk
        import psyqlib
        blob = lnk.write_object({".text": bytes(range(16)) * 5000, ".data": b"abcd", ".bss": 32})
        o = psyqlib.parse_obj(blob, 0)
        by_name = {s[0]: s for s in o["sections"].values()}
        self.assertEqual(bytes(by_name[".text"][1]), bytes(range(16)) * 5000)
        self.assertEqual(bytes(by_name[".data"][1]), b"abcd")
        self.assertEqual(by_name[".bss"][2], 32)

    def test_elf_for_objdiff(self):
        import objdiff_objs
        base, target, names = objdiff_objs.convert(ROOT / "decomp" / "src" / "leaf4.c")
        for blob in (base, target):
            self.assertEqual(blob[:4], b"\x7fELF")
            self.assertEqual(struct.unpack_from("<H", blob, 18)[0], 8)      # EM_MIPS
        self.assertEqual(names, ["fn_8018D1A0"])
        self.assertEqual(base, objdiff_objs.convert(ROOT / "decomp" / "src" / "leaf4.c")[0])   # deterministic
        self.assertEqual(len(base), len(target))


if __name__ == "__main__":
    unittest.main()
