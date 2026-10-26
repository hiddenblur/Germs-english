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
