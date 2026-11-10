# Germs: Nerawareta Machi: English translation and PC port

PS1 game SLPS-02107 (Japan only). Goals: an English fan translation with half-width text, then a native PC port.

## Phases

1. **Translation patch** (current). Dump the script, translate it, add a half-width 8x16 font to the text
   renderer, reinsert the text, rebuild the disc, and distribute an xdelta/PPF patch.
2. **PC port.** Static recompilation using psxrecomp (git submodule) in its own repo. The real BIOS is
   recompiled, so the Kanji ROM font calls keep working; we supply our own half-width font.

## Layout

- `tools/`: Python tools. Run them from the repo root with `python -I tools/<name>.py ...`.
- `docs/`: research notes. [docs/disc-survey.md](docs/disc-survey.md) covers the disc, text format and font.
- `extracted/`: output of `tools/extract_disc.py` plus dumps (gitignored).
- `translations/`: our English, as `{"<file>:<offset>": "text"}` maps (ids from the dump), one file
  per sheet. These hold no Japanese, so they are committed. Written by `tools/sheets.py import`.
- `sheets/`: translator spreadsheets from `tools/sheets.py export` (gitignored: Japanese inside).
  Workflow and rules: [docs/translating.md](docs/translating.md).
- `tests/fixtures/test_lines.json`: the hand-made test translation used for test discs.
- Text stored as images (the computer's mails and screens, RES.R TIMs): `tools/images.py` (ids `RES.R@<offset>`;
  screens with artwork take `{"regions": [...]}` rectangles, see `translations/screens.json`),
  `tools/tim.py` (TIM read/write and PNG export), `tools/font.py` (our own pixel font; never draw
  English with the BIOS font into images, since it can't be redistributed).
- `edits/`: hand-edited menu PNGs (gitignored: game artwork). `python -I tools/image_edit.py export` writes the
  translated room-file menus (M/A/*.RM) there; the inserter draws every PNG in edits/ over its TIM, after the
  text regions. See the docstring in `tools/image_edit.py`.
- `build/`: inserter output and rebuilt disc images (gitignored).

## Building a patched disc

```
python -I tools/sheets.py check
python -I tools/insert_script.py extracted build translations
python -I tools/patch_exe.py build/SLPS_021.07 build/SLPS_021.07
python -I tools/build_disc.py "Germs - Nerawareta Machi (Japan).bin" extracted/manifest.json build "build/disc/<name>.bin"
```

`build_disc.py` keeps the original file layout. The inserter refuses any change that would grow
SCE.S (each script area has fixed free space) and reports all problems at once, like `check`.
Window rules (widths, wrapping, choice labels) live in `tools/windows.py`; `prepare()` in
`insert_script.py` applies them.
- The disc image (`*.bin` / `*.cue`) sits in the repo root and is gitignored.

## Conventions

- **Never commit game data:** no disc images, extracted files, dumped Japanese script, or captured
  overlay code. Commit only tools, docs, our own translations and our own assets.
- Main EXE `SLPS_021.07`: RAM address = file offset - 0x800 + 0x80170000. Write RAM addresses as
  `0x801B1370`, and file offsets as `FILE+0x1234`.
- Text is Shift-JIS (decode with `cp932`). Single-byte control codes: space = one full 16 px cell,
  `,` = line break, other ASCII = colour (`byte - 0x30`). See the survey doc before changing the encoding.
- Record new findings (addresses, formats) in `docs/` as they are confirmed, and mark anything unconfirmed.
- Python 3 standard library plus `capstone` (disassembly), `keystone-engine` (assembling EXE patches)
  and `unicorn` (running patched code in tests). Debug in PCSX-Redux or DuckStation.
- Translation values are half-width by default; use `{"text": ..., "width": "full"}` only for text
  drawn by a renderer that isn't patched yet. Only `0x8018C864` is left (see the renderer table in
  docs/disc-survey.md).
- Live debugging: the DuckStation MCP fork (localhost:2346). Game controls are tank style: Left/Right
  rotate, Up/Down look, Triangle forward, Cross back, Circle interact.
- EXE patches go in `tools/patch_exe.py`, each checking the retail instructions it replaces. Hand-fill
  delay slots and load-delay slots (`.set noreorder`), and cover new code with a unicorn test.
- Tests: `python -m unittest discover tests` (needs `extracted/` and the script dump). The SCE.S
  rebuild must stay byte-identical when nothing is translated.
