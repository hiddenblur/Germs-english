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
(like the pad update) next to libetc/libapi, so that range is not pure library code.

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
| right Y | pitch `+0x6C`, `stick * dt >> 6`, clamped -25..65 | Up/Down | confirmed in game by the user (2026-11-09) |
| left X | strafe `+0x4E`, `stick * dt * 6 >> 7` | L1/R1 | confirmed in game by the user (2026-11-09) |

All four stick axes are confirmed working in game (user playtest, 2026-11-09).

Digital pads (ID `0x41`) are untouched. The Analog button turns analog mode on
(DuckStation resets it on a state load). `[+0x46] != 0` was skipped at first; see "Subway" below.

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

## Subway: sticks with `[+0x46] = 3` (found and fixed 2026-11-09)

User report: the sticks did nothing in the subway. Seen in DuckStation in a subway: the frame still
goes through the city call (`ra = 0x801A8888`, `a1 = 2`) with the player mode `[+0x46] = 3`, and the
wrapper skipped every non-zero mode. In that mode the retail function sends the d-pad to the look
pair instead of pitch and yaw: Up/Down change `0x801E114C` and Left/Right `0x801E114E`, `+-dt` per
frame (`0x801E1118 + 0x34/0x36`), and the city call multiplies both velocities by 4 (`0x801999AC`).
Holding Up took `0x801E114C` from 0 to 1431 with no stop, so retail has no limit there.

The wrapper now does the same for any non-zero mode: right stick X/Y go to `0x801E114E`/`0x801E114C`
with the usual scaling and no clamp, and the left stick velocities get the x4 (still x10 when
`a1 != 2`). Modes seen so far: 0 on foot, 1 car (never reaches this function), 3 subway; 2 is unknown
and gets the same treatment as the retail d-pad gives it. Checked live by writing the new block into
the running game and faking the right stick bytes at a breakpoint on the wrapper: the pair went
(0, -90) to (4, -83) in one frame with `dt = 2`. Both sticks then confirmed in the subway by the user
(2026-11-09); unit tests in `tests/test_sticks.py`.

DuckStation MCP note: when the plugin is not connected to the session, the server still answers plain
JSON-RPC over HTTP at `http://localhost:2346/mcp` (`initialize`, then `tools/call` with the
`MCP-Session-Id` header).

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

## Speed outside the city (fixed 2026-10-25)

After setting the forward/sideways velocity (`+0x50`/`+0x4E`) from the buttons, `0x80199548` rescales
it by the mode `a1`: `a1 != 2` (buildings: `0x801942E4` passes 0, `0x8017DF7C` passes 1) multiplies both
by 10 (`0x801999C8`); `a1 == 2` (city) with `[+0x46] != 0` multiplies by 4, and with `[+0x46] == 0` it
only applies the `[a0+0x42]` diagonal factors (x0.9 / x0.7). The stick wrapper runs after that, so
indoors its velocity was 10x too small (user: "walking is very slow in buildings"). It now saves `a1`
and applies the same x10 when `a1 != 2`. The city path is unchanged (the 0.9/0.7 factor is not
reproduced). Interiors use finer position units, so the x10 is what makes the pad and stick speeds match.

## Driving (found 2026-11-09 from the code; behaviour confirmed by playing the patched disc)

The game does have a car. In the city frame routine (`0x801A8768`) the player mode `[+0x46]` picks
the input function: 1 = in the car, `jal 0x801ABC70` at `0x801A87EC` (the only caller) with
`a0 = 0x801E0710` and `a1 =` the held pad word; anything else goes on to the on-foot `0x80199548`.
A non-zero return puts the city into state 4 (`0x356($gp)`), inferred to be leaving the car.

`0x801ABC70` works on the **car state at `0x801E1158`**:

| Offset | Address | Meaning |
|---|---|---|
| `+0x00` | `0x801E1158` | halfword set by the physics; while set, `0x8019A3E8` and `0x801ABA88` run first and can skip the input |
| `+0x04` | `0x801E115C` | wheel, -45..45. L1 = down, R1 = up, `dt` per frame; returns to 0 by itself while the speed is not 0 |
| `+0x06` | `0x801E115E` | gear: 1 forward, -1 reverse, 0 after init. A pedal changes it only while the speed is 0, and that zeroes both pedals |
| `+0x08` | `0x801E1160` | forward pedal, 0..0x100: Triangle held = `+dt`, released = `-dt` |
| `+0x0C` | `0x801E1164` | reverse pedal, same, on Cross |
| `+0x10` | `0x801E1168` | speed this frame, written by the physics |
| `+0x24` | `0x801E117C` | look up/down, -20..20 (d-pad Up/Down) |
| `+0x26` | `0x801E117E` | look left/right, -65..65 (d-pad Left/Right) |

(`0x801E114C`/`0x801E114E`, which the on-foot function changes when `[+0x46] != 0`, are a different
pair: `0x801E1118 + 0x34/0x36`.)

Physics, `0x801AA360`: in gear 1 the engine value is `0x320 + 30 * forward pedal` (at most `0x1964`)
`- 45 * reverse pedal` (at least `0x320`, the idle value, which gives speed 0); in gear -1 the two
pedals swap and the speed is negative. So the pedal of the other direction is the brake, and
retail Cross is "brake, then reverse". All the inertia is in the pedals' ramp.

### Analog driving controls (2026-11-09)

`DRIVE_WRAPPER` in `tools/patch_exe.py` (after the pad fix in the old `GsSetFlatLight`, block now
212 of 348 words) wraps the call at `0x801A87EC`. A digital pad (ID `0x41`) is untouched. In
analog mode (ID `0x73`):

| Input | Does | How |
|---|---|---|
| Cross | accelerate | passed on as the Triangle bit (forward pedal); brakes first if reversing |
| Triangle | reverse | passed on as the Cross bit (reverse pedal); brakes first if going forward |
| Square | brake | passed on as the pedal that brakes in the current gear, and the gear is restored after the call, so it stops the car and holds it instead of driving off the other way. Wins over Cross/Triangle |
| left stick X | steer | wheel `= (stick - dead zone 24) * 7 >> 4`, clamped to -45..45, written after the call. In the dead zone L1/R1 and the self-centring work as before |

D-pad look, L1/R1 and every other button are passed through. Unit test: `tests/test_drive.py`
(unicorn, runs the real `0x801ABC70`). **Confirmed in game by the user (2026-11-09):** all four
inputs work and stick left steers left. The direct wheel is a little twitchy; the user chose to keep
it that way as in keeping with the original game's feel.
Not done: analog throttle (the pad has no analog buttons in mode `0x73`), right stick look in the car.
