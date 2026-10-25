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

## Implications for half-width English

1. A font has to be supplied either way. The BIOS ROM has no half-width Latin glyphs, and the PC port can't ship the BIOS.
2. The renderer already reads single bytes, so ASCII letters can be added as a new single-byte branch: draw an 8x16 glyph from our own table and advance 8 px (2 VRAM words at 4bpp) instead of 16 px.
   A variable-width font is also possible, but non-4-px-aligned widths need compositing into a RAM buffer before the VRAM upload.
3. Byte collisions need a new encoding: ASCII digits are colour codes and `,` is a line break, so English digits, commas and spaces need remapping. The space currently means a full cell, which menu alignment relies on.
4. Line and column limits (row limit at `0x98(sp)` in the loop above) and the window sizes will need checking against English line lengths.
