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
    "decomp/src/angle.c": ["norm_angle", "angle_quadrant"],
    "decomp/src/batch10.c": ["fn_801A6AC4", "fn_8017D0E0", "fn_8019A5D4"],
    "decomp/src/batch3.c": ["fn_80199C68", "fn_80184160", "fn_80199CC0", "fn_801AC4A8", "fn_8017E544"],
    "decomp/src/batch4.c": ["fn_801AC500", "fn_80184100", "fn_801863B4", "fn_801A8F2C", "fn_8018655C"],
    "decomp/src/batch5.c": ["fn_80186718", "fn_801A39F0", "fn_801AC214", "fn_80186414", "fn_801A3C58", "fn_801841C4"],
    "decomp/src/batch6.c": ["fn_80189054", "fn_801890C4", "fn_801A68F0", "fn_801762F4"],
    "decomp/src/batch7.c": ["fn_8018677C", "fn_801865C0", "fn_801A5DA0", "fn_801A8F8C", "fn_801AC0E4"],
    "decomp/src/batch8.c": ["fn_80189970", "fn_80189928", "fn_801867E8", "fn_8018BD8C", "fn_801A7AFC"],
    "decomp/src/batch9.c": ["fn_801898C0", "fn_80184094", "fn_801A8FF8", "fn_80185548", "fn_801A3970", "fn_801A252C", "fn_80186884", "fn_8018AABC", "fn_801A3BCC"],
    "decomp/src/calls1.c": ["fn_8017D3F0", "fn_8018BD60", "fn_801A8EFC", "fn_801A69E0", "fn_80176734"],
    "decomp/src/calls2.c": ["fn_801854B8", "fn_80192F20", "fn_801A20A8", "fn_801A4370", "fn_801A533C"],
    "decomp/src/leaf1.c": ["fn_8017D564", "fn_8018D1F0", "fn_8019A6A4", "fn_801A216C", "fn_801A3DBC", "fn_801AC9B4", "fn_80186230", "fn_80186258", "fn_80186280", "fn_801AC55C", "fn_8019A664", "fn_80199FA0", "fn_8017E504"],
    "decomp/src/leaf2.c": ["fn_801AC464"],
    "decomp/src/leaf3.c": ["fn_80188DE8", "fn_80199D18", "fn_8018D294"],
    "decomp/src/leaf4.c": ["fn_8018D1A0"],
    "decomp/src/lookup.c": ["fn_801767D4", "fn_80176890", "fn_80188FEC", "fn_801891A4", "fn_80174F54", "fn_8018F590"],
    "decomp/src/misc1.c": ["fn_801749E8", "fn_8017D170", "fn_8018C170", "fn_801A3D74", "fn_801AC6C8", "fn_801AC844"],
    "decomp/src/misc2.c": ["fn_801A3A54", "fn_80186630", "fn_80184408", "fn_8018F91C", "fn_8018C50C", "fn_80186838"],
    "decomp/src/pools.c": ["fn_80174FA8", "fn_801762A0", "fn_80176780", "fn_8017683C", "fn_80188F98", "fn_80189150", "fn_8018F53C"],
    "decomp/src/queue.c": ["fn_801854FC", "fn_8018E2F8", "fn_801A43A8", "fn_801A7B58"],
    "decomp/src/special.c": ["fn_801A0690"],
    "decomp/src/tables.c": ["tbl_short"],
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
