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
