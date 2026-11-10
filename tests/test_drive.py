"""Analog driving controls (tools/patch_exe.py DRIVE_WRAPPER) on an emulated R3000.

The patched EXE is loaded under unicorn and the wrapper runs the real retail driving input
function 0x801ABC70 on a car state set up by the test (the physics that turns the pedals into a
speed is not run: the test sets the speed).
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
PAD, PLAYER, DT, CTRL, CAR = 0x80007570, 0x801E0620, 0x801E6DB4, 0x801E0710, patch_exe.CAR
# Called first when car +0 is set. EVENT_CHECK != 0 skips the input and returns 0; otherwise
# LEAVE_CHECK >= 0 skips the input and is returned (the caller then leaves the driving state).
EVENT_CHECK, LEAVE_CHECK = 0x8019A3E8, 0x801ABA88
L1, R1, TRIANGLE, CROSS, SQUARE = 0x04, 0x08, 0x10, 0x40, 0x80


def P(addr):
    return addr & 0x1FFFFFFF


class Drive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exe = patch_exe.apply(EXE_PATH.read_bytes())

    def drive(self, pad=0, pad_id=0x73, lx=0x80, gear=0, speed=0, fwd=0, rev=0, steer=0, busy=None, dt=3):
        """One frame. Returns the car's gear, forward pedal, reverse pedal and wheel."""
        uc = Uc(UC_ARCH_MIPS, UC_MODE_32 | UC_MODE_LITTLE_ENDIAN)
        uc.mem_map(P(0x80000000), 0x200000)
        uc.mem_write(P(LOAD), self.exe[0x800:])
        uc.mem_write(P(PAD), bytes([0, pad_id, 0xFF, 0xFF, 0x80, 0x80, lx, 0x80]))
        uc.mem_write(P(DT), struct.pack("<I", dt))
        uc.mem_write(P(CTRL + 0x5C), struct.pack("<I", PLAYER))
        uc.mem_write(P(CAR), struct.pack("<hhhhiii", busy is not None, 0, steer, gear, fwd, rev, speed))

        def hook(uc, addr, size, _):
            if addr == SENTINEL:
                uc.emu_stop()
            elif addr in (EVENT_CHECK, LEAVE_CHECK):
                uc.reg_write(R.UC_MIPS_REG_V0, busy[addr == LEAVE_CHECK] & 0xFFFFFFFF)
                uc.reg_write(R.UC_MIPS_REG_PC, uc.reg_read(R.UC_MIPS_REG_RA))
        uc.hook_add(UC_HOOK_CODE, hook)
        saved = {R.UC_MIPS_REG_SP: 0x801FF000, R.UC_MIPS_REG_S0: 0x1234, R.UC_MIPS_REG_S1: 0x5678,
                 R.UC_MIPS_REG_S2: 0x9ABC}
        for reg, value in saved.items():
            uc.reg_write(reg, value)
        uc.reg_write(R.UC_MIPS_REG_RA, SENTINEL)
        uc.reg_write(R.UC_MIPS_REG_A0, CTRL)
        uc.reg_write(R.UC_MIPS_REG_A1, pad)
        uc.emu_start(patch_exe.DRIVE_FIX, SENTINEL)
        for reg, value in saved.items():
            self.assertEqual(uc.reg_read(reg), value)             # stack and callee-saved registers
        self.v0 = uc.reg_read(R.UC_MIPS_REG_V0)
        _, _, steer, gear, fwd, rev, _ = struct.unpack("<hhhhiii", uc.mem_read(P(CAR), 20))
        return dict(gear=gear, fwd=fwd, rev=rev, steer=steer)

    def test_digital_pad_keeps_the_retail_controls(self):
        d = dict(pad_id=0x41)
        self.assertEqual(self.drive(TRIANGLE, **d), dict(gear=1, fwd=3, rev=0, steer=0))
        self.assertEqual(self.drive(CROSS, **d), dict(gear=-1, fwd=0, rev=3, steer=0))
        self.assertEqual(self.drive(SQUARE, lx=0xFF, steer=10, **d), dict(gear=0, fwd=0, rev=0, steer=10))
        self.assertEqual(self.drive(L1, speed=50, gear=1, **d)["steer"], -3)

    def test_cross_accelerates(self):
        self.assertEqual(self.drive(CROSS), dict(gear=1, fwd=3, rev=0, steer=0))
        self.assertEqual(self.drive(CROSS, gear=1, speed=90, fwd=100), dict(gear=1, fwd=103, rev=0, steer=0))
        # still rolling backwards: it brakes (the gear only changes at a standstill)
        self.assertEqual(self.drive(CROSS, gear=-1, speed=-90, rev=100), dict(gear=-1, fwd=3, rev=97, steer=0))
        self.assertEqual(self.drive(CROSS, gear=-1, rev=100), dict(gear=1, fwd=3, rev=0, steer=0))

    def test_triangle_reverses(self):
        self.assertEqual(self.drive(TRIANGLE), dict(gear=-1, fwd=0, rev=3, steer=0))
        self.assertEqual(self.drive(TRIANGLE, gear=-1, speed=-90, rev=100), dict(gear=-1, fwd=0, rev=103, steer=0))
        self.assertEqual(self.drive(TRIANGLE, gear=1, speed=90, fwd=100), dict(gear=1, fwd=97, rev=3, steer=0))
        self.assertEqual(self.drive(CROSS | TRIANGLE)["gear"], 1)                 # Cross wins

    def test_square_brakes_in_either_gear(self):
        self.assertEqual(self.drive(SQUARE, gear=1, speed=90, fwd=100), dict(gear=1, fwd=97, rev=3, steer=0))
        self.assertEqual(self.drive(SQUARE, gear=-1, speed=-90, rev=100), dict(gear=-1, fwd=3, rev=97, steer=0))
        # it wins over the accelerator
        self.assertEqual(self.drive(SQUARE | CROSS, gear=1, speed=90, fwd=100), dict(gear=1, fwd=97, rev=3, steer=0))

    def test_square_never_changes_the_gear(self):
        for gear in (1, 0, -1):
            self.assertEqual(self.drive(SQUARE, gear=gear, fwd=60, rev=40)["gear"], gear)
        # stopped with the brake held: the forward pedal stays up, so the car stays put
        self.assertEqual(self.drive(SQUARE, gear=1, fwd=60, rev=40)["fwd"], 0)
        self.assertEqual(self.drive(SQUARE, gear=-1, fwd=60, rev=40)["rev"], 0)

    def test_left_stick_sets_the_wheel(self):
        self.assertEqual(self.drive(lx=0xFF)["steer"], 45)
        self.assertEqual(self.drive(lx=0x00)["steer"], -45)
        self.assertEqual(self.drive(lx=0x80 + 64)["steer"], (40 * 7) >> 4)       # 17
        self.assertEqual(self.drive(lx=0x80 - 64)["steer"], (-40 * 7) >> 4)      # -18
        self.assertEqual(self.drive(lx=0xFF, steer=-45, gear=1, speed=90)["steer"], 45)
        self.assertEqual(self.drive(R1, lx=0x00)["steer"], -45)                  # the stick wins over L1/R1

    def test_dead_zone_leaves_the_wheel_to_the_game(self):
        for lx in (0x80, 0x80 + 24, 0x80 - 24):
            self.assertEqual(self.drive(lx=lx, steer=10)["steer"], 10)           # parked: stays
            self.assertEqual(self.drive(lx=lx, steer=10, gear=1, speed=90)["steer"], 7)   # moving: self-centres
        self.assertEqual(self.drive(L1, gear=1, speed=90)["steer"], -3)
        self.assertEqual(self.drive(R1, gear=1, speed=90)["steer"], 3)

    def test_nothing_is_steered_when_the_game_takes_over(self):
        r = self.drive(CROSS, lx=0xFF, busy=(0, 1), steer=5)                     # leaving the car
        self.assertEqual((r, self.v0), (dict(gear=0, fwd=0, rev=0, steer=5), 1))
        r = self.drive(CROSS, lx=0xFF, busy=(0, -1), steer=5)                    # carries on driving
        self.assertEqual((r, self.v0), (dict(gear=1, fwd=3, rev=0, steer=45), 0))
        # an event frame skips the pedals and returns 0, like the on-foot path: the stick still applies
        self.assertEqual(self.drive(CROSS, lx=0xFF, busy=(1, 0), steer=5), dict(gear=0, fwd=0, rev=0, steer=45))

    def test_call_site_goes_through_the_wrapper(self):
        word = struct.unpack_from("<I", self.exe, patch_exe.DRIVE_CALL - LOAD + patch_exe.HEADER)[0]
        self.assertEqual(word, 0x0C000000 | (patch_exe.DRIVE_FIX >> 2 & 0x3FFFFFF))
        self.assertLessEqual(patch_exe.DRIVE_FIX + len(patch_exe.asm(patch_exe.DRIVE_WRAPPER, patch_exe.DRIVE_FIX)),
                             patch_exe.STICK_BLOCK_END)


if __name__ == "__main__":
    unittest.main()
