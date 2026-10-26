# Decomp setup notes

## Toolchain (installed 2026-10-25)

- `psyq/` (gitignored): Psy-Q programmer tools CD DTL-S2002 (11/26/96) plus `zips/Lib44.zip`, `Lib45.zip`.
  `bin/CC1PSX.EXE`, `CPPPSX.EXE`, `ASPSX.EXE`, `CCPSX.EXE` are **Win32 PE**: they run natively on Windows.
  `PSYLIB.EXE` and `DUMPOBJ.EXE` do not (DOS), so `tools/psyqlib.py` reads the LIB/LNK format itself.
- splat64 0.51.0 (`pip install` of the wheel, plus rabbitizer, spimdisasm, n64img, crunch64).
- maspsx: not on PyPI; cloned to `tools/vendor/maspsx` (gitignored), run as `python tools/vendor/maspsx/maspsx.py`.
- objdiff and Ghidra 12.2 sit in the repo root (gitignored).

## SDK version

`tools/libmatch.py` masks relocated words and searches the EXE for each Psy-Q library function.
Unique functions found (main SDK / Lib44 / Lib45):

| Library | main | Lib44 | Lib45 |
|---|---|---|---|
| LIBCARD | 4/11 | **11/11** | 4/10 |
| LIBMCRD | 19/34 | **30/30** | 24/32 |
| LIBCD | 26/64 | **35/60** | 32/60 |
| LIBSND | 124/254 | **131/254** | 130/254 |
| LIBGTE | 65/534 | **70/527** | 70/527 |
| LIBGPU | 36/106 | **40/106** | 40/106 |

Lib44 (SDK 4.4 libraries) is the best match; LIBCARD and LIBMCRD match completely. Use `Lib44` for
decomp linking. Unmatched counts are mostly functions the game never linked in. Not yet done: check
that remaining partial libraries (LIBCD, LIBAPI) differ only because of unlinked modules and not
version skew. `LIBSN.LIB` has an opcode `psyqlib.py` doesn't parse (irrelevant for matching).
Match list: `python -I tools/libmatch.py extracted/files/SLPS_021.07 <lib>...` (output stays in `extracted/`).

## EXE memory map (from the code; confirmed by the library matches)

| Range (RAM) | Contents |
|---|---|
| `0x80170000-0x80173054` | `.rdata` (strings, tables) |
| `0x80173054-0x801ACA50` | game code (518 functions found by splat) |
| `0x801ACA50-0x801D1E60` | Psy-Q 4.4 libraries (libc2, libgpu, libgs, libgte, libcd, libetc, libmath, libsnd, libspu, libsn, libmcrd, libcard, libapi) |
| `0x801D1E60-0x801D7330` | more text, not yet identified |
| `0x801D7330-0x801DFE50` | `.data` / `.sdata` |
| `0x801DFE50-0x801E7A10` | bss, zeroed by `__SN_ENTRY_POINT` (`0x801C8840`) |

`gp = 0x801DFC58`, `main = 0x8018BDE8`. The kanji ROM font call is `Krom2RawAdd2` at `0x801B1370`
(libgpu), with `kanjitrans` at `0x801B141C`.

## Splat

`decomp/germs.yaml` is the first-draft config; `tools/gen_symbols.py` writes `decomp/symbol_addrs.txt`
(437 named library functions) from `extracted/libmatch.txt`. From `decomp/`: `python -m splat split germs.yaml`.
Generated asm, linker script and macros are gitignored (they contain game code). Limits of the draft:
the game and library text are single blobs (no per-object boundaries), `.data` and `.rdata` are not
split per object, and short library functions (under 8 words) are skipped as ambiguous.

## Compiler check (2026-10-26): the Psy-Q toolchain reproduces retail code

`tools/cc_check.py` runs `CPPPSX` -> `CC1PSX -O2` -> `ASPSX` (all Win32, in `psyq/bin`, SDK 11/96), reads
the object with `psyqlib.py`, and compares each function with the EXE at its address from
`decomp/functions.txt`. Words the linker rewrites (calls, `$gp` offsets of globals) are masked; nothing
else is. `tests/test_cc.py` runs it (skipped without `psyq/`).

| Function | Address | Words | Result |
|---|---|---|---|
| `norm_angle` (wraps an angle to 0..359, a loop with branches) | `0x8018C750` | 16 | **byte-identical**, no relocations |
| `tbl_short` (table lookup through a `$gp` pointer) | `0x8018BD44` | 7 | identical apart from the masked `$gp` offset |
| `angle_quadrant` (the same wrap, then a 4-way range test) | `0x8018C790` | 33 | **not matching**: same code except the post-loop `(short)a` uses `$v1`/`$v1` instead of the retail `$v0`->`$v1`, and the loop's delay slot is filled from the target instead of the fall-through |

What this settles:
- The compiler is gcc 2.7.x as shipped in Psy-Q, `-O2`, default `-G8` (`-G0` changes `tbl_short`, so the
  game was built with `$gp`-relative small data).
- Sources are K&R/ANSI C where shorts live in registers unextended: `short norm_angle(int a)` with explicit
  `(short)` casts matches; declaring the parameter `short` adds a sign-extension the retail code lacks.
- The 11/96 compiler and ASPSX already give the exact bytes for these, so the SDK version mismatch with
  the game's 4.4 libraries does not show up in compiled code (yet).
- Delay-slot scheduling is done by `CC1PSX` itself (`.set noreorder` blocks); ASPSX only appends `nop`
  where `CC1PSX` left a plain `j $31`.

`psyqlib.py` learned two more opcodes from ASPSX objects (28 = source file, 60 = precedes an XBSS).
The `angle_quadrant` near-miss: about 15 source shapes tried (int/short temporaries, `inline` helper,
unsigned range tests, `for(;;)`, nested ifs); none changed the register choice.

## Batch of 16 byte-identical functions (2026-10-26)

`decomp/src/` now holds C for 16 retail functions that `cc_check.py` reports as byte-identical
(`tests/test_cc.py` lists them). Findings:

- **Flags differ per object.** Most functions only match with `-O2 -fno-schedule-insns2` (the post-reload
  scheduler off); `fn_801AC464` (and so its object) only matches with plain `-O2`. A `/* cc-flags: ... */`
  comment at the top of each C file sets them; `cc_check.py` reads it. `norm_angle` and the tiny
  functions match either way.
- **Globals decide the addressing.** A variable *defined* in the file (`int ga;`, `short gsv;`) goes in
  `.sbss` and is reached through `$gp`; an `extern` is not small data, even if tiny, and gets `lui`/offset.
  A big object (`typedef struct { short h[0x80]; } H; extern H g;`) gives the retail `lui` + `addiu` base.
  Fixed addresses (`*(short *)0x801E58C`) give `lui` + offset with the register reuse the retail code has.
- **Register allocation follows declaration order:** `int i = 0; short *p = ...; for (; i < 5; i++)`
  matched where `for (i = 0; ...)` with `p` declared first did not (counter and pointer registers swapped).
- **Statement order is the store order** (the scheduler never reorders stores): `fn_801AC464` needs
  `w[6]`, `w[12]`, `w[14]`, `w[13]` as in the retail code.
- **Parser fix:** relocation patch offsets in a Psy-Q object are relative to the start of the code chunk
  they follow, not the section. `psyqlib.py` now adds the chunk start; before, `cc_check.py` masked the
  wrong words and `libmatch.py` under-counted LIBPAD (3 -> 30 of 42 functions found with Lib44).

Not matching yet: `angle_quadrant` (same code, but the loop branch delay slot is filled from the target
instead of the fall-through: `beqz v0, +4` vs retail `beqz v0, 0`) and `set_hi` at `0x8018BAE0` (retail has
no delay-slot fill and different registers; probably another module or toolchain).

## Batch 2 and the compiler version (2026-10-26)

51 functions now have C in `decomp/src/`: **30 byte-identical**, **8 identical except for register
choice** (`REGS`), 13 not matching. Per-function results, with the flag sets that reproduce each one,
are in `decomp/flags.txt` (generated by `cc_check.py --which-flags`; `tests/test_cc.py` pins the 30).
`cc_check.py` reports `REGS-ONLY` when the code is the same once register fields are ignored.

**The SDK compiler is not the game's compiler.** `psyq/bin/CC1PSX.EXE` identifies as
`GNU C version 2.95.2 19991024 BUILD 4.0.0030 (PSX)`. Sony's own change logs (`psyq/psx/LIBCHG_E.TXT`,
Lib45 `Libchg_e.txt`) say Run-time Library 4.4 (Oct 1998) shipped `cc1psx` as GNU 2.8.1, and 4.5
also bundled the GCC 2.7.2 source. The game (library code dated early 1998, best matching the 4.4
libraries) was built with 2.7.2 or 2.8.1, so this 2.95.2 differs in places:

- Plain functions and ones with simple call/branch structure match. 30 do.
- Where gcc makes a free register choice it can differ. The pool-release family (7 copies,
  `fn_80174FA8` etc.) and `fn_801A3A54` are identical except the first loaded value is `$v0` in the
  retail code and `$v1` here.
- The scheduler also behaves differently: some functions only match with `-O2`, others only with
  `-O2 -fno-schedule-insns2`, even next to each other (`fn_801AC464` needs the first, `fn_801AC9B4` and
  `fn_8019A664` the second). My earlier note that this was "per-module flags" is probably wrong: it is
  most likely one retail flag set (`-O2`) seen through a different compiler version. Treat the flag
  column as "what this compiler needs", not as what Sony used.
- `fn_801749E8`, `fn_8017D170` and 4 siblings (`move $a1, $a0` first, pointer loaded straight into
  `$a0`) never match, another sign of different register preference.

**Next step for exact matching:** build or obtain gcc 2.7.2 / 2.8.1 for mipsel (the SDK 4.4/4.5
`gnusrc\gcc272s.zip`, `gcc281s.zip` are the sources; `decompals/old-gcc` has Linux builds) or a
Psy-Q 4.0-4.3 `CC1PSX.EXE`. Every function listed `REGS`/`NONE` is a test case for it.

Source-shape lessons from this batch:
- A function that walks a pool through `W *g = &extern_struct` keeps `g` in `$s0` (callee-saved) across
  calls; an absolute address `(W *)0x801E02D8` does not (gcc folds the constant instead).
- `return c ? a : b;` and `if (c) return a; return b;` lay out the branches differently: match the
  retail fall-through (`fn_80176734` is a ternary, `fn_80199D18` tests `!= 0` first).
- Declaration order is register order (`fn_8018D294`: pointer first, then `short i`).

## gcc 2.8.1 reproduces the retail code (2026-10-26)

**The game was built with gcc 2.8.1, `-O2 -G8`.** `tools/oldgcc/` builds the psx variants of old gcc
natively on Windows (see its README; binaries in `tools/vendor/oldgcc/bin`), and `cc_check.py` uses
2.8.1 by default (`--cc1 sdk|2.7.2|2.8.1`). Of the 61 functions with C in `decomp/src/`:

| Compiler | byte-identical | same code, other registers | not matching |
|---|---|---|---|
| SDK `CC1PSX.EXE` (gcc 2.95.2) | 30 | 10 | 21 |
| gcc 2.7.2 psx | 9 | 1 | 51 |
| **gcc 2.8.1 psx** | **52** | 0 | 9 |

- Every one of the 52 matches uses **plain `-O2`** (and `-G8`): no scheduler flags. The earlier "per-module
  flags" were an artifact of using the wrong compiler (see the previous section; `decomp/flags.txt` has
  the per-function table for all three compilers). There is nothing to record per module: one flag set.
- All 8 functions that were "registers only" with the SDK compiler now match exactly, as do the whole
  pointer-wrapper family (`fn_8017D170` and 5 siblings) that never matched before.
- 2.7.2 only matches trivial functions, so the game is not 2.7.2.
- Sources written for 2.95 sometimes need changing: `fn_801AC464` matched in a reordered statement
  order for 2.95 and matches in the natural order for 2.8.1; `fn_80184408` needs the shared `-1` in a
  variable (`int m1 = -1;`); `fn_8018F91C` needs `for (...; i++, p += 0x20)`.
- Pipeline notes: `cc1` needs `TMPDIR` and `-G8`; 2.8.1 writes `.comm` after the code, so `cc_check.py`
  hoists it before ASPSX (single pass) to get `$gp` accesses.

Still not matching (all with 2.8.1): `angle_quadrant`, `fn_801A3D74`, `fn_801A0690`, `fn_8018C50C`,
`fn_80186838`, and the four table lookups in `lookup.c` (`fn_801767D4`, `fn_80176890`, `fn_80188FEC`,
`fn_801891A4`: retail copies the loop count and id into `$a0`/`$a3` before the loop). `set_hi`
(`0x8018BAE0`) was dropped. Next: more functions, then splat per-object segments and a link step.

## Batch 3 (2026-10-26): 86 functions, 81 byte-identical with gcc 2.8.1

`python -I tools/decomp_status.py` re-runs every file and rewrites `decomp/flags.txt` and the pinned
list in `tests/test_cc.py`. Status: **81 byte-identical**, 2 identical except registers
(`fn_801AC214`, `fn_801AC4A8`: the pointer read from `0x801E076C` is in `$v0`/`$v1` here, `$a1`/`$a0` in
the retail code), 3 not matching (`fn_8018C50C`, `angle_quadrant`, `fn_801A3C58`). Of the nine that
differed last time, seven now match: `fn_801A3D74`, `fn_80186838`, the four table lookups, and
`fn_801A0690` (only with `-mno-split-addresses`, see `special.c`; probably a source-shape difference).

`tools/variants.py` is a parallel search harness: build a dict of candidate sources, it compiles each
(about 20 per second per thread) and reports exact and registers-only hits. Most stubborn functions
fell to it. What it found, as rules for writing C that gcc 2.8.1 turns into the retail code:

- **K&R `short` parameters** (`f(id) short id;`) make the compiler copy the argument at entry, which is
  what the retail code does. Passing `int` and casting in the body gives different registers.
- **A loop bound read from memory in the condition** (`for (i = 0; i < g->w[9]; i++)`) is hoisted into a
  fresh register, giving the `move $a0, $a2` the retail loops have. A local `int n = ...` is not.
- **Tables inside a bigger struct** (`extern struct { char pad[0x204]; struct E e[4]; } g;` then
  `g.e[i]`) keep the base register and the large offsets apart; a `char *` plus offset gets folded.
- **Arrays in a struct for pointer tables** (`struct T { int a[2]; }`), and **declaration order** decides
  which of two pointers gets the lower register (`struct G *g` before `int c = p[3]`).
- **Shared constants:** `int m1 = -1;` used for two stores keeps one register, as in `fn_80184408`.
- **Shorts in locals** (`short a = p[0x12], b = p[0x13]; int m = a < b ? b : a;`) for `fn_801A3D74`.
- **An extern symbol array for a fixed global** (`extern unsigned short e0u[]; e0u[0x6DB4 / 2]`) matches
  where a constant address (`*(unsigned short *)0x801E6DB4`) does not, and the reverse in other places:
  try both.
- `-mno-split-addresses` flips only `fn_801A0690`; it makes 22 other functions fail. Not a global setting.

Brute-force notes: 30,000 random statement orders of `fn_8018C50C` produced no exact or registers-only
hit, so its difference is structural (the retail hoists the constant `1` into its own register before the
fifth argument load). `angle_quadrant` is identical but for one branch target (the loop delay slot is filled
from the target instead of the fall-through).

## Linked build, first pass (2026-10-26)

**Linker choice.** `psyq/bin/PSYLINK.EXE` (v2.82) is a Win32 program and runs here (`psylink /options
sources,output,symbol,map,libraries`; `/o` org, `/x` entry, `/gp`, `/p` pure binary, `/e sym=value`).
`PSYLIB.EXE` and `DUMPOBJ.EXE` are DOS and do not run. So the real link needs no download and no ELF
conversion: link our ASPSX objects plus the Lib44 `.LIB` files (unpacked locally into the gitignored
`tools/vendor/psyq44/`) with a `.LNK` script. That full link is the next step; it needs per-object
splitting of the retail layout (game code and library code are interleaved) and `.data/.sdata/.bss`
placement, none of which is settled yet.

**What exists now (no linker needed, addresses are fixed):**
- `tools/build_exe.py` compiles every `decomp/src/*.c` (flags from its `cc-flags:` line), writes each function
  over the retail bytes at its address and reports. Relocated fields (jal targets, `%hi/%lo`, `$gp` offsets)
  keep the retail bits, so this checks compiler output, not symbol resolution. Result: 81/86 functions
  byte-identical, 1620 of 102583 code words (1.6%) are C; the rebuilt image differs from retail in 55 words, all
  inside the 5 known non-matching functions (`angle_quadrant`, `fn_8018C50C`, `fn_801A3C58`, and the
  registers-only `fn_801AC214`, `fn_801AC4A8`). The image goes to `build/SLPS_021.07.rebuilt` (gitignored).
- `tools/objdiff_objs.py` + `objdiff.json`: objdiff does not read Psy-Q LNK objects, so the script converts
  to ELF (a small writer, one `.text` and one FUNC symbol per function). `base` = our compiled C, `target` =
  the retail bytes of the same functions; relocated fields are masked on both sides. Open the repo root in
  `objdiff-windows-x86_64.exe` after `python -I tools/objdiff_objs.py`. Not yet checked in the objdiff GUI
  (only the ELF headers were verified); the target side is not split-asm, because a per-function slice of the
  retail bytes is equivalent for comparing and needs no assembler.
- `tests/test_build.py` covers both.

## Per-object split and PSYLINK relink (2026-10-26)

- `tools/objmap.py` finds whole Lib44 modules in the EXE (their `.text` with relocated words masked) and writes
  `decomp/objects.txt` (address, size, library, module; addresses and names only, committed). 303 modules,
  137,584 bytes, from `0x801AC9D0` to `0x801D1E70`; 15 short modules match in several places and are left out;
  identical modules (LIBC/LIBC2 QSORT and MEMMOVE, GS_132/VWUNIT, ...) are folded into one line with `also:`.
  15 gaps (15 KB) remain inside that range: game code (the pad update `0x801CD6B4` sits in one) and the ambiguous modules.
- `tools/gen_splat.py` writes `decomp/germs.yaml` with one subsegment per object: 303 library modules and
  gap runs as `asm`, the 86 C functions as `c` (one segment per function, since our `decomp/src` files are
  groupings we made, not the original compilation units, and their functions are scattered). Splat's stubs go to
  `decomp/splat_src/` (gitignored) so they never mix with our C. `.rdata`, `.data/.sdata` and `.bss` are still
  one segment each: nothing says which object owns which data yet. Splat's `.ld` is of limited use (the link
  is done by PSYLINK, not GNU ld).
- `tools/lib_relink.py` cuts each module's object out of its Lib44 `.LIB`, links it with the real
  `PSYLINK.EXE` (`/c /p /m @m.lnk,...`; the script has `org`, `include "m.obj"` and `name equ addr` lines for
  every external; `/e` has a length limit) so its `.text` lands on its retail address, and compares with the
  EXE. **All 303 modules relink to the retail bytes**; 1,969 relocated words (jal targets, `%hi/%lo` of text
  symbols) were resolved by the linker and equal retail. 4,686 words that point into data are skipped, because
  data is not placed yet. Symbols come from the module map plus `decomp/symbol_addrs.txt`; the aliases
  `SsUtReverbOff`/`SpuInit` (same 8 instructions, two places) are settled from the retail call sites
  (`OVERRIDES`). PSYLINK is case sensitive only with `/c`, and `equ` names must match the object's case.
- `tools/build_exe.py` now writes the PSYLINK-linked library modules and our compiled C over the retail
  bytes: of 102,583 code words, 1,620 (1.6%) are our C, 34,396 (33.5%) are linked library modules and
  66,567 are still asm. The result differs from retail only in the 5 non-matching functions (55 words).
- `psyqlib.parse_obj` now also returns `xrefs`, `sym_ids` and `patch_refs` (which symbols each patch uses).

## Data split and the whole-image PSYLINK link (2026-10-26)

`python -I tools/fulllink.py` links the whole EXE image (everything up to the start of bss) with the real
`PSYLINK.EXE` and gets **0 words different from `SLPS_021.07`**. The input is the 303 Lib44 modules (cut from
their `.LIB`s) plus glue objects holding the retail bytes of what is not a located module. The build is
`build/link/` (gitignored); `full.lnk` is the link script, `full.map` the map.

What it took (all measured, see the sources):
- **Retail link layout.** One run of PSYLINK: `.rdata`, `.text`, `.ctors`, `.dtors`, `.data`, `.sdata` (all in
  the `text` group), then `.sbss`, `.bss` (the `bss` group), each section the concatenation of the objects'
  sections in link order. `.rdata` 0x80170000, `.text` 0x80173054 to 0x801D7328 (the retail `__textlen` is 0x642D4),
  `.data` from 0x801D7328, `.sdata` from `gp` = 0x801DFC58, `.sbss` 0x801DFE50-0x801DFFE8, `.bss` to 0x801E7A10
  (`SNMAIN`'s data holds `__bss` = 0x801DFFE8, `__bsslen` = 0x7A28, and refers to the start of the empty
  `.ctors`/`.dtors` sections, so the script must declare them).
- **Section bases from relocations** (`tools/datamap.py`). Every relocation that points into the module's own
  section (`HI16/LO16`, `JMP26`, 32-bit words; tags 82, 84, 74, 16 of the LNK patch records) was resolved by
  the linker to base+offset, so reading the retail word gives the base. This placed `.rdata` (26), `.data` (38),
  `.sbss` (1) and `.bss` (19 sections) of the located modules, all in link order, no overlaps; initialized
  sections were checked byte for byte. OBJT2 and OBJT3 have the same code; OBJT2's `.data` would have to sit in
  bss, so the game has OBJT3 (`objmap.PREFER`).
- **External names** (99, e.g. `main`, `_stacksize`, game functions the libraries call) get the address the
  retail relocations resolve them to (`datamap.symbol_values`) as `name equ addr` lines in the script.
- **Common symbols** (LNK op 48 `xbss`, ~12 KB: `_que`, `GsDRAWENV`, ...) are allocated by the linker in an
  order that depends on every object of the link, so they cannot be left to it while the game objects are
  missing. Each record is rewritten into a plain reference (op 14, same symbol id) and the symbol is an `equ`
  at its retail address; the space is part of the bss glue.
- **Alignment byte of a LNK section** (PSYLINK 2.82, measured with `tools/lnk.py` objects): 2 = no padding,
  4 = 2 bytes, 8 = 4 bytes (what ASPSX writes), 1 and 16 = 256 bytes. Glue objects use 2.
- `tools/lnk.py` writes LNK objects (sections of bytes or bss sizes); `psyqlib.parse_obj` now returns local
  symbols, expression trees (`patch_exprs`) and the xbss records with their byte spans.

`tools/gen_splat.py` now also splits `.rdata`, `.data` and `.sdata` into one piece per located module and per run
of game data (`lib_<LIB>_<MODULE>_<section>`, `game_<section>_<addr>`); the bss stays one splat segment (its pieces
would start past the end of the file), its per-module split is `fulllink.layout()`. `tools/lib_relink.py` is
still the per-module check (303/303); `tools/fulllink.py` is the real link.

## Our C in the link (2026-10-26)

`python -I tools/fulllink.py` now links the compiled C too: **86 functions (1,620 code words) come from our
compiled objects, 81 of them reproduce the retail image, and the differences are exactly the 5 known
non-matching functions** (`fn_8018C50C` 10 words, `angle_quadrant` 16, `fn_801A3C58` 25, `fn_801AC214` 2,
`fn_801AC4A8` 2). `--no-c` links the libraries only (0 words differ). `tests/test_build.py` pins both.

- `tools/cobjs.py` turns each compiled C file into one Psy-Q object per function (the functions of a file sit at
  different places of the EXE). The `.text` is cut at the function symbols, the patch records are rewritten with
  names: `.text + n` (calls inside the file) names the callee, the rest already names an extern or a common
  symbol. Written with `lnk.write_object` (now with xdefs, xrefs and patch expressions).
- `fulllink.slot_objects` cuts the text glue at the function addresses and puts the object of each function
  in its place; PSYLINK resolves the calls (`jal` to library modules, other C functions and glue code) and
  the `$gp`-relative accesses of the `gp` variables (patch tag 100, GPREL16, base = start of `.sdata`).
- **What is still taken from the retail words:** the addresses of the data symbols the C names (the `gNNN`
  externs, the `gpNN` commons in `.sbss`) are read back from the retail relocations (`cobjs.address_of`,
  `datamap.symbol_values`; names `fn_XXXXXXXX` carry their address). So a wrong data layout in the C would not
  show up yet; calls and the encoding of every relocation do get checked by the linker. Real data symbols need
  the C to define the game's data, which comes with the data split per game object.
- Patch tags seen in the C objects: 74 (JMP26), 82/84 (HI16/LO16), 100 (GPREL16). Strings in `.rdata` and
  other sections are refused by `cobjs.rewrite` until a function needs them.

Next: more C (every new function in `decomp/src` + `decomp/functions.txt` shows up here), the 5 diffs, game
data as C objects (so the data symbols come from the link, not from the retail words), and replacing the rest of
the glue (66 k code words) by compiled functions, starting with the ones next to library code.
## All 86 functions match (2026-10-26)

The five functions that did not match now do: **86 of 86 byte-identical with gcc 2.8.1, and the PSYLINK link
with our C equals the retail image (0 words differ)**; `tests/test_build.py` and `tests/test_cc.py` pin it
(`NOT_C_YET` is empty). What each one needed, as rules for the remaining functions:

- **A value that is passed on lives in an argument register.** `fn_801AC214`, `fn_801AC4A8`: the pointer read
  from `0x801E076C` sat in `$a1`/`$a0` in the retail code because it is also an argument of the callees
  (`fn_801A923C(x, q)`, `fn_801AA360(q)`); the callees take it (our externs are unprototyped, so extra
  arguments cost nothing). `fn_801A3C58`: the `lh $a1, 2($s0)` before the test is `q[1]` passed to the first call,
  `fn_801C1018(q[0], q[1])`. When the retail code loads something into `$aN` early for no visible reason, look
  for a call that takes it.
- **A global read where it is used** (`e0s[0x6DB8 / 2]` twice in the second call, not a local before the first
  call) keeps the retail order of the loads and avoids a callee-saved register for it.
- **`angle_quadrant`: a backward `goto`, not a loop.** The retail delay slot of the wrap branch is filled from
  the fall-through; reorg.c `mostly_true_jump` takes the target thread for a branch to a label that follows a
  `NOTE_INSN_LOOP_BEG` (every `do/while`, `for`), so the code only comes out as retail when gcc does not see a
  loop. Also `int v = (short)a;` (an int, so the range tests are signed, no `andi` masks). `norm_angle`
  (a real loop in the retail code) stays a `do/while`. Look for this whenever a loop's last branch has the
  "wrong" delay slot.
- **`fn_8018C50C`: the first statement decides register sharing.** The retail code keeps the constant `1` in its
  own register (`$t0`); it comes out of `sa = 1; s2 = 2; s6 = 0; s4 = 1; pc = sym; ...` (exhaustive over
  the order of the first five stores; 4 of 120 orders match). The earlier random sampling of all 10 stores
  (30,000 of 3.6M) had missed it.
## More C: 114 functions (2026-10-27)

`decomp/src/batch8.c`-`batch12.c` add 28 functions (all byte-identical, all in the PSYLINK link; 114 pinned in
`tests/test_cc.py`, 2,532 of 102,583 code words are C). Candidates come from the splat asm
(`nonmatching func_XXXXXXXX, 0xSIZE` lines in `decomp/asm/game_*.s`, game range below `0x801AC9D0`), smallest first.
Near misses are parked in `decomp/wip/near_miss.c` (not in `functions.txt`, so not linked) with a note on what differs:
`fn_801A20CC`/`fn_801A211C`, `fn_801A3B5C`, `fn_801A6968`, `fn_80187560`, `fn_8017D574`, `fn_801AC88C`,
`fn_801855C8`/`fn_801A44B8` (same shape as `fn_8018E56C`), `fn_801A5C34`, `fn_80194F08`.
`fn_801AC91C` and `fn_80199E1C` were looked at and not written yet.

Rules that matched stubborn functions (add to the ones above):
- **K&R `short`/`unsigned short` parameters are copied at entry** (`move v1,a1`, `move s2,s1`, or an `andi` for
  `unsigned short`); the original argument register stays alive for other uses. `fn_8018A968(a, b) short a, b`,
  `fn_8018D200(a, b) unsigned short a; int b`. A plain local copy (`int c = a`) is propagated away instead.
- **A value that is also an argument of a call lives in an argument register** (`fn_801AC214`); passing the same
  value (or an extra one) to the callee reproduces it: `fn_80189928` calls `gp280(p, e)`.
- **Loops without loop optimization.** A `while` that the retail code does not rotate, or a loop whose limit
  (`addiu v0,s1,0xa0`) is recomputed every pass and whose pointer is not strength-reduced, is written with a
  backward `goto` (no loop notes): `fn_80185548`, `fn_801A7BA4`, `fn_801A252C`, `angle_quadrant`. In
  `fn_801A252C` the addresses are also `int`s (signed `slt`). A `for (;;)` with `break` keeps the loop optimizer.
- **A store placed before a call ends up in its delay slot**: if the retail delay slot holds a store, the store is
  before the call in the source (`fn_801A3BCC`, `fn_8018AABC`).
- **In-place pointer add**: `s += s[1]; d = s[4]` (`fn_8018A8CC`) gives `addu v1,v1,v0`; `s[s[1] + 4]` does not.
- **Base registers**: `H *q = &g368b;` (a local pointer to the extern) gives `lui/addiu` once and offsets from
  it (`fn_8018BD8C`, `fn_80186680`); direct member access of an extern struct gives `lui $at` per store.
  `e0s[0x1040 / 2] = a;` on the `0x801E0000` array gives `lui v0; sh a,0x1040(v0)` (`fn_8018AABC`).
- `/`, `%` by constants and `short` division are reproduced by writing the same expression
  (`(s[4] << 4) / 100`, `((v * 3 << 18) / 360) >> 14`).
- Cheap way to look at a diff: put the candidate after the file's header in a scratch `.c`, add its name to
  `decomp/functions.txt`, and run `python -I tools/cc_check.py <file> --show`; `tools/variants.py` runs many
  candidates (see its docstring); parking is just moving the function into `decomp/wip/` and removing it from
  `functions.txt`.