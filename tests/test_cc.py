"""The Psy-Q compiler reproduces retail code: decomp/src/*.c must match the EXE byte for byte.

Needs psyq/ (not in the repo) and extracted/. Skipped when either is missing.
Only functions listed in MATCHING are required to match; the rest are work in progress.
"""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HAVE = (ROOT / "psyq" / "bin" / "CC1PSX.EXE").exists() and (ROOT / "extracted" / "files" / "SLPS_021.07").exists()
MATCHING = {
    "decomp/src/angle.c": ["norm_angle"],
    "decomp/src/tables.c": ["tbl_short"],
    "decomp/src/leaf1.c": ["fn_8017D564", "fn_8018D1F0", "fn_8019A6A4", "fn_801A216C", "fn_801A3DBC", "fn_801AC9B4",
                           "fn_80186230", "fn_80186258", "fn_80186280", "fn_801AC55C", "fn_8019A664", "fn_80199FA0",
                           "fn_8017E504"],
    "decomp/src/leaf2.c": ["fn_801AC464"],
}


@unittest.skipUnless(HAVE, "needs psyq/ and extracted/")
class CompilerMatches(unittest.TestCase):
    def test_functions_match_retail(self):
        for source, names in MATCHING.items():
            out = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "cc_check.py"), str(ROOT / source)],
                                 capture_output=True, text=True).stdout
            for name in names:
                line = next((l for l in out.splitlines() if l.startswith(name + " @")), "")
                self.assertTrue(line.endswith("MATCH"), f"{name}: {line or out}")


if __name__ == "__main__":
    unittest.main()
