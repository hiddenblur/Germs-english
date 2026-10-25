# Disc survey: Germs: Nerawareta Machi (SLPS-02107)

## Disc

- Single MODE2/2352 data track, volume `GERMS001`, 80,788 sectors, 75 files.
- Every sector is Form 1 data, so there are no XA/Form 2 streams. The STR video is stored as ordinary data (frame magic `0x80010160`).
- `SYSTEM.CNF`: `BOOT = cdrom:SLPS_021.07;1`, TCB 4, EVENT 16, STACK `801FFF00`.
- `SLPS_021.07`: PS-X EXE, region "Japan area". Loads at `0x80170000` (0x70000 bytes), entry point `0x801C8840`.
  RAM address = file offset - 0x800 + 0x80170000.

| File(s) | Size | Notes |
|---|---|---|
| `SLPS_021.07` | 450 KB | Main code. Holds system/menu strings (83). |
| `SCE.S` | 7.0 MB | Scenario archive with most of the script (~2,450 strings, uncompressed SJIS) plus TIMs. 2 KB header sectors of 24-byte entries `(offset, size, ?, ?, ?, ?)`. After `0xE1000` the chunks are tagged `AREA`. |
| `RES.R` | 3.8 MB | Resource archive: a chain of 15 blocks, each with a 2 KB header. 209 TIMs, 72 strings. |
| `M.STR`, `D.STR` | 48 MB each | Byte-identical FMV. `D.STR` is probably filler/duplicate to control where data sits on the disc. |
| `C/CITY.*` | 27 MB | City map data. No text. |
| `B/A/*.B`, `F/A/*.F`, `M/A/*.RM` | | Per-area data, tagged by 3-letter area code (CDL, HTL, PSN...). No text. |

## Text format

- Null-terminated strings, padded to 4 bytes, mixing 2-byte Shift-JIS with single bytes.
- The renderer (e.g. `0x80182590`) treats bytes like this:
  - `>= 0x80`: 2-byte SJIS character, one 16x16 cell.
  - `0x20` (space): advance one **full** 16 px cell. Used for padding menu columns.
  - `0x2C` (`,`): line break (column = 0, row + 1). Japanese text uses `、` for commas.
  - Any other ASCII byte: sets the text colour to `byte - 0x30` (stored at `gp+0x21C`). Examples: `8` = highlight, `1` = normal, `3` before the `○` button glyph.
  - `%s` / `%d` appear in format strings filled in with sprintf first.
- Existing "English" text is written in full-width letters (e.g. `Ｖｉｔａｌｉｔｙ`).
- Tools: `tools/find_text.py <file>` lists strings with their offsets.

## Script commands (SCE.S)

Confirmed by size-field arithmetic on every parsed command:

```
u32 size      bytes after this field (next command = offset + 4 + size)
u16 opcode
u16 flag
u32 0
u32 argc
argc null-terminated string args, zero-padded to a 4-byte boundary
```

- All arguments are strings, numbers included (`"4"`, `"-1"`...).
- Opcode `0x05` is the only one carrying text (2,185 strings), with the text always in arg 0.
  - flag 1, argc 6: menu/choice entries (text, then numeric args).
  - flag 0, argc 2: dialogue/narration.
- The u32 after flag is a parameter (e.g. `7`, `0x86`), not always zero.
- **No slack inside commands:** every string fills its command exactly. Growth is absorbed by the
  ASET padding (see below).

## SCE.S container (confirmed: parse + rebuild is byte-identical, `tools/sce.py`)

```
EXE scene table   u32[24] at FILE+0x67F80 (RAM 0x801D7780): byte offset of each scene in SCE.S.
                  The RES.R block table sits just before it (RAM 0x801D7744, u32[15]).
scene             DIR sector (0x800): 24-byte entries (offset from scene, size, a, b, c, d), ended by
                  a zero entry. Entries are contiguous from +0x800. Unlisted AREA chunks follow
                  until the next scene. All 24 scenes tile exactly.
  MIDI / VABH     sound data (scene 0 MIDI, others VAB banks), kept raw.
  AREA            sector 0: "AREA", 0x7F8, 12-byte trigger entries (not decoded).
                  Then sub-chunks "TAG" u32 size payload, until the next AREA or scene end:
    ASET          event records chained by size, then zero padding (16..2040 bytes per ASET).
    ENMY, ACTR    kept raw (likely enemy and actor placement).
record            u32 size (including itself) | 0x38-byte header (u16 event id, u16 flag...) |
                  u32 command count | commands.
```

- 24 scenes, 84 AREAs, 9,693 commands. Text is only ever opcode 0x05, arg 0.
- Nothing points into records: record offsets appear in the AREA headers, ENMY or ACTR no more often
  than chance. Event ids are not positional, so the game presumably walks the chain by id.
- **Resizing rules** (as implemented in `tools/insert_script.py`):
  1. A changed command gets new size fields (command and record). Its ASET keeps its size while the
     records still fit with at least 16 zero bytes after them.
  2. Otherwise the ASET (so the AREA) grows by whole sectors. Later chunks in the scene move (DIR
     entries rewritten), later scenes move (EXE scene table rewritten), and SCE.S grows.
- **Unverified at runtime:**
  - Scene load buffer. The largest retail scene is 0x76000 bytes, and growth may overflow whatever
    buffer the game loads scenes into. Find the load routine (reads of the scene table at
    0x801D7780) and its size limit.
  - Disc rebuild after SCE.S grows. The EXE holds no hardcoded LBAs for SCE.S or the files after it,
    so files are probably found by name, but this needs checking in a debugger.
  - The DIR entry fields a..d and the record header fields are kept as-is. Their meaning is unknown.
- Other text in SCE.S (454 strings: character names, profiles, unit names) sits in fixed fields
  outside commands. RES.R holds item and food names (81). The EXE holds 89 system/menu strings.

## Script dump

`python -I tools/dump_script.py extracted` writes `extracted/script/<file>.json` (gitignored: it is
game text). Each entry has `id`, `file`, `offset`, `length`, `capacity`, `cmd` (opcode, flag, args)
for command strings, `ja` and an empty `en`. Totals: SCE.S 2,639 / RES.R 81 / EXE 89 strings,
about 157 KB of Japanese text.

## Font

- **The game has no font of its own.** It reads glyphs from the console BIOS Kanji ROM through the Psy-Q routine at `0x801B1370`, which calls BIOS `B(0x51) Krom2RawAdd` at `0x801B1A80`.
- Each glyph is 16x15 1bpp (30 bytes). The game expands it to a 4bpp 16x16 block (128 bytes) and uploads it to VRAM in a grid: x = base + col*4 VRAM words (16 px), y = base + row*16.
- The Kanji lookup is called from 4 places: `0x8018263C`, `0x801829EC` and `0x80182E58`, which share the space/comma/colour handling above, and `0x8018C908`, a single-character case that hasn't been investigated yet.

## Confirmed in emulator (test disc, 2026-10-24)

- Full-width English inserted by `tools/insert_script.py` displays correctly.
- The opening narration is the loose string `SCE.S:59008`, in scene 0's first chunk (tagged
  `MIDI`, so that chunk holds more than music).
- The narration window wraps automatically every **16 cells**, about 16 full-width letters per line.
  Explicit `,` line breaks also work.
- The ROM lookup draws only SJIS `0x8140-0x84BE` and `0x889F-0x9872` (from the disassembly).
  Anything else is drawn as a blank cell. In-game: full-width `＂` (cp932 extension code) showed as
  a blank. The encoder now uses “ ” and ’, and rejects characters with no glyph.

## Text renderers

Four functions call the Kanji lookup. All draw 16x16 4bpp cells into a VRAM text page with
LoadImage (`0x801B05A8`), using the window object from `0x801A44B8(gp+0x58)`, whose `+0x1C` points to
the page origin (x, y).

| Function | Used for | State | Half-width |
|---|---|---|---|
| `0x80182860` | narration typewriter: one glyph per call, 16x3 cells, then a page prompt via `0x801A4A68(0x40A, 1)`. Also NPC dialogue (confirmed live: the assistant's lines, caller `0x80183C18`) | gp `+0x218` col, `+0x21A` row, `+0x21C` colour, `+0x21E` length, `+0x220` index | **patched, confirmed live** |
| `0x80182518` | whole string at once into a cleared window (caller clears it with `0x801AE070` first). Prompts and menus: confirmed live with the desk prompt at `0x80170CF8` (EXE data, caller `0x80183FFC`, row limit 1) | `s2` col, `s4` row, `s3` index, `fp` string, `s6` window, row limit at `0x98(sp)` | **patched, confirmed live** |
| `0x80182D34` | 4-line panel (caller `0x80183778`: three struct strings + one sprintf line). Lines 0-1 centred, lines 2+ start at col 1 and wrap at 15. Line y from the table at `0x801D76A4` (3, 21, 39, 57, 74, 91). Composites onto the background via StoreImage `0x801B0694` | `s2` col, `s5` line, `s7` line y, `s3` index, `s6` window | **patched**, emulator-tested only (screen not found yet) |
| `0x8018C864` | glyphs from a struct (`+4`), 8x15 rects with its own 2/`0xE` pixel values | | not yet (never seen firing) |

## Half-width text (narration, menu and panel renderers)

All three use one routine template (`glyph_routine` in `tools/patch_exe.py`), parameterised by
where each renderer keeps its column, row and string pointer, and by whether it composites. Tests
run the retail and patched code on the same Japanese strings and require identical VRAM.

- **Intended difference:** the panel centres lines 0-1 in half-cells. Retail rounds down to whole
  cells, so Japanese with an odd number of spare cells now sits 8 px further right.
- **Retail quirk fixed along the way:** the panel's line advance after a wrap (`0x80183044`) reused
  the column register (always 1 in retail). With the start column now 2, it uses a constant 1.
- **Menu padding:** in half-width strings, pad to a column with the game's full-cell space `{20}`
  (16 px per byte) rather than half spaces (8 px per byte). The office ASET has no spare bytes.

- **Font:** BIOS charset 4, 8x15 ASCII `0x21-0x7F` at `0xBFC7F8DE`, 15 bytes per glyph (one byte per row,
  MSB = left pixel; the spacing ends exactly at charset 5, `0xBFC7FE6F`). It is in every PS1 BIOS, so
  no font data is needed in RAM, and the PC port gets it from the real BIOS. `\` draws as yen and `~` as
  an overline.
- **Encoding:** byte = ASCII + 0x80. `0xA0` is a half space (advance only); `0xA1-0xFE` are glyphs.
  These bytes never drew anything in retail: they're half-width katakana or SJIS lead bytes the ROM
  lookup doesn't cover. Exceptions: 2 retail strings (`SCE.S:1874FC`, `SCE.S:4B92FC`) contain stray
  half-width katakana; they will be translated anyway.
- **Layout:** columns count 8 px half-cells. Half-width advances 1, full-width SJIS 2, and the game's
  `0x20` space 2, so untranslated Japanese looks exactly as before. Narration wraps at 32 half-cells.
- **Patch** (`tools/patch_exe.py`): the 132-instruction unrolled glyph expansion at
  `0x801829DC-0x80182BE8` becomes one 79-instruction loop handling both widths. Plus the wrap compares
  (`0x801828E8`, `0x80182C40`, `0x80182CD0`: 16 -> 32) and the space advance (`0x801829A8`: 1 -> 2).
- **Tested** by running the real patched EXE code under unicorn (`tests/test_halfwidth.py`), with a
  synthetic ROM font and stubbed LoadImage. The same harness reproduces the retail renderer's uploads.
- **Confirmed in emulator:** half-width narration displays correctly (charset 4 is MSB-left), and
  pages break after 3 rows.
- **Scene splits:** the opening narration `SCE.S:59008` is typed across two scenes. The game shows
  15 rows (5 pages) on a black screen, loads the office and keeps typing the same string in the office
  window. The retail text breaks exactly there. A translation that ends inside the first 15 rows hangs
  the game with an error sound when the office loads (bisected: the EXE patch and the menu rebuild were
  fine). `tools/layout.py` simulates the window and the inserter rejects such text. The code that counts
  the pages hasn't been found yet. The ending narration `SCE.S:59808` (17 rows) may be split the same
  way; unchecked.
- **Known limit:** a full-width character starting at half-column 31 overflows the page by 8 px.
  Translated text shouldn't mix full-width characters in, so this is only an edge case.
- **Not yet verified on a real BIOS:** the bit order of charset 4 (assumed MSB-left like the Kanji ROM).
  If letters come out mirrored, flip the mask direction in `NARRATION_DRAW`.

## Implications for half-width English

1. A font has to be supplied either way. The BIOS ROM has no half-width Latin glyphs, and the PC port can't ship the BIOS.
2. The renderer already reads single bytes, so ASCII letters can be added as a new single-byte branch: draw an 8x16 glyph from our own table and advance 8 px (2 VRAM words at 4bpp) instead of 16 px.
   A variable-width font is also possible, but non-4-px-aligned widths need compositing into a RAM buffer before the VRAM upload.
3. Byte collisions need a new encoding: ASCII digits are colour codes and `,` is a line break, so English digits, commas and spaces need remapping. The space currently means a full cell, which menu alignment relies on.
4. Line and column limits (row limit at `0x98(sp)` in the loop above) and the window sizes will need checking against English line lengths.
