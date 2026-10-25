# Germs: Nerawareta Machi: English translation and PC port

PS1 game SLPS-02107 (Japan only). Goals: an English fan translation with half-width text, then a native PC port.

## Phases

1. **Translation patch** (current). Dump the script, translate it, add a half-width 8x16 font to the text
   renderer, reinsert the text, rebuild the disc, and distribute an xdelta/PPF patch.
2. **PC port.** Static recompilation using psxrecomp (git submodule) in its own repo. The real BIOS is
   recompiled, so the Kanji ROM font calls keep working; we supply our own half-width font.
3. **Matching decomp** (optional, later). splat + maspsx + the original GCC version, following BFM-decomp.

## Layout

- `tools/`: Python tools. Run them from the repo root with `python -I tools/<name>.py ...`.
- `docs/`: research notes. [docs/disc-survey.md](docs/disc-survey.md) covers the disc, text format and font.
- `extracted/`: output of `tools/extract_disc.py` plus dumps (gitignored).
- The disc image (`*.bin` / `*.cue`) sits in the repo root and is gitignored.

## Conventions

- **Never commit game data:** no disc images, extracted files, dumped Japanese script, or captured
  overlay code. Commit only tools, docs, our own translations and our own assets.
- Main EXE `SLPS_021.07`: RAM address = file offset - 0x800 + 0x80170000. Write RAM addresses as
  `0x801B1370`, and file offsets as `FILE+0x1234`.
- Text is Shift-JIS (decode with `cp932`). Single-byte control codes: space = one full 16 px cell,
  `,` = line break, other ASCII = colour (`byte - 0x30`). See the survey doc before changing the encoding.
- Record new findings (addresses, formats) in `docs/` as they are confirmed, and mark anything unconfirmed.
- Python 3 standard library plus `capstone` for disassembly. Debug in PCSX-Redux or DuckStation.
- Tests: `python -m unittest discover tests` (needs `extracted/` and the script dump). The SCE.S
  rebuild must stay byte-identical when nothing is translated.
