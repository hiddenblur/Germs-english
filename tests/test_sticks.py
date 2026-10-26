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
YAW, PITCH, STRAFE, FORWARD, MOVING = PLAYER + 0x6E, PLAYER + 0x6C, PLAYER + 0x4E, PLAYER + 0x50, PLAYER + 0x3C


def P(addr):
    return addr & 0x1FFFFFFF


class Stick(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exe = patch_exe.apply(EXE_PATH.read_bytes())

    def run_wrapper(self, pad_id=0x73, rx=0x80, ry=0x80, lx=0x80, ly=0x80, dt=3, mode=0, yaw=100, pitch=0):
        uc = Uc(UC_ARCH_MIPS, UC_MODE_32 | UC_MODE_LITTLE_ENDIAN)
        uc.mem_map(P(0x80000000), 0x200000)
        uc.mem_write(P(LOAD), self.exe[0x800:])
        uc.mem_write(P(PAD), bytes([0, pad_id, 0xFF, 0xFF, rx, ry, lx, ly]))
        uc.mem_write(P(DT), struct.pack("<I", dt))
        uc.mem_write(P(PLAYER + 0x46), struct.pack("<H", mode))
        uc.mem_write(P(YAW), struct.pack("<H", yaw))
        uc.mem_write(P(PITCH), struct.pack("<h", pitch))
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
        return dict(yaw=h(YAW), pitch=h(PITCH), strafe=h(STRAFE), fwd=h(FORWARD), moving=h(MOVING))

    def test_calls_retail_movement_and_restores_the_stack(self):
        self.run_wrapper()
        self.assertEqual(self.moves, 1)
        self.assertEqual(self.sp, 0x801FF000)

    def test_idle_and_digital_leave_the_player_alone(self):
        idle = dict(yaw=100, pitch=0, strafe=0, fwd=0, moving=0)
        self.assertEqual(self.run_wrapper(), idle)
        self.assertEqual(self.run_wrapper(pad_id=0x41, rx=0xFF, ry=0, lx=0, ly=0), idle)
        self.assertEqual(self.run_wrapper(rx=0xFF, ry=0, lx=0, ly=0, mode=1), idle)
        near = 0x80 + 24
        self.assertEqual(self.run_wrapper(rx=near, ry=near, lx=0x80 - 24, ly=near), idle)

    def test_turn_right_stick_x(self):
        self.assertEqual(self.run_wrapper(rx=0xFF)["yaw"], 100 + ((127 * 3) >> 5))
        self.assertEqual(self.run_wrapper(rx=0x00)["yaw"], 100 + ((-128 * 3) >> 5))
        self.assertEqual(self.run_wrapper(rx=0xFF, dt=1)["yaw"], 100 + (127 >> 5))
        self.assertEqual(self.run_wrapper(rx=0xFF)["moving"], 1)    # the view only updates with this set

    def test_pitch_right_stick_y_and_limits(self):
        self.assertEqual(self.run_wrapper(ry=0x00)["pitch"], (128 * 3) >> 6)          # up: look up
        self.assertEqual(self.run_wrapper(ry=0xFF)["pitch"], -((127 * 3) >> 6))         # down
        self.assertEqual(self.run_wrapper(ry=0x00, pitch=64)["pitch"], 65)            # clamped at 65
        self.assertEqual(self.run_wrapper(ry=0xFF, pitch=-24)["pitch"], -25)          # and -25
        self.assertEqual(self.run_wrapper(ry=0x00)["moving"], 1)

    def test_forward_and_back_left_stick_y(self):
        r = self.run_wrapper(ly=0x00)
        self.assertEqual((r["fwd"], r["moving"], r["yaw"]), (((128 * 3) * 11) >> 7, 1, 100))   # 33
        r = self.run_wrapper(ly=0xFF)
        self.assertEqual((r["fwd"], r["moving"]), (((-127 * 3) * 11) >> 7, 1))

    def test_strafe_left_stick_x(self):
        r = self.run_wrapper(lx=0xFF)
        self.assertEqual((r["strafe"], r["moving"], r["yaw"]), (((127 * 3) * 6) >> 7, 1, 100))
        self.assertEqual(self.run_wrapper(lx=0x00)["strafe"], ((-128 * 3) * 6) >> 7)

    def test_call_site_goes_through_the_wrapper(self):
        off = patch_exe.MOVE_CALL - LOAD + patch_exe.HEADER
        word = struct.unpack_from("<I", self.exe, off)[0]
        self.assertEqual(word, 0x0C000000 | (patch_exe.STICK_BLOCK >> 2 & 0x3FFFFFF))


if __name__ == "__main__":
    unittest.main()
