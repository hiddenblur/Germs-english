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
