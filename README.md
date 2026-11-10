# Germs: Nerawareta Machi: English translation patch

An unofficial fan translation of *Germs: Nerawareta Machi* (PlayStation, SLPS-02107, Japan only),
with an added **twin-stick control mod** for analog controllers.

This project does **not** contain the game. It is an xdelta3 patch that you apply to your own
disc image. You need a dump of your own copy of the game.

## Applying the patch

You need:

- Your own disc image of SLPS-02107 as a `.bin` / `.cue` pair, matching the checksums below
  (a Redump-style dump).
- The `Germs_EN.xdelta` patch from the Releases page.
- A patcher: [Delta Patcher](https://www.romhacking.net/utilities/704/),
  [xdelta-UI](https://www.romhacking.net/utilities/598/), or the xdelta3 command line.

With a graphical patcher: choose the original `.bin` as the source file, `Germs_EN.xdelta` as the
patch, and a new output name ending in `.bin`. Keep your original `.cue` file, copy it next to the new
`.bin`, and edit the `FILE "..."` line inside it to the new `.bin` name.

With the command line:

```
xdelta3 -d -s "Germs - Nerawareta Machi (Japan).bin" Germs_EN.xdelta "Germs - English.bin"
```

Load the new `.cue` in an emulator such as DuckStation. If the patcher reports a checksum
mismatch or "source file does not match", your dump is not the one the patch was made for.

### Expected original disc

| | |
|---|---|
| Size | 190,013,376 bytes |
| CRC32 | `B32D4A63` |
| MD5 | `e0afd6299ac6e10c7fd8027871a73701` |
| SHA-1 | `8ef1ed69c8f532d8e2ee91e1e4650b6a014ac2d4` |

`Germs_EN.checksums.txt` in the release lists the checksums of the patched image too.

Only play on an emulator that is known to work with this game. Real hardware is untested.

## What is translated

See the release notes for the current state. Text in the script, menus, and the in-game images
(the computer's mails and screens) is translated; the text uses a half-width font that the patch adds.

## Twin-stick controls

The original game only reads the digital buttons (tank-style controls). The patch adds dual-stick
control when a controller is in **analog mode**:

| Input | Action |
|---|---|
| Left stick up/down | Walk forward / back (full tilt = run speed) |
| Left stick left/right | Strafe |
| Right stick left/right | Turn |
| Right stick up/down | Look up / down |

The original buttons (d-pad to turn and look, Triangle / Cross to walk, L1 / R1 to strafe) keep
working, in analog mode too, and a digital pad plays exactly as before. In DuckStation, set the
controller type to *DualShock* and turn analog mode on with the Analog button (it resets when you load a
save state). The sticks have a dead zone, and turning and looking speeds are fixed for now.

### Driving

In analog mode the car gets its own layout:

| Input | Action |
|---|---|
| Left stick left/right | Steer |
| Cross | Accelerate |
| Square | Brake |
| Triangle | Reverse |

The d-pad still looks around, and L1 / R1 still steer. A digital pad keeps the original driving
controls (Triangle forward, Cross brake and reverse, L1 / R1 steer).

## Building the patch yourself

This repository holds only tools, notes and the English text, never game data. To rebuild the
patched disc and the patch from your own copy, see [CLAUDE.md](CLAUDE.md) and
[docs/translating.md](docs/translating.md):

```
python -I tools/sheets.py check
python -I tools/insert_script.py extracted build translations
python -I tools/patch_exe.py build/SLPS_021.07 build/SLPS_021.07
python -I tools/build_disc.py "Germs - Nerawareta Machi (Japan).bin" extracted/manifest.json build "build/disc/Germs - English.bin"
python -I tools/make_patch.py "Germs - Nerawareta Machi (Japan).bin" "build/disc/Germs - English.bin" release
```

`make_patch.py` needs xdelta3 (set `$XDELTA3`, put it in `tools/vendor/`, or add it to PATH).

## License

- Tools and code: MIT, see [LICENSE](LICENSE).
- The English translation (`translations/`) and documentation: CC BY 4.0.
- *Germs: Nerawareta Machi* and all of its original content belong to its respective rights
  holders. This project is not affiliated with or endorsed by them.
