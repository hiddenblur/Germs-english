# Player controls: findings (2026-10-25)

Found in the retail game running in DuckStation (city, first person), with an execute breakpoint on
every `andi rX, rY, 0x2000` site (Right) and a read breakpoint on the held-buttons word. Addresses are
RAM. **Confirmed** = seen in the debugger; **inferred** = read from the code only.

## Pad path (confirmed)

1. The BIOS pad buffer (`0x801E6DC0`, digital pad: byte 0 = status, bytes 2-3 = buttons, active low) is
   read by `PadRead` (`0x801CCA40`, libetc: returns `~[0x801E6DC0]`).
2. `0x801CD6B4` (per-frame pad update) stores it into the **held word `0x801E6DA0`** and the previous
   frame's value into `0x801E6DA4`. Bits (pressed = 1): L2 `0x0001`, R2 `0x0002`, L1 `0x0004`, R1 `0x0008`,
   Triangle `0x0010`, Circle `0x0020`, Cross `0x0040`, Square `0x0080`, Select `0x0100`, Start `0x0800`,
   Up `0x1000`, Right `0x2000`, Down `0x4000`, Left `0x8000`.
3. Only the digital buttons are used. There is no analog code path (the game never switches the pad to
   analog mode), so sticks and mouse have to be added.
4. The per-frame time step is the word at **`0x801E6DB4`** (3 while running normally). Every movement
   delta below is multiplied by it.

Note: game code is interleaved with the Psy-Q libraries. `0x801CC...-0x801D1...` holds game routines
(like the pad update) next to libetc/libapi, so `psyq_libs` in `decomp/germs.yaml` is not pure library.

## Movement function `0x80199548` (confirmed it runs each frame; fields inferred from the code)

`jal 0x80199548` with `a0 = 0x801E0710` (controller state), `a1 = 2` (mode), `a2 = pad bits`; the call
is at `0x801A8880`. Other callers: `0x8017DF7C`, `0x801942E4` (other screens). It is a leaf: no stack
frame. `a3 = [a0+0x5C] = 0x801E0620`, the **player struct**:

| Offset | Address | Meaning |
|---|---|---|
| `+0x3C` | `0x801E065C` | "input this frame" flag (set by any direction/move button) |
| `+0x42` | `0x801E0662` | flags; bit `0x1000` = run (L2 held at a1 = 2), cleared again on release |
| `+0x46` | `0x801E0666` | mode: 0 = turn/look the player, non-zero = move the camera look offsets instead |
| `+0x4A` | `0x801E066A` | speed step, ramps 4 up to 11 while a move button is held, resets to 4 |
| `+0x4E` | `0x801E066E` | sideways velocity (L1 = negative, R1 = positive; `6 * dt`, or `step * dt` when running) |
| `+0x50` | `0x801E0670` | forward velocity (Triangle = positive, Cross = negative; same scaling) |
| `+0x6C` | `0x801E068C` | pitch (Up/Down look), `+-dt` per frame |
| `+0x6E` | `0x801E068E` | **yaw / heading** (Left/Right turn), `+-dt` per frame (seen 162 -> 165 over 3 frames) |

With `+0x46 != 0` the same Up/Down/Left/Right bits change `[0x801E114C]` and `[0x801E114E]` instead
(a look offset). With `a1 == 2` and `[a0+0x42]` = 2 or 3 the forward and sideways velocities are
rescaled (`v * 9 / 10`, `0x6666667` division: probably diagonal speed limiting).

So the "tank" feel is just: **Left/Right integrate the yaw, Triangle/Cross set the forward velocity.**
The position update that consumes `+0x4E`/`+0x50` and the yaw has not been found yet.

## What this means for new controls

- Keyboard + mouse, or dual stick: the cleanest hook is to leave `0x80199548` alone and, after it runs
  each frame, add `mouse_dx * k` / `right_stick_x * k` to `+0x6E`, `right_stick_y * k` to `+0x6C`,
  and set `+0x50` / `+0x4E` from WASD or the left stick (scaled to the same range the pad produces:
  about `6 * dt`, running about `step * dt`). Yaw and pitch units are unconfirmed (the compass in the
  screenshot shows E-SE at yaw about 165, so a full circle is probably `0x1000`; check this).
- In a recomp the hook is a function-level override or a post-call callback. psxrecomp's `.psxmod`
  packages are byte patches, asset overlays and VBlank plugins (per its README, not tested here); they
  do not describe function hooks, so the port should own this function.
- Not checked: driving or vehicle sections (this game may not have any), how the camera reads yaw,
  and whether any other screen uses these fields.

## Analog stick prototype (2026-10-25)

`tools/patch_exe.py` (`STICK_WRAPPER`): the call to `0x80199548` at `0x801A8880` goes through a wrapper
that runs it and then reads the sticks from the BIOS pad buffer `0x80007570` (+4 RX, +5 RY, +6 LX,
+7 LY, 0x80 = centre), which a pad in analog mode (ID byte `0x73`) fills. The wrapper lives in
`GsSetFlatLight` (`0x801B1F90`-`0x801B2500`, never called: an execute breakpoint saw 0 hits).

| Stick | Field | Like the button | Status |
|---|---|---|---|
| right X | yaw `+0x6E`, `stick * dt >> 5` | Left/Right | confirmed live (compass E to S); needs `+0x3C` set too |
| left Y | forward `+0x50`, `-stick * dt * 11 >> 7` (full = run speed) | Triangle/Cross | confirmed live (view moved) |
| right Y | pitch `+0x6C`, `stick * dt >> 6`, clamped -25..65 | Up/Down | unit test only |
| left X | strafe `+0x4E`, `stick * dt * 6 >> 7` | L1/R1 | unit test only |

Digital pads (ID `0x41`) and `[+0x46] != 0` are untouched. The Analog button turns analog mode on
(DuckStation resets it on a state load).

Original controls (confirmed by the user): d-pad rotates the view (Left/Right turn, Up/Down look
up/down), Triangle/Cross forward/back, L1/R1 strafe. Measured with the real buttons: Up stops at
pitch +65 and Down at -25 (clamped inside the game), and R1 strafes the view sideways.

An earlier note here said pitch and strafe do nothing. That was wrong: the character was pushed
against a wall or in a prompt state, where the pad buttons did nothing either.

Yaw is not 0..0xFFF: it kept counting past `0x1400` with no wrap. The world code reads it as a
signed halfword (`lh 0x6E`) and passes it through `0x8018C0A0`, so the real unit is still open.
Collision/movement reader: `0x8017A29C`.

DuckStation's `set_analog` is overridden by a connected physical pad (the buffer showed 0x7B-0x82
noise), so scripted stick tests need that pad unplugged or idle.

Unit test: `tests/test_sticks.py` (unicorn; the retail movement function is stubbed).
Not done: mouse input (needs the recomp), a smoother turn curve, sensitivity options.

Fix 2026-10-25: the view only updates while `[+0x3C]` ("moving this frame") is 1, and every
retail direction button sets it. The first stick version set it only for forward/strafe, so the
right stick turned and looked only while the left stick was also deflected. Yaw and pitch now set it
too (user report; unit tests check it).

Call sites (found booting the patched disc: the office did not use the city one): `0x80199548` is
called from `0x801A8880` (city, a1 = 2), `0x801942E4` (office, a1 = 0, pad word in a2) and `0x8017DF7C`
(a1 = 1; not seen running yet). All three go through the stick wrapper, which finds the player struct
through `[a0 + 0x5C]` instead of a fixed address and saves `s0`/`ra` around the call.
Boot check, 2026-10-25: a disc built with `insert_script` + `patch_exe` + `build_disc` boots, shows the
English intro, and hits the wrapper in the office (execute breakpoint at `0x801B1F90`, caller `0x801942EC`).

## Buttons die in analog mode (found 2026-10-25, fixed)

The game reads the pad through libetc `PadRead` (`0x801CCA40`), which calls the BIOS routine B0:0x16
(stub `0x801CCA94`). That routine fills the word at `0x801E6DC0` from the pad buffer `0x80007570`, but
only for ID `0x41` (digital) or `0x23` (neGcon; BIOS code at `0x61F8`-`0x6244`). With an analog pad
(ID `0x73`) the word stays `0xFFFFFFFF`, so the held-buttons word `0x801E6DA0` is 0 and **no button
works** while analog mode is on (user report: Circle dead; I then saw Triangle dead too). This
also explains the earlier "Up does nothing" results in analog mode. The same would happen on a
real console with the DualShock Analog button on.

Fix (`PAD_FIX_ASM` in `tools/patch_exe.py`, after the stick wrapper): the call at `0x801CCA48` goes
through a wrapper that runs the BIOS call, then for ID `0x73` with status 0 stores
`(buf[2] << 8) | buf[3]` into the halfword at `0x801E6DC0`, as the BIOS does for a digital pad.
Tested in DuckStation (Triangle read as `0x10` in the held word, Circle triggered a scene change) and
with unicorn (`PadButtons` in `tests/test_sticks.py`).
