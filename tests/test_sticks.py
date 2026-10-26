"""Analog stick wrapper (tools/patch_exe.py STICK_WRAPPER) on an emulated R3000.

The patched EXE is loaded under unicorn with the retail movement function 0x80199548 stubbed
out, so only the wrapper's own effect on the player struct is checked.
Run: python -m unittest discover tests
"""
import struct
import sys
import unittest
from pathlib import Path

from unicorn import UC_ARCH_MIPS, UC_HOOK_CODE, UC_MODE_32, UC_MODE_LITTLE_ENDIAN, Uc
from unicorn import mips_const as R

ROOT = Path(__file__).resolve().parent.parent
EXE_PATH = ROOT / "extracted" / "files" / "SLPS_021.07"
sys.path.insert(0, str(ROOT / "tools"))
import patch_exe

LOAD, SENTINEL = 0x80170000, 0x80000100
PAD, PLAYER, DT = 0x80007570, 0x801E0620, 0x801E6DB4
YAW, FORWARD, MOVING, MODE = PLAYER + 0x6E, PLAYER + 0x50, PLAYER + 0x3C, PLAYER + 0x46


def P(addr):
    return addr & 0x1FFFFFFF


class Stick(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exe = patch_exe.apply(EXE_PATH.read_bytes())

    def run_wrapper(self, pad_id=0x73, rx=0x80, ry=0x80, lx=0x80, ly=0x80, dt=3, mode=0, yaw=100):
        uc = Uc(UC_ARCH_MIPS, UC_MODE_32 | UC_MODE_LITTLE_ENDIAN)
        uc.mem_map(P(0x80000000), 0x200000)
        uc.mem_write(P(LOAD), self.exe[0x800:])
        uc.mem_write(P(PAD), bytes([0, pad_id, 0xFF, 0xFF, rx, ry, lx, ly]))
        uc.mem_write(P(DT), struct.pack("<I", dt))
        uc.mem_write(P(PLAYER + 0x46), struct.pack("<H", mode))
        uc.mem_write(P(YAW), struct.pack("<H", yaw))
        self.moves = 0

        def hook(uc, addr, size, _):
            if addr == SENTINEL:
                uc.emu_stop()
            elif addr == patch_exe.MOVE:
                self.moves += 1
                uc.reg_write(R.UC_MIPS_REG_PC, uc.reg_read(R.UC_MIPS_REG_RA))
        uc.hook_add(UC_HOOK_CODE, hook)
        uc.reg_write(R.UC_MIPS_REG_SP, 0x801FF000)
        uc.reg_write(R.UC_MIPS_REG_RA, SENTINEL)
        uc.emu_start(patch_exe.STICK_BLOCK, SENTINEL)
        self.sp = uc.reg_read(R.UC_MIPS_REG_SP)
        h = lambda a: struct.unpack("<h", uc.mem_read(P(a), 2))[0]
        return h(YAW), h(FORWARD), h(MOVING)

    def test_calls_retail_movement_and_restores_the_stack(self):
        self.run_wrapper()
        self.assertEqual(self.moves, 1)
        self.assertEqual(self.sp, 0x801FF000)

    def test_idle_and_digital_leave_the_player_alone(self):
        self.assertEqual(self.run_wrapper(), (100, 0, 0))
        self.assertEqual(self.run_wrapper(pad_id=0x41, rx=0xFF, ly=0x00), (100, 0, 0))
        self.assertEqual(self.run_wrapper(rx=0xFF, ly=0x00, mode=1), (100, 0, 0))
        self.assertEqual(self.run_wrapper(rx=0x80 + 24, lx=0x80 - 24, ly=0x80 + 24), (100, 0, 0))

    def test_turn(self):
        self.assertEqual(self.run_wrapper(rx=0xFF)[0], 100 + ((127 * 3) >> 5))
        self.assertEqual(self.run_wrapper(rx=0x00)[0], 100 + ((-128 * 3) >> 5))
        self.assertEqual(self.run_wrapper(lx=0xFF)[0], 100 + ((127 * 3) >> 5))     # left stick turns too
        self.assertEqual(self.run_wrapper(rx=0xFF, lx=0x00)[0], 100 + ((-1 * 3) >> 5))
        self.assertEqual(self.run_wrapper(rx=0xFF, dt=1)[0], 100 + (127 >> 5))

    def test_forward_and_back(self):
        _, fwd, moving = self.run_wrapper(ly=0x00)
        self.assertEqual((fwd, moving), (((128 * 3) * 11) >> 7, 1))            # 33 = full run speed
        _, back, moving = self.run_wrapper(ly=0xFF)
        self.assertEqual((back, moving), (((-127 * 3) * 11) >> 7, 1))
        self.assertEqual(self.run_wrapper(ly=0x00)[0], 100)                    # forward does not turn

    def test_call_site_goes_through_the_wrapper(self):
        off = patch_exe.MOVE_CALL - LOAD + patch_exe.HEADER
        word = struct.unpack_from("<I", self.exe, off)[0]
        self.assertEqual(word, 0x0C000000 | (patch_exe.STICK_BLOCK >> 2 & 0x3FFFFFF))


if __name__ == "__main__":
    unittest.main()
