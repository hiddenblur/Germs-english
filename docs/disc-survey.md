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
  outside commands. RES.R holds item and food names (81), and a `WEPN` table at `RES.R:0x76000`: an 8-byte header (`WEPN`, u32 size), then 0x60-byte records `[u16 id][u16 category][char name[32]][stats from +0x24]`, 18 weapons (dumped as fixed 32-byte fields, window "weapon"). The EXE holds 89 system/menu strings.

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
| `0x8018C864` | weapon names: the RES.R `WEPN` record's name (`+4`), seen on the attack analysis screen (caller `0x8018CD10`, list rows 0x11 apart). Each Kanji ROM glyph is squashed to an 8x15 cell (2 source pixels -> 1: both set 2, both clear `0xE`, mixed `0xA`); always 12 cells, blanks filled with `0xEE` | `s4` record, `s2` byte index, rect at `0x10(sp)` | **patched** (one cell per half-width byte, 12 cells), emulator-tested only |

## Typewriter speed and the opening/ending narration cues

- The text command handler (state machine at `0x801837F0`, state in `(*cmd)+2`: 0 init, 3 typing,
  4 page wait) calls the typewriter once per frame. On a non-zero return (page full) it waits on the
  `gp+0x222` timer, and when a page is full (`row == 3`) it clears the window and continues.
  `0x801749E8` re-queues the command on the list at `gp+0x1FC` so it runs again.
- **The opening and ending narration use a different path** (confirmed live, 2026-11-09). The scene
  function `0x80194780` (scene id at `0x801E0356`: 1 = opening, 2 = ending) starts them with
  `0x80183CFC(string)`. That creates a task (`0x801D15C8`): period 10 vblanks (`+0x2C`), tick
  `0x80184338` (one typewriter call with `a1 = 0`, no page prompt; after a full page it skips one
  tick via `gp+0x8E`), progress `+0x24` = typewriter index, end `+0x26` = string length, end callback
  `0x80184408`. The task handle is kept at `0x801E05B0` (-1 when no narration runs). Ticks are
  type-2 events handled inside the event getter `0x801CC378`, which the scene loop calls each frame.
- **Scene cues are keyed to the typewriter index.** Each frame the scene loop calls
  `0x80184434(scene - 1)` (from `0x80194990`). While the task is alive it compares `gp+0x220` with
  fixed values, each cue one-shot:
  | Scene | Index | Action | Flag |
  |---|---|---|---|
  | opening | 426 (`0x1AA`) | `0x80186128(0, 3)`: fades the office in | `gp+0x224` |
  | opening | 538 (`0x21A`) | `0x801A3CC0(3)` (purpose unconfirmed, probably sound) | `gp+0x226` |
  | ending | 386 (`0x182`) | `0x80186128(0, 3)` | `gp+0x224` |

  Retail tests for **equality**. That is why the office "never loads" when the index steps over 426
  (typing more than one glyph per tick) or never reaches it (a translation shorter than 426 bytes):
  the fade never starts and the game stays black after the text ends. It is not a timer. The index
  counts bytes of the string, so in English the cues come at byte 426/538, wherever that falls on
  screen.
- **Narration pace (2026-11-09):** 3 glyphs per 10-vblank tick looked choppy, so the narration task is
  off the wrapper: its two typewriter calls (`0x80183E40`, `0x801843EC`) stay retail (one glyph per tick)
  and `NARRATION_PERIOD` (`+0x2C` of the task, set at `0x80183D5C`, retail 10) is 4. Measured live: about
  one glyph per 4.8 vblanks (the loop runs every 3 vblanks, so the period rounds up to frame ticks), 12.6
  glyphs/s, against 6/s retail and 18/s with the wrapper. Period 3 would give 20/s.
- `tools/patch_exe.py` redirects the other 3 typewriter calls (`0x80183588`, `0x80183C18`, `0x801842C0`:
  ordinary dialogue) to a wrapper (after the narration glyph
  routine) that draws 3 glyphs per call. The cue tests are patched to
  `index >= value` (`NARRATION_CUES`), so they fire at any pace. Watch the load-delay slot after
  `lh $v1, 0x220($gp)` there. The old "timed" marker (`FE FF` after the terminator) and the
  length test for the retail strings are gone.
- **Confirmed in emulator (2026-11-09, disc "English 6 (fast opening)"):** the English opening types
  at 3 units per 10 vblanks (about 31 s instead of 100 s), the fade starts at index 428, both cues
  fire, and the game reaches the desk prompt. The ending cue patch is covered by the unicorn test
  only; the ending has not been played.
- A translation of the opening shorter than 426 bytes (ending: 386) would still never fade.
  Unpatched; the scene-split rule in `tools/layout.py` keeps the opening long enough in practice.
- Circle to finish or advance a page: tried (wrapper reading the raw pad buffer) but it didn't work
  in game, and retail never supported it. Removed for now. Pages advance on the `gp+0x222` timer;
  that's the place to look if this is picked up again.
- Controller: the BIOS fills a raw pad buffer at `0x80007570` (byte 0 = 0 when a pad answered,
  bytes 2-3 buttons active low; Circle = byte 3 bit 5). The game's own held-buttons word is at
  `0x801E6DA0` (Square = `0x0080`).

## Profiles (panel renderer 0x80182D34)

From the code; not seen in game yet. The likely trigger is "Residual thoughts remain" on a body.
The caller (`0x80183618`) gets a profile record from `0x801767D4` and draws:
- **line 0:** name at `+0x0C`, centred.
- **line 1:** title at `+0x2C`, centred.
- **line 2:** `sprintf(fmt @0x801704F0, age, sex, height, blood)`. The values come from the record
  header: `+2` height, `+4` sex index, `+6` age, `+8` blood index. The words come from tables at
  `0x801D76C4` (sex: ？/男/女) and `0x801D76D0` (blood: ？/A/B/O/AB型), stored at `0x801DFCB4..E0`.
  These EXE strings are added to the dump by hand (`FIXED_EXE` in `tools/dump_script.py`).
- **lines 3-7:** description at `+0x4C`. The line y table at `0x801D76A4` has 8 entries, so up to
  5 rows. The renderer wraps mid-word at half-column 30 and ignores line breaks, so
  `insert_script.profile_text` word-wraps into rows of 26 half-cells. It pads each row with
  full-cell spaces (2 half-cells per byte), then adds a blank full-width space that crosses column 30.

Records repeat across scenes. 373 unique texts cover the 452 fields.

The computer also has a **Config** screen (third icon: message speed, which feeds the `gp+0x222`
page timer, and car speed) and a **Status** screen (fourth icon). Both are images still to
translate, and so is the City map's label bar (first icon).

## Computer screens: text is images (confirmed live, 2026-10-25)

The in-office computer (desk prompt, then Down x2 to the blue icon, Circle for the inbox, Circle to
open a mail) draws **no text through the Kanji ROM**. Breakpoints on `0x801B1370` and `0x8018C864`
never fire, and the mail text isn't in RAM or on disc as Shift-JIS.

- The mail body is a pre-rendered **4bpp TIM, 240x128**, with a 16-colour palette (index 0 white ink,
  index 14 dark background). It's loaded from RES.R into RAM (seen at `0x800ACD80`) and uploaded
  as-is to VRAM x=960, y=0. Fujita's first mail is the TIM at `RES.R:0x1F5030` (rows match byte for byte).
- RES.R holds 209 TIMs: 79 are 240x128 4bpp (mail bodies), 34 are 240x16 (likely mail-list rows),
  plus UI panels and labels (green panels near `0x1E305C`, a label block near `0x1C223C`).
- The inbox list is first uploaded as a blank 240x128 canvas (all `0xEE`) to VRAM x=960, y=256
  (TIM in RAM at `0x800B463C`).

Translating these means editing images: export each TIM, render English with our own pixel font
(not the BIOS font, which can't be redistributed), convert back to 4bpp with the same palette, and
write it in place at the same size.

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
  fine). `tools/layout.py` simulates the window and the inserter rejects such text. Nothing counts
  pages: the office fade is a cue at typewriter index 426 (see "Typewriter speed and the
  opening/ending narration cues"). The ending narration `SCE.S:59808` (17 rows) may be split the same
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


## HUD clock (confirmed live in DuckStation)

- `RES.R@8901C` is an 8bpp 96x32 TIM (VRAM image (336, 64), CLUT (0, 484)). The game draws it as ONE
  sprite (cmd `0x66`, 96x32, uv (32, 64), at screen (16, 24)); no per-digit primitives exist.
- The digits are lit through the palette: each of the 6 digits (day tens/ones, hour tens/ones,
  minute tens/ones) has 7 segments with their own palette indices (`0x02-0x08`, `0x09-0x0F`,
  `0x10-0x16`, `0x17-0x1D`, `0x1E-0x24`, `0x25-0x2B`). Every time change the game rewrites those CLUT
  entries at VRAM (0, 484) (white = lit, 0 = off); the image pixels never change (VRAM watch on the
  image: no writes). `0x30` is the static white (the "Day" text and the colon).
- So the digit positions are just where those indices sit in the TIM: moving a digit needs no EXE
  patch, only the same indices at the new spot. `tools/image_edit.py` (`SEGMENT_DIGITS`) does that
  for PNG edits.
