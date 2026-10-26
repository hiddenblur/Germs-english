"""gcc 2.8.1 (psx variant, built by tools/oldgcc) reproduces retail code: decomp/src/*.c must match the EXE.

Needs psyq/ (CPPPSX and ASPSX), the old-gcc 2.8.1 build in tools/vendor/oldgcc/bin, and extracted/.
Skipped when any is missing.
Only functions listed in MATCHING are required to match; the rest are work in progress.
"""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HAVE = ((ROOT / "psyq" / "bin" / "ASPSX.EXE").exists() and (ROOT / "tools" / "vendor" / "oldgcc" / "bin" / "cc1-2.8.1.exe").exists()
        and (ROOT / "extracted" / "files" / "SLPS_021.07").exists())
MATCHING = {
    "decomp/src/angle.c": ["norm_angle"],
    "decomp/src/calls1.c": ["fn_8017D3F0", "fn_8018BD60", "fn_801A8EFC", "fn_801A69E0", "fn_80176734"],
    "decomp/src/calls2.c": ["fn_801854B8", "fn_80192F20", "fn_801A20A8", "fn_801A4370", "fn_801A533C"],
    "decomp/src/leaf1.c": ["fn_8017D564", "fn_8018D1F0", "fn_8019A6A4", "fn_801A216C", "fn_801A3DBC", "fn_801AC9B4", "fn_80186230", "fn_80186258", "fn_80186280", "fn_801AC55C", "fn_8019A664", "fn_80199FA0", "fn_8017E504"],
    "decomp/src/leaf2.c": ["fn_801AC464"],
    "decomp/src/leaf3.c": ["fn_80188DE8", "fn_80199D18", "fn_8018D294"],
    "decomp/src/leaf4.c": ["fn_8018D1A0"],
    "decomp/src/lookup.c": ["fn_80174F54", "fn_8018F590"],
    "decomp/src/pools.c": ["fn_80174FA8", "fn_801762A0", "fn_80176780", "fn_8017683C", "fn_80188F98", "fn_80189150", "fn_8018F53C"],
    "decomp/src/queue.c": ["fn_801854FC", "fn_8018E2F8", "fn_801A43A8", "fn_801A7B58"],
    "decomp/src/tables.c": ["tbl_short"],
    "decomp/src/wip.c": ["fn_801749E8", "fn_8017D170", "fn_8018C170", "fn_801AC6C8", "fn_801AC844"],
    "decomp/src/wip2.c": ["fn_801A3A54", "fn_80186630", "fn_80184408", "fn_8018F91C"],
}


@unittest.skipUnless(HAVE, "needs psyq/, the 2.8.1 build and extracted/")
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
